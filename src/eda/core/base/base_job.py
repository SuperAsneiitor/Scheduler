"""EDA 作业抽象基类：配合 :class:`eda.plugins.registry.JobRegistry` 做插件自注册。

设计说明：
- **为何使用 ``__init_subclass__``**：在子类 *定义完成* 时即可登记，无需手动维护
  ``setup.py`` entry points 或中央 ``if/elif`` 列表；导入模块即完成注册。
- **为何延迟导入 ``JobRegistry``**：避免注册表与基类之间的循环依赖。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar


class BaseEDAJob(ABC):
    """所有 EDA 原子作业插件的统一抽象。

    Attributes:
        job_type: 全局唯一字符串 ID（建议使用 ``域.工具.名称`` 风格），用于工厂查找。
    """

    job_type: ClassVar[str] = ""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # 延迟导入：保证 ``eda.plugins.registry.JobRegistry`` 在子类定义时已可用，且不形成顶层环依赖。
        from eda.plugins.registry import JobRegistry  # noqa: PLC0415

        JobRegistry.register_plugin(cls)

    @abstractmethod
    def pre_check(self) -> None:
        """运行前校验：输入文件、License、工具路径等。"""

    @abstractmethod
    def generate_scripts(self) -> Path:
        """生成工具运行脚本（如 ``.tcl`` / ``.sp``），返回主脚本路径。"""

    @abstractmethod
    def post_check(self) -> None:
        """运行后校验：报告错误数、产物完整性等。"""
