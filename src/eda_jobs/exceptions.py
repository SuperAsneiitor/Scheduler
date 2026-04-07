"""EDA 子任务生命周期中的领域异常。

设计说明：将「可预期业务失败」与「程序缺陷」区分开，便于调度层按类型做重试、
跳过或人工介入，而不是笼统地捕获 ``Exception``。
"""


class EDAJobError(Exception):
    """所有 EDA 作业相关异常的基类。"""


class EDAJobPreCheckError(EDAJobError):
    """``pre_check`` 阶段失败：输入缺失、License 不可用、工具路径错误等。"""


class EDAJobPostCheckError(EDAJobError):
    """``post_check`` 阶段失败：DRC 非零错误、产物不符合签名校验等。"""


class EDAJobRunError(EDAJobError):
    """``run`` 子进程执行失败：无法启动、超时、非零退出且被判定为致命错误等。"""
