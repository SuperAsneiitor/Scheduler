"""EDA 子任务抽象基类：统一生命周期与 ``subprocess`` 运行骨架。

设计说明：
- **为什么拆成 pre/generate/run/post/collect**：与 EDA 工具的真实工作流一致，便于单测对每一阶段
  注入假文件/假日志；调度器也可在 ``run`` 前后插入指标采集。
- **为什么 ``run`` 放在基类**：进程拉起、超时、流式日志属于横切关注点，避免每个工具复制一份
  ``Popen``/线程读取逻辑；子类只关心「命令行长什么样」「脚本里写什么」。
- **为什么用线程读 stdout/stderr**：在避免死锁的前提下并行排空管道，实现「准实时」落盘与日志；
  Windows/POSIX 行为一致，不依赖 ``select`` 在 Win 上的局限。
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from eda_jobs.context import JobContext, JobRunResult, RetryBackoff
from eda_jobs.exceptions import EDAJobPostCheckError, EDAJobRunError
from orchestration.workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)


class BaseEDAJob(ABC):
    """EDA 原子任务的模板方法骨架。

    典型调用顺序（由 :meth:`execute_pipeline` 固定）::

        pre_check -> generate_scripts -> build_command -> run -> post_check -> collect_metadata

    子类只需实现抽象方法；若某工具需要完全自定义 ``run``，可在子类覆写，但应谨慎复制
    安全逻辑（超时、日志、路径校验）。
    """

    def __init__(self, context: JobContext) -> None:
        self._context = context
        self._generated_main_script: Optional[Path] = None
        self._last_run_result: Optional[JobRunResult] = None

    @property
    def context(self) -> JobContext:
        """只读上下文，避免子类意外改坏不可变配置。"""
        return self._context

    @abstractmethod
    def pre_check(self) -> None:
        """运行前校验：输入文件、License、可执行路径等。

        Raises:
            EDAJobPreCheckError: 条件不满足且不应继续生成脚本/启动工具时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def generate_scripts(self) -> Path:
        """根据模板与参数生成主脚本（如 ``.tcl`` / ``.sp`` / ``runme.sh``）。

        Returns:
            生成的主脚本路径；后续 :meth:`build_command` 可依赖该路径拼命令行。

        Raises:
            OSError: 写盘失败。
            ValueError: 模板参数不合法。
        """
        raise NotImplementedError

    @abstractmethod
    def build_command(self) -> List[str]:
        """构造 argv 列表（第一个元素必须是可执行文件）。

        说明：与 :meth:`generate_scripts` 解耦，便于同一脚本在不同模式下以不同引擎启动
        （例如仅改 ``calibre`` vs ``qsub`` 包装）。

        Raises:
            EDAJobPreCheckError: 缺少生成物或上下文不足以拼出命令时抛出。
        """
        raise NotImplementedError

    def run(self, command: Sequence[str], *, cwd: Optional[Path] = None) -> JobRunResult:
        """以流式方式拉起子进程，并将 stdout/stderr 分别写入工作目录下日志文件。

        **环境隔离**：所有日志与子进程 ``cwd`` 必须位于用户工作区内；若设置了 ``FLOW_ROOT``，
        则禁止向该只读软件根目录及其子路径写入（防止污染安装树）。

        该方法可在子类覆写，但推荐保留「超时 + 日志落盘」语义。

        Args:
            command: 完整命令行（含可执行文件路径）。
            cwd: 子进程工作目录；默认使用 :attr:`JobContext.workdir`。

        Returns:
            :class:`JobRunResult`：退出码与日志路径。

        Raises:
            EDAJobRunError: 进程无法启动、超时或等待失败。
            PermissionError: 试图在 ``FLOW_ROOT`` 下写入。
        """
        if not command:
            raise EDAJobRunError("命令行为空，拒绝启动子进程")

        workdir = cwd if cwd is not None else self._context.workdir
        workdir = Path(workdir).resolve()
        workdir.mkdir(parents=True, exist_ok=True)

        flow_root_raw = os.environ.get("FLOW_ROOT")
        flow_root_path = Path(flow_root_raw).resolve() if flow_root_raw else None
        WorkspaceManager.path_must_not_be_under_flow_root(workdir, flow_root_path)

        stdout_path = workdir / "eda_job.stdout.log"
        stderr_path = workdir / "eda_job.stderr.log"
        WorkspaceManager.path_must_not_be_under_flow_root(stdout_path, flow_root_path)
        WorkspaceManager.path_must_not_be_under_flow_root(stderr_path, flow_root_path)

        argv = [str(part) for part in command]
        logger.info("启动 EDA 子进程: cwd=%s argv=%s", workdir, argv)

        start = time.monotonic()
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(workdir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise EDAJobRunError(f"无法启动子进程: {exc}") from exc

        def _pump_stream(stream: Optional[Any], log_path: Path, stream_name: str) -> None:
            """在独立线程中读取子进程管道，边读边写文件并打 INFO 日志。"""
            if stream is None:
                return
            try:
                with open(log_path, "w", encoding="utf-8", errors="replace") as log_file:
                    for line in iter(stream.readline, ""):
                        if not line:
                            break
                        log_file.write(line)
                        log_file.flush()
                        logger.info("[%s] %s", stream_name, line.rstrip("\n"))
            finally:
                try:
                    stream.close()
                except OSError:
                    pass

        threads: List[threading.Thread] = []
        if proc.stdout is not None:
            threads.append(
                threading.Thread(
                    target=_pump_stream,
                    args=(proc.stdout, stdout_path, "STDOUT"),
                    daemon=True,
                )
            )
        if proc.stderr is not None:
            threads.append(
                threading.Thread(
                    target=_pump_stream,
                    args=(proc.stderr, stderr_path, "STDERR"),
                    daemon=True,
                )
            )
        for thread in threads:
            thread.start()

        timeout = self._context.timeout_seconds
        try:
            return_code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            raise EDAJobRunError(f"子进程超时（>{timeout}s）") from exc
        finally:
            for thread in threads:
                thread.join(timeout=5.0)

        duration = time.monotonic() - start
        result = JobRunResult(
            exit_code=int(return_code),
            stdout_log_path=stdout_path,
            stderr_log_path=stderr_path,
            command=list(argv),
            duration_seconds=duration,
        )
        self._last_run_result = result
        logger.info(
            "子进程结束: exit=%s duration=%.3fs stdout=%s stderr=%s",
            result.exit_code,
            result.duration_seconds,
            stdout_path,
            stderr_path,
        )
        return result

    @abstractmethod
    def post_check(self, run_result: JobRunResult) -> None:
        """对日志与产物做领域规则校验（DRC 错误数、.lib Corner 等）。

        Args:
            run_result: :meth:`run` 的输出；即使 ``exit_code==0`` 也可能需要业务层判失败。

        Raises:
            EDAJobPostCheckError: 结果不满足签名校验或业务阈值时抛出。
        """
        raise NotImplementedError

    @abstractmethod
    def collect_metadata(self, run_result: JobRunResult) -> Dict[str, float]:
        """从日志/报告中抽取 PPA 或等价指标（面积、时序裕量等）。

        说明：返回纯 ``float`` 字典便于序列化；若需结构化模型，可在调度层再包一层。
        """
        raise NotImplementedError

    def execute_pipeline(self) -> Tuple[JobRunResult, Dict[str, float]]:
        """执行完整生命周期（含简单重试策略，由 :class:`RetryPolicy` 描述）。

        Returns:
            ``(run_result, metadata)``

        Raises:
            EDAJobPreCheckError: 前置失败。
            EDAJobRunError: 运行失败。
            EDAJobPostCheckError: 后置校验失败。
        """
        self.pre_check()
        self._generated_main_script = self.generate_scripts()
        command = self.build_command()

        policy = self._context.retry_policy
        last_error: Optional[Exception] = None
        attempts = max(1, policy.max_attempts)
        delay = policy.initial_delay_seconds

        run_result: Optional[JobRunResult] = None
        for attempt in range(1, attempts + 1):
            try:
                run_result = self.run(command)
                break
            except EDAJobRunError as exc:
                last_error = exc
                logger.warning("run 失败 attempt=%s/%s err=%s", attempt, attempts, exc)
                if attempt >= attempts:
                    raise
                if delay > 0:
                    time.sleep(delay)
                if policy.backoff == RetryBackoff.FIXED:
                    pass
                elif policy.backoff == RetryBackoff.LINEAR:
                    delay += policy.initial_delay_seconds
                elif policy.backoff == RetryBackoff.NONE:
                    delay = 0.0

        if run_result is None:
            assert last_error is not None
            raise last_error

        self.post_check(run_result)
        metadata = self.collect_metadata(run_result)
        return run_result, metadata
