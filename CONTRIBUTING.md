# 贡献指南：EDA 任务插件开发（SOP）

本文面向需要在仓库内**新增 EDA 工具对接或子任务**的 IC / 工具链工程师。目标是在**不改动调度内核**的前提下，以插件方式扩展能力。

---

## 1. 开发原则

| 规则 | 说明 |
|------|------|
| **规范文件** | 若仓库根目录存在 **`.cursorrules`**，开发与提交前须完整阅读并遵守。 |
| **禁止随意修改系统代码** | **`src/core/`**（插件基座、`BaseEDAJob` 契约）与 **`src/orchestrator/`**（监控、调度循环）视为**系统代码**。缺陷修复或通用能力增强须通过评审；**业务专用工具逻辑不得写入上述目录**。 |
| **扩展位置** | 所有新增工具、流程序、厂商适配**仅允许**在 **`src/jobs/`** 下以 **Python 包/模块**形式新增，并通过 **`BaseEDAJob` + `JobRegistry`** 注册。 |
| **测试** | 必须在 **`tests/test_jobs/`** 下为新增插件编写 pytest；**禁止**在 CI/本地单测中真实调用 EDA 可执行文件或许可证服务。 |

---

## 2. 实战步骤（Step-by-Step）

### Step 1：继承基类并注册

在 **`src/jobs/`** 下新增模块（例如 `src/jobs/my_tool/my_job.py`），继承：

```text
from core.base_job import BaseEDAJob
```

为类设置**全局唯一**的 `job_type`（建议 `域.工具.名称` 风格，如 `eda.drc.calibre_dummy`）。子类定义被加载时，会通过 `__init_subclass__` 自动注册到 `JobRegistry`（无需改中央列表）。

**入口发现**：应用启动时调用一次 `jobs.discover_jobs()`，以扫描 `src/jobs` 包内模块（与现有 `tests/test_job_registry.py` 行为一致）。

---

### Step 2：实现生命周期方法

当前 **`src/core/base_job.BaseEDAJob`** 要求子类**必须实现**以下三个抽象方法（与带完整子进程流水线的 `eda_jobs.base_job.BaseEDAJob` 不同，请勿混淆）：

| 方法 | 职责 |
|------|------|
| **`pre_check()`** | 校验输入文件、规则牌、License 环境变量、可执行路径等；不满足时应抛异常或记录后中止，避免生成无效脚本。 |
| **`generate_scripts()`** | 生成 EDA 所需脚本（如 `.tcl`、`.sp`、`.sh`），返回**主脚本路径** `Path`。 |
| **`post_check()`** | 在工具执行结束后解析日志/报告，判断违规数、收敛性等；可与 `pre_check` 对应，形成闭环。 |

**关于「执行 / run」**：

- **核心插件契约**中**没有**名为 `run` 的抽象方法；若你需要在本插件内**直接调用 `subprocess`** 拉起 EDA 命令行，建议：
  - 将具体执行封装在**私有方法**（如 `_run_eda()`）中，并在合适的生命周期阶段调用；或
  - 参考 **`src/eda_jobs/base_job.py`** 中的 **`build_command()`、`execute_pipeline()`** 等模板方法（该路径属于**参考实现**，新插件仍应放在 `src/jobs/`，且不要为适配它而修改 `core`/`orchestrator`）。
- 无论采用何种执行方式，**任务工作目录**内需满足下文的 **`status.json` 约定**，以便 `JobMonitor` 与 DAG 状态一致。

---

### Step 3：状态汇报约定（核心）

调度侧的 **`JobMonitor`**（`src/orchestrator/monitor.py`）根据任务节点上的 **`workspace_path`** 轮询：

| 文件 | 作用 |
|------|------|
| **`.running`** | 运行中标志；存在时间超过阈值且仍无合法 `status.json` 时，可判为超时类状态。 |
| **`status.json`** | 任务**结束**时写入的**终态**摘要；解析成功则得到 `Success` / `Failed` 及指标。 |

**`status.json` 推荐字段**（与 `StatusJsonPayload` 一致）：

| 字段 | 类型 | 说明 |
|------|------|------|
| **`status`** | 字符串 | **`Success`** 或 **`Failed`**（大小写不敏感，解析后会规范化）。 |
| **`ppa`** | 对象 | 键为字符串、值为**浮点数**的指标字典（如功耗、时序、DRC 数量等）；无则可为 `{}`。 |

**示例：在任务工作目录写入 `status.json`**

```python
import json
from pathlib import Path

def write_status_json(workspace: Path, success: bool, metrics: dict) -> None:
    """任务结束时调用；metrics 的 value 须可转为 float（与监控器 Pydantic 模型一致）。"""
    payload = {
        "status": "Success" if success else "Failed",
        "ppa": {k: float(v) for k, v in metrics.items()},
    }
    path = workspace / "status.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
```

**注意**：业务上常说的「metrics」在本仓库监控模型中落在 **`ppa`** 字段名之下；若 JSON 缺字段或类型不符，监控器会回退到基于 `.running` 的推断逻辑，可能导致状态不如预期。

---

### Step 4：TDD 与测试约束

| 要求 | 说明 |
|------|------|
| **位置** | 新增测试文件放在 **`tests/test_jobs/`**，命名建议 `test_<插件名>.py`。 |
| **禁止** | **禁止**在单元测试中真实执行 Calibre、Virtuoso、HSpice 等商业/重型 EDA 软件。 |
| **推荐** | 使用 **`unittest.mock.patch`**（或 `pytest-mock`）模拟 **`subprocess.run` / `subprocess.Popen`**、文件系统敏感操作，仅断言你方插件的**命令行拼装、日志解析、status.json 内容**。 |
| **参考** | 现有 `tests/test_eda_jobs.py`、`tests/test_job_registry.py` 中的 mock 写法。 |

**最小示例：模拟子进程**

```python
from unittest.mock import patch, MagicMock

@patch("subprocess.run")
def test_my_job_builds_command(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    # 实例化你的插件，调用会触发 subprocess 的路径，然后：
    mock_run.assert_called_once()
    # 对 argv、cwd 等做断言
```

---

## 3. 极简插件模板（DummyJob）

以下骨架可直接复制到 `src/jobs/<包名>/<模块>.py` 并按工具改写。**不要**把该文件提交为同名生产模块时忘记改 `job_type` 与类名。

```python
"""示例：最小 BaseEDAJob 插件（无真实 EDA 调用）。"""

from __future__ import annotations

from pathlib import Path

from core.base_job import BaseEDAJob


class DummyJob(BaseEDAJob):
    """占位插件：演示注册与三阶段生命周期。"""

    job_type = "eda.example.dummy"

    def pre_check(self) -> None:
        """检查输入、License、环境变量等。"""
        return None

    def generate_scripts(self) -> Path:
        """生成主脚本并返回路径。"""
        out = Path("dummy_run.tcl")
        out.write_text("# dummy\n", encoding="utf-8")
        return out.resolve()

    def post_check(self) -> None:
        """解析日志/报告，判成功或违规。"""
        return None
```

接入真实流水线时，请在**任务工作目录**中于适当时机写入 **`.running`**（开始）与 **`status.json`**（结束），并与编排层下发的 `workspace_path` 对齐。

---

## 4. 提交前自检

- [ ] 未修改 `src/core/`、`src/orchestrator/` 中与本需求无关的文件。
- [ ] 新代码仅位于 `src/jobs/`（及对应测试 `tests/test_jobs/`）。
- [ ] `python -m pytest tests` 通过，且无不必要的外部 EDA 依赖。
- [ ] 日志使用 `logging`，生产路径避免 `print()`（与项目规范一致）。
