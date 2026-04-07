"""集群调度相关的数据模型。"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SubmitStatus(str, Enum):
    """任务向集群提交后的即时结果（非 DAG 任务终态）。"""

    WAITING_RESOURCES = "waiting_resources"
    SUBMITTED = "submitted"


class TaskSubmitResult(BaseModel):
    """单次 ``submit_task`` 调用的结果。

    Attributes:
        status: 资源不足时为 ``WAITING_RESOURCES``；成功占用资源并完成（模拟）投递时为 ``SUBMITTED``。
        cluster_job_id: 集群侧 Job ID（仅 ``SUBMITTED`` 时有值）。
        message: 人类可读说明，便于日志与排障。
    """

    status: SubmitStatus
    cluster_job_id: Optional[str] = Field(
        default=None,
        description="LSF/Slurm 等返回的集群 Job ID",
    )
    message: Optional[str] = Field(default=None, description="补充说明")

    model_config = {"frozen": True}
