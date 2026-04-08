"""EDA 作业抽象基类：配合 :class:`eda_tasks.plugins.JobRegistry` 做插件自注册。

设计说明：
- 每个插件实现 ``pre_check``、``generate_scripts``、``build_command``、``post_check``
  四个阶段，由调度层 ``DefaultTaskTemplate`` 按序驱动。
- ``__init_subclass__`` 在子类定义完成时即自动注册；导入模块即完成注册，无需手动维护列表。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar, List


class BaseEDAJob(ABC):
    """所有 EDA 原子作业插件的统一抽象。

    Attributes:
        job_type: 全局唯一字符串 ID（建议使用 ``域.工具.名称`` 风格），用于工厂查找。
    """

    job_type: ClassVar[str] = ""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        from eda_tasks.plugins import JobRegistry  # noqa: PLC0415

        JobRegistry.register_plugin(cls)

    @abstractmethod
    def pre_check(self, workspace: Path) -> None:
        """运行前校验：输入文件、License、工具路径等。

        Args:
            workspace: 本次任务的工作目录（由调度层分配）。
        """

    @abstractmethod
    def generate_scripts(self, workspace: Path) -> Path:
        """在 *workspace* 下生成工具运行脚本（如 ``.tcl`` / ``.sp``），返回主脚本路径。

        Args:
            workspace: 本次任务的工作目录。
        """

    @abstractmethod
    def build_command(self) -> List[str]:
        """构造 argv（第一个元素为可执行文件路径）。

        须在 :meth:`generate_scripts` 之后调用；命令中引用脚本路径时应使用
        :meth:`generate_scripts` 返回的绝对路径。
        """

    @abstractmethod
    def post_check(self, workspace: Path) -> None:
        """运行后校验：报告错误数、产物完整性等。

        Args:
            workspace: 本次任务的工作目录。
        """
