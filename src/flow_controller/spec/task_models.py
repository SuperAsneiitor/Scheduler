"""任务节点与枚举定义（Pydantic 校验）。"""

from enum import Enum
from pathlib import Path
from typing import Any, List, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from flow_controller.spec.artifacts import ArtifactCheck

class TaskType(str, Enum):
    """EDA 任务类型（可按业务扩展）。"""

    GDS_EXPORT = "GDS_Export"
    DRC = "DRC"
    PEX = "PEX"
    PLACEHOLDER = "PLACEHOLDER"


class TaskStatus(str, Enum):
    """任务生命周期状态。"""

    PENDING = "Pending"
    READY = "Ready"
    RUNNING = "Running"
    SUCCESS = "Success"
    FAILED = "Failed"


class TaskNode(BaseModel):
    """DAG 中的单个任务节点。

    Attributes:
        task_id: 全局唯一任务标识。
        task_type: 业务任务类型。
        status: 当前状态。
        upstream_dependencies: 上游任务 ID 列表（这些任务必须先成功，当前任务才可执行）。
    """

    task_id: str = Field(..., min_length=1, description="任务唯一 ID")
    task_type: TaskType
    status: TaskStatus = TaskStatus.PENDING
    upstream_dependencies: List[str] = Field(default_factory=list)
    inputs: List[str] = Field(
        default_factory=list,
        description="调度层：运行前相对工程根校验的 glob 列表",
    )
    outputs: List[str] = Field(
        default_factory=list,
        description="调度层：成功后相对任务工作区校验的 glob 列表",
    )
    input_checks: List[ArtifactCheck] = Field(
        default_factory=list,
        description="调度层：更强的输入签名校验规则；非空时优先于 inputs",
    )
    output_checks: List[ArtifactCheck] = Field(
        default_factory=list,
        description="调度层：更强的输出签名校验规则；非空时优先于 outputs",
    )
    workspace_path: Optional[Path] = Field(
        default=None,
        description="任务工作区路径（监控器读取 status.json / .running）",
    )
    job: Optional[Any] = Field(
        default=None,
        exclude=True,
        description="运行时插件实例（BaseEDAJob 子类；不参与序列化）",
    )

    model_config = {"frozen": False, "arbitrary_types_allowed": True}

    @field_validator("workspace_path", mode="before")
    @classmethod
    def _coerce_workspace_path(cls, value: Union[str, Path, None]) -> Optional[Path]:
        if value is None:
            return None
        if isinstance(value, Path):
            return value
        stripped = str(value).strip()
        if not stripped:
            return None
        return Path(stripped)

    @field_validator("task_id", mode="before")
    @classmethod
    def strip_task_id(cls, value: Union[str, None]) -> str:
        """去除首尾空白并拒绝空串与 None。"""
        if value is None:
            raise TypeError("task_id 不能为 None")
        stripped = str(value).strip()
        if not stripped:
            raise ValueError("task_id 不能为空")
        return stripped

    @field_validator("upstream_dependencies", mode="before")
    @classmethod
    def normalize_upstream_dependencies(
        cls, value: Union[List[str], None]
    ) -> List[str]:
        """规范化上游依赖列表并校验元素非空。"""
        if value is None:
            return []
        cleaned: List[str] = []
        for dep in value:
            if dep is None:
                raise ValueError("upstream_dependencies 中不能包含 None")
            dep_stripped = str(dep).strip()
            if not dep_stripped:
                raise ValueError("upstream_dependencies 中存在空字符串依赖")
            cleaned.append(dep_stripped)
        return cleaned

    @field_validator("inputs", "outputs", mode="before")
    @classmethod
    def _normalize_io_patterns(cls, value: Union[List[str], None]) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("inputs/outputs 必须为字符串列表")
        cleaned: List[str] = []
        for item in value:
            if item is None:
                raise ValueError("inputs/outputs 列表中不能包含 null 元素")
            s = str(item).strip()
            if not s:
                raise ValueError("inputs/outputs 列表中不能包含空字符串")
            cleaned.append(s)
        return cleaned

    @field_validator("input_checks", "output_checks", mode="before")
    @classmethod
    def _checks_must_be_list(cls, value: Union[List[ArtifactCheck], None]) -> List[ArtifactCheck]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("input_checks/output_checks 必须为列表")
        return value

    @model_validator(mode="after")
    def reject_self_dependency(self) -> "TaskNode":
        """禁止任务出现在自己的上游依赖列表中。"""
        for dep in self.upstream_dependencies:
            if dep == self.task_id:
                raise ValueError("任务不能依赖自身")
        return self
