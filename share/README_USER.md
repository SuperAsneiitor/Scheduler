# 用户参考区

- **demos/**：按组件拆分的示例（需 Bash/Git Bash）：

| Demo | 组件主题 | 运行命令 | 预期 |
|------|----------|----------|------|
| `01_basic_gds_to_k/` | 最小线性 DAG | `./run_demo.sh` | 跑通基础链路 |
| `01_flow_dag/` | DAG 依赖解析 | `./run_demo.sh` | 任务按依赖推进 |
| `02_executor_local_parallel/` | 本地执行器并发 | `./run_demo.sh` | 并发受 `max_parallel_jobs` 限制 |
| `03_runtime_monitor/` | 运行态监控 | `./run_demo.sh` | 生成 `.running`/`status.json` |
| `04_eda_plugin_registry/` | 插件注册与发现 | 见目录 README | `JobRegistry` 列出已注册插件 |

- 项目根 **`bin/env.sh`**：设置 `FLOW_ROOT`、`PATH`、`PYTHONPATH`（指向 `src/`），为推荐入口。
- 测试与演示脚本产生的文件位于仓库根目录 **`test_work/`**（已加入 `.gitignore`）。
