"""执行相关 YAML/字典配置（Pydantic 校验）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Literal, Optional, Union

import yaml
from pydantic import BaseModel, Field, model_validator


class LocalSettings(BaseModel):
    """本地执行器设置。"""

    max_parallel_jobs: int = Field(
        ...,
        ge=1,
        le=65535,
        description="本地同时运行的外部命令上限（如 LVS/DRC 进程数）",
    )


class ExecutionConfig(BaseModel):
    """顶层执行配置：解析嵌套 YAML/字典结构。

    典型 YAML::

        mode: local
        local_settings:
          max_parallel_jobs: 4
    """

    mode: Literal["local", "cluster"]
    local_settings: Optional[LocalSettings] = None

    model_config = {"frozen": True}

    @model_validator(mode="after")
    def validate_mode_and_nested_settings(self) -> ExecutionConfig:
        """mode 为 local 时必须提供 ``local_settings``。"""
        if self.mode == "local" and self.local_settings is None:
            raise ValueError("mode 为 'local' 时必须提供 local_settings（含 max_parallel_jobs）")
        return self


def load_execution_config_from_yaml(path: Union[str, Path]) -> ExecutionConfig:
    """从 YAML 文件加载并校验为 :class:`ExecutionConfig`。

    Args:
        path: YAML 文件路径。

    Returns:
        校验后的配置对象。

    Raises:
        TypeError: 根节点不是 ``dict``。
        ValueError: 文件为空或 YAML 解析结果为空。
        pydantic.ValidationError: 字段不合法。
    """
    file_path = Path(path)
    raw_text = file_path.read_text(encoding="utf-8")
    loaded = yaml.safe_load(raw_text)
    if loaded is None:
        raise ValueError(f"YAML 内容为空: {file_path}")
    if not isinstance(loaded, dict):
        raise TypeError("YAML 根节点必须为 mapping（字典）")
    return ExecutionConfig.model_validate(loaded)


def load_execution_config_from_mapping(data: Dict[str, Any]) -> ExecutionConfig:
    """从内存中的字典构造配置（便于测试与动态拼装）。"""
    if not isinstance(data, dict):
        raise TypeError("data 必须为 dict")
    return ExecutionConfig.model_validate(data)
