"""cellflow CLI。

最小目标：支持在用户工程目录中执行 ``cellflow run run_config.yaml``：
- 解析 YAML：抽取 ``tasks``（供 DAG）与可选 ``execution``（供本地执行器并发上限）
- 基于 DAG 依赖顺序推进任务
- 在每个任务工作目录生成 ``.running`` 与 ``status.json``，便于 JobMonitor 无状态监控

说明：
- 该 CLI 当前实现为“演示级”闭环：若 YAML task 中提供 ``command``（列表），会调用本地执行器运行；
  否则以占位任务成功结束。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from sys_config import load_execution_config_from_mapping
from flow_controller import DAGManager
from flow_controller.executors.backends import LocalExecutor, get_executor
from flow_controller.runtime.local_orchestrator import LocalFlowOrchestrator
from flow_controller.runtime.modes.local_mode import LocalMode
from flow_controller.runtime.modes.lsf_mode import LsfMode
from flow_controller.runtime.workspace_manager import WorkspaceManager
from flow_controller.spec.yaml_parser import apply_flow_config_to_dag
from flow_controller.spec.yaml_parser import YAMLParser as FlowYAMLParser

logger = logging.getLogger(__name__)


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _load_yaml_mapping(path: Path) -> Dict[str, Any]:
    raw_text = path.read_text(encoding="utf-8")
    loaded = yaml.safe_load(raw_text)
    if loaded is None:
        raise ValueError(f"YAML 内容为空: {path}")
    if not isinstance(loaded, dict):
        raise TypeError("YAML 根节点必须为 mapping（字典）")
    return loaded


def _extract_task_commands(raw: Dict[str, Any]) -> Dict[str, List[str]]:
    """从原始 YAML 中提取每个 task 的 command（可选）。"""
    commands: Dict[str, List[str]] = {}
    tasks = raw.get("tasks", [])
    if not isinstance(tasks, list):
        return commands
    for item in tasks:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("id", "")).strip()
        if not task_id:
            continue
        cmd = item.get("command")
        if isinstance(cmd, list) and cmd:
            commands[task_id] = [str(x) for x in cmd]
    return commands


def _extract_execution_cfg(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    exec_raw = raw.get("execution")
    if exec_raw is None:
        return None
    if not isinstance(exec_raw, dict):
        raise TypeError("execution 必须为 mapping（字典）")
    # 兼容 demo 里的 execution: {mode: local, local_settings: {...}}
    return exec_raw


def _build_dag(flow_yaml_path: Path) -> Tuple[DAGManager, Dict[str, Any]]:
    raw = _load_yaml_mapping(flow_yaml_path)
    flow = FlowYAMLParser.parse_mapping({k: v for k, v in raw.items() if k in ("flow", "tasks")})
    dag = DAGManager()
    apply_flow_config_to_dag(flow, dag, create_missing_upstream=True)
    return dag, raw


def _run_local(
    dag: DAGManager,
    raw: Dict[str, Any],
    *,
    dry_run: bool,
) -> int:
    wm = WorkspaceManager()
    exec_cfg_raw = _extract_execution_cfg(raw) or {"mode": "local", "local_settings": {"max_parallel_jobs": 1}}
    exec_cfg = load_execution_config_from_mapping(exec_cfg_raw)
    executor = LocalExecutor.from_execution_config(exec_cfg)
    commands = _extract_task_commands(raw)
    mode = LocalMode(executor, commands=commands)
    orchestrator = LocalFlowOrchestrator.with_default_template(wm, mode=mode)
    return orchestrator.run(dag, dry_run=dry_run)


def _extract_lsf_queue(raw: Dict[str, Any]) -> str:
    exec_raw = raw.get("execution") if isinstance(raw.get("execution"), dict) else {}
    if not isinstance(exec_raw, dict):
        return ""
    lsf_settings = exec_raw.get("lsf_settings", {})
    if not isinstance(lsf_settings, dict):
        return ""
    queue = str(lsf_settings.get("queue", "")).strip()
    return queue


def _extract_task_job_scripts(raw: Dict[str, Any]) -> Dict[str, Path]:
    scripts: Dict[str, Path] = {}
    tasks = raw.get("tasks", [])
    if not isinstance(tasks, list):
        return scripts
    for item in tasks:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("id", "")).strip()
        if not task_id:
            continue
        job_script = item.get("job_script")
        if job_script is None:
            continue
        script_path = Path(str(job_script)).expanduser()
        scripts[task_id] = script_path
    return scripts


def _run_lsf(
    dag: DAGManager,
    raw: Dict[str, Any],
    *,
    dry_run: bool,
) -> int:
    wm = WorkspaceManager()
    queue = _extract_lsf_queue(raw)
    if not queue:
        raise ValueError("execution.lsf_settings.queue 不能为空（lsf 模式需要）")
    executor = get_executor("lsf", queue=queue)
    scripts = _extract_task_job_scripts(raw)
    mode = LsfMode(
        executor,  # type: ignore[arg-type]
        job_scripts=scripts,
        inject_flow_isolation=bool((raw.get("execution") or {}).get("inject_flow_isolation", False))
        if isinstance(raw.get("execution"), dict)
        else False,
        user_project_cwd=wm.user_cwd,
        poll_interval_seconds=1.0,
        max_polls=10,
    )
    orchestrator = LocalFlowOrchestrator.with_default_template(wm, mode=mode)
    return orchestrator.run(dag, dry_run=dry_run)


def cmd_run(args: argparse.Namespace) -> int:
    path = Path(args.yaml).resolve()
    dag, raw = _build_dag(path)
    mode = ((raw.get("execution") or {}).get("mode") or "local") if isinstance(raw.get("execution"), dict) else "local"
    if mode == "local":
        return _run_local(dag, raw, dry_run=bool(args.dry_run))
    if mode == "lsf":
        return _run_lsf(dag, raw, dry_run=bool(args.dry_run))
    raise NotImplementedError(f"当前 CLI 仅演示 local/lsf 模式，未知 mode={mode!r}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cellflow")
    p.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    sub = p.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="运行一个工作流 YAML")
    run_p.add_argument("yaml", help="run_config.yaml 路径")
    run_p.add_argument("--dry-run", action="store_true", help="仅打印就绪任务，不执行")
    run_p.set_defaults(func=cmd_run)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    _configure_logging(bool(ns.verbose))
    return int(ns.func(ns))


if __name__ == "__main__":
    raise SystemExit(main())

