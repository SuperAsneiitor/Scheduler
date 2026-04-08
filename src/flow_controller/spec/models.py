"""用户 Workflow YAML 对应的 Pydantic 数据模型。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from flow_controller.spec.artifacts import ArtifactCheck
from flow_controller.spec.task_models import TaskType


class TaskConfig(BaseModel):
    """单任务配置（与 YAML 中一项对应）。"""

    id: str = Field(..., min_length=1, description="任务唯一 ID，对应 DAG 中 task_id")
    type: TaskType = Field(..., description="任务类型，须为 TaskType 枚举取值")
    job_type: Optional[str] = Field(
        default=None,
        description="EDA 插件 job_type（从 JobRegistry 实例化；如 eda.drc.calibre_dummy）",
    )
    job_params: Dict[str, Any] = Field(
        default_factory=dict,
        description="传递给插件构造函数的关键字参数",
    )
    depends_on: List[str] = Field(
        default_factory=list,
        description="上游任务 id 列表；未写或显式 null 时解析为空列表",
    )
    inputs: List[str] = Field(
        default_factory=list,
        description="可选；运行前在工程根下校验的 glob 列表（调度层契约）",
    )
    outputs: List[str] = Field(
        default_factory=list,
        description="可选；成功后在该任务工作目录下校验的 glob 列表（调度层契约）",
    )
    input_checks: List[ArtifactCheck] = Field(
        default_factory=list,
        description="可选；比 inputs 更强的输入签名校验（pattern + size/regex 等）",
    )
    output_checks: List[ArtifactCheck] = Field(
        default_factory=list,
        description="可选；比 outputs 更强的输出签名校验（pattern + size/regex 等）",
    )

    model_config = {"frozen": True}

    @field_validator("id", mode="before")
    @classmethod
    def _strip_id(cls, value: Any) -> str:
        if value is None:
            raise TypeError("id 不能为 None")
        stripped = str(value).strip()
        if not stripped:
            raise ValueError("id 不能为空")
        return stripped

    @field_validator("depends_on", mode="before")
    @classmethod
    def _depends_on_must_be_list(cls, value: Any) -> List[str]:
        """若 YAML 中写了 depends_on，则必须是列表（禁止标量/字典）。"""
        if value is None:
            return []
        if isinstance(value, list):
            cleaned: List[str] = []
            for item in value:
                if item is None:
                    raise ValueError("depends_on 列表中不能包含 null 元素")
                s = str(item).strip()
                if not s:
                    raise ValueError("depends_on 列表中不能包含空字符串")
                cleaned.append(s)
            return cleaned
        raise ValueError("depends_on 必须为列表（例如 [] 或 [task_a, task_b]）")

    @field_validator("inputs", "outputs", mode="before")
    @classmethod
    def _string_list_patterns(cls, value: Any) -> List[str]:
        """glob 模式列表：元素须为非空字符串。"""
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
    def _checks_must_be_list(cls, value: Any) -> Any:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("input_checks/output_checks 必须为列表")
        return value


class FlowGlobalSettings(BaseModel):
    """流程级元数据（可选）。"""

    name: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None

    model_config = {"frozen": True}


class FlowConfig(BaseModel):
    """完整工作流配置：全局段 + 任务列表。"""

    flow: Optional[FlowGlobalSettings] = Field(
        default=None,
        description="全局/流程级元数据",
    )
    tasks: List[TaskConfig] = Field(..., min_length=1, description="任务定义列表")

    model_config = {"frozen": True}

    @field_validator("tasks", mode="before")
    @classmethod
    def _tasks_must_be_list(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("tasks 不能为空")
        if not isinstance(value, list):
            raise ValueError("tasks 必须为列表")
        return value
