"""ExecutionConfig 解析与校验测试。"""

import pytest
from pydantic import ValidationError

from config import (
    ExecutionConfig,
    load_execution_config_from_mapping,
    load_execution_config_from_yaml,
)


def test_execution_config_from_nested_mapping_parses_local_settings() -> None:
    """嵌套字典应解析 mode 与 local_settings.max_parallel_jobs。"""
    raw = {
        "mode": "local",
        "local_settings": {"max_parallel_jobs": 8},
    }
    cfg = load_execution_config_from_mapping(raw)
    assert cfg.mode == "local"
    assert cfg.local_settings is not None
    assert cfg.local_settings.max_parallel_jobs == 8


def test_execution_config_local_without_local_settings_raises() -> None:
    """mode=local 且缺少 local_settings 应校验失败。"""
    with pytest.raises(ValidationError):
        load_execution_config_from_mapping({"mode": "local"})


def test_execution_config_cluster_allows_missing_local_settings() -> None:
    """cluster 模式可不提供 local_settings。"""
    cfg = load_execution_config_from_mapping({"mode": "cluster"})
    assert cfg.mode == "cluster"
    assert cfg.local_settings is None


def test_load_execution_config_from_yaml_file(tmp_path) -> None:
    """YAML 文件应加载为 ExecutionConfig。"""
    yaml_path = tmp_path / "exec.yaml"
    yaml_path.write_text(
        "mode: local\nlocal_settings:\n  max_parallel_jobs: 4\n",
        encoding="utf-8",
    )
    cfg = load_execution_config_from_yaml(yaml_path)
    assert isinstance(cfg, ExecutionConfig)
    assert cfg.local_settings is not None
    assert cfg.local_settings.max_parallel_jobs == 4
