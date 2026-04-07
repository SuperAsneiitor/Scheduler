"""WorkspaceManager 与 FLOW_ROOT 写入隔离测试。"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from flow.runtime.workspace_manager import WorkspaceManager


def test_workspace_manager_uses_getcwd(tmp_path: Path, monkeypatch) -> None:
    """未传入 cwd 时应使用 os.getcwd() 的解析路径。"""
    monkeypatch.chdir(tmp_path)
    wm = WorkspaceManager()
    assert wm.user_cwd == Path(os.getcwd()).resolve()


def test_create_job_dir_standard_layout(tmp_path: Path) -> None:
    """应在 <CWD>/jobs/<name>/ 下创建目录。"""
    wm = WorkspaceManager(cwd=tmp_path)
    job_dir = wm.create_job_dir("drc_run_01")
    assert job_dir == (tmp_path / "jobs" / "drc_run_01").resolve()
    assert job_dir.is_dir()


def test_create_job_dir_rejects_unsafe_name(tmp_path: Path) -> None:
    """含路径穿越的 job_name 应拒绝。"""
    wm = WorkspaceManager(cwd=tmp_path)
    with pytest.raises(ValueError):
        wm.create_job_dir("../evil")


def test_path_must_not_be_under_flow_root_raises(tmp_path: Path) -> None:
    """工作目录落在 FLOW_ROOT 下时应拒绝写入。"""
    flow = tmp_path / "flow_install"
    flow.mkdir()
    bad = (flow / "jobs").resolve()
    with pytest.raises(PermissionError):
        WorkspaceManager.path_must_not_be_under_flow_root(bad, flow)


def test_path_must_not_be_under_flow_root_allows_outside(tmp_path: Path) -> None:
    """用户工程路径在 FLOW_ROOT 外时应通过。"""
    flow = tmp_path / "flow_install"
    flow.mkdir()
    user = tmp_path / "user_proj" / "jobs" / "a"
    user.mkdir(parents=True)
    WorkspaceManager.path_must_not_be_under_flow_root(user, flow)


def test_flow_root_from_environ(monkeypatch, tmp_path: Path) -> None:
    """应能从环境变量解析 FLOW_ROOT。"""
    flow = tmp_path / "f"
    flow.mkdir()
    monkeypatch.setenv("FLOW_ROOT", str(flow))
    wm = WorkspaceManager(cwd=tmp_path)
    assert wm.flow_root == flow.resolve()
