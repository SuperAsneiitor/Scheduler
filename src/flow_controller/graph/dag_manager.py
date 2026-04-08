"""基于 NetworkX 的 DAG 任务编排管理器。"""

import logging
from typing import Dict, List, Optional

import networkx as nx

from flow_controller.graph.exceptions import CyclicDependencyError
from flow_controller.spec.task_models import TaskNode, TaskStatus, TaskType

logger = logging.getLogger(__name__)


class DAGManager:
    """管理 EDA 任务 DAG：增量加边、环路检测、状态更新与可运行任务查询。

    图语义：若任务 ``T`` 依赖上游 ``U``，则存在有向边 ``U -> T``（先完成 U，再运行 T）。
    """

    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()
        self._tasks: Dict[str, TaskNode] = {}

    def add_task_and_dependencies(
        self,
        task: TaskNode,
        *,
        create_missing_upstream: bool = True,
    ) -> None:
        """注册或更新任务节点，并按上游依赖动态更新 DAG。

        Args:
            task: 任务节点模型（含上游依赖 ID 列表）。
            create_missing_upstream: 为 True 时，对尚未注册的上游 ID 自动创建占位节点，
                便于无序增量注册；为 False 时，任一未知上游将触发 KeyError。

        Raises:
            CyclicDependencyError: 加入边后图中出现有向环。
            KeyError: ``create_missing_upstream`` 为 False 且存在未知上游任务 ID。
            TypeError: ``task`` 不是 ``TaskNode`` 实例。
            ValueError: Pydantic 校验失败。
        """
        if not isinstance(task, TaskNode):
            raise TypeError("task 必须为 TaskNode 实例")

        task_id = task.task_id
        logger.debug("Adding or updating task_id=%s with %d upstream deps", task_id, len(task.upstream_dependencies))

        if task_id in self._tasks:
            self._remove_incoming_edges(task_id)

        self._tasks[task_id] = task
        self._graph.add_node(task_id)

        for upstream_id in task.upstream_dependencies:
            if upstream_id not in self._tasks:
                if not create_missing_upstream:
                    raise KeyError(f"未知上游任务 ID: {upstream_id}")
                self._add_placeholder_task(upstream_id)
            self._graph.add_edge(upstream_id, task_id)

        self.check_circular_dependencies()

    def check_circular_dependencies(self) -> None:
        """检测当前图是否为 DAG；若存在有向环则抛出异常。

        Raises:
            CyclicDependencyError: 图中存在环路。
        """
        if self._graph.number_of_nodes() == 0:
            return

        if nx.is_directed_acyclic_graph(self._graph):
            return

        cycle_vertices: List[str] = self._extract_one_cycle_vertices()
        logger.error("Directed cycle detected involving: %s", cycle_vertices)
        raise CyclicDependencyError(
            f"检测到任务依赖环路，涉及节点（示例顺序）: {' -> '.join(cycle_vertices)}"
        )

    def update_task_status(self, task_id: str, new_status: TaskStatus) -> None:
        """更新指定任务的状态。

        Args:
            task_id: 任务 ID。
            new_status: 新状态。

        Raises:
            KeyError: 任务不存在。
            TypeError: ``new_status`` 不是 ``TaskStatus``。
        """
        if not isinstance(new_status, TaskStatus):
            raise TypeError("new_status 必须为 TaskStatus 枚举")

        if task_id is None or not str(task_id).strip():
            raise ValueError("task_id 不能为空")

        normalized_id = str(task_id).strip()
        if normalized_id not in self._tasks:
            raise KeyError(f"任务不存在: {normalized_id}")

        self._tasks[normalized_id].status = new_status
        logger.info("Task status updated: task_id=%s new_status=%s", normalized_id, new_status.value)

    def get_ready_tasks(self) -> List[TaskNode]:
        """返回当前「可调度」任务：Pending 且所有上游均为 Success。

        无上游依赖的 Pending 任务视为可调度（空依赖在逻辑上视为全部满足）。

        Returns:
            满足条件的 ``TaskNode`` 列表（顺序不保证稳定，调用方若需确定性可自行排序）。
        """
        ready: List[TaskNode] = []
        for task_id, node in self._tasks.items():
            if node.status is not TaskStatus.PENDING:
                continue
            predecessors: List[str] = list(self._graph.predecessors(task_id))
            if not predecessors:
                ready.append(node)
                continue
            if self._all_predecessors_successful(predecessors):
                ready.append(node)
        logger.debug("get_ready_tasks count=%d", len(ready))
        return ready

    def get_task(self, task_id: str) -> Optional[TaskNode]:
        """按 ID 返回任务副本或 None（只读查询，不用于修改状态）。"""
        if task_id is None or not str(task_id).strip():
            return None
        return self._tasks.get(str(task_id).strip())

    def iter_tasks(self) -> List[TaskNode]:
        """返回当前图中全部任务节点（顺序不稳定）。"""
        return list(self._tasks.values())

    def _all_predecessors_successful(self, predecessor_ids: List[str]) -> bool:
        for pred_id in predecessor_ids:
            pred = self._tasks.get(pred_id)
            if pred is None:
                logger.warning("图与任务表不一致：缺少上游节点 task_id=%s", pred_id)
                return False
            if pred.status is not TaskStatus.SUCCESS:
                return False
        return True

    def _remove_incoming_edges(self, task_id: str) -> None:
        predecessors: List[str] = list(self._graph.predecessors(task_id))
        for upstream_id in predecessors:
            if self._graph.has_edge(upstream_id, task_id):
                self._graph.remove_edge(upstream_id, task_id)

    def _add_placeholder_task(self, task_id: str) -> None:
        placeholder = TaskNode(
            task_id=task_id,
            task_type=TaskType.PLACEHOLDER,
            status=TaskStatus.PENDING,
            upstream_dependencies=[],
        )
        self._tasks[task_id] = placeholder
        self._graph.add_node(task_id)
        logger.debug("Created placeholder upstream task_id=%s", task_id)

    def _extract_one_cycle_vertices(self) -> List[str]:
        """从图中抽一条有向环上的节点序列（用于错误信息）。"""
        cycles: List[List] = list(nx.simple_cycles(self._graph))
        if not cycles:
            return ["<unknown>"]
        return [str(node) for node in cycles[0]]
