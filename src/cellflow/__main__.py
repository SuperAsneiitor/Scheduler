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
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

from config import load_execution_config_from_mapping
from flow import DAGManager, TaskNode, TaskStatus
from flow.runtime.status_reporting import clear_running_flag, write_running_flag, write_status_json
from flow.runtime.workspace_manager import WorkspaceManager
from flow.spec.yaml_parser import apply_flow_config_to_dag
from flow.spec.yaml_parser import YAMLParser as FlowYAMLParser

from flow.executors.backends import LocalExecutor

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


def _write_running_flag(workspace: Path) -> None:
    _ = write_running_flag(workspace)


def _write_status_json(workspace: Path, *, success: bool, ppa: Optional[Dict[str, float]] = None) -> None:
    _ = write_status_json(workspace, success=success, ppa=ppa)


def _remove_running_flag(workspace: Path) -> None:
    clear_running_flag(workspace)


def _task_workspace(wm: WorkspaceManager, task_id: str) -> Path:
    # 复用 WorkspaceManager 的安全检查与 <CWD>/jobs/<task_id> 约定
    return wm.create_job_dir(task_id)


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

    # 将 DAG 任务的 workspace_path 补齐（供监控/调度层使用）
    # 通过内部任务表拿到全部任务 ID（DAGManager 目前未提供 public list API）
    task_table: Dict[str, TaskNode] = getattr(dag, "_tasks", {})
    for tid, node in task_table.items():
        if node.workspace_path is None:
            node.workspace_path = _task_workspace(wm, tid)

    # 简单闭环：不断取 ready tasks 执行，直到无 pending
    while True:
        ready = dag.get_ready_tasks()
        if not ready:
            # 若仍有 pending 但无 ready，说明被失败阻塞或图异常；此处退出
            break

        # 并发执行 ready（由 LocalExecutor semaphore 控制实际并发度）
        async_jobs: List[Tuple[TaskNode, Sequence[str]]] = []
        for node in ready:
            if node.workspace_path is None:
                node.workspace_path = _task_workspace(wm, node.task_id)
            dag.update_task_status(node.task_id, TaskStatus.READY)
            cmd = commands.get(node.task_id)
            if cmd is None:
                async_jobs.append((node, []))
            else:
                async_jobs.append((node, cmd))

        if dry_run:
            for node, cmd in async_jobs:
                logger.info("[dry-run] ready task=%s cmd=%s", node.task_id, cmd or "<placeholder>")
                dag.update_task_status(node.task_id, TaskStatus.SUCCESS)
            continue

        # 逐个 submit（submit_job 自身会 await 子进程结束，但同时受 semaphore 控制并发）
        import asyncio

        async def _one(node: TaskNode, cmd: Sequence[str]) -> None:
            assert node.workspace_path is not None
            workspace = Path(node.workspace_path)
            _write_running_flag(workspace)
            dag.update_task_status(node.task_id, TaskStatus.RUNNING)
            try:
                if not cmd:
                    # 占位任务：模拟 50ms 运行
                    await asyncio.sleep(0.05)
                    _write_status_json(workspace, success=True, ppa={})
                    dag.update_task_status(node.task_id, TaskStatus.SUCCESS)
                    return

                log_file = str(workspace / "executor.stdout.log")
                job_id = await executor.submit_job(cmd, log_file)
                logger.info("local executor done task=%s job_id=%s", node.task_id, job_id)
                # LocalExecutor 会记录终态（DONE/EXIT）
                state = executor.check_status(job_id)
                success = state == "DONE"
                _write_status_json(workspace, success=success, ppa={})
                dag.update_task_status(node.task_id, TaskStatus.SUCCESS if success else TaskStatus.FAILED)
            except Exception:
                logger.exception("task failed: %s", node.task_id)
                _write_status_json(workspace, success=False, ppa={})
                dag.update_task_status(node.task_id, TaskStatus.FAILED)
            finally:
                _remove_running_flag(workspace)

        async def _run_batch() -> None:
            await asyncio.gather(*(_one(n, c) for n, c in async_jobs))

        asyncio.run(_run_batch())

    # 若还有 pending 且未执行到，视为失败退出码
    remaining_pending = [
        t
        for t in task_table.values()
        if t.status in (TaskStatus.PENDING, TaskStatus.READY, TaskStatus.RUNNING)
    ]
    if remaining_pending:
        logger.error("workflow unfinished, remaining=%s", [t.task_id for t in remaining_pending])
        return 2
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    path = Path(args.yaml).resolve()
    dag, raw = _build_dag(path)
    mode = ((raw.get("execution") or {}).get("mode") or "local") if isinstance(raw.get("execution"), dict) else "local"
    if mode != "local":
        raise NotImplementedError("当前 CLI 仅演示 local 模式；cluster 模式请使用 flow.cluster 组件或扩展实现。")
    return _run_local(dag, raw, dry_run=bool(args.dry_run))


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

