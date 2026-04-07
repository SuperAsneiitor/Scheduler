"""作业上下文与策略参数（Pydantic 建模）。

设计说明：将「一次 EDA 子任务运行所需的全部外部配置」收敛为不可变值对象，
避免在 ``BaseEDAJob`` 子类中散落魔法常量；调度器序列化/落盘时也可直接导出该模型。
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator


class RetryBackoff(str, Enum):
    """重试退避策略（供调度器解释；基类 ``run`` 可选用简单实现）。"""

    NONE = "none"
    FIXED = "fixed"
    LINEAR = "linear"


class RetryPolicy(BaseModel):
    """重试策略：与集群/本地执行器的「任务级重试」解耦，描述业务语义即可。"""

    max_attempts: int = Field(1, ge=1, le=100, description="包含首次尝试的总次数")
    initial_delay_seconds: float = Field(0.0, ge=0.0, description="首次失败后等待时间")
    backoff: RetryBackoff = Field(RetryBackoff.NONE, description="退避模式")
    backoff_multiplier: float = Field(1.5, ge=1.0, description="指数/线性退避系数")

    model_config = {"frozen": True}


class JobContext(BaseModel):
    """单次 EDA 子任务运行上下文。

    Attributes:
        workdir: 工作目录（日志、中间文件、生成脚本默认落盘位置）。
        tool_version_requirements: 工具名 -> 期望版本前缀/完整版本号；``pre_check`` 用于核对。
        timeout_seconds: 子进程墙钟超时；``None`` 表示不限制（依赖外部调度器杀进程）。
        retry_policy: 任务级重试策略；具体是否在 ``run`` 内循环由基类策略决定。
        extra: 扩展键值，避免为每个工具频繁改模型字段（如 PVT Corner、工艺节点名）。
    """

    workdir: Path
    tool_version_requirements: Dict[str, str] = Field(default_factory=dict)
    timeout_seconds: Optional[float] = Field(default=None, description="子进程超时（秒）；None 表示不限制")
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    extra: Dict[str, Union[str, int, float, bool]] = Field(default_factory=dict)

    model_config = {"frozen": True}

    @field_validator("timeout_seconds")
    @classmethod
    def _validate_timeout_seconds(cls, value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        if value <= 0:
            raise ValueError("timeout_seconds 必须为正数")
        return value

    @field_validator("workdir", mode="before")
    @classmethod
    def _coerce_workdir(cls, value: Union[str, Path]) -> Path:
        if isinstance(value, Path):
            return value
        return Path(str(value))


class JobRunResult(BaseModel):
    """子进程一次执行的可观测结果（供 ``post_check`` / 元数据提取）。"""

    exit_code: int
    stdout_log_path: Path
    stderr_log_path: Path
    command: List[str] = Field(default_factory=list)
    duration_seconds: float = Field(0.0, ge=0.0)

    model_config = {"frozen": True}
