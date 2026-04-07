"""执行器工厂。"""

from typing import Union

from flow.executors.backends.base import BaseExecutor
from flow.executors.backends.local_executor import LocalExecutor
from flow.executors.backends.lsf_executor import LSFExecutor


def get_executor(mode: str, **kwargs) -> Union[LocalExecutor, LSFExecutor]:
    """根据运行模式构造执行器实例。

    Args:
        mode: ``"local"`` 使用 :class:`LocalExecutor`；
            ``"lsf"`` 或 ``"cluster"`` 使用 :class:`LSFExecutor`。
        **kwargs: 透传给具体执行器构造器。LSF 模式必须提供 ``queue``。

    Returns:
        ``local`` 为 :class:`LocalExecutor`（异步接口，不继承 :class:`BaseExecutor`）；
        ``lsf`` / ``cluster`` 为 :class:`LSFExecutor`。

    Raises:
        ValueError: 未知 ``mode``，或 LSF 模式缺少 ``queue``。
    """
    normalized = mode.strip().lower()
    if normalized == "local":
        parallel = kwargs.get("max_parallel_jobs", kwargs.get("max_concurrent_jobs", 4))
        return LocalExecutor(max_parallel_jobs=parallel)

    if normalized in ("lsf", "cluster"):
        if "queue" not in kwargs:
            raise ValueError("LSF/cluster 模式需要提供关键字参数 queue")
        return LSFExecutor(**kwargs)

    raise ValueError(f"不支持的执行器模式: {mode!r}")
