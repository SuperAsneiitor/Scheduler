"""Workflow YAML 解析与 DAG 转换测试。"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from flow import (
    DAGManager,
    YAMLParser,
    apply_flow_config_to_dag,
)
from flow.graph.exceptions import CyclicDependencyError
from flow.spec.task_models import TaskStatus, TaskType


def test_yaml_parser_loads_flow_config(tmp_path: Path) -> None:
    """YAMLParser 应解析 flow + tasks 并校验通过。"""
    yaml_path = tmp_path / "flow.yaml"
    yaml_path.write_text(
        """
flow:
  name: demo
  version: "1.0"
tasks:
  - id: gds_1
    type: GDS_Export
  - id: drc_1
    type: DRC
    depends_on: [gds_1]
""",
        encoding="utf-8",
    )

    parser = YAMLParser(yaml_path)
    flow = parser.parse()
    assert flow.flow is not None
    assert flow.flow.name == "demo"
    assert len(flow.tasks) == 2
    assert flow.tasks[1].depends_on == ["gds_1"]


def test_task_config_depends_on_must_be_list(tmp_path: Path) -> None:
    """depends_on 若存在且非列表应校验失败。"""
    yaml_path = tmp_path / "bad.yaml"
    yaml_path.write_text(
        """
tasks:
  - id: a
    type: DRC
    depends_on: not_a_list
""",
        encoding="utf-8",
    )

    parser = YAMLParser(yaml_path)
    with pytest.raises(ValidationError):
        parser.parse()


def test_apply_flow_config_to_dag_builds_ready_chain(tmp_path: Path) -> None:
    """转换逻辑应调用 DAGManager 并得到 GDS -> DRC 就绪顺序。"""
    yaml_path = tmp_path / "chain.yaml"
    yaml_path.write_text(
        """
flow:
  name: chain
tasks:
  - id: job_gds
    type: GDS_Export
  - id: job_drc
    type: DRC
    depends_on: [job_gds]
""",
        encoding="utf-8",
    )

    flow = YAMLParser(yaml_path).parse()
    dag = DAGManager()
    apply_flow_config_to_dag(flow, dag)

    ready = {t.task_id for t in dag.get_ready_tasks()}
    assert ready == {"job_gds"}

    dag.update_task_status("job_gds", TaskStatus.SUCCESS)
    ready2 = {t.task_id for t in dag.get_ready_tasks()}
    assert ready2 == {"job_drc"}


def test_apply_flow_config_cycle_raises(tmp_path: Path) -> None:
    """环路配置应触发 CyclicDependencyError。"""
    yaml_path = tmp_path / "cycle.yaml"
    yaml_path.write_text(
        """
tasks:
  - id: A
    type: DRC
    depends_on: [B]
  - id: B
    type: PEX
    depends_on: [A]
""",
        encoding="utf-8",
    )

    flow = YAMLParser(yaml_path).parse()
    dag = DAGManager()
    with pytest.raises(CyclicDependencyError):
        apply_flow_config_to_dag(flow, dag)


def test_parse_mapping_roundtrip() -> None:
    """parse_mapping 应与 YAML 结构等价。"""
    data = {
        "flow": {"name": "n"},
        "tasks": [
            {"id": "x", "type": "DRC", "depends_on": []},
        ],
    }
    from flow.spec.yaml_parser import YAMLParser

    flow = YAMLParser.parse_mapping(data)
    assert flow.tasks[0].id == "x"
    assert flow.tasks[0].type is TaskType.DRC
