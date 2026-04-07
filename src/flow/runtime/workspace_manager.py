"""用户工作区管理：隔离「软件只读根 (FLOW_ROOT)」与「用户工程 CWD」。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

_SAFE_JOB_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class WorkspaceManager:
    """在**用户当前工作目录**下分配任务子目录；``FLOW_ROOT`` 仅作只读引用。

    设计说明：
    - **CWD**：用户在其工程目录执行命令时的目录，用 :func:`os.getcwd` 捕获（或由调用方注入）。
    - **FLOW_ROOT**：静态只读软件树，通过环境变量传入；本类**不向该路径写入**任何内容。
    """

    def __init__(self, cwd: Optional[Path] = None) -> None:
        """初始化工作区管理器。

        Args:
            cwd: 用户工程根目录；默认使用 :func:`os.getcwd` 的解析路径。
        """
        if cwd is None:
            self._user_cwd = Path(os.getcwd()).resolve()
        else:
            self._user_cwd = Path(cwd).resolve()

        raw_flow = os.environ.get("FLOW_ROOT")
        self._flow_root: Optional[Path] = Path(raw_flow).resolve() if raw_flow else None

    @property
    def user_cwd(self) -> Path:
        """用户工程目录（当前工作目录的规范路径）。"""
        return self._user_cwd

    @property
    def flow_root(self) -> Optional[Path]:
        """``FLOW_ROOT`` 环境变量对应的只读软件根；未设置时为 ``None``。"""
        return self._flow_root

    def create_job_dir(self, job_name: str) -> Path:
        """在 ``<user_cwd>/jobs/<job_name>/`` 下创建任务目录并返回。

        Args:
            job_name: 任务目录名（禁止 ``..``、路径分隔符等）。

        Returns:
            已创建并规范化的任务目录路径。

        Raises:
            ValueError: ``job_name`` 非法。
        """
        if job_name is None or not str(job_name).strip():
            raise ValueError("job_name 不能为空")
        normalized = str(job_name).strip()
        if not _SAFE_JOB_NAME.match(normalized):
            raise ValueError(
                "job_name 仅允许字母数字、下划线、点、短横线，且不能以路径分隔符开头"
            )
        job_dir = (self._user_cwd / "jobs" / normalized).resolve()
        try:
            job_dir.relative_to(self._user_cwd)
        except ValueError as exc:
            raise ValueError("job_name 解析后越出用户 CWD") from exc
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    @staticmethod
    def path_must_not_be_under_flow_root(path: Path, flow_root: Optional[Path]) -> None:
        """若 ``path`` 落在 ``FLOW_ROOT`` 下则抛出异常（用于禁止向只读树写入）。"""
        if flow_root is None:
            return
        target = Path(path).resolve()
        root = Path(flow_root).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return
        raise PermissionError(
            f"禁止在只读软件根 FLOW_ROOT 下写入: {target} (FLOW_ROOT={root})"
        )
