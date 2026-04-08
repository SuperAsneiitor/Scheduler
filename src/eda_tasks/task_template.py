"""第 4 层 TaskTemplate：统一节点生命周期（含 artifact 契约与多 mode 执行）。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from flow_controller.runtime.artifact_checks import validate_artifact_checks
from flow_controller.runtime.artifact_globs import require_patterns_match
from flow_controller.runtime.exceptions import NodeArtifactCheckError
from flow_controller.runtime.status_reporting import clear_running_flag, write_running_flag, write_status_json
from flow_controller.runtime.workspace_manager import WorkspaceManager
from flow_controller.spec.task_models import TaskNode

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LaunchHandle:
    """一次 launch 的句柄：mode 可用于观测/查询状态。"""

    job_id: str
    log_path: Path


class ExecutionMode(ABC):
    """执行 mode 适配层：local/LSF 等。"""

    @abstractmethod
    async def launch(
        self,
        *,
        node: TaskNode,
        workspace: Path,
        command: Optional[List[str]] = None,
    ) -> LaunchHandle:
        """提交/启动任务并返回句柄。

        Args:
            node: 任务节点。
            workspace: 任务工作目录。
            command: 可选的 argv 覆盖；若为 None 则 mode 使用自身默认映射。
        """

    @abstractmethod
    async def wait(self, *, handle: LaunchHandle) -> bool:
        """等待任务进入终态，返回 success 与否。"""


class TaskTemplate(ABC):
    """抽象 TaskTemplate。"""

    @abstractmethod
    def prepare_workspace(self, node: TaskNode, wm: WorkspaceManager) -> Path:
        ...

    @abstractmethod
    def check_inputs(self, node: TaskNode, project_root: Path) -> None:
        ...

    @abstractmethod
    async def launch(self, node: TaskNode, *, mode: ExecutionMode, wm: WorkspaceManager) -> bool:
        ...

    @abstractmethod
    def check_outputs(self, node: TaskNode, workspace: Path) -> None:
        ...

    @abstractmethod
    def collect(self, node: TaskNode, workspace: Path) -> Dict[str, float]:
        ...


class DefaultTaskTemplate(TaskTemplate):
    """默认模板：inputs 相对工程根，outputs 相对任务工作区。

    若 ``node.job`` 不为 None，则在 launch 中驱动完整插件生命周期::

        pre_check(workspace)
        -> generate_scripts(workspace)
        -> build_command()          # 得到 argv
        -> mode.launch(command=argv)
        -> mode.wait(handle)
        -> post_check(workspace)    # 仅在 success=True 时调用
    """

    def prepare_workspace(self, node: TaskNode, wm: WorkspaceManager) -> Path:
        path = wm.create_job_dir(node.task_id)
        node.workspace_path = path
        return path

    def check_inputs(self, node: TaskNode, project_root: Path) -> None:
        root = Path(project_root).resolve()
        if node.input_checks:
            validate_artifact_checks(
                list(node.input_checks),
                base=root,
                task_id=node.task_id,
                kind="inputs",
            )
            return
        require_patterns_match(list(node.inputs), root, task_id=node.task_id, kind="inputs")

    def check_outputs(self, node: TaskNode, workspace: Path) -> None:
        ws = Path(workspace).resolve()
        if node.output_checks:
            validate_artifact_checks(
                list(node.output_checks),
                base=ws,
                task_id=node.task_id,
                kind="outputs",
            )
            return
        require_patterns_match(list(node.outputs), ws, task_id=node.task_id, kind="outputs")

    async def launch(self, node: TaskNode, *, mode: ExecutionMode, wm: WorkspaceManager) -> bool:
        if node.workspace_path is None:
            workspace = self.prepare_workspace(node, wm)
        else:
            workspace = Path(node.workspace_path)

        self.check_inputs(node, wm.user_cwd)

        command_override: Optional[List[str]] = None
        if node.job is not None:
            job = node.job
            try:
                job.pre_check(workspace)
            except Exception as exc:
                logger.error("plugin pre_check failed task=%s err=%s", node.task_id, exc)
                raise NodeArtifactCheckError(f"pre_check failed for {node.task_id}: {exc}") from exc
            job.generate_scripts(workspace)
            command_override = job.build_command()
            logger.debug("plugin build_command task=%s argv=%s", node.task_id, command_override)

        _ = write_running_flag(workspace)
        success = False
        try:
            handle = await mode.launch(node=node, workspace=workspace, command=command_override)
            success = await mode.wait(handle=handle)
            if success:
                if node.job is not None:
                    try:
                        node.job.post_check(workspace)
                    except Exception as exc:
                        logger.error("plugin post_check failed task=%s err=%s", node.task_id, exc)
                        success = False
                try:
                    self.check_outputs(node, workspace)
                except NodeArtifactCheckError:
                    success = False
            _ = write_status_json(workspace, success=success, ppa={})
            return success
        finally:
            clear_running_flag(workspace)

    def collect(self, node: TaskNode, workspace: Path) -> Dict[str, float]:
        _ = node
        _ = workspace
        return {}
