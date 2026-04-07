"""插件注册工厂与 BaseEDAJob 的单元测试。"""

from pathlib import Path

import pytest


def test_discover_jobs_registers_dummy_calibre_plugin() -> None:
    """discover_jobs 后应能通过 job_type 实例化假 Calibre 插件。"""
    from jobs import JobRegistry, discover_jobs

    discover_jobs()
    job = JobRegistry.create_job("eda.drc.calibre_dummy")
    path = job.generate_scripts()
    assert path.name == "run.tcl"
    assert "eda.drc.calibre_dummy" in JobRegistry.registered_types()


def test_register_plugin_rejects_non_subclass() -> None:
    """非 BaseEDAJob 子类手动注册应抛 PluginRegistrationError。"""
    from jobs import JobRegistry, PluginRegistrationError

    class NotAJob:
        pass

    with pytest.raises(PluginRegistrationError):
        JobRegistry.register_plugin(NotAJob)  # type: ignore[arg-type]


def test_register_plugin_rejects_incomplete_with_job_type() -> None:
    """声明 job_type 但未实现全部抽象方法应抛 PluginRegistrationError。"""
    from core.base_job import BaseEDAJob
    from jobs import PluginRegistrationError

    with pytest.raises(PluginRegistrationError):

        class BadPlugin(BaseEDAJob):
            job_type = "eda.bad.incomplete"

            def pre_check(self) -> None:
                return None

            def generate_scripts(self) -> Path:
                return Path(".")

            # 故意不实现 post_check，保留父类抽象


def test_register_plugin_accepts_intermediate_abstract_without_job_type() -> None:
    """中间抽象基类（无 job_type、仍有抽象方法）不应抛错，也不进入注册表。"""
    from abc import abstractmethod

    from core.base_job import BaseEDAJob
    from jobs import JobRegistry

    class Intermediate(BaseEDAJob):
        @abstractmethod
        def extra(self) -> None:
            ...

        def pre_check(self) -> None:
            return None

        def generate_scripts(self):
            return Path(".")

        def post_check(self) -> None:
            return None

    _ = Intermediate
    assert "Intermediate" not in {c.__name__ for c in JobRegistry.registered_types().values()}
