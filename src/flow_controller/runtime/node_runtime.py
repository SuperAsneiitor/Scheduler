"""调度抽象节点（第一层）：工作区准备与 inputs/outputs 门控。

与 `eda_tasks` 的关系：
- 这里做“配置级 artifact 契约”（glob/签名等）与工作区路径分配；
- 工具级语义校验仍由 `eda_tasks` 的具体 Job（`pre_check`/`post_check`）负责。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

from flow_controller.runtime.artifact_globs import require_patterns_match
from flow_controller.runtime.exceptions import NodeArtifactCheckError
from flow_controller.runtime.workspace_manager import WorkspaceManager
from flow_controller.spec.task_models import TaskNode

logger = logging.getLogger(__name__)


@runtime_checkable
class SchedulingNodeProtocol(Protocol):
    def prepare_workspace(self, node: TaskNode, workspace_manager: WorkspaceManager) -> Path:
        ...

    def check_inputs_ready(self, node: TaskNode, project_root: Path) -> None:
        ...

    def check_outputs_ready(self, node: TaskNode, task_workspace: Path) -> None:
        ...


class DefaultSchedulingNode:
    """默认实现：inputs 相对工程根；outputs 相对任务工作区。"""

    def prepare_workspace(self, node: TaskNode, workspace_manager: WorkspaceManager) -> Path:
        path = workspace_manager.create_job_dir(node.task_id)
        node.workspace_path = path
        logger.debug("prepare_workspace task_id=%s path=%s", node.task_id, path)
        return path

    def check_inputs_ready(self, node: TaskNode, project_root: Path) -> None:
        try:
            require_patterns_match(list(node.inputs), Path(project_root).resolve(), task_id=node.task_id, kind="inputs")
        except ValueError as exc:
            raise NodeArtifactCheckError(f"任务 {node.task_id!r} inputs 配置无效: {exc}") from exc

    def check_outputs_ready(self, node: TaskNode, task_workspace: Path) -> None:
        try:
            require_patterns_match(list(node.outputs), Path(task_workspace).resolve(), task_id=node.task_id, kind="outputs")
        except ValueError as exc:
            raise NodeArtifactCheckError(f"任务 {node.task_id!r} outputs 配置无效: {exc}") from exc

