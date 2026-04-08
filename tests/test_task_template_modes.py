"""TaskTemplate + Mode 组合测试（mock LSF/local 执行器）。"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from flow_controller import DAGManager, TaskNode, TaskStatus, TaskType
from flow_controller.executors.backends.local_executor import LocalExecutor
from flow_controller.executors.backends.lsf_executor import LSFExecutor
from flow_controller.runtime.local_orchestrator import LocalFlowOrchestrator
from flow_controller.runtime.modes.local_mode import LocalMode
from flow_controller.runtime.modes.lsf_mode import LsfMode
from flow_controller.runtime.workspace_manager import WorkspaceManager


def test_task_template_local_mode_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    dag = DAGManager()
    dag.add_task_and_dependencies(
        TaskNode(task_id="t", task_type=TaskType.DRC, status=TaskStatus.PENDING, upstream_dependencies=[]),
    )
    wm = WorkspaceManager(cwd=tmp_path)
    executor = LocalExecutor(max_parallel_jobs=1)
    with patch.object(executor, "submit_job", new=AsyncMock(return_value="local_job_0001")):
        with patch.object(executor, "check_status", return_value="DONE"):
            mode = LocalMode(executor, commands={"t": ["python", "-c", "print(1)"]})
            orch = LocalFlowOrchestrator.with_default_template(wm, mode=mode)
            assert orch.run(dag, dry_run=False) == 0
            assert dag.get_task("t").status == TaskStatus.SUCCESS


def test_task_template_lsf_mode_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    dag = DAGManager()
    dag.add_task_and_dependencies(
        TaskNode(task_id="t", task_type=TaskType.DRC, status=TaskStatus.PENDING, upstream_dependencies=[]),
    )
    wm = WorkspaceManager(cwd=tmp_path)

    executor = LSFExecutor(queue="q")
    # mock submit_job/check_status：不触发真实 bsub/bjobs
    with patch.object(executor, "submit_job", return_value="123"):
        with patch.object(executor, "check_status", side_effect=["RUN", "DONE"]):
            scripts = {"t": tmp_path / "runme.sh"}
            scripts["t"].write_text("#!/bin/bash\necho hi\n", encoding="utf-8")
            mode = LsfMode(executor, job_scripts=scripts, poll_interval_seconds=0.0, max_polls=3, user_project_cwd=wm.user_cwd)
            orch = LocalFlowOrchestrator.with_default_template(wm, mode=mode)
            assert orch.run(dag, dry_run=False) == 0
            assert dag.get_task("t").status == TaskStatus.SUCCESS

