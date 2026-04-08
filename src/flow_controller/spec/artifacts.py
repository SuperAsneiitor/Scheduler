"""Artifact（输入/输出件）检查模型：用于调度层的轻量契约校验。

说明：
- 该模型用于第 4 层 TaskTemplate 的「入口/出口检查」。
- 不替代第 5 层 EDA Job 的 ``pre_check`` / ``post_check``（工具语义校验）。
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ArtifactCheck(BaseModel):
    """单条 artifact 校验规则。"""

    pattern: str = Field(..., min_length=1, description="glob 模式（相对根目录或绝对路径）")
    min_size_bytes: Optional[int] = Field(
        default=None,
        ge=0,
        description="匹配到的至少一个文件需满足的最小字节数；None 表示不检查大小",
    )
    must_contain_regex: Optional[str] = Field(
        default=None,
        description="匹配到的至少一个文本文件内容需匹配该正则；None 表示不检查内容",
    )

    model_config = {"frozen": True}

    @field_validator("pattern", mode="before")
    @classmethod
    def _strip_pattern(cls, value: object) -> str:
        if value is None:
            raise TypeError("pattern 不能为 None")
        stripped = str(value).strip()
        if not stripped:
            raise ValueError("pattern 不能为空")
        return stripped

    @field_validator("must_contain_regex", mode="before")
    @classmethod
    def _normalize_regex(cls, value: object) -> Optional[str]:
        if value is None:
            return None
        stripped = str(value).strip()
        if not stripped:
            return None
        return stripped

