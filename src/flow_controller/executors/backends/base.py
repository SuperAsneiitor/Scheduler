"""执行器抽象基类与统一状态枚举。"""

from abc import ABC, abstractmethod
from enum import Enum


class ExecutorJobState(str, Enum):
    """与 LSF ``bjobs`` STAT 列对齐的简化状态（本地执行器复用同一套取值）。"""

    RUN = "RUN"
    DONE = "DONE"
    EXIT = "EXIT"


class BaseExecutor(ABC):
    """EDA 作业执行器抽象：本地子进程或 LSF 集群。"""

    @abstractmethod
    def submit_job(self, job_script_path: str, log_path: str) -> str:
        """提交作业脚本并返回执行器侧 job_id。

        Args:
            job_script_path: 可执行脚本路径（本地通常为 shell 脚本；LSF 为 bsub 的作业脚本）。
            log_path: 标准输出/日志文件路径。

        Returns:
            作业标识：本地为进程 PID 字符串；LSF 为集群 Job ID 字符串。

        Raises:
            ExecutorSubmissionError: 提交失败。
            FileNotFoundError: 脚本或日志路径无效（由具体实现决定）。
        """
        raise NotImplementedError

    @abstractmethod
    def check_status(self, job_id: str) -> str:
        """查询作业状态。

        Args:
            job_id: :meth:`submit_job` 返回的标识。

        Returns:
            ``RUN`` / ``DONE`` / ``EXIT`` 之一（与 :class:`ExecutorJobState` 取值一致）。

        Raises:
            JobNotFoundError: 未知 job_id。
            ExecutorSubmissionError: 查询命令失败（由具体实现决定）。
        """
        raise NotImplementedError
