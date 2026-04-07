"""演示：10 个 sleep(2) 任务在 max_parallel_jobs=4 下分批完成（终端时间戳可见）。

运行（在项目根目录）::

    python scripts/demo_local_parallel.py

日志输出目录：``test_work/demo_logs_parallel``（见仓库根 ``.gitignore``）。
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SRC = ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from config import load_execution_config_from_mapping
from executors import LocalExecutor


def _timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


async def _run_demo() -> None:
    """并发提交 10 个 ``python -c "sleep 2"``，观察结束时间呈 4 个一组。"""
    cfg = load_execution_config_from_mapping(
        {
            "mode": "local",
            "local_settings": {"max_parallel_jobs": 4},
        }
    )
    executor = LocalExecutor.from_execution_config(cfg)
    log_dir = ROOT / "test_work" / "demo_logs_parallel"
    log_dir.mkdir(parents=True, exist_ok=True)

    async def _one(task_index: int) -> None:
        print(f"[{_timestamp()}] 开始 task={task_index:02d}（最多 4 路并行执行中）")
        job_id = await executor.submit_job(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            str(log_dir / f"task_{task_index:02d}.log"),
        )
        print(f"[{_timestamp()}] 结束 task={task_index:02d} job_id={job_id}")

    await asyncio.gather(*(_one(i) for i in range(1, 11)))

    failed = executor.get_failed_job_ids()
    if failed:
        print(f"[{_timestamp()}] 失败任务 ID: {failed}")
    else:
        print(f"[{_timestamp()}] 全部任务退出码为 0，无失败记录。")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except OSError:
            pass
    asyncio.run(_run_demo())


if __name__ == "__main__":
    main()
