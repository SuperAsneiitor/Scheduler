"""EDA 作业插件包：动态注册工厂 ``JobRegistry``。

设计说明：
- **注册策略**：仅当子类 *完整实现* 所有抽象方法且声明非空 ``job_type`` 时才登记；
  中间抽象基类（仍含 ``__abstractmethods__``）会被静默跳过。
- **显式失败**：若开发者声明了 ``job_type`` 却仍遗留抽象方法，说明其意图为“可实例化插件”，
  此时在类定义阶段抛出 :exc:`PluginRegistrationError`，避免运行期才 ``TypeError``。
- **可选发现**：:func:`discover_jobs` 遍历 ``eda.plugins`` 子包并 ``import_module``，触发各模块中的类定义，
  从而完成注册（适合按目录组织的插件）。
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import Any, Dict, Final, Type

from eda.core.base.base_job import BaseEDAJob

logger = logging.getLogger(__name__)


class PluginRegistrationError(TypeError):
    """插件未满足继承关系、抽象方法或 ``job_type`` 约定时抛出。"""


class JobRegistry:
    """作业类型字符串 -> 具体作业类的映射（进程内单例表）。"""

    _registry: Final[Dict[str, Type[BaseEDAJob]]] = {}

    @classmethod
    def register_plugin(cls, plugin_cls: Type[Any]) -> None:
        """由 :meth:`BaseEDAJob.__init_subclass__` 调用；外部一般无需直接调用。

        Raises:
            PluginRegistrationError: 类型不合法、``job_type`` 冲突或“声明了插件 ID 但未实现抽象方法”。
        """
        if plugin_cls is BaseEDAJob:
            return

        if not issubclass(plugin_cls, BaseEDAJob):
            raise PluginRegistrationError(
                f"{plugin_cls.__name__} 必须继承 BaseEDAJob 才能作为插件注册"
            )

        # 使用 inspect.isabstract：在 __init_subclass__ 触发点，__abstractmethods__ 有时尚未稳定，
        # 直接依赖 frozenset 可能误判“已具体化”。
        is_abstract = inspect.isabstract(plugin_cls)
        abstract_names = getattr(plugin_cls, "__abstractmethods__", None) or frozenset()
        job_type = (getattr(plugin_cls, "job_type", None) or "").strip()

        if is_abstract:
            if job_type:
                detail = (
                    f"{sorted(abstract_names)}"
                    if abstract_names
                    else "inspect.isabstract=True 但 __abstractmethods__ 为空（请检查 ABC 元类状态）"
                )
                raise PluginRegistrationError(
                    f"插件 {plugin_cls.__name__} 声明了 job_type={job_type!r}，"
                    f"但仍为抽象类或未实现抽象方法: {detail}"
                )
            return

        if not job_type:
            logger.debug(
                "跳过注册 %s：未设置 job_type（若为非插件基类可忽略）",
                plugin_cls.__name__,
            )
            return

        if job_type in cls._registry:
            raise PluginRegistrationError(
                f"job_type 重复注册: {job_type!r} "
                f"已存在 {cls._registry[job_type].__name__}"
            )

        cls._registry[job_type] = plugin_cls
        logger.info("已注册 EDA 作业插件: %s -> %s", job_type, plugin_cls.__name__)

    @classmethod
    def get_job_class(cls, job_type: str) -> Type[BaseEDAJob]:
        """按 ``job_type`` 解析插件类。

        Raises:
            KeyError: 未注册。
        """
        return cls._registry[job_type]

    @classmethod
    def create_job(cls, job_type: str) -> BaseEDAJob:
        """实例化插件（无参构造示例；真实场景可改为传入 ``JobContext``）。"""
        job_cls = cls.get_job_class(job_type)
        return job_cls()

    @classmethod
    def registered_types(cls) -> Dict[str, Type[BaseEDAJob]]:
        """返回当前已注册映射的浅拷贝（便于调试与测试）。"""
        return dict(cls._registry)


def discover_jobs(package_name: str = "eda.plugins") -> None:
    """遍历 EDA 插件包（及子包）并导入所有模块，触发 ``BaseEDAJob`` 子类注册。

    Args:
        package_name: 通常为 ``eda.plugins``，对应 ``src/eda/plugins``。
    """
    package = importlib.import_module(package_name)
    if not hasattr(package, "__path__"):
        raise PluginRegistrationError(f"{package_name} 不是包")

    for module_info in pkgutil.walk_packages(
        package.__path__,
        prefix=f"{package_name}.",
    ):
        importlib.import_module(module_info.name)
        logger.debug("discover_jobs: imported %s", module_info.name)


__all__ = [
    "BaseEDAJob",
    "JobRegistry",
    "PluginRegistrationError",
    "discover_jobs",
]
