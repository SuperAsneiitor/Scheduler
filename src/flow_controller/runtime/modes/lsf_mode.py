"""LSF mode：封装 LSFExecutor 为 ExecutionMode（提交脚本并轮询 bjobs）。"""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path
from typing import Dict, List, Optional

from flow_controller.executors.backends.lsf_executor import LSFExecutor
from eda_tasks.task_template import ExecutionMode, LaunchHandle
from flow_controller.spec.task_models import TaskNode


class LsfMode(ExecutionMode):
    def __init__(
        self,
        executor: LSFExecutor,
        *,
        job_scripts: Optional[Dict[str, Path]] = None,
        log_name: str = "executor.stdout.log",
        poll_interval_seconds: float = 1.0,
        max_polls: int = 3600,
        inject_flow_isolation: bool = False,
        user_project_cwd: Optional[Path] = None,
    ) -> None:
        self._executor = executor
        self._job_scripts: Dict[str, Path] = job_scripts or {}
        self._log_name = log_name
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._max_polls = int(max_polls)
        self._inject_isolation = bool(inject_flow_isolation)
        self._user_cwd = user_project_cwd

    async def launch(
        self,
        *,
        node: TaskNode,
        workspace: Path,
        command: Optional[List[str]] = None,
    ) -> LaunchHandle:
        log_path = workspace / self._log_name

        script: Optional[Path] = self._job_scripts.get(node.task_id)

        # 若调用方提供了 command（来自插件 build_command()），则在 workspace 中生成
        # 一个封装 shell 脚本再提交给 bsub；这样 LSF 仍以 job script 方式工作。
        if command is not None and script is None:
            wrapper = workspace / "eda.sh"
            wrapper.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    {' '.join(command)}
                    """
                ),
                encoding="utf-8",
            )
            script = wrapper

        if script is None:
            return LaunchHandle(job_id="placeholder", log_path=log_path)

        job_id = self._executor.submit_job(
            str(script),
            str(log_path),
            user_project_cwd=str(self._user_cwd) if self._user_cwd is not None else None,
            inject_flow_isolation=self._inject_isolation,
        )
        return LaunchHandle(job_id=job_id, log_path=log_path)

    async def wait(self, *, handle: LaunchHandle) -> bool:
        if handle.job_id == "placeholder":
            return True
        for _ in range(max(1, self._max_polls)):
            state = self._executor.check_status(handle.job_id)
            if state == "DONE":
                return True
            if state == "EXIT":
                return False
            await asyncio.sleep(self._poll_interval_seconds)
        return False
