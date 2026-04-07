"""作业监控：基于 ``status.json`` 与 ``.running`` 标志文件推断任务状态。"""

from __future__ import annotations

import json
import logging
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field, ValidationError, field_validator

from flow.spec.task_models import TaskNode

logger = logging.getLogger(__name__)

STATUS_JSON_NAME = "status.json"
RUNNING_FLAG_NAME = ".running"


class JobStatus(str, Enum):
    """监控器语义状态（与 :class:`~flow.spec.task_models.TaskStatus` 区分：含超时与未启动）。"""

    SUCCESS = "Success"
    FAILED = "Failed"
    RUNNING = "Running"
    TIMEOUT_FAILED = "TimeoutFailed"
    NOT_STARTED = "NotStarted"


class StatusJsonPayload(BaseModel):
    """``status.json`` 的受控结构；用于防御不完整或类型错乱的输入。"""

    status: str = Field(..., min_length=1, description="Success 或 Failed（大小写不敏感）")
    ppa: Dict[str, float] = Field(default_factory=dict, description="PPA 指标键值")

    model_config = {"frozen": True}

    @field_validator("status")
    @classmethod
    def _normalize_status(cls, value: str) -> str:
        normalized = str(value).strip()
        upper = normalized.upper()
        if upper in ("SUCCESS", "FAILED"):
            return "Success" if upper == "SUCCESS" else "Failed"
        if normalized in ("Success", "Failed"):
            return normalized
        raise ValueError("status 必须为 Success 或 Failed")


class JobStatusReport(BaseModel):
    """对外统一报告：供调度器更新 DAG 节点与释放资源。"""

    job_id: str
    monitor_status: JobStatus
    ppa_data: Dict[str, float] = Field(default_factory=dict)
    message: Optional[str] = None

    model_config = {"frozen": True}


class JobMonitor:
    """基于工作区标志文件轮询任务进度。"""

    def __init__(self, running_timeout_seconds: float) -> None:
        """初始化监控器。

        Args:
            running_timeout_seconds: ``.running`` 存在时允许的最长存活时间（秒），
                超过则判定 :attr:`JobStatus.TIMEOUT_FAILED`。
        """
        if running_timeout_seconds <= 0:
            raise ValueError("running_timeout_seconds 必须为正数")
        self._running_timeout_seconds = float(running_timeout_seconds)

    def get_latest_status(self, job_node: TaskNode) -> JobStatusReport:
        """根据 ``TaskNode.workspace_path`` 生成最新监控报告。

        Args:
            job_node: 必须包含非空 ``workspace_path``。

        Returns:
            :class:`JobStatusReport`。

        Raises:
            TypeError: ``job_node`` 类型错误。
            ValueError: 未配置工作区路径。
        """
        if not isinstance(job_node, TaskNode):
            raise TypeError("job_node 必须为 TaskNode")
        workspace = job_node.workspace_path
        if workspace is None:
            raise ValueError(f"任务 {job_node.task_id} 缺少 workspace_path，无法监控")
        monitor_status = self._determine_status_by_flags(Path(workspace))
        ppa_data: Dict[str, float] = {}
        message: Optional[str] = None

        status_path = Path(workspace) / STATUS_JSON_NAME
        if monitor_status in (JobStatus.SUCCESS, JobStatus.FAILED) and status_path.is_file():
            payload = self._try_parse_status_json(status_path)
            if payload is not None:
                ppa_data = dict(payload.ppa)
                message = None
            else:
                # 理论上不应到达：终态由完整 JSON 解析得到
                message = "status.json 在终态路径上解析异常"

        if monitor_status == JobStatus.TIMEOUT_FAILED:
            message = (
                f".running 超过 {self._running_timeout_seconds:.1f}s 未产出有效 status.json"
            )
        elif monitor_status == JobStatus.NOT_STARTED:
            message = "未检测到 .running 且不存在有效 status.json"

        return JobStatusReport(
            job_id=job_node.task_id,
            monitor_status=monitor_status,
            ppa_data=ppa_data,
            message=message,
        )

    def _determine_status_by_flags(self, workspace_path: Path) -> JobStatus:
        """核心判定：优先完整 ``status.json``，否则根据 ``.running`` 时间与超时策略推断。"""
        workspace_path = Path(workspace_path)
        status_file = workspace_path / STATUS_JSON_NAME
        running_file = workspace_path / RUNNING_FLAG_NAME

        if status_file.is_file():
            payload = self._try_parse_status_json(status_file)
            if payload is not None:
                if payload.status == "Success":
                    return JobStatus.SUCCESS
                return JobStatus.FAILED
            logger.warning(
                "status.json 存在但无法通过校验，将回退到 .running 逻辑: %s",
                status_file,
            )

        if running_file.is_file():
            age_seconds = self._file_age_seconds(running_file)
            if age_seconds <= self._running_timeout_seconds:
                return JobStatus.RUNNING
            return JobStatus.TIMEOUT_FAILED

        return JobStatus.NOT_STARTED

    def _try_parse_status_json(self, path: Path) -> Optional[StatusJsonPayload]:
        """读取并校验 JSON；损坏或不完整时返回 ``None``（不抛异常）。"""
        try:
            raw_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("读取 status.json 失败: %s err=%s", path, exc)
            return None

        try:
            data: Any = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            logger.warning("status.json JSON 解析失败: %s err=%s", path, exc)
            return None

        if not isinstance(data, dict):
            logger.warning("status.json 根节点不是对象: %s", path)
            return None

        try:
            return StatusJsonPayload.model_validate(
                {"status": data.get("status"), "ppa": data.get("ppa", {})}
            )
        except ValidationError as exc:
            logger.warning("status.json Pydantic 校验失败: %s err=%s", path, exc)
            return None

    @staticmethod
    def _file_age_seconds(path: Path) -> float:
        """返回文件自修改以来经过的秒数（墙钟）。"""
        try:
            mtime = path.stat().st_mtime
        except OSError as exc:
            logger.warning("无法 stat 标志文件: %s err=%s", path, exc)
            return float("inf")
        return max(0.0, time.time() - mtime)
