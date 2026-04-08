"""调度器 + 监控器集成测试（临时目录模拟工作区，不启动真实 EDA）。"""

import os
import time
from pathlib import Path

import pytest

from flow_controller.spec.task_models import TaskNode, TaskStatus, TaskType
from flow_controller.runtime.orchestrator.monitor import JobMonitor, JobStatus
from flow_controller.runtime.orchestrator.scheduler import TaskScheduler


def test_scheduler_closed_loop_running_then_success_releases_slot(tmp_path: Path) -> None:
    """提交 -> .running -> RUNNING；写入 status.json -> SUCCESS -> 移出队列并释放槽位。"""
    workspace = tmp_path / "ws1"
    workspace.mkdir()

    monitor = JobMonitor(running_timeout_seconds=3600.0)
    scheduler = TaskScheduler(max_concurrent_slots=1, job_monitor=monitor)

    task = TaskNode(
        task_id="job_1",
        task_type=TaskType.DRC,
        status=TaskStatus.READY,
        upstream_dependencies=[],
        workspace_path=workspace,
    )

    (workspace / ".running").write_text("pid=123\n", encoding="utf-8")

    scheduler.register_running_job(task)
    assert scheduler.available_slots == 0
    assert len(scheduler.running_jobs) == 1

    scheduler.update_all_jobs_status()
    assert task.status == TaskStatus.RUNNING
    assert len(scheduler.running_jobs) == 1

    (workspace / "status.json").write_text(
        '{"status": "Success", "ppa": {"area": 1.23}}',
        encoding="utf-8",
    )

    scheduler.update_all_jobs_status()
    assert task.status == TaskStatus.SUCCESS
    assert len(scheduler.running_jobs) == 0
    assert scheduler.available_slots == 1


def test_monitor_corrupt_status_json_falls_back_to_running_flag(tmp_path: Path) -> None:
    """损坏的 status.json 不抛异常，回退到 .running 判定为 RUNNING。"""
    workspace = tmp_path / "ws_bad"
    workspace.mkdir()
    (workspace / ".running").write_text("x", encoding="utf-8")
    (workspace / "status.json").write_text("{not json", encoding="utf-8")

    monitor = JobMonitor(running_timeout_seconds=60.0)
    task = TaskNode(
        task_id="t_bad_json",
        task_type=TaskType.DRC,
        status=TaskStatus.RUNNING,
        upstream_dependencies=[],
        workspace_path=workspace,
    )
    report = monitor.get_latest_status(task)
    assert report.monitor_status == JobStatus.RUNNING


def test_monitor_partial_json_missing_status_field_is_invalid(tmp_path: Path) -> None:
    """仅有一半字段（缺 status）应视为无效 JSON 负载并回退。"""
    workspace = tmp_path / "ws_half"
    workspace.mkdir()
    (workspace / ".running").write_text("x", encoding="utf-8")
    (workspace / "status.json").write_text('{"ppa": {}}', encoding="utf-8")

    monitor = JobMonitor(running_timeout_seconds=60.0)
    task = TaskNode(
        task_id="t_half",
        task_type=TaskType.DRC,
        status=TaskStatus.RUNNING,
        upstream_dependencies=[],
        workspace_path=workspace,
    )
    report = monitor.get_latest_status(task)
    assert report.monitor_status == JobStatus.RUNNING


def test_monitor_running_flag_timeout_returns_timeout_failed(tmp_path: Path) -> None:
    """``.running`` 过旧且仍无有效 status.json -> TIMEOUT_FAILED。"""
    workspace = tmp_path / "ws_timeout"
    workspace.mkdir()
    running_file = workspace / ".running"
    running_file.write_text("x", encoding="utf-8")
    old = time.time() - 100.0
    os.utime(running_file, (old, old))

    monitor = JobMonitor(running_timeout_seconds=10.0)
    task = TaskNode(
        task_id="t_to",
        task_type=TaskType.DRC,
        status=TaskStatus.RUNNING,
        upstream_dependencies=[],
        workspace_path=workspace,
    )
    report = monitor.get_latest_status(task)
    assert report.monitor_status == JobStatus.TIMEOUT_FAILED


def test_scheduler_timeout_final_state_releases_slot(tmp_path: Path) -> None:
    """TIMEOUT_FAILED 为终态，应从 running_jobs 移除并释放槽位。"""
    workspace = tmp_path / "ws_to_sched"
    workspace.mkdir()
    running_file = workspace / ".running"
    running_file.write_text("x", encoding="utf-8")
    old = time.time() - 100.0
    os.utime(running_file, (old, old))

    monitor = JobMonitor(running_timeout_seconds=10.0)
    scheduler = TaskScheduler(max_concurrent_slots=1, job_monitor=monitor)

    task = TaskNode(
        task_id="job_to",
        task_type=TaskType.DRC,
        status=TaskStatus.RUNNING,
        upstream_dependencies=[],
        workspace_path=workspace,
    )
    scheduler.register_running_job(task)
    assert scheduler.available_slots == 0

    scheduler.update_all_jobs_status()
    assert task.status == TaskStatus.FAILED
    assert len(scheduler.running_jobs) == 0
    assert scheduler.available_slots == 1


def test_monitor_status_json_failed_maps_to_failed(tmp_path: Path) -> None:
    """status.json 标记 Failed -> 监控 FAILED。"""
    workspace = tmp_path / "ws_fail"
    workspace.mkdir()
    (workspace / "status.json").write_text(
        '{"status": "Failed", "ppa": {}}',
        encoding="utf-8",
    )

    monitor = JobMonitor(running_timeout_seconds=60.0)
    task = TaskNode(
        task_id="t_fail",
        task_type=TaskType.DRC,
        status=TaskStatus.RUNNING,
        upstream_dependencies=[],
        workspace_path=workspace,
    )
    report = monitor.get_latest_status(task)
    assert report.monitor_status == JobStatus.FAILED
