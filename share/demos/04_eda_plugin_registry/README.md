# Demo 04锛欵DA 鎻掍欢娉ㄥ唽锛圝obRegistry锛?
璇?Demo 婕旂ず锛?
- `eda_tasks.base_job.BaseEDAJob` 鐨?`__init_subclass__` 鑷姩娉ㄥ唽鏈哄埗
- `eda_tasks.plugins.registry.discover_jobs()` 鎵弿鎻掍欢鍖呭苟瀹屾垚娉ㄥ唽
- 浣跨敤 `JobRegistry.create_job(job_type)` 瀹炰緥鍖栨彃浠?
杩愯锛堜粨搴撴牴鐩綍锛夛細

```bash
source bin/env.sh
python -c "from eda_tasks.plugins.registry import JobRegistry, discover_jobs; discover_jobs(); print(sorted(JobRegistry.registered_types().keys()))"
```

> 褰撳墠浠撳簱鎻愪緵绀轰緥鎻掍欢 `eda.drc.calibre_dummy`锛岀敓鎴愯剼鏈細鍐欏叆 `test_work/`锛堣 `.gitignore` 蹇界暐锛夈€?
