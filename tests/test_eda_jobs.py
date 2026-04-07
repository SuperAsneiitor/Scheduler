"""EDA Job 抽象与示例子类的单元测试（不启动真实 Calibre/Spectre）。"""

from pathlib import Path
from unittest.mock import patch

import pytest

from eda.lib.eda_jobs import (
    CharacterizationJob,
    DRCJob,
    EDAJobPostCheckError,
    EDAJobPreCheckError,
    JobContext,
    JobRunResult,
)


def test_drc_extract_violation_count_calibre_style(tmp_path: Path) -> None:
    """Calibre 风格汇总行应能解析违规数。"""
    job = _make_drc_job(tmp_path, tmp_path / "summary.rpt")
    text = "Some banner\nTOTAL RESULTS = 0\n"
    assert job._extract_violation_count(text) == 0


def test_drc_post_check_nonzero_raises(tmp_path: Path) -> None:
    """汇总违规非零应抛 EDAJobPostCheckError。"""
    report = tmp_path / "sum.rpt"
    report.write_text("TOTAL RESULTS = 3\n", encoding="utf-8")

    job = _make_drc_job(tmp_path, report)
    run_result = JobRunResult(
        exit_code=0,
        stdout_log_path=tmp_path / "stdout.log",
        stderr_log_path=tmp_path / "stderr.log",
        command=["calibre"],
        duration_seconds=1.0,
    )
    with pytest.raises(EDAJobPostCheckError):
        job.post_check(run_result)


def test_char_pre_check_missing_include_raises(tmp_path: Path) -> None:
    """include 指向不存在文件时 pre_check 应失败。"""
    netlist = tmp_path / "top.sp"
    netlist.write_text(".include 'missing.inc'\n", encoding="utf-8")
    ctx = JobContext(workdir=tmp_path / "wd")
    job = CharacterizationJob(
        ctx,
        netlist_path=netlist,
        expected_lib_path=tmp_path / "out.lib",
    )
    with pytest.raises(EDAJobPreCheckError):
        job.pre_check()


def test_char_post_check_lib_missing_corner_raises(tmp_path: Path) -> None:
    """缺少期望 Corner 关键字时应失败。"""
    wd = tmp_path / "wd"
    wd.mkdir()
    netlist = tmp_path / "top.sp"
    netlist.write_text(".subckt inv a y\n.ends\n", encoding="utf-8")

    lib_path = tmp_path / "cell.lib"
    lib_path.write_text("library (mylib) {\n}\n", encoding="utf-8")

    ctx = JobContext(
        workdir=wd,
        extra={"expected_lib_corners": "ss_0p9v_125c" },
    )
    job = CharacterizationJob(
        ctx,
        netlist_path=netlist,
        expected_lib_path=lib_path,
    )
    job.pre_check()
    job._generated_main_script = job.generate_scripts()

    run_result = JobRunResult(
        exit_code=0,
        stdout_log_path=wd / "stdout.log",
        stderr_log_path=wd / "stderr.log",
        command=["spectre"],
        duration_seconds=0.1,
    )
    with pytest.raises(EDAJobPostCheckError):
        job.post_check(run_result)


def test_execute_pipeline_mocks_run_skips_real_tools(tmp_path: Path) -> None:
    """集成测试：Mock ``run``，验证 pipeline 串联 pre/post/collect。"""
    report = tmp_path / "sum.rpt"
    report.write_text("TOTAL RESULTS = 0\n", encoding="utf-8")

    wd = tmp_path / "wd"
    wd.mkdir(parents=True)
    ctx = JobContext(workdir=wd)
    job = DRCJob(ctx, summary_report_path=report)

    fake_run = JobRunResult(
        exit_code=0,
        stdout_log_path=tmp_path / "stdout.log",
        stderr_log_path=tmp_path / "stderr.log",
        command=["calibre"],
        duration_seconds=0.1,
    )

    with patch.object(job, "run", return_value=fake_run):
        run_result, metadata = job.execute_pipeline()

    assert run_result.exit_code == 0
    assert "drc_violations" in metadata
    assert metadata["drc_violations"] == 0.0


def _make_drc_job(workdir: Path, summary: Path) -> DRCJob:
    ctx = JobContext(workdir=workdir)
    return DRCJob(ctx, summary_report_path=summary)
