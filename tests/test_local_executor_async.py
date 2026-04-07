"""LocalExecutor 异步提交测试（Mock asyncio.create_subprocess_exec，不跑真实 EDA）。"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from config import load_execution_config_from_mapping
from executors import (
    ExecutorJobState,
    JobNotFoundError,
    LocalExecutor,
    LocalProcessStartError,
)


def test_submit_job_mock_success_records_done_status(tmp_path) -> None:
    """模拟子进程返回 0 时 check_status 为 DONE。"""

    async def _main() -> None:
        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=0)

        with patch(
            "executors.local_executor.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ):
            executor = LocalExecutor(max_parallel_jobs=2)
            log_path = tmp_path / "run.log"
            job_id = await executor.submit_job(
                ["python", "-c", "print(1)"],
                str(log_path),
            )

        assert job_id.startswith("local_job_")
        assert executor.check_status(job_id) == ExecutorJobState.DONE.value
        assert executor.get_failed_job_ids() == []

    asyncio.run(_main())


def test_submit_job_mock_nonzero_records_failed_job_id(tmp_path) -> None:
    """非零退出码应记录到 failed_job_ids。"""

    async def _main() -> None:
        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=42)

        with patch(
            "executors.local_executor.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_proc),
        ):
            executor = LocalExecutor(max_parallel_jobs=2)
            job_id = await executor.submit_job(
                ["python", "-c", "import sys; sys.exit(1)"],
                str(tmp_path / "bad.log"),
            )

        assert job_id in executor.get_failed_job_ids()
        assert executor.check_status(job_id) == ExecutorJobState.EXIT.value

    asyncio.run(_main())


def test_local_executor_from_execution_config_uses_max_parallel_jobs() -> None:
    """from_execution_config 应读取 max_parallel_jobs。"""
    cfg = load_execution_config_from_mapping(
        {
            "mode": "local",
            "local_settings": {"max_parallel_jobs": 3},
        }
    )
    executor = LocalExecutor.from_execution_config(cfg)
    assert executor._max_parallel_jobs == 3


def test_check_status_unknown_job_raises_job_not_found() -> None:
    """未知 job_id 应抛 JobNotFoundError。"""
    executor = LocalExecutor(max_parallel_jobs=1)
    with pytest.raises(JobNotFoundError):
        executor.check_status("local_job_9999")


def test_submit_job_empty_command_raises_value_error(tmp_path) -> None:
    """空 command 应抛 ValueError。"""

    async def _run() -> None:
        executor = LocalExecutor(max_parallel_jobs=1)
        await executor.submit_job([], str(tmp_path / "a.log"))

    with pytest.raises(ValueError):
        asyncio.run(_run())


def test_submit_job_oserror_raises_local_process_start_error(tmp_path) -> None:
    """create_subprocess_exec 抛 OSError 时应包装为 LocalProcessStartError。"""

    async def _boom(*args, **kwargs):
        raise OSError("no such file")

    async def _main() -> None:
        with patch(
            "executors.local_executor.asyncio.create_subprocess_exec",
            new=_boom,
        ):
            executor = LocalExecutor(max_parallel_jobs=1)
            with pytest.raises(LocalProcessStartError):
                await executor.submit_job(["/nonexistent/binary"], str(tmp_path / "x.log"))

    asyncio.run(_main())
