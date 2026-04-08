"""EDA 作业插件包：注册表 + 内置插件。

- 插件需继承 ``eda_tasks.base_job.BaseEDAJob``
- 子类定义完成时会通过 ``BaseEDAJob.__init_subclass__`` 自动注册到此表
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import Any, Dict, Final, Type

from eda_tasks.base_job import BaseEDAJob

logger = logging.getLogger(__name__)


class PluginRegistrationError(TypeError):
    """插件未满足继承关系、抽象方法或 job_type 约定时抛出。"""


class JobRegistry:
    """job_type -> plugin class 的进程内映射表。"""

    _registry: Final[Dict[str, Type[BaseEDAJob]]] = {}

    @classmethod
    def register_plugin(cls, plugin_cls: Type[Any]) -> None:
        if plugin_cls is BaseEDAJob:
            return
        if not issubclass(plugin_cls, BaseEDAJob):
            raise PluginRegistrationError(f"{plugin_cls.__name__} 必须继承 BaseEDAJob 才能注册")

        is_abstract = inspect.isabstract(plugin_cls)
        abstract_names = getattr(plugin_cls, "__abstractmethods__", None) or frozenset()
        job_type = (getattr(plugin_cls, "job_type", None) or "").strip()

        if is_abstract:
            if job_type:
                raise PluginRegistrationError(
                    f"插件 {plugin_cls.__name__} 声明了 job_type={job_type!r}，但仍未实现抽象方法: "
                    f"{sorted(abstract_names)}"
                )
            return

        if not job_type:
            return
        if job_type in cls._registry:
            raise PluginRegistrationError(f"job_type 重复注册: {job_type!r}")
        cls._registry[job_type] = plugin_cls

    @classmethod
    def get_job_class(cls, job_type: str) -> Type[BaseEDAJob]:
        return cls._registry[str(job_type).strip()]

    @classmethod
    def create_job(cls, job_type: str) -> BaseEDAJob:
        return cls.get_job_class(job_type)()

    @classmethod
    def registered_types(cls) -> Dict[str, Type[BaseEDAJob]]:
        return dict(cls._registry)


def discover_jobs(package_name: str = "eda_tasks.plugins") -> None:
    """导入插件包下所有模块，触发注册。"""
    package = importlib.import_module(package_name)
    if not hasattr(package, "__path__"):
        raise PluginRegistrationError(f"{package_name} 不是包")

    for module_info in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}."):
        importlib.import_module(module_info.name)
        logger.debug("discover_jobs: imported %s", module_info.name)


__all__ = [
    "BaseEDAJob",
    "JobRegistry",
    "PluginRegistrationError",
    "discover_jobs",
]
