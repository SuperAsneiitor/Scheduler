"""本地异步执行器：asyncio.Semaphore + create_subprocess_exec 限制并发。"""

from __future__ import annotations

import asyncio
import itertools
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence

if TYPE_CHECKING:
    from config.execution_config import ExecutionConfig

from flow.executors.backends.base import ExecutorJobState
from flow.executors.backends.exceptions import JobNotFoundError, LocalProcessStartError

logger = logging.getLogger(__name__)


class LocalExecutor:
    """使用 ``asyncio.Semaphore`` 限制本地外部命令并发度。

    与 :class:`~flow.executors.backends.lsf_executor.LSFExecutor` 不同，本类**不**继承
    :class:`~flow.executors.backends.base.BaseExecutor`：接口为异步 ``submit_job(command, log_file)``，
    面向 ``asyncio`` 调度循环。

    并发语义：在 ``submit_job`` 内 ``async with semaphore`` 包裹
    ``create_subprocess_exec`` + ``wait``，同一时刻处于运行态的子进程数不超过
    ``max_parallel_jobs``。
    """

    def __init__(
        self,
        max_parallel_jobs: Optional[int] = None,
        *,
        max_concurrent_jobs: Optional[int] = None,
    ) -> None:
        """初始化本地执行器。

        Args:
            max_parallel_jobs: 并发上限（>=1）。与 ``max_concurrent_jobs`` 二选一。
            max_concurrent_jobs: 兼容旧参数名，同 ``max_parallel_jobs``。

        Raises:
            ValueError: 未提供上限或数值非法。
        """
        limit = max_parallel_jobs if max_parallel_jobs is not None else max_concurrent_jobs
        if limit is None:
            limit = 4
        if limit < 1:
            raise ValueError("max_parallel_jobs 必须 >= 1")

        self._max_parallel_jobs = limit
        self._semaphore = asyncio.Semaphore(limit)
        self._job_id_seq = itertools.count(1)
        self._lock = threading.Lock()
        self._exit_codes: Dict[str, int] = {}
        self._failed_job_ids: List[str] = []

    @classmethod
    def from_execution_config(cls, config: ExecutionConfig) -> "LocalExecutor":
        """由 :class:`~config.execution_config.ExecutionConfig` 构造实例。

        Args:
            config: 已校验的配置；必须为 ``mode='local'`` 且含 ``local_settings``。

        Raises:
            ValueError: ``mode`` 非 local 或缺少 ``local_settings``。
        """
        from config.execution_config import ExecutionConfig as ExecutionConfigModel

        if not isinstance(config, ExecutionConfigModel):
            raise TypeError("config 必须为 ExecutionConfig")
        if config.mode != "local" or config.local_settings is None:
            raise ValueError("from_execution_config 需要 mode='local' 且提供 local_settings")
        return cls(max_parallel_jobs=config.local_settings.max_parallel_jobs)

    async def submit_job(self, command: Sequence[str], log_file: str) -> str:
        """启动外部命令并将 stdout/stderr 合并写入 ``log_file``。

        在信号量保护下并发执行；方法在子进程结束后返回。

        Args:
            command: 非空的可执行文件路径及参数列表（不得使用 shell 管道；需要时请显式调用 ``sh``/``bash``）。
            log_file: 日志文件路径（父目录不存在时会创建）。

        Returns:
            本执行器分配的任务 ID（形如 ``local_job_0001``）。

        Raises:
            ValueError: ``command`` 非法。
            LocalProcessStartError: 进程启动失败（包装 ``OSError``）。
        """
        if not command:
            raise ValueError("command 不能为空")
        normalized = [str(part) for part in command]
        job_id = self._next_job_id()

        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(
            "Local job scheduled job_id=%s max_parallel=%s cmd=%s log=%s",
            job_id,
            self._max_parallel_jobs,
            normalized,
            log_file,
        )

        log_handle = open(log_path, "wb")
        return_code: int
        try:
            async with self._semaphore:
                logger.debug("Slot acquired job_id=%s (active limited by semaphore)", job_id)
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *normalized,
                        stdout=log_handle,
                        stderr=asyncio.subprocess.STDOUT,
                        stdin=asyncio.subprocess.DEVNULL,
                    )
                except OSError as exc:
                    raise LocalProcessStartError(f"无法启动子进程: {exc}") from exc

                return_code = await proc.wait()
        finally:
            try:
                log_handle.close()
            except OSError as exc:
                logger.warning("关闭日志文件失败 job_id=%s err=%s", job_id, exc)

        with self._lock:
            self._exit_codes[job_id] = return_code
            if return_code != 0:
                self._failed_job_ids.append(job_id)
                logger.error(
                    "子进程非零退出 job_id=%s returncode=%s cmd=%s",
                    job_id,
                    return_code,
                    normalized,
                )
            else:
                logger.info("子进程正常结束 job_id=%s returncode=0", job_id)

        return job_id

    def check_status(self, job_id: str) -> str:
        """在 ``submit_job`` 完成后查询终态（``RUN``/``DONE``/``EXIT``）。

        由于 ``submit_job`` 会等待子进程结束，通常仅在返回后调用本方法；
        未完成前不会写入 ``exit_codes``。

        Raises:
            JobNotFoundError: 未知 ``job_id``。
        """
        with self._lock:
            if job_id not in self._exit_codes:
                raise JobNotFoundError(f"未知本地作业 job_id={job_id}")
            return_code = self._exit_codes[job_id]

        if return_code == 0:
            return ExecutorJobState.DONE.value
        return ExecutorJobState.EXIT.value

    def get_failed_job_ids(self) -> List[str]:
        """返回非零退出任务 ID 列表的拷贝。"""
        with self._lock:
            return list(self._failed_job_ids)

    def clear_failed_job_ids(self) -> None:
        """清空失败记录（监控模块确认后可调用）。"""
        with self._lock:
            self._failed_job_ids.clear()

    def _next_job_id(self) -> str:
        return f"local_job_{next(self._job_id_seq):04d}"
