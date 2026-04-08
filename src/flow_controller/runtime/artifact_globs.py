"""配置级 inputs/outputs 的 glob 展开与存在性校验（调度层，非 EDA 工具语义）。"""

from __future__ import annotations

import glob
import logging
from pathlib import Path
from typing import List

from flow_controller.runtime.exceptions import NodeArtifactCheckError

logger = logging.getLogger(__name__)


def expand_glob_pattern(pattern: str, base: Path) -> List[Path]:
    """将单条 glob 模式相对于 ``base``（或绝对路径）展开为已存在路径列表。

    Args:
        pattern: glob 模式；若以路径分隔符构成绝对路径则相对 ``base`` 忽略前缀规则，
            按 :func:`pathlib.Path.is_absolute` 判定。
        base: 相对模式的前缀目录（通常为工程根或任务工作区）。

    Returns:
        匹配到的路径（文件或目录），可能为空列表。

    Raises:
        ValueError: 模式为空或仅空白。
    """
    raw = str(pattern).strip()
    if not raw:
        raise ValueError("glob 模式不能为空")
    candidate: Path
    if Path(raw).is_absolute():
        candidate = Path(raw)
    else:
        candidate = (base / raw).resolve()
    matches = glob.glob(str(candidate), recursive=True)
    result: List[Path] = []
    for item in matches:
        path_item = Path(item)
        if path_item.exists():
            result.append(path_item)
    logger.debug("expand_glob_pattern pattern=%s base=%s matches=%d", raw, base, len(result))
    return result


def require_patterns_match(
    patterns: List[str],
    base: Path,
    *,
    task_id: str,
    kind: str,
) -> None:
    """要求每个非空模式至少匹配到一个已存在路径。

    Args:
        patterns: glob 模式列表；空列表表示不做校验。
        base: 展开相对模式时使用的根目录。
        task_id: 用于错误信息。
        kind: ``inputs`` 或 ``outputs``，用于错误信息。

    Raises:
        NodeArtifactCheckError: 某一模式无匹配时。
        ValueError: 某模式字符串非法（如空串）。
    """
    if not patterns:
        return
    for pattern in patterns:
        paths = expand_glob_pattern(pattern, base)
        if not paths:
            message = (
                f"任务 {task_id!r} 的 {kind} 未匹配到任何路径: "
                f"pattern={pattern!r} base={base}"
            )
            logger.error(message)
            raise NodeArtifactCheckError(message)
