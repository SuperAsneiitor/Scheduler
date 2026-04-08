"""工作流编排器：将 DAG 就绪任务批量交给 TaskTemplate + ExecutionMode。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Tuple

from eda_tasks.task_template import DefaultTaskTemplate, ExecutionMode, TaskTemplate
from flow_controller.graph.dag_manager import DAGManager
from flow_controller.runtime.exceptions import NodeArtifactCheckError
from flow_controller.runtime.workspace_manager import WorkspaceManager
from flow_controller.spec.task_models import TaskNode, TaskStatus

logger = logging.getLogger(__name__)


class LocalFlowOrchestrator:
    """编排器（历史名字保留）：推进 DAG 并调用 TaskTemplate。"""

    def __init__(
        self,
        workspace_manager: WorkspaceManager,
        *,
        template: TaskTemplate,
        mode: ExecutionMode,
    ) -> None:
        """Args:
            workspace_manager: 用户工程工作区管理器。
            template: 第 4 层 TaskTemplate。
            mode: 执行 mode（local/LSF 等）。
        """
        self._wm = workspace_manager
        self._template = template
        self._mode = mode

    @classmethod
    def with_default_template(
        cls,
        workspace_manager: WorkspaceManager,
        *,
        mode: ExecutionMode,
    ) -> "LocalFlowOrchestrator":
        """使用 :class:`DefaultTaskTemplate` 的便捷构造。"""
        return cls(workspace_manager, template=DefaultTaskTemplate(), mode=mode)

    def run(self, dag: DAGManager, *, dry_run: bool) -> int:
        """推进 DAG 直至无就绪任务或全部完成。

        Returns:
            0 表示全部任务成功；2 表示存在失败任务或仍有未决/挂起节点。
        """
        task_table = dag.iter_tasks()
        for node in task_table:
            if node.workspace_path is None:
                _ = self._template.prepare_workspace(node, self._wm)

        while True:
            ready = dag.get_ready_tasks()
            if not ready:
                break

            async_jobs: List[TaskNode] = []
            for node in ready:
                if node.workspace_path is None:
                    self._template.prepare_workspace(node, self._wm)
                dag.update_task_status(node.task_id, TaskStatus.READY)
                async_jobs.append(node)

            if dry_run:
                for node in async_jobs:
                    logger.info("[dry-run] ready task=%s", node.task_id)
                    try:
                        self._template.check_inputs(node, self._wm.user_cwd)
                    except NodeArtifactCheckError as exc:
                        logger.error("[dry-run] inputs check failed task=%s err=%s", node.task_id, exc)
                        dag.update_task_status(node.task_id, TaskStatus.FAILED)
                        continue
                    dag.update_task_status(node.task_id, TaskStatus.SUCCESS)
                continue

            asyncio.run(self._run_batch(dag, async_jobs))

        failed_tasks = [t for t in task_table if t.status == TaskStatus.FAILED]
        remaining_pending = [
            t
            for t in task_table
            if t.status in (TaskStatus.PENDING, TaskStatus.READY, TaskStatus.RUNNING)
        ]
        if failed_tasks:
            logger.error("workflow had failed tasks: %s", [t.task_id for t in failed_tasks])
            return 2
        if remaining_pending:
            logger.error("workflow unfinished, remaining=%s", [t.task_id for t in remaining_pending])
            return 2
        return 0

    async def _run_batch(
        self,
        dag: DAGManager,
        async_jobs: List[TaskNode],
    ) -> None:
        await asyncio.gather(*(self._run_one(dag, node) for node in async_jobs))

    async def _run_one(
        self,
        dag: DAGManager,
        node: TaskNode,
    ) -> None:
        dag.update_task_status(node.task_id, TaskStatus.RUNNING)
        try:
            success = await self._template.launch(node, mode=self._mode, wm=self._wm)
            dag.update_task_status(node.task_id, TaskStatus.SUCCESS if success else TaskStatus.FAILED)
        except asyncio.CancelledError:
            raise
        except NodeArtifactCheckError as exc:
            logger.error("artifact check failed task=%s err=%s", node.task_id, exc)
            dag.update_task_status(node.task_id, TaskStatus.FAILED)
        except Exception:
            logger.exception("task failed: %s", node.task_id)
            dag.update_task_status(node.task_id, TaskStatus.FAILED)
