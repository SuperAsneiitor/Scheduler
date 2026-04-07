"""示例插件：演示 ``BaseEDAJob`` 子类如何被 ``JobRegistry`` 自动发现。

使用方式（在应用启动时调用一次）::

    from eda.plugins.registry import JobRegistry, discover_jobs
    discover_jobs()
    job = JobRegistry.create_job("eda.drc.calibre_dummy")

说明：
- 本模块被 ``import`` 或 ``discover_jobs`` 加载时，类体执行完成即完成注册。
- ``job_type`` 使用点分字符串，避免与文件路径强绑定，便于跨仓库迁移。
"""

from __future__ import annotations

from pathlib import Path

from eda.core.base.base_job import BaseEDAJob


class DummyCalibreDRCJob(BaseEDAJob):
    """假 Calibre DRC 插件：仅用于演示注册与调用链，不包含真实 Calibre 调用。"""

    job_type = "eda.drc.calibre_dummy"

    def pre_check(self) -> None:
        """占位：真实实现应检查版图路径与规则文件。"""
        return None

    def generate_scripts(self) -> Path:
        """在工作目录写入占位 ``run.tcl`` 并返回路径。"""
        repo_root = Path(__file__).resolve().parents[3]
        work = repo_root / "test_work" / "dummy_calibre_workspace"
        work.mkdir(parents=True, exist_ok=True)
        script = work / "run.tcl"
        script.write_text("# dummy calibre drc deck\n", encoding="utf-8")
        return script

    def post_check(self) -> None:
        """占位：真实实现应解析汇总报告并判错。"""
        return None


def demo_run() -> str:
    """供文档/测试调用的最小演示：发现插件、实例化并跑通占位生命周期。"""
    from eda.plugins.registry import JobRegistry, discover_jobs

    discover_jobs()
    instance = JobRegistry.create_job(DummyCalibreDRCJob.job_type)
    instance.pre_check()
    path = instance.generate_scripts()
    instance.post_check()
    return str(path)
