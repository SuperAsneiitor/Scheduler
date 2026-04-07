"""LSF 集群执行器：``bsub`` 提交与 ``bjobs`` 查询。"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Pattern

from flow.executors.backends.base import BaseExecutor, ExecutorJobState
from flow.executors.backends.exceptions import ExecutorSubmissionError, JobNotFoundError

logger = logging.getLogger(__name__)

# LSF bsub 典型输出：Job <12345> is submitted to queue <normal>.
_BSUB_JOB_ID_PATTERNS: List[Pattern[str]] = [
    re.compile(r"Job\s+<(\d+)>"),
    re.compile(r"Submission\s+of\s+job\s+<(\d+)>"),
    re.compile(r"job\s+<(\d+)>", re.IGNORECASE),
]


class LSFExecutor(BaseExecutor):
    """通过 ``bsub`` 提交作业，通过 ``bjobs`` 解析 STAT 列。"""

    def __init__(
        self,
        queue: str,
        *,
        bsub_path: str = "bsub",
        bjobs_path: str = "bjobs",
    ) -> None:
        """初始化 LSF 执行器。

        Args:
            queue: ``bsub -q`` 队列名。
            bsub_path: ``bsub`` 可执行文件路径。
            bjobs_path: ``bjobs`` 可执行文件路径。

        Raises:
            ValueError: ``queue`` 为空。
        """
        if queue is None or not str(queue).strip():
            raise ValueError("queue 不能为空")
        self._queue = str(queue).strip()
        self._bsub_path = bsub_path
        self._bjobs_path = bjobs_path

    def submit_job(
        self,
        job_script_path: str,
        log_path: str,
        *,
        user_project_cwd: Optional[str] = None,
        inject_flow_isolation: bool = False,
    ) -> str:
        """执行 ``bsub -q <queue> -o <log_path> <job_script_path>`` 并解析 Job ID。

        当 ``inject_flow_isolation=True`` 时，会在 **用户可写目录**（``log_path`` 所在目录）
        生成包装脚本，头部包含 ``cd <user_project_cwd>`` 与 ``source "$FLOW_ROOT/env.sh"``，
        再 ``exec`` 原始作业脚本，确保计算节点复现用户提交时的工程目录与只读软件环境。

        生产环境在此拼接命令；解析失败时抛出 :class:`ExecutorSubmissionError`。

        Raises:
            ExecutorSubmissionError: ``bsub`` 非零退出或无法从 stdout 解析 Job ID。
            FileNotFoundError: 作业脚本路径不存在。
            ValueError: 打开隔离包装但未提供 ``user_project_cwd``。
        """
        script_path = Path(job_script_path)
        if not script_path.is_file():
            raise FileNotFoundError(f"作业脚本不存在: {job_script_path}")

        script_to_submit: Path
        if inject_flow_isolation:
            if user_project_cwd is None or not str(user_project_cwd).strip():
                raise ValueError("inject_flow_isolation=True 时必须提供 user_project_cwd（用户工程 CWD）")
            user_cwd_abs = str(Path(user_project_cwd).resolve())
            original_abs = str(script_path.resolve())
            log_parent = Path(log_path).resolve().parent
            log_parent.mkdir(parents=True, exist_ok=True)
            wrapper_path = log_parent / f"lsf_cluster_launcher_{script_path.stem}.sh"
            wrapper_path.write_text(
                self._render_cluster_launcher_body(user_cwd_abs, original_abs),
                encoding="utf-8",
                newline="\n",
            )
            try:
                os.chmod(wrapper_path, 0o755)
            except OSError as exc:
                logger.warning("无法为包装脚本设置可执行位: %s err=%s", wrapper_path, exc)
            script_to_submit = wrapper_path
            logger.info(
                "已生成 LSF 集群包装脚本: %s (user_cwd=%s FLOW_ROOT=%s)",
                wrapper_path,
                user_cwd_abs,
                os.environ.get("FLOW_ROOT"),
            )
        else:
            script_to_submit = script_path.resolve()

        cmd = [
            self._bsub_path,
            "-q",
            self._queue,
            "-o",
            log_path,
            str(script_to_submit),
        ]
        logger.info("Submitting LSF job: %s", " ".join(cmd))

        # ------------------------------------------------------------------
        # 真实环境：保持 capture_output=True 以便用正则从 stdout 提取 Job ID；
        # 若改为实时流式读取，请同步调整 _extract_job_id_from_bsub_stdout 的输入来源。
        # ------------------------------------------------------------------
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise ExecutorSubmissionError(
                f"bsub 失败 (exit={completed.returncode}): "
                f"{completed.stderr.strip() or completed.stdout.strip()}"
            )

        job_id = self._extract_job_id_from_bsub_stdout(completed.stdout)
        logger.info("LSF job submitted: job_id=%s queue=%s", job_id, self._queue)
        return job_id

    def check_status(self, job_id: str) -> str:
        """执行 ``bjobs <job_id>`` 并解析 STAT 为 ``RUN`` / ``DONE`` / ``EXIT``。"""
        if job_id is None or not str(job_id).strip():
            raise JobNotFoundError("job_id 不能为空")

        normalized_id = str(job_id).strip()
        cmd = [self._bjobs_path, normalized_id]
        logger.debug("Query LSF job status: %s", " ".join(cmd))

        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        stdout = completed.stdout or ""
        stderr = (completed.stderr or "").strip()

        if completed.returncode != 0 and not stdout.strip():
            raise ExecutorSubmissionError(
                f"bjobs 查询失败 (exit={completed.returncode}): {stderr or stdout}"
            )

        stat_token = self._parse_stat_from_bjobs_table(stdout, normalized_id)
        if not stat_token:
            if "not found" in stderr.lower() or "not found" in stdout.lower():
                raise JobNotFoundError(f"集群中不存在作业 job_id={normalized_id}")
            raise JobNotFoundError(f"无法解析 bjobs 输出中的 STAT: {stdout!r}")

        return self._map_lsf_stat_to_executor_state(stat_token)

    @staticmethod
    def _render_cluster_launcher_body(user_project_cwd: str, original_script: str) -> str:
        """生成在计算节点上执行的 Bash 包装脚本正文（含 ``cd`` 与 ``source env.sh``）。"""
        return (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f'cd "{user_project_cwd}"\n'
            'if [ -n "${FLOW_ROOT:-}" ] && [ -f "$FLOW_ROOT/env.sh" ]; then\n'
            '  # shellcheck source=/dev/null\n'
            '  source "$FLOW_ROOT/env.sh"\n'
            "fi\n"
            f'exec bash "{original_script}"\n'
        )

    @staticmethod
    def _extract_job_id_from_bsub_stdout(stdout: str) -> str:
        if stdout is None:
            raise ExecutorSubmissionError("bsub stdout 为空，无法解析 Job ID")
        for pattern in _BSUB_JOB_ID_PATTERNS:
            match = pattern.search(stdout)
            if match:
                return match.group(1)
        raise ExecutorSubmissionError(f"无法从 bsub 输出解析 Job ID: {stdout!r}")

    @staticmethod
    def _parse_stat_from_bjobs_table(stdout: str, job_id: str) -> str:
        """从 ``bjobs`` 表格输出中解析目标 ``JOBID`` 对应行的 STAT 字段。"""
        lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
        if not lines:
            return ""

        header = lines[0].split()
        jobid_idx = 0
        stat_idx = 2
        if header and header[0].upper() == "JOBID" and len(header) >= 3:
            try:
                jobid_idx = header.index("JOBID")
                stat_idx = header.index("STAT")
            except ValueError:
                jobid_idx = 0
                stat_idx = 2

        for line in lines[1:]:
            parts = line.split()
            if len(parts) <= max(jobid_idx, stat_idx):
                continue
            if parts[jobid_idx] == job_id:
                return parts[stat_idx]

        if len(lines) == 1:
            parts = lines[0].split()
            if len(parts) >= 3 and parts[0] == job_id:
                return parts[2]

        return ""

    @staticmethod
    def _map_lsf_stat_to_executor_state(stat_token: str) -> str:
        """将 LSF STAT 映射为 ``RUN`` / ``DONE`` / ``EXIT``。"""
        stat = stat_token.upper()
        if stat == "DONE":
            return ExecutorJobState.DONE.value
        if stat == "EXIT":
            return ExecutorJobState.EXIT.value
        return ExecutorJobState.RUN.value
