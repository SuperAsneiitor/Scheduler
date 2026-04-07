"""任务调度器：维护运行中任务集合、并发槽位与监控轮询。"""

from __future__ import annotations

import logging
import threading
from typing import List

from flow.spec.task_models import TaskNode, TaskStatus

from flow.runtime.orchestrator.monitor import JobMonitor, JobStatus, JobStatusReport

logger = logging.getLogger(__name__)


class TaskScheduler:
    """在并发上限内跟踪 RUNNING 任务，并结合 :class:`JobMonitor` 推进状态。"""

    def __init__(
        self,
        max_concurrent_slots: int,
        job_monitor: JobMonitor,
    ) -> None:
        """初始化调度器。

        Args:
            max_concurrent_slots: 全局并发槽位上限。
            job_monitor: 作业监控器实例。

        Raises:
            ValueError: 槽位数非法。
        """
        if max_concurrent_slots < 1:
            raise ValueError("max_concurrent_slots 必须 >= 1")
        self._max_slots = max_concurrent_slots
        self._job_monitor = job_monitor
        self._lock = threading.RLock()
        self._running_jobs: List[TaskNode] = []
        self._slots_in_use = 0

    @property
    def running_jobs(self) -> List[TaskNode]:
        """运行中任务列表的浅拷贝（只读视图）。"""
        with self._lock:
            return list(self._running_jobs)

    @property
    def available_slots(self) -> int:
        """当前可用槽位数。"""
        with self._lock:
            return max(0, self._max_slots - self._slots_in_use)

    def register_running_job(self, task_node: TaskNode) -> None:
        """将已提交执行的任务登记为 RUNNING 并占用一个槽位。

        Args:
            task_node: 需已设置 ``workspace_path``，且 ``status`` 建议为 RUNNING。

        Raises:
            RuntimeError: 无可用槽位。
            ValueError: 缺少 ``workspace_path``。
        """
        if task_node.workspace_path is None:
            raise ValueError("register_running_job 需要 TaskNode.workspace_path")
        with self._lock:
            if self._slots_in_use >= self._max_slots:
                raise RuntimeError("并发槽位已满，拒绝登记新任务")
            self._slots_in_use += 1
            self._running_jobs.append(task_node)
            task_node.status = TaskStatus.RUNNING
        logger.info(
            "任务登记为运行中: task_id=%s slots_in_use=%s/%s",
            task_node.task_id,
            self._slots_in_use,
            self._max_slots,
        )

    def update_all_jobs_status(self) -> None:
        """轮询所有运行中任务：更新 :class:`TaskNode` 状态并在终态释放槽位。"""
        with self._lock:
            snapshot = list(self._running_jobs)

        remaining: List[TaskNode] = []
        for task in snapshot:
            report = self._job_monitor.get_latest_status(task)
            self._apply_monitor_report(task, report)
            if self._is_terminal_monitor_status(report.monitor_status):
                self._finalize_job(task, report)
            else:
                remaining.append(task)

        with self._lock:
            self._running_jobs = remaining

    def _apply_monitor_report(self, task: TaskNode, report: JobStatusReport) -> None:
        """将监控语义映射到 DAG :class:`TaskStatus`。"""
        mapped = self._map_to_task_status(report.monitor_status)
        task.status = mapped
        if report.ppa_data:
            logger.debug(
                "任务 %s PPA 更新: %s",
                task.task_id,
                report.ppa_data,
            )
        if report.message:
            logger.info("任务 %s 监控说明: %s", task.task_id, report.message)

    def _finalize_job(self, task: TaskNode, report: JobStatusReport) -> None:
        """终态任务释放槽位并记录日志。"""
        with self._lock:
            if self._slots_in_use <= 0:
                logger.error("槽位计数异常，拒绝释放: task_id=%s", task.task_id)
                return
            self._slots_in_use -= 1
        logger.info(
            "任务进入终态并释放槽位: task_id=%s monitor=%s slots_in_use=%s/%s",
            task.task_id,
            report.monitor_status.value,
            self._slots_in_use,
            self._max_slots,
        )

    @staticmethod
    def _map_to_task_status(monitor_status: JobStatus) -> TaskStatus:
        """监控状态 -> DAG 任务状态。"""
        if monitor_status == JobStatus.SUCCESS:
            return TaskStatus.SUCCESS
        if monitor_status in (JobStatus.FAILED, JobStatus.TIMEOUT_FAILED):
            return TaskStatus.FAILED
        if monitor_status == JobStatus.RUNNING:
            return TaskStatus.RUNNING
        if monitor_status == JobStatus.NOT_STARTED:
            return TaskStatus.RUNNING
        raise ValueError(f"未覆盖的监控状态: {monitor_status}")

    @staticmethod
    def _is_terminal_monitor_status(monitor_status: JobStatus) -> bool:
        """判定是否应移出 ``running_jobs`` 并释放槽位。"""
        return monitor_status in (
            JobStatus.SUCCESS,
            JobStatus.FAILED,
            JobStatus.TIMEOUT_FAILED,
        )
