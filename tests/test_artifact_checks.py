"""ArtifactCheck（签名校验）单测。"""

from pathlib import Path

import pytest

from flow_controller.runtime.artifact_checks import validate_artifact_checks
from flow_controller.runtime.exceptions import NodeArtifactCheckError
from flow_controller.spec.artifacts import ArtifactCheck


def test_validate_artifact_checks_min_size_ok(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("hello", encoding="utf-8")
    checks = [ArtifactCheck(pattern="a.txt", min_size_bytes=1)]
    matched = validate_artifact_checks(checks, base=tmp_path, task_id="t", kind="inputs")
    assert matched[0][1].resolve() == p.resolve()


def test_validate_artifact_checks_min_size_fail(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("", encoding="utf-8")
    checks = [ArtifactCheck(pattern="a.txt", min_size_bytes=1)]
    with pytest.raises(NodeArtifactCheckError):
        validate_artifact_checks(checks, base=tmp_path, task_id="t", kind="outputs")


def test_validate_artifact_checks_regex_ok(tmp_path: Path) -> None:
    p = tmp_path / "rpt.log"
    p.write_text("ERRORS: 0\n", encoding="utf-8")
    checks = [ArtifactCheck(pattern="*.log", must_contain_regex=r"ERRORS:\s*0")]
    matched = validate_artifact_checks(checks, base=tmp_path, task_id="t", kind="outputs")
    assert matched[0][1].resolve() == p.resolve()


def test_validate_artifact_checks_regex_fail(tmp_path: Path) -> None:
    p = tmp_path / "rpt.log"
    p.write_text("ERRORS: 3\n", encoding="utf-8")
    checks = [ArtifactCheck(pattern="*.log", must_contain_regex=r"ERRORS:\s*0")]
    with pytest.raises(NodeArtifactCheckError):
        validate_artifact_checks(checks, base=tmp_path, task_id="t", kind="outputs")

