"""从 YAML 加载 FlowConfig，并应用到 DAGManager。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Union

import yaml
from pydantic import ValidationError

from flow_controller.graph.dag_manager import DAGManager
from flow_controller.spec.task_models import TaskNode, TaskStatus
from flow_controller.spec.models import FlowConfig, TaskConfig

logger = logging.getLogger(__name__)


class YAMLParser:
    """读取用户 Workflow YAML，使用 Pydantic 校验后供调度器构建 DAG。"""

    def __init__(self, yaml_path: Union[str, Path]) -> None:
        """Args:
            yaml_path: YAML 文件路径。
        """
        self._path = Path(yaml_path)

    def parse(self) -> FlowConfig:
        """读取并校验 YAML，返回 :class:`FlowConfig`。

        Raises:
            FileNotFoundError: 文件不存在。
            ValueError: YAML 根节点非法或为空。
            pydantic.ValidationError: 字段不满足模型约束。
        """
        if not self._path.is_file():
            raise FileNotFoundError(f"YAML 文件不存在: {self._path}")

        raw_text = self._path.read_text(encoding="utf-8")
        loaded: Any = yaml.safe_load(raw_text)
        if loaded is None:
            raise ValueError(f"YAML 内容为空: {self._path}")
        if not isinstance(loaded, dict):
            raise TypeError("YAML 根节点必须为 mapping（字典）")

        try:
            return FlowConfig.model_validate(loaded)
        except ValidationError:
            logger.exception("FlowConfig 校验失败: %s", self._path)
            raise

    @staticmethod
    def parse_mapping(data: Dict[str, Any]) -> FlowConfig:
        """从已加载的字典构造 :class:`FlowConfig`（便于测试与内存拼装）。"""
        if not isinstance(data, dict):
            raise TypeError("data 必须为 dict")
        return FlowConfig.model_validate(data)


def apply_flow_config_to_dag(
    flow: FlowConfig,
    dag_manager: DAGManager,
    *,
    create_missing_upstream: bool = True,
) -> None:
    """将 :class:`FlowConfig` 中的任务依次注册到 :class:`DAGManager`。

    对每个 :class:`TaskConfig` 构造 :class:`~flow.spec.task_models.TaskNode` 并调用
    :meth:`~flow.graph.dag_manager.DAGManager.add_task_and_dependencies`。
    任务顺序任意；若某依赖尚未出现且 ``create_missing_upstream=True``，将由 DAGManager
    创建占位节点（与现有行为一致）。

    Args:
        flow: 已校验的流程配置。
        dag_manager: 目标 DAG 管理器。
        create_missing_upstream: 是否允许自动创建未声明的上游占位任务。

    Raises:
        CyclicDependencyError: 配置形成环路。
        KeyError: ``create_missing_upstream=False`` 且存在未知上游。
        TypeError: ``task`` 类型错误。
    """
    for task_cfg in flow.tasks:
        node = _task_config_to_task_node(task_cfg)
        dag_manager.add_task_and_dependencies(
            node,
            create_missing_upstream=create_missing_upstream,
        )
        logger.debug(
            "已自 YAML 注册任务: id=%s type=%s deps=%s",
            node.task_id,
            node.task_type.value,
            node.upstream_dependencies,
        )


def _task_config_to_task_node(task_cfg: TaskConfig) -> TaskNode:
    """将 ``TaskConfig`` 转为编排层 ``TaskNode``。

    若 ``task_cfg.job_type`` 非空，则通过 ``JobRegistry`` 实例化对应插件并挂在
    ``TaskNode.job`` 上，供 ``DefaultTaskTemplate`` 驱动完整生命周期。
    """
    node = TaskNode(
        task_id=task_cfg.id,
        task_type=task_cfg.type,
        status=TaskStatus.PENDING,
        upstream_dependencies=list(task_cfg.depends_on),
        inputs=list(task_cfg.inputs),
        outputs=list(task_cfg.outputs),
        input_checks=list(task_cfg.input_checks),
        output_checks=list(task_cfg.output_checks),
    )
    if task_cfg.job_type:
        try:
            from eda_tasks.plugins import JobRegistry  # noqa: PLC0415

            job_cls = JobRegistry.get_job_class(task_cfg.job_type)
            node.job = job_cls(**task_cfg.job_params)
            logger.debug("已实例化插件 job_type=%s task_id=%s", task_cfg.job_type, task_cfg.id)
        except Exception:
            logger.exception(
                "无法实例化 job_type=%s task_id=%s，task 将跳过插件生命周期",
                task_cfg.job_type,
                task_cfg.id,
            )
    return node
