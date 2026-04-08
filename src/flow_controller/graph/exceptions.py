"""工作流模块自定义异常。"""


class CyclicDependencyError(ValueError):
    """当任务依赖关系形成有向环时抛出。

    例如存在 A→B 且 B→A（或更长的环），则无法构成合法 DAG。
    """

    pass
