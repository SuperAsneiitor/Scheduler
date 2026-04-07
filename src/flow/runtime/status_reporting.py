"""status.json / .running 写入工具。

约定：
- `.running`：任务开始运行时创建（空文件即可）。
- `status.json`：任务结束时写入，字段：
  - status: "Success" / "Failed"
  - ppa: Dict[str, float]

监控器优先解析 `status.json`，若解析失败才回退 `.running` 的超时推断。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from flow.runtime.orchestrator.monitor import RUNNING_FLAG_NAME, STATUS_JSON_NAME


def write_running_flag(workspace: Path) -> Path:
    """创建 `.running` 标志文件。"""
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / RUNNING_FLAG_NAME
    path.write_text("", encoding="utf-8")
    return path


def write_status_json(
    workspace: Path,
    *,
    success: bool,
    ppa: Optional[Dict[str, float]] = None,
) -> Path:
    """写入终态 `status.json`。"""
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "Success" if success else "Failed",
        "ppa": dict(ppa or {}),
    }
    path = workspace / STATUS_JSON_NAME
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def clear_running_flag(workspace: Path) -> None:
    """尽力删除 `.running`（终态以 status.json 为准，失败不抛异常）。"""
    path = Path(workspace).resolve() / RUNNING_FLAG_NAME
    try:
        if path.exists():
            path.unlink()
    except OSError:
        return

