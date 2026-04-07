"""EDA 子任务抽象（execute_pipeline 模板方法）与示例 Job 实现。

该目录位于 ``eda.lib``，用于复用“子进程运行骨架/日志/重试”等实现；它不是插件注册入口。
"""

from eda.lib.eda_jobs.base_job import BaseEDAJob
from eda.lib.eda_jobs.characterization_job import CharacterizationJob
from eda.lib.eda_jobs.context import JobContext, JobRunResult, RetryPolicy, RetryBackoff
from eda.lib.eda_jobs.drc_job import DRCJob
from eda.lib.eda_jobs.exceptions import (
    EDAJobError,
    EDAJobPostCheckError,
    EDAJobPreCheckError,
    EDAJobRunError,
)

__all__ = [
    "BaseEDAJob",
    "CharacterizationJob",
    "DRCJob",
    "EDAJobError",
    "EDAJobPostCheckError",
    "EDAJobPreCheckError",
    "EDAJobRunError",
    "JobContext",
    "JobRunResult",
    "RetryBackoff",
    "RetryPolicy",
]
