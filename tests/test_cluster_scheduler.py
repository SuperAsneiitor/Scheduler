"""ClusterScheduler 单元测试（不调用真实 bsub/sbatch/subprocess）。"""

import asyncio

import pytest

from flow import TaskNode, TaskStatus, TaskType
from flow.cluster.scheduler import (
    ClusterScheduler,
    SubmitStatus,
    TaskSubmitResult,
    simulate_concurrent_submits,
)


def test_submit_task_with_insufficient_resources_returns_waiting() -> None:
    """资源不足时不得扣减池，且返回 WAITING_RESOURCES。"""
    scheduler = ClusterScheduler(
        resource_pool={"cpu_cores": 2, "memory_gb": 4},
    )
    task = TaskNode(
        task_id="t1",
        task_type=TaskType.DRC,
        status=TaskStatus.PENDING,
        upstream_dependencies=[],
    )
    result = scheduler.submit_task(task, required_cpu=4, required_mem=1)
    assert isinstance(result, TaskSubmitResult)
    assert result.status is SubmitStatus.WAITING_RESOURCES
    assert result.cluster_job_id is None
    assert scheduler.get_resource_pool_snapshot() == {"cpu_cores": 2, "memory_gb": 4}
    assert scheduler.get_task_to_cluster_job_mapping() == {}


def test_submit_task_with_sufficient_resources_deducts_pool_and_returns_cluster_job_id() -> None:
    """资源充足时扣减池、生成 lsf_job_* 并写入映射。"""
    scheduler = ClusterScheduler(
        resource_pool={"cpu_cores": 8, "memory_gb": 32},
    )
    task = TaskNode(
        task_id="gds_1",
        task_type=TaskType.GDS_EXPORT,
        status=TaskStatus.PENDING,
        upstream_dependencies=[],
    )
    result = scheduler.submit_task(task, required_cpu=4, required_mem=8)
    assert result.status is SubmitStatus.SUBMITTED
    assert result.cluster_job_id is not None
    assert result.cluster_job_id.startswith("lsf_job_")
    assert scheduler.get_resource_pool_snapshot() == {"cpu_cores": 4, "memory_gb": 24}
    assert scheduler.get_task_to_cluster_job_mapping() == {"gds_1": result.cluster_job_id}


def test_submit_task_duplicate_task_id_returns_existing_mapping_without_double_deduct() -> None:
    """同一 task_id 重复提交应幂等：不二次扣资源，返回已有集群 Job ID。"""
    scheduler = ClusterScheduler(
        resource_pool={"cpu_cores": 10, "memory_gb": 10},
    )
    task = TaskNode(
        task_id="same",
        task_type=TaskType.PEX,
        status=TaskStatus.PENDING,
        upstream_dependencies=[],
    )
    first = scheduler.submit_task(task, 2, 2)
    second = scheduler.submit_task(task, 2, 2)
    assert first.cluster_job_id == second.cluster_job_id
    assert scheduler.get_resource_pool_snapshot() == {"cpu_cores": 8, "memory_gb": 8}


def test_submit_task_async_submits_without_blocking_event_loop_contract() -> None:
    """submit_task_async 应返回与同步路径一致的提交结果（不测真实 IO）。"""

    async def _run() -> None:
        scheduler = ClusterScheduler(
            resource_pool={"cpu_cores": 4, "memory_gb": 4},
        )
        task = TaskNode(
            task_id="async_t",
            task_type=TaskType.DRC,
            status=TaskStatus.PENDING,
            upstream_dependencies=[],
        )
        result = await scheduler.submit_task_async(task, 1, 1)
        assert result.status is SubmitStatus.SUBMITTED
        assert result.cluster_job_id is not None

    asyncio.run(_run())


def test_simulate_concurrent_submits_does_not_raise_and_preserves_pool_invariants() -> None:
    """线程池并发提交：锁保护下池不为负、映射条数合理。"""
    scheduler = ClusterScheduler(
        resource_pool={"cpu_cores": 20, "memory_gb": 40},
    )
    tasks = tuple(
        (
            TaskNode(
                task_id=f"conc_{idx}",
                task_type=TaskType.DRC,
                status=TaskStatus.PENDING,
                upstream_dependencies=[],
            ),
            1,
            1,
        )
        for idx in range(10)
    )
    simulate_concurrent_submits(scheduler, tasks, max_workers=5)
    snapshot = scheduler.get_resource_pool_snapshot()
    assert snapshot["cpu_cores"] >= 0
    assert snapshot["memory_gb"] >= 0
    assert len(scheduler.get_task_to_cluster_job_mapping()) == 10


def test_submit_task_invalid_resource_request_raises_value_error() -> None:
    """非法资源请求应抛出 ValueError。"""
    scheduler = ClusterScheduler()
    task = TaskNode(
        task_id="bad",
        task_type=TaskType.DRC,
        status=TaskStatus.PENDING,
        upstream_dependencies=[],
    )
    with pytest.raises(ValueError):
        scheduler.submit_task(task, required_cpu=0, required_mem=1)
