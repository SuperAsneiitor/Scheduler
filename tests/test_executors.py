"""执行器模块单元测试：全部 Mock subprocess，不调用真实 bsub/bjobs/本地长任务。"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from flow.executors.backends import (
    ExecutorJobState,
    ExecutorSubmissionError,
    LocalExecutor,
    LSFExecutor,
    get_executor,
)


def test_get_executor_local_returns_local_executor() -> None:
    """mode=local 应返回 LocalExecutor。"""
    executor = get_executor("local", max_parallel_jobs=3)
    assert isinstance(executor, LocalExecutor)


def test_get_executor_lsf_requires_queue_raises_value_error() -> None:
    """LSF/cluster 模式缺少 queue 应抛 ValueError。"""
    with pytest.raises(ValueError) as excinfo:
        get_executor("lsf")
    assert "queue" in str(excinfo.value).lower()


def test_get_executor_lsf_returns_lsf_executor() -> None:
    """mode=lsf 且提供 queue 应返回 LSFExecutor。"""
    executor = get_executor("cluster", queue="normal")
    assert isinstance(executor, LSFExecutor)


def test_get_executor_unknown_mode_raises_value_error() -> None:
    """未知 mode 应抛 ValueError。"""
    with pytest.raises(ValueError):
        get_executor("slurm_only")


@patch("flow.executors.backends.lsf_executor.subprocess.run")
def test_lsf_submit_job_extracts_job_id_from_bsub_stdout(
    mock_run: MagicMock,
    tmp_path,
) -> None:
    """bsub 成功时应用正则从 stdout 提取 Job ID。"""
    script = tmp_path / "eda.sh"
    script.write_text("#!/bin/bash\ntrue\n")

    completed = MagicMock()
    completed.returncode = 0
    completed.stdout = "Job <9527> is submitted to queue <normal>."
    completed.stderr = ""
    mock_run.return_value = completed

    executor = LSFExecutor(queue="normal")
    job_id = executor.submit_job(str(script), str(tmp_path / "out.log"))

    assert job_id == "9527"
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "bsub"
    assert "-q" in cmd
    assert "normal" in cmd


@patch("flow.executors.backends.lsf_executor.subprocess.run")
def test_lsf_submit_job_bsub_failure_raises_executor_submission_error(
    mock_run: MagicMock,
    tmp_path,
) -> None:
    """bsub 非零退出应抛 ExecutorSubmissionError。"""
    script = tmp_path / "eda.sh"
    script.write_text("#!/bin/bash\ntrue\n")

    completed = MagicMock()
    completed.returncode = 255
    completed.stdout = ""
    completed.stderr = "bad queue"
    mock_run.return_value = completed

    executor = LSFExecutor(queue="bad")
    with pytest.raises(ExecutorSubmissionError):
        executor.submit_job(str(script), str(tmp_path / "log.txt"))


@patch("flow.executors.backends.lsf_executor.subprocess.run")
def test_lsf_check_status_parses_run_done_exit(mock_run: MagicMock) -> None:
    """bjobs 输出应解析为 RUN / DONE / EXIT。"""
    executor = LSFExecutor(queue="normal")

    def _side_effect(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        if cmd[-1] == "100":
            result.stdout = "JOBID USER STAT QUEUE\n100 u1 RUN normal\n"
        elif cmd[-1] == "200":
            result.stdout = "JOBID USER STAT QUEUE\n200 u1 DONE normal\n"
        elif cmd[-1] == "300":
            result.stdout = "JOBID USER STAT QUEUE\n300 u1 EXIT normal\n"
        else:
            result.stdout = ""
        result.stderr = ""
        return result

    mock_run.side_effect = _side_effect

    assert executor.check_status("100") == ExecutorJobState.RUN.value
    assert executor.check_status("200") == ExecutorJobState.DONE.value
    assert executor.check_status("300") == ExecutorJobState.EXIT.value


@patch("flow.executors.backends.lsf_executor.subprocess.run")
def test_lsf_submit_job_inject_flow_isolation_writes_wrapper_and_calls_bsub(
    mock_run: MagicMock,
    tmp_path,
) -> None:
    """inject_flow_isolation 时应在日志目录生成包装脚本并提交该脚本。"""
    user_proj = tmp_path / "proj"
    user_proj.mkdir()
    script = user_proj / "runme.sh"
    script.write_text("#!/bin/bash\ntrue\n", encoding="utf-8")
    log_path = user_proj / "logs" / "out.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    completed = MagicMock()
    completed.returncode = 0
    completed.stdout = "Job <100> is submitted to queue <normal>."
    completed.stderr = ""
    mock_run.return_value = completed

    executor = LSFExecutor(queue="normal")
    executor.submit_job(
        str(script),
        str(log_path),
        user_project_cwd=str(user_proj),
        inject_flow_isolation=True,
    )

    wrapper = log_path.parent / "lsf_cluster_launcher_runme.sh"
    assert wrapper.is_file()
    text = wrapper.read_text(encoding="utf-8")
    assert "cd \"" in text
    assert 'source "$FLOW_ROOT/env.sh"' in text
    assert "exec bash" in text

    submitted = mock_run.call_args[0][0][-1]
    assert Path(submitted) == wrapper


def test_lsf_inject_flow_isolation_requires_user_project_cwd(tmp_path) -> None:
    """打开隔离但未提供 user_project_cwd 应抛 ValueError。"""
    script = tmp_path / "eda.sh"
    script.write_text("#!/bin/bash\ntrue\n", encoding="utf-8")
    executor = LSFExecutor(queue="normal")
    with pytest.raises(ValueError):
        executor.submit_job(
            str(script),
            str(tmp_path / "out.log"),
            inject_flow_isolation=True,
        )
