"""DRC 子任务骨架：侧重 ``post_check`` 解析 Calibre / Assura 汇总报告。

设计说明：
- **为什么单独成类**：DRC 的「成功」往往不能只看 ``exit_code``，而要看报告中的
  ``TOTAL RESULTS`` / ``RULECHECK RESULTS`` 等统计行；与仿真类 Job 的判据完全不同，
  因此用子类封装解析策略，避免在基类里写满 ``if tool == "drc"``。
- **报告格式差异**：Calibre 与 Assura 文本布局不同，这里用「多模式正则 + 优先级」
  做兼容；生产环境可替换为官方解析库或数据库接口。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Pattern, Tuple

from eda_jobs.base_job import BaseEDAJob
from eda_jobs.context import JobContext, JobRunResult
from eda_jobs.exceptions import EDAJobPostCheckError, EDAJobPreCheckError

logger = logging.getLogger(__name__)


class DRCJob(BaseEDAJob):
    """物理验证 DRC 作业：示例聚焦 Calibre/Assura 汇总段解析。"""

    # 常见汇总行模式（按顺序尝试）；实际项目应以工艺/PDK 文档为准进行校准。
    _CALIBRE_TOTAL_PATTERNS: Tuple[Pattern[str], ...] = (
        re.compile(r"^\s*TOTAL\s+RESULTS\s*=\s*(\d+)\s*$", re.IGNORECASE | re.MULTILINE),
        re.compile(r"^\s*RULECHECK\s+RESULTS\s*:\s*(\d+)\s*$", re.IGNORECASE | re.MULTILINE),
    )
    _ASSURA_VIOLATION_PATTERN: Pattern[str] = re.compile(
        r"^\s*Violations\s*:\s*(\d+)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    def __init__(self, context: JobContext, *, summary_report_path: Path) -> None:
        """初始化 DRC Job。

        Args:
            context: 运行上下文。
            summary_report_path: 工具生成的汇总报告路径（可由 ``extra`` 覆盖约定键）。
        """
        super().__init__(context)
        self._summary_report_path = summary_report_path

    def pre_check(self) -> None:
        """检查规则平台可执行文件、输入版图路径等（示例为占位逻辑）。"""
        workdir = self.context.workdir
        if not workdir.exists():
            raise EDAJobPreCheckError(f"工作目录不存在: {workdir}")

        required = self.context.extra.get("layout_path")
        if isinstance(required, str) and not Path(required).is_file():
            raise EDAJobPreCheckError(f"版图输入不存在: {required}")

        tool_req = self.context.tool_version_requirements.get("calibre")
        if tool_req is not None:
            # 真实环境应查询 ``which calibre`` 或读取安装清单比对版本前缀。
            logger.debug("期望 Calibre 版本前缀: %s", tool_req)

    def generate_scripts(self) -> Path:
        """生成 Calibre/Assura 规则运行脚本（此处写入最小占位 ``.tcl``）。"""
        self.context.workdir.mkdir(parents=True, exist_ok=True)
        script_path = self.context.workdir / "drc_run.tcl"
        script_path.write_text(
            "# auto-generated placeholder\n"
            "# real flow: load layout, attach rules deck, run drc, save summary report\n",
            encoding="utf-8",
        )
        return script_path

    def build_command(self) -> List[str]:
        """示例命令：``calibre -drc -tcl <script>``；实际以现场安装为准。"""
        if self._generated_main_script is None:
            raise EDAJobPreCheckError("generate_scripts 尚未执行")
        return ["calibre", "-drc", "-tcl", str(self._generated_main_script)]

    def post_check(self, run_result: JobRunResult) -> None:
        """解析汇总报告中的错误计数；非零则判失败。

        设计要点：
        - **优先读专用汇总文件**：stdout 往往混杂 banner，报告文件更稳定。
        - **多引擎兼容**：Calibre/Assura 关键字不同，因此拆分正则并记录命中的模式名。
        """
        report_path = self._resolve_summary_report_path()
        if not report_path.is_file():
            raise EDAJobPostCheckError(f"未找到 DRC 汇总报告: {report_path}")

        text = report_path.read_text(encoding="utf-8", errors="replace")
        violations = self._extract_violation_count(text)
        if violations is None:
            raise EDAJobPostCheckError("无法在汇总报告中解析违规计数（请检查规则/格式）")

        if violations != 0:
            raise EDAJobPostCheckError(f"DRC 违规数非零: {violations}")

        if run_result.exit_code != 0:
            # 某些流程 exit 非 0 仍输出完整报告；此处策略可按项目收紧/放宽。
            logger.warning(
                "工具 exit_code=%s 但汇总违规为 0，请结合 stdout/stderr 复核",
                run_result.exit_code,
            )

    def collect_metadata(self, run_result: JobRunResult) -> Dict[str, float]:
        """从报告中抽取可量化指标（示例：违规数、运行时长）。"""
        report_path = self._resolve_summary_report_path()
        text = report_path.read_text(encoding="utf-8", errors="replace") if report_path.is_file() else ""
        violations = self._extract_violation_count(text)
        return {
            "drc_violations": float(violations if violations is not None else -1.0),
            "tool_exit_code": float(run_result.exit_code),
            "wall_seconds": float(run_result.duration_seconds),
        }

    def _resolve_summary_report_path(self) -> Path:
        """允许通过 ``extra["drc_summary_report"]`` 覆盖默认路径。"""
        override = self.context.extra.get("drc_summary_report")
        if isinstance(override, str):
            return Path(override)
        return self._summary_report_path

    def _extract_violation_count(self, report_text: str) -> Optional[int]:
        """从报告文本中提取违规计数；无法识别时返回 ``None``。"""
        for pattern in self._CALIBRE_TOTAL_PATTERNS:
            match = pattern.search(report_text)
            if match:
                return int(match.group(1))
        match = self._ASSURA_VIOLATION_PATTERN.search(report_text)
        if match:
            return int(match.group(1))
        return None
