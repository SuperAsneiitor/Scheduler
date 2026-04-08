"""EDA Job 插件接口的单元测试（不启动真实 Calibre/Spectre）。"""

from __future__ import annotations

from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import pytest

from eda_tasks.base_job import BaseEDAJob
from eda_tasks.plugins import JobRegistry, discover_jobs
from eda_tasks.plugins.drc.dummy_calibre import DummyCalibreDRCJob


# ---------------------------------------------------------------------------
# 辅助：最小具体插件（不触发真实工具）
# ---------------------------------------------------------------------------

class _NoopDRCJob(BaseEDAJob):
    """测试用最小插件：所有阶段均无操作。"""

    job_type = "test.drc.noop"

    def pre_check(self, workspace: Path) -> None:
        return None

    def generate_scripts(self, workspace: Path) -> Path:
        script = workspace / "noop.tcl"
        script.write_text("# noop\n", encoding="utf-8")
        self._script = script
        return script

    def build_command(self) -> List[str]:
        return ["echo", "noop-drc"]

    def post_check(self, workspace: Path) -> None:
        return None


class _FailingPreCheckJob(BaseEDAJob):
    """pre_check 总是抛出异常的插件。"""

    job_type = "test.drc.fail_pre"

    def pre_check(self, workspace: Path) -> None:
        raise RuntimeError("mock pre_check failure")

    def generate_scripts(self, workspace: Path) -> Path:
        return workspace / "fail.tcl"

    def build_command(self) -> List[str]:
        return ["echo", "never"]

    def post_check(self, workspace: Path) -> None:
        return None


class _FailingPostCheckJob(BaseEDAJob):
    """post_check 总是抛出异常的插件。"""

    job_type = "test.drc.fail_post"

    def pre_check(self, workspace: Path) -> None:
        return None

    def generate_scripts(self, workspace: Path) -> Path:
        s = workspace / "post_fail.tcl"
        s.write_text("", encoding="utf-8")
        return s

    def build_command(self) -> List[str]:
        return ["echo", "post_fail_cmd"]

    def post_check(self, workspace: Path) -> None:
        raise RuntimeError("mock post_check failure")


# ---------------------------------------------------------------------------
# BaseEDAJob 接口与注册表
# ---------------------------------------------------------------------------

def test_base_eda_job_is_abstract() -> None:
    """BaseEDAJob 是抽象类，不可直接实例化。"""
    with pytest.raises(TypeError):
        BaseEDAJob()  # type: ignore[abstract]


def test_subclass_auto_registers() -> None:
    """子类定义时自动注册到 JobRegistry。"""
    assert JobRegistry.get_job_class("test.drc.noop") is _NoopDRCJob


def test_registry_raises_for_unknown_type() -> None:
    """查询未注册的 job_type 应抛 KeyError。"""
    with pytest.raises(KeyError):
        JobRegistry.get_job_class("not.exists.ever")


def test_registry_create_job_returns_instance() -> None:
    """JobRegistry.create_job 返回正确类型实例。"""
    instance = JobRegistry.create_job("test.drc.noop")
    assert isinstance(instance, _NoopDRCJob)


# ---------------------------------------------------------------------------
# DummyCalibreDRCJob 完整生命周期
# ---------------------------------------------------------------------------

def test_dummy_calibre_pre_check_is_noop(tmp_path: Path) -> None:
    job = DummyCalibreDRCJob()
    job.pre_check(tmp_path)  # should not raise


def test_dummy_calibre_generate_scripts_writes_file(tmp_path: Path) -> None:
    job = DummyCalibreDRCJob()
    script = job.generate_scripts(tmp_path)
    assert script.exists()
    assert script.read_text(encoding="utf-8").startswith("#")


def test_dummy_calibre_build_command_after_generate(tmp_path: Path) -> None:
    job = DummyCalibreDRCJob()
    job.generate_scripts(tmp_path)
    cmd = job.build_command()
    assert isinstance(cmd, list)
    assert len(cmd) >= 1
    assert "echo" in cmd[0] or cmd[0] == "echo"


def test_dummy_calibre_post_check_is_noop(tmp_path: Path) -> None:
    job = DummyCalibreDRCJob()
    job.post_check(tmp_path)  # should not raise


def test_dummy_calibre_full_lifecycle(tmp_path: Path) -> None:
    """完整走通一遍 DummyCalibreDRCJob 的四个阶段。"""
    job = DummyCalibreDRCJob()
    job.pre_check(tmp_path)
    script = job.generate_scripts(tmp_path)
    cmd = job.build_command()
    job.post_check(tmp_path)
    assert script.exists()
    assert len(cmd) > 0


# ---------------------------------------------------------------------------
# discover_jobs
# ---------------------------------------------------------------------------

def test_discover_jobs_loads_dummy_plugin() -> None:
    """discover_jobs 后能从 registry 查到 dummy 插件。"""
    discover_jobs()
    cls = JobRegistry.get_job_class(DummyCalibreDRCJob.job_type)
    assert cls is DummyCalibreDRCJob


# ---------------------------------------------------------------------------
# DefaultTaskTemplate 集成：node.job 生命周期
# ---------------------------------------------------------------------------

def test_task_template_calls_plugin_lifecycle(tmp_path: Path) -> None:
    """DefaultTaskTemplate.launch 应依次调用插件的四个阶段。"""
    import asyncio
    from unittest.mock import AsyncMock, patch

    from eda_tasks.task_template import DefaultTaskTemplate, LaunchHandle
    from flow_controller.spec.task_models import TaskNode, TaskType
    from flow_controller.runtime.workspace_manager import WorkspaceManager

    job = MagicMock(spec=_NoopDRCJob)
    job.build_command.return_value = ["echo", "test"]

    wm = MagicMock(spec=WorkspaceManager)
    wm.create_job_dir.return_value = tmp_path
    wm.user_cwd = tmp_path

    node = TaskNode(task_id="t1", task_type=TaskType.DRC)
    node.job = job

    fake_handle = LaunchHandle(job_id="placeholder", log_path=tmp_path / "out.log")
    fake_mode = MagicMock()
    fake_mode.launch = AsyncMock(return_value=fake_handle)
    fake_mode.wait = AsyncMock(return_value=True)

    template = DefaultTaskTemplate()

    async def _run() -> bool:
        return await template.launch(node, mode=fake_mode, wm=wm)

    result = asyncio.run(_run())

    assert result is True
    job.pre_check.assert_called_once_with(tmp_path)
    job.generate_scripts.assert_called_once_with(tmp_path)
    job.build_command.assert_called_once()
    job.post_check.assert_called_once_with(tmp_path)

    _, kwargs = fake_mode.launch.call_args
    assert kwargs["command"] == ["echo", "test"]


def test_task_template_pre_check_failure_marks_failed(tmp_path: Path) -> None:
    """插件 pre_check 抛异常时 launch 应抛 NodeArtifactCheckError。"""
    import asyncio
    from unittest.mock import AsyncMock

    from eda_tasks.task_template import DefaultTaskTemplate, LaunchHandle
    from flow_controller.runtime.exceptions import NodeArtifactCheckError
    from flow_controller.spec.task_models import TaskNode, TaskType
    from flow_controller.runtime.workspace_manager import WorkspaceManager

    job = MagicMock(spec=_FailingPreCheckJob)
    job.pre_check.side_effect = RuntimeError("pre fail")

    wm = MagicMock(spec=WorkspaceManager)
    wm.create_job_dir.return_value = tmp_path
    wm.user_cwd = tmp_path

    node = TaskNode(task_id="t_prefail", task_type=TaskType.DRC)
    node.job = job

    fake_mode = MagicMock()
    fake_mode.launch = AsyncMock()

    template = DefaultTaskTemplate()

    async def _run() -> None:
        await template.launch(node, mode=fake_mode, wm=wm)

    with pytest.raises(NodeArtifactCheckError):
        asyncio.run(_run())

    fake_mode.launch.assert_not_called()
