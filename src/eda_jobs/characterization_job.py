"""表征（K 库 / .lib）子任务骨架：侧重网表前置校验与 .lib 后置校验。

设计说明：
- **为什么 pre_check 要验证网表**：表征输入通常是 SPICE/Spectre 网表；若缺失 include、
  子电路引用或空文件，长耗时仿真会在数小时后才失败；前置快速失败可节省集群资源。
- **为什么 post_check 看 .lib**：数字后端更关心 ``cell``/``pin``/``timing`` 表是否出现，
  以及 PVT Corner 是否与 ``JobContext.extra`` 中声明的一致；这比单纯判断文件大小更可靠。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Set

from eda_jobs.base_job import BaseEDAJob
from eda_jobs.context import JobContext, JobRunResult
from eda_jobs.exceptions import EDAJobPostCheckError, EDAJobPreCheckError

logger = logging.getLogger(__name__)


class CharacterizationJob(BaseEDAJob):
    """库表征作业：示例展示网表完整性与 ``.lib`` Corner 校验。"""

    def __init__(
        self,
        context: JobContext,
        *,
        netlist_path: Path,
        expected_lib_path: Path,
    ) -> None:
        super().__init__(context)
        self._netlist_path = netlist_path
        self._expected_lib_path = expected_lib_path

    def pre_check(self) -> None:
        """验证网表存在、非空，并做轻量结构检查（示例级，不做完整 SPICE 解析）。"""
        netlist = self._netlist_path
        if not netlist.is_file():
            raise EDAJobPreCheckError(f"网表文件不存在: {netlist}")
        if netlist.stat().st_size <= 0:
            raise EDAJobPreCheckError(f"网表为空: {netlist}")

        text = netlist.read_text(encoding="utf-8", errors="replace")
        if "subckt" not in text.lower() and ".subckt" not in text.lower():
            # 纯示例启发式：真实流程应调用解析器检查端口/实例化完整性。
            logger.warning("网表未检测到 subckt 关键字，请确认是否为顶层网表")

        includes = self._collect_include_paths(text, netlist.parent)
        missing = [path for path in includes if not path.is_file()]
        if missing:
            raise EDAJobPreCheckError(f"include 引用缺失: {missing}")

    def generate_scripts(self) -> Path:
        """生成表征主控脚本（占位：Spectre/Hspice 语法依 PDK 而定）。"""
        self.context.workdir.mkdir(parents=True, exist_ok=True)
        script_path = self.context.workdir / "char_run.sp"
        script_path.write_text(
            "* placeholder characterization deck\n"
            "* include netlist, sweep PVT, save .lib via mdl/measure flow\n",
            encoding="utf-8",
        )
        return script_path

    def build_command(self) -> List[str]:
        """示例：``spectre +sp <deck>``；真实环境请替换为许可证允许的调用方式。"""
        if self._generated_main_script is None:
            raise EDAJobPreCheckError("generate_scripts 尚未执行")
        return ["spectre", "+sp", str(self._generated_main_script)]

    def post_check(self, run_result: JobRunResult) -> None:
        """验证 ``.lib`` 已生成，并检查是否包含期望的 PVT Corner 关键字。"""
        lib_path = self._expected_lib_path
        if not lib_path.is_file():
            raise EDAJobPostCheckError(f".lib 未生成: {lib_path}")
        if lib_path.stat().st_size <= 0:
            raise EDAJobPostCheckError(f".lib 为空: {lib_path}")

        lib_text = lib_path.read_text(encoding="utf-8", errors="replace")
        if "library" not in lib_text.lower():
            raise EDAJobPostCheckError(".lib 内容缺少 library 段（可能不是有效 Liberty）")

        corners = self._expected_corners_from_context()
        missing_corners = [corner for corner in corners if corner not in lib_text]
        if missing_corners:
            raise EDAJobPostCheckError(f".lib 缺少期望 Corner: {missing_corners}")

        if run_result.exit_code != 0:
            logger.warning("表征工具 exit_code=%s，但 .lib 校验通过，请复核日志", run_result.exit_code)

    def collect_metadata(self, run_result: JobRunResult) -> Dict[str, float]:
        """示例：记录 .lib 大小与运行时长；可扩展为提取 delay/power 表格指标。"""
        lib_bytes = (
            self._expected_lib_path.stat().st_size if self._expected_lib_path.is_file() else 0
        )
        return {
            "lib_size_bytes": float(lib_bytes),
            "tool_exit_code": float(run_result.exit_code),
            "wall_seconds": float(run_result.duration_seconds),
        }

    def _collect_include_paths(self, netlist_text: str, base_dir: Path) -> List[Path]:
        """解析 ``.include`` / ``include`` 行，返回绝对路径列表（示例级简化实现）。"""
        pattern = re.compile(r"^\s*\.?include\s+['\"]?([^'\"\\n]+)['\"]?", re.IGNORECASE | re.MULTILINE)
        paths: List[Path] = []
        for match in pattern.finditer(netlist_text):
            raw = match.group(1).strip()
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = (base_dir / candidate).resolve()
            paths.append(candidate)
        return paths

    def _expected_corners_from_context(self) -> Set[str]:
        """从 ``JobContext.extra`` 读取期望 Corner 列表（逗号分隔字符串）。"""
        raw = self.context.extra.get("expected_lib_corners")
        if raw is None:
            return set()
        if isinstance(raw, str):
            return {part.strip() for part in raw.split(",") if part.strip()}
        return set()
