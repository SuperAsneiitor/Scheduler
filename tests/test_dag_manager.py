"""DAGManager 与 TaskNode 的单元测试（Mock 外部集群，仅内存图逻辑）。"""

import pytest

from flow import DAGManager, TaskNode, TaskStatus, TaskType
from flow.graph.exceptions import CyclicDependencyError


def test_get_ready_tasks_gds_drc_pex_chain_returns_next_pending_after_upstream_success() -> None:
    """GDS -> DRC -> PEX 串联：仅当前置全部 Success 时释放下一 Pending。"""
    manager = DAGManager()

    gds = TaskNode(
        task_id="job_gds",
        task_type=TaskType.GDS_EXPORT,
        status=TaskStatus.PENDING,
        upstream_dependencies=[],
    )
    drc = TaskNode(
        task_id="job_drc",
        task_type=TaskType.DRC,
        status=TaskStatus.PENDING,
        upstream_dependencies=["job_gds"],
    )
    pex = TaskNode(
        task_id="job_pex",
        task_type=TaskType.PEX,
        status=TaskStatus.PENDING,
        upstream_dependencies=["job_drc"],
    )

    manager.add_task_and_dependencies(gds)
    manager.add_task_and_dependencies(drc)
    manager.add_task_and_dependencies(pex)

    ready_initial = manager.get_ready_tasks()
    assert len(ready_initial) == 1
    assert ready_initial[0].task_id == "job_gds"

    manager.update_task_status("job_gds", TaskStatus.SUCCESS)
    ready_after_gds = manager.get_ready_tasks()
    assert {n.task_id for n in ready_after_gds} == {"job_drc"}

    manager.update_task_status("job_drc", TaskStatus.SUCCESS)
    ready_after_drc = manager.get_ready_tasks()
    assert {n.task_id for n in ready_after_drc} == {"job_pex"}


def test_add_task_and_dependencies_raises_cyclic_dependency_error_when_cycle_formed() -> None:
    """A->B 且 B->A 时必须在增量加边后检测到环并抛 CyclicDependencyError。"""
    manager = DAGManager()
    task_a = TaskNode(
        task_id="A",
        task_type=TaskType.DRC,
        status=TaskStatus.PENDING,
        upstream_dependencies=[],
    )
    task_b = TaskNode(
        task_id="B",
        task_type=TaskType.PEX,
        status=TaskStatus.PENDING,
        upstream_dependencies=["A"],
    )
    manager.add_task_and_dependencies(task_a)
    manager.add_task_and_dependencies(task_b)

    task_a_cycle = TaskNode(
        task_id="A",
        task_type=TaskType.DRC,
        status=TaskStatus.PENDING,
        upstream_dependencies=["B"],
    )
    with pytest.raises(CyclicDependencyError):
        manager.add_task_and_dependencies(task_a_cycle)


def test_update_task_status_unknown_task_raises_key_error() -> None:
    """更新不存在的任务应抛出 KeyError。"""
    manager = DAGManager()
    with pytest.raises(KeyError):
        manager.update_task_status("missing", TaskStatus.SUCCESS)


def test_get_ready_tasks_skips_pending_when_upstream_not_all_success() -> None:
    """上游存在非 Success 时，下游 Pending 不应出现在就绪列表。"""
    manager = DAGManager()
    manager.add_task_and_dependencies(
        TaskNode(
            task_id="u1",
            task_type=TaskType.GDS_EXPORT,
            status=TaskStatus.SUCCESS,
            upstream_dependencies=[],
        )
    )
    manager.add_task_and_dependencies(
        TaskNode(
            task_id="u2",
            task_type=TaskType.DRC,
            status=TaskStatus.FAILED,
            upstream_dependencies=[],
        )
    )
    manager.add_task_and_dependencies(
        TaskNode(
            task_id="t",
            task_type=TaskType.PEX,
            status=TaskStatus.PENDING,
            upstream_dependencies=["u1", "u2"],
        )
    )
    assert manager.get_ready_tasks() == []
