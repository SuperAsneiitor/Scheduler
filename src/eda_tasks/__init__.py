"""EDA 任务组件（``eda_tasks``）。

包含：插件抽象 ``BaseEDAJob``、插件注册表，以及第 4 层 :mod:`eda_tasks.task_template`。
"""

from eda_tasks.base_job import BaseEDAJob
from eda_tasks.task_template import (  # noqa: F401
    DefaultTaskTemplate,
    ExecutionMode,
    LaunchHandle,
    TaskTemplate,
)

__all__ = [
    # 插件抽象基类
    "BaseEDAJob",
    # task template (第 4 层)
    "TaskTemplate",
    "DefaultTaskTemplate",
    "ExecutionMode",
    "LaunchHandle",
]
