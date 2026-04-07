"""执行器模块异常定义。"""


class ExecutorSubmissionError(RuntimeError):
    """集群或本地作业提交失败（命令非零退出、无法解析 Job ID 等）。"""


class JobNotFoundError(LookupError):
    """check_status 时找不到对应 job_id（未由本执行器提交或已清理）。"""


class LocalProcessStartError(RuntimeError):
    """本地子进程无法启动（如可执行文件不存在、权限不足）。"""
