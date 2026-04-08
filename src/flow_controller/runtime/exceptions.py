"""flow_controller.runtime 使用的异常类型。"""


class NodeArtifactCheckError(RuntimeError):
    """调度层：任务配置的 ``inputs`` / ``outputs`` glob 未满足时出现。

    典型原因：运行前输入路径缺失，或运行成功后未在任务工作区找到声明的输出匹配项。
    """

    pass
