"""基于 :class:`flow.spec.artifacts.ArtifactCheck` 的签名校验实现。"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional, Pattern, Tuple

from flow_controller.runtime.artifact_globs import expand_glob_pattern
from flow_controller.runtime.exceptions import NodeArtifactCheckError
from flow_controller.spec.artifacts import ArtifactCheck

logger = logging.getLogger(__name__)


def _compile_optional_regex(expr: Optional[str]) -> Optional[Pattern[str]]:
    if expr is None:
        return None
    try:
        return re.compile(expr)
    except re.error as exc:
        raise ValueError(f"非法正则: {expr!r} err={exc}") from exc


def _find_first_satisfying_path(
    paths: List[Path],
    *,
    min_size_bytes: Optional[int],
    must_contain: Optional[Pattern[str]],
) -> Optional[Path]:
    for p in paths:
        try:
            if p.is_dir():
                # 目录无法做 size/regex 检查，仅作为存在性命中
                if min_size_bytes is None and must_contain is None:
                    return p
                continue
            if not p.is_file():
                continue
            if min_size_bytes is not None:
                if p.stat().st_size < int(min_size_bytes):
                    continue
            if must_contain is not None:
                text = p.read_text(encoding="utf-8", errors="replace")
                if must_contain.search(text) is None:
                    continue
            return p
        except OSError:
            continue
    return None


def validate_artifact_checks(
    checks: List[ArtifactCheck],
    *,
    base: Path,
    task_id: str,
    kind: str,
) -> List[Tuple[ArtifactCheck, Path]]:
    """对一组规则执行校验并返回命中的路径。

    语义：每条 check 必须至少命中一个路径且满足约束；返回 (check, matched_path) 列表。
    """
    resolved_base = Path(base).resolve()
    results: List[Tuple[ArtifactCheck, Path]] = []
    for check in checks:
        paths = expand_glob_pattern(check.pattern, resolved_base)
        if not paths:
            raise NodeArtifactCheckError(
                f"任务 {task_id!r} 的 {kind} 未匹配到任何路径: "
                f"pattern={check.pattern!r} base={resolved_base}"
            )

        must_contain = _compile_optional_regex(check.must_contain_regex)
        matched = _find_first_satisfying_path(
            paths,
            min_size_bytes=check.min_size_bytes,
            must_contain=must_contain,
        )
        if matched is None:
            raise NodeArtifactCheckError(
                f"任务 {task_id!r} 的 {kind} 签名校验失败: "
                f"pattern={check.pattern!r} min_size_bytes={check.min_size_bytes!r} "
                f"must_contain_regex={check.must_contain_regex!r} base={resolved_base}"
            )
        logger.debug(
            "artifact check ok task=%s kind=%s pattern=%s matched=%s",
            task_id,
            kind,
            check.pattern,
            matched,
        )
        results.append((check, matched))
    return results

