---
name: eda-python-scheduler
description: >-
  Enforces Python 3.9+ typing, SOLID scheduling architecture, defensive parsing,
  structured logging, and pytest with mocks for EDA distributed job systems (LSF/Slurm,
  log parsing, YAML config). Use when writing or reviewing backend scheduler code,
  EDA executors, orchestrators, log parsers, cluster adapters, or tests in this repo.
---

# EDA Python 调度后端规范（Python 3.9+）

## 何时应用

在本仓库实现或修改 **调度编排、EDA 执行器、集群适配、日志/配置解析、异常与测试** 时，默认遵循本 Skill；输出代码前先给出**简短中文要点**（设计思路、模式），再写实现。

## 语言与类型

- **基线**：Python **3.9+**。
- **强类型**：所有公开函数参数与返回值必须有类型注解；复杂结构用 **Pydantic** 建模与校验。
- **3.9 注意**：联合类型使用 `typing.Union` / `Optional`，或 `typing.List` / `typing.Dict` 等；**勿使用** `X | Y` 语法（需 3.10+）。若项目日后仅支持 3.10+ 再统一改为内置泛型与 `|`。
- **命名**：类 `PascalCase`；函数与变量 `snake_case`；常量 `UPPER_SNAKE_CASE`。禁止无业务含义的 `a`、`temp`、`data` 等泛指名。
- **格式**：符合 PEP 8，风格对齐 Black。

## 架构与质量

- **解耦**：调度（Orchestrator）与执行器（Workers）通过 **`abc` 抽象基类** 分离，遵循 **SRP** 与 **OCP**。
- **防御性**：不信任外部输入（EDA 日志、用户 YAML 等）；解析前做 **None 检查**与**类型/结构校验**。
- **异常**：
  - 禁止裸露 `except Exception:`。
  - 捕获或抛出**具体**异常（如 `FileNotFoundError`、`subprocess.TimeoutExpired`）。
  - 业务层定义并抛出**自定义异常**（例如 `FlowCyclicDependencyError`、`EDALicenseError`）。

## 日志与文档

- **禁止**在生产逻辑中使用 `print()`；统一使用 **`logging`**，区分 `DEBUG` / `INFO` / `WARNING` / `ERROR`。
- 调度核心路径日志应带 **Job ID** 上下文（`LoggerAdapter` 或 `extra` 等一致方式）。
- 模块、类、公开方法使用 **Google 风格 Docstring**（含 Args、Returns、Raises）。

## 测试（pytest）

- **唯一**单元测试框架：**`pytest`**。
- 核心逻辑（调度、正则解析等）须**同步**编写 `test_*.py`。
- **必须 Mock** 外部依赖：真实集群提交（LSF/Slurm）、真实 `subprocess` 跑 EDA、大文件真实 IO；使用 `unittest.mock`（`@patch`、`MagicMock`）或 **`pytest-mock`**。
- 覆盖 **非 happy path**：配置缺失、正则无匹配、提交超时、命令非零退出码等。
- 测试函数命名：`test_<目标函数名>_<场景>_<预期>`（例：`test_submit_job_with_insufficient_resources_returns_pending`）。

## 风险沟通

若需求易导致 **死锁、内存膨胀或模块强耦合**，在实现前直接说明风险并给出更稳妥的替代方案。

## 实现前检查清单

- [ ] 类型与 Pydantic 模型是否覆盖边界输入？
- [ ] 调度与执行器是否经抽象边界交互？
- [ ] 异常是否具体、业务异常是否定义？
- [ ] 日志是否无 `print`、关键路径是否带 Job ID？
- [ ] 测试是否 mock 外部系统、是否含失败与边界用例？
