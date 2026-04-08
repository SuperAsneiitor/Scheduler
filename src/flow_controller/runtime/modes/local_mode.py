"""Local mode：封装 LocalExecutor 为 ExecutionMode。"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from flow_controller.executors.backends.local_executor import LocalExecutor
from eda_tasks.task_template import ExecutionMode, LaunchHandle
from flow_controller.spec.task_models import TaskNode


class LocalMode(ExecutionMode):
    def __init__(self, executor: LocalExecutor, *, commands: Optional[Dict[str, List[str]]] = None) -> None:
        self._executor = executor
        self._commands: Dict[str, List[str]] = commands or {}

    async def launch(
        self,
        *,
        node: TaskNode,
        workspace: Path,
        command: Optional[List[str]] = None,
    ) -> LaunchHandle:
        # 优先使用调用方传入的 command（来自插件 build_command()），
        # 其次查静态映射，均无则返回占位句柄。
        argv: List[str] = command or self._commands.get(node.task_id, [])
        log_path = workspace / "executor.stdout.log"
        if not argv:
            return LaunchHandle(job_id="placeholder", log_path=log_path)
        job_id = await self._executor.submit_job(argv, str(log_path))
        return LaunchHandle(job_id=job_id, log_path=log_path)

    async def wait(self, *, handle: LaunchHandle) -> bool:
        if handle.job_id == "placeholder":
            return True
        state = self._executor.check_status(handle.job_id)
        return state == "DONE"
