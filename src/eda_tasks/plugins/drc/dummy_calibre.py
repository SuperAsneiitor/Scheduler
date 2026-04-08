"""示例插件：Dummy Calibre DRC（仅用于演示注册表与 discover_jobs）。"""

from __future__ import annotations

from pathlib import Path
from typing import List

from eda_tasks.base_job import BaseEDAJob


class DummyCalibreDRCJob(BaseEDAJob):
    """假 Calibre DRC 插件：不包含真实工具调用，展示标准插件接口。"""

    job_type = "eda.drc.calibre_dummy"

    def __init__(self) -> None:
        self._script_path: Path = Path()

    def pre_check(self, workspace: Path) -> None:
        """无真实前置检查；子类可在此校验 runset / layout 文件存在。"""
        return None

    def generate_scripts(self, workspace: Path) -> Path:
        """在 *workspace* 下写入占位 DRC runset 并记录路径。"""
        workspace.mkdir(parents=True, exist_ok=True)
        script = workspace / "run.tcl"
        script.write_text("# dummy calibre drc deck\n", encoding="utf-8")
        self._script_path = script
        return script

    def build_command(self) -> List[str]:
        """返回 Calibre 调用命令（此处为 echo 占位）。"""
        return ["echo", f"dummy-calibre-drc {self._script_path}"]

    def post_check(self, workspace: Path) -> None:
        """无真实后置检查；子类可在此解析 summary.rpt 违规数。"""
        return None


def demo_run() -> str:
    """最小演示：发现插件、实例化并跑通占位生命周期。"""
    from pathlib import Path as _Path
    from eda_tasks.plugins import JobRegistry, discover_jobs

    discover_jobs()
    instance = JobRegistry.create_job(DummyCalibreDRCJob.job_type)
    ws = _Path("/tmp/dummy_demo_ws")
    instance.pre_check(ws)
    path = instance.generate_scripts(ws)
    cmd = instance.build_command()
    instance.post_check(ws)
    return f"script={path} cmd={cmd}"
