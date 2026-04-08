"""插件注册工厂与 BaseEDAJob 的单元测试。"""

from pathlib import Path

import pytest


def test_discover_jobs_registers_dummy_calibre_plugin(tmp_path: Path) -> None:
    """discover_jobs 后应能通过 job_type 实例化假 Calibre 插件。"""
    from eda_tasks.plugins import JobRegistry, discover_jobs

    discover_jobs()
    job = JobRegistry.create_job("eda.drc.calibre_dummy")
    path = job.generate_scripts(tmp_path)
    assert path.name == "run.tcl"
    assert "eda.drc.calibre_dummy" in JobRegistry.registered_types()


def test_register_plugin_rejects_non_subclass() -> None:
    """非 BaseEDAJob 子类手动注册应抛 PluginRegistrationError。"""
    from eda_tasks.plugins import JobRegistry, PluginRegistrationError

    class NotAJob:
        pass

    with pytest.raises(PluginRegistrationError):
        JobRegistry.register_plugin(NotAJob)  # type: ignore[arg-type]


def test_register_plugin_rejects_incomplete_with_job_type() -> None:
    """澹版槑 job_type 浣嗘湭瀹炵幇鍏ㄩ儴鎶借薄鏂规硶搴旀姏 PluginRegistrationError銆?"""
    from eda_tasks.base_job import BaseEDAJob
    from eda_tasks.plugins import PluginRegistrationError

    with pytest.raises(PluginRegistrationError):

        class BadPlugin(BaseEDAJob):
            job_type = "eda.bad.incomplete"

            def pre_check(self) -> None:
                return None

            def generate_scripts(self) -> Path:
                return Path(".")

            # 鏁呮剰涓嶅疄鐜?post_check锛屼繚鐣欑埗绫绘娊璞?

def test_register_plugin_accepts_intermediate_abstract_without_job_type() -> None:
    """涓棿鎶借薄鍩虹被锛堟棤 job_type銆佷粛鏈夋娊璞℃柟娉曪級涓嶅簲鎶涢敊锛屼篃涓嶈繘鍏ユ敞鍐岃〃銆?"""
    from abc import abstractmethod

    from eda_tasks.base_job import BaseEDAJob
    from eda_tasks.plugins import JobRegistry

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
