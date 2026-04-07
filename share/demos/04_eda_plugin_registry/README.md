# Demo 04：EDA 插件注册（JobRegistry）

该 Demo 演示：

- `eda.core.base.BaseEDAJob` 的 `__init_subclass__` 自动注册机制
- `eda.plugins.registry.discover_jobs()` 扫描插件包并完成注册
- 使用 `JobRegistry.create_job(job_type)` 实例化插件

运行（仓库根目录）：

```bash
source bin/env.sh
python -c "from eda.plugins.registry import JobRegistry, discover_jobs; discover_jobs(); print(sorted(JobRegistry.registered_types().keys()))"
```

> 当前仓库提供示例插件 `eda.drc.calibre_dummy`，生成脚本会写入 `test_work/`（被 `.gitignore` 忽略）。

