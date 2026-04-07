"""Pytest 引导。

- ``pythonpath = src`` 见 ``pytest.ini``。
- ``--basetemp=test_work/pytest-basetemp``：pytest 临时目录位于 ``test_work`` 下。
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEST_WORK = _REPO_ROOT / "test_work"


def pytest_configure(config: pytest.Config) -> None:
    """预先创建 ``test_work``，否则 ``--basetemp=.../pytest-basetemp`` 在部分环境下无法建父链。"""
    _TEST_WORK.mkdir(parents=True, exist_ok=True)
