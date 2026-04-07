"""模拟 LSF/Slurm 的集群调度器：资源池与任务提交。"""

from __future__ import annotations

import asyncio
import itertools
import logging
import threading
from copy import deepcopy
from typing import Dict, Optional, Tuple

from flow.spec.task_models import TaskNode

from flow.cluster.scheduler.models import SubmitStatus, TaskSubmitResult

logger = logging.getLogger(__name__)

# 资源池键名（与业务监控/配置对齐）
RESOURCE_CPU_CORES = "cpu_cores"
RESOURCE_MEMORY_GB = "memory_gb"


class ClusterScheduler:
    """将 DAG 就绪任务派发到集群：校验资源、扣减配额、记录 Task→Cluster Job 映射。

    线程安全：资源池与映射表在 ``submit_task`` 内受互斥锁保护，可与
    ``concurrent.futures.ThreadPoolExecutor`` 或多线程调用配合做并发模拟。
    """

    def __init__(
        self,
        resource_pool: Optional[Dict[str, int]] = None,
    ) -> None:
        """初始化调度器与资源池。

        Args:
            resource_pool: 可选初始资源；缺省为 ``cpu_cores=100``, ``memory_gb=500``。
                键应包含 :data:`RESOURCE_CPU_CORES` 与 :data:`RESOURCE_MEMORY_GB`。

        Raises:
            ValueError: 资源值为负数或缺少必需键。
            TypeError: ``resource_pool`` 类型不正确。
        """
        self._lock = threading.RLock()
        self._pool: Dict[str, int] = self._normalize_initial_pool(resource_pool)
        self._task_to_cluster_job: Dict[str, str] = {}
        self._job_id_counter = itertools.count(1)

    def submit_task(
        self,
        task: TaskNode,
        required_cpu: int,
        required_mem: int,
    ) -> TaskSubmitResult:
        """提交单个就绪任务：资源足够则扣减并生成集群 Job ID；否则返回等待。

        真实环境应在 :meth:`_dispatch_cluster_job` 中调用 ``bsub``/``sbatch`` 等。
        此处默认仅模拟，不发起子进程。

        Args:
            task: 通常来自 :meth:`flow.graph.dag_manager.DAGManager.get_ready_tasks`。
            required_cpu: 所需 CPU 核数（正整数）。
            required_mem: 所需内存（GB，正整数，与资源池 ``memory_gb`` 同单位）。

        Returns:
            :class:`TaskSubmitResult`：资源不足为 ``WAITING_RESOURCES``；成功为 ``SUBMITTED`` 并带 ``cluster_job_id``。

        Raises:
            TypeError: ``task`` 不是 :class:`~flow.spec.task_models.TaskNode`。
            ValueError: 资源请求非法。
        """
        if not isinstance(task, TaskNode):
            raise TypeError("task 必须为 TaskNode 实例")
        self._validate_resource_request(required_cpu, required_mem)
        task_id = task.task_id

        with self._lock:
            existing_cluster_id = self._task_to_cluster_job.get(task_id)
            if existing_cluster_id is not None:
                return TaskSubmitResult(
                    status=SubmitStatus.SUBMITTED,
                    cluster_job_id=existing_cluster_id,
                    message="任务已提交，返回已有集群 Job ID（幂等）",
                )

            if not self._has_sufficient_resources(required_cpu, required_mem):
                logger.info(
                    "Insufficient resources for task_id=%s need_cpu=%s need_mem=%s pool=%s",
                    task_id,
                    required_cpu,
                    required_mem,
                    dict(self._pool),
                )
                return TaskSubmitResult(
                    status=SubmitStatus.WAITING_RESOURCES,
                    cluster_job_id=None,
                    message="集群资源不足，任务保持等待",
                )

            self._deduct_resources(required_cpu, required_mem)
            cluster_job_id = self._dispatch_cluster_job(task, required_cpu, required_mem)
            self._task_to_cluster_job[task_id] = cluster_job_id

        logger.info(
            "Cluster job dispatched: task_id=%s cluster_job_id=%s remaining_pool=%s",
            task_id,
            cluster_job_id,
            dict(self._pool),
        )
        return TaskSubmitResult(
            status=SubmitStatus.SUBMITTED,
            cluster_job_id=cluster_job_id,
            message="已占用资源并完成集群提交（模拟）",
        )

    async def submit_task_async(
        self,
        task: TaskNode,
        required_cpu: int,
        required_mem: int,
    ) -> TaskSubmitResult:
        """异步封装：在线程池中执行 :meth:`submit_task`，避免阻塞事件循环。

        Args:
            task: 就绪任务节点。
            required_cpu: 所需 CPU 核数。
            required_mem: 所需内存（GB）。

        Returns:
            与 :meth:`submit_task` 相同。

        Raises:
            与 :meth:`submit_task` 相同。
        """
        return await asyncio.to_thread(self.submit_task, task, required_cpu, required_mem)

    def get_task_to_cluster_job_mapping(self) -> Dict[str, str]:
        """返回系统 Task ID → 集群 Job ID 映射的浅拷贝（便于监控模块读取）。"""
        with self._lock:
            return dict(self._task_to_cluster_job)

    def get_resource_pool_snapshot(self) -> Dict[str, int]:
        """返回当前资源池快照（拷贝），用于观测与测试断言。"""
        with self._lock:
            return dict(self._pool)

    def _normalize_initial_pool(
        self,
        resource_pool: Optional[Dict[str, int]],
    ) -> Dict[str, int]:
        if resource_pool is None:
            return {
                RESOURCE_CPU_CORES: 100,
                RESOURCE_MEMORY_GB: 500,
            }
        if not isinstance(resource_pool, dict):
            raise TypeError("resource_pool 必须为 dict")

        pool = deepcopy(resource_pool)
        required_keys = (RESOURCE_CPU_CORES, RESOURCE_MEMORY_GB)
        for key in required_keys:
            if key not in pool:
                raise ValueError(f"resource_pool 缺少键: {key}")
            value = pool[key]
            if not isinstance(value, int):
                raise TypeError(f"{key} 必须为 int")
            if value < 0:
                raise ValueError(f"{key} 不能为负数")
        return pool

    def _validate_resource_request(self, required_cpu: int, required_mem: int) -> None:
        if not isinstance(required_cpu, int) or not isinstance(required_mem, int):
            raise TypeError("required_cpu 与 required_mem 必须为 int")
        if required_cpu <= 0 or required_mem <= 0:
            raise ValueError("required_cpu 与 required_mem 必须为正整数")

    def _has_sufficient_resources(self, required_cpu: int, required_mem: int) -> bool:
        return (
            self._pool[RESOURCE_CPU_CORES] >= required_cpu
            and self._pool[RESOURCE_MEMORY_GB] >= required_mem
        )

    def _deduct_resources(self, required_cpu: int, required_mem: int) -> None:
        self._pool[RESOURCE_CPU_CORES] -= required_cpu
        self._pool[RESOURCE_MEMORY_GB] -= required_mem

    def _dispatch_cluster_job(
        self,
        task: TaskNode,
        required_cpu: int,
        required_mem: int,
    ) -> str:
        """向集群投递作业并解析集群 Job ID。

        生产环境应在此构造 ``bsub`` / ``sbatch`` 等命令并通过 ``subprocess.run`` 提交，
        再从标准输出解析 Job ID。以下为占位说明，勿在单元测试中依赖真实外部命令。

        示例（LSF ``bsub``，仅作接口占位，默认不执行）::

            # import subprocess
            #
            # completed = subprocess.run(
            #     [
            #         "bsub",
            #         "-J",
            #         task.task_id,
            #         "-n",
            #         str(required_cpu),
            #         "-R",
            #         f"rusage[mem={required_mem}]",
            #         "your_eda_wrapper.sh",
            #     ],
            #     capture_output=True,
            #     text=True,
            #     check=True,
            # )
            # return self._parse_lsf_job_id_from_bsub_stdout(completed.stdout)

        Args:
            task: 业务任务节点（用于作业名、日志上下文等）。
            required_cpu: 申请核数。
            required_mem: 申请内存（GB）。

        Returns:
            集群侧 Job ID 字符串。
        """
        _ = (required_cpu, required_mem)
        logger.debug(
            "Dispatch placeholder for task_id=%s task_type=%s",
            task.task_id,
            task.task_type.value,
        )
        return self._generate_mock_lsf_job_id()

    def _generate_mock_lsf_job_id(self) -> str:
        """生成模拟的 LSF 风格 Job ID（单机测试与演示用）。"""
        next_id = next(self._job_id_counter)
        return f"lsf_job_{next_id:04d}"


def simulate_concurrent_submits(
    scheduler: ClusterScheduler,
    payloads: Tuple[Tuple[TaskNode, int, int], ...],
    max_workers: int = 4,
) -> None:
    """使用线程池并发调用 ``submit_task``，用于压测调度器锁与资源扣减（可选工具函数）。

    Args:
        scheduler: 调度器实例。
        payloads: 元组序列 ``(task, required_cpu, required_mem)``。
        max_workers: 线程池大小。

    Note:
        此为辅助函数；生产路径请使用业务层编排。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _run(item: Tuple[TaskNode, int, int]) -> TaskSubmitResult:
        task_node, cpu, mem = item
        return scheduler.submit_task(task_node, cpu, mem)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_run, payload) for payload in payloads]
        for future in as_completed(futures):
            future.result()
