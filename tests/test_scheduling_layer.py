"""调度层（第一层）：glob 契约、DefaultSchedulingNode、LocalFlowOrchestrator。"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sys_config import load_execution_config_from_mapping
from flow_controller import DAGManager, TaskNode, TaskStatus, TaskType
from flow_controller.executors.backends import LocalExecutor
from flow_controller.runtime.artifact_globs import expand_glob_pattern, require_patterns_match
from flow_controller.runtime.exceptions import NodeArtifactCheckError
from flow_controller.runtime.local_orchestrator import LocalFlowOrchestrator
from flow_controller.runtime.node_runtime import DefaultSchedulingNode
from flow_controller.runtime.modes.local_mode import LocalMode
from flow_controller.runtime.workspace_manager import WorkspaceManager


def test_expand_glob_pattern_finds_file(tmp_path: Path) -> None:
    """相对模式应在 base 下命中已存在文件。"""
    target = tmp_path / "a.txt"
    target.write_text("x", encoding="utf-8")
    found = expand_glob_pattern("a.txt", tmp_path)
    assert found
    assert found[0].resolve() == target.resolve()


def test_require_patterns_match_raises_when_missing(tmp_path: Path) -> None:
    """无匹配时应抛出 NodeArtifactCheckError。"""
    with pytest.raises(NodeArtifactCheckError):
        require_patterns_match(
            ["no_such_file_*.xyz"],
            tmp_path,
            task_id="t1",
            kind="inputs",
        )


def test_default_scheduling_node_check_inputs_ready_ok(tmp_path: Path) -> None:
    """inputs 全部命中时不抛异常。"""
    (tmp_path / "in.txt").write_text("ok", encoding="utf-8")
    node = TaskNode(
        task_id="n1",
        task_type=TaskType.DRC,
        status=TaskStatus.PENDING,
        upstream_dependencies=[],
        inputs=["in.txt"],
    )
    wm = WorkspaceManager(cwd=tmp_path)
    sn = DefaultSchedulingNode()
    _ = sn.prepare_workspace(node, wm)
    sn.check_inputs_ready(node, tmp_path)


def test_default_scheduling_node_check_inputs_ready_missing(tmp_path: Path) -> None:
    """inputs 未命中时应失败。"""
    node = TaskNode(
        task_id="n2",
        task_type=TaskType.DRC,
        status=TaskStatus.PENDING,
        upstream_dependencies=[],
        inputs=["missing.bin"],
    )
    wm = WorkspaceManager(cwd=tmp_path)
    sn = DefaultSchedulingNode()
    _ = sn.prepare_workspace(node, wm)
    with pytest.raises(NodeArtifactCheckError):
        sn.check_inputs_ready(node, tmp_path)


def test_local_flow_orchestrator_placeholder_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """无 inputs/outputs、无 command 的占位任务应收官为成功。"""
    monkeypatch.chdir(tmp_path)
    dag = DAGManager()
    dag.add_task_and_dependencies(
        TaskNode(
            task_id="only",
            task_type=TaskType.DRC,
            status=TaskStatus.PENDING,
            upstream_dependencies=[],
        ),
    )
    wm = WorkspaceManager(cwd=tmp_path)
    exec_cfg = load_execution_config_from_mapping(
        {"mode": "local", "local_settings": {"max_parallel_jobs": 1}},
    )
    executor = LocalExecutor.from_execution_config(exec_cfg)
    mode = LocalMode(executor, commands={})
    orch = LocalFlowOrchestrator.with_default_template(wm, mode=mode)
    code = orch.run(dag, dry_run=False)
    assert code == 0
    only = dag.get_task("only")
    assert only is not None
    assert only.status == TaskStatus.SUCCESS


def test_local_flow_orchestrator_input_gate_fails_before_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """inputs 不满足时任务应 FAILED，且不启动占位 sleep 以外的副作用。"""
    monkeypatch.chdir(tmp_path)
    dag = DAGManager()
    dag.add_task_and_dependencies(
        TaskNode(
            task_id="bad_in",
            task_type=TaskType.DRC,
            status=TaskStatus.PENDING,
            upstream_dependencies=[],
            inputs=["nope.txt"],
        ),
    )
    wm = WorkspaceManager(cwd=tmp_path)
    exec_cfg = load_execution_config_from_mapping(
        {"mode": "local", "local_settings": {"max_parallel_jobs": 1}},
    )
    executor = LocalExecutor.from_execution_config(exec_cfg)
    mode = LocalMode(executor, commands={})
    orch = LocalFlowOrchestrator.with_default_template(wm, mode=mode)
    code = orch.run(dag, dry_run=False)
    assert code == 2
    node = dag.get_task("bad_in")
    assert node is not None
    assert node.status == TaskStatus.FAILED


def test_local_flow_orchestrator_output_gate_after_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """命令成功后校验 outputs；写入产物后应收官 SUCCESS。"""
    monkeypatch.chdir(tmp_path)
    dag = DAGManager()
    dag.add_task_and_dependencies(
        TaskNode(
            task_id="out1",
            task_type=TaskType.DRC,
            status=TaskStatus.PENDING,
            upstream_dependencies=[],
            outputs=["result.txt"],
        ),
    )
    wm = WorkspaceManager(cwd=tmp_path)
    exec_cfg = load_execution_config_from_mapping(
        {"mode": "local", "local_settings": {"max_parallel_jobs": 1}},
    )
    executor = LocalExecutor.from_execution_config(exec_cfg)
    job_dir = tmp_path / "jobs" / "out1"
    out_file = job_dir / "result.txt"
    py = (
        "from pathlib import Path\n"
        f"p = Path({str(out_file)!r})\n"
        "p.parent.mkdir(parents=True, exist_ok=True)\n"
        "p.write_text('ok', encoding='utf-8')\n"
    )
    commands = {"out1": [sys.executable, "-c", py]}
    mode = LocalMode(executor, commands=commands)
    orch = LocalFlowOrchestrator.with_default_template(wm, mode=mode)
    code = orch.run(dag, dry_run=False)
    assert code == 0
    node = dag.get_task("out1")
    assert node is not None
    assert node.status == TaskStatus.SUCCESS
    assert out_file.is_file()


def test_local_flow_orchestrator_output_gate_fails_when_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """声明 outputs 但命令未生成时应 FAILED。"""
    monkeypatch.chdir(tmp_path)
    dag = DAGManager()
    dag.add_task_and_dependencies(
        TaskNode(
            task_id="out2",
            task_type=TaskType.DRC,
            status=TaskStatus.PENDING,
            upstream_dependencies=[],
            outputs=["never_created.txt"],
        ),
    )
    wm = WorkspaceManager(cwd=tmp_path)
    exec_cfg = load_execution_config_from_mapping(
        {"mode": "local", "local_settings": {"max_parallel_jobs": 1}},
    )
    executor = LocalExecutor.from_execution_config(exec_cfg)
    commands = {"out2": [sys.executable, "-c", "print('no file')"]}
    mode = LocalMode(executor, commands=commands)
    orch = LocalFlowOrchestrator.with_default_template(wm, mode=mode)
    code = orch.run(dag, dry_run=False)
    assert code == 2
    node = dag.get_task("out2")
    assert node is not None
    assert node.status == TaskStatus.FAILED


def test_local_flow_orchestrator_mock_executor_skips_real_subprocess(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock submit_job 时仍应走 outputs 校验逻辑。"""
    monkeypatch.chdir(tmp_path)
    dag = DAGManager()
    dag.add_task_and_dependencies(
        TaskNode(
            task_id="mocked",
            task_type=TaskType.DRC,
            status=TaskStatus.PENDING,
            upstream_dependencies=[],
            outputs=["w.txt"],
        ),
    )
    wm = WorkspaceManager(cwd=tmp_path)
    executor = LocalExecutor(max_parallel_jobs=1)
    ws = wm.create_job_dir("mocked")
    (ws / "w.txt").write_text("x", encoding="utf-8")

    with patch.object(executor, "submit_job", new=AsyncMock(return_value="local_job_0001")):
        with patch.object(executor, "check_status", return_value="DONE"):
            mode = LocalMode(executor, commands={"mocked": [sys.executable, "-c", "print(1)"]})
            orch = LocalFlowOrchestrator.with_default_template(wm, mode=mode)
            code = orch.run(dag, dry_run=False)

    assert code == 0
    assert dag.get_task("mocked").status == TaskStatus.SUCCESS


def test_dag_manager_iter_tasks_includes_all_nodes() -> None:
    """iter_tasks 应包含已注册的全部节点。"""
    m = DAGManager()
    m.add_task_and_dependencies(
        TaskNode(task_id="a", task_type=TaskType.DRC, status=TaskStatus.PENDING, upstream_dependencies=[]),
    )
    m.add_task_and_dependencies(
        TaskNode(task_id="b", task_type=TaskType.PEX, status=TaskStatus.PENDING, upstream_dependencies=["a"]),
    )
    ids = {n.task_id for n in m.iter_tasks()}
    assert ids == {"a", "b"}
