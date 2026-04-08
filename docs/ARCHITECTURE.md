# Scheduler Architecture

## Layered View

From top to bottom:

1. User entry
   - `cellflow run <workflow.yaml>`
2. Flow manager
   - `flow_controller.runtime.local_orchestrator.LocalFlowOrchestrator`
3. Abstract task node
   - `flow_controller.spec.task_models.TaskNode`
4. Abstract task template
   - `eda_tasks.task_template.TaskTemplate` and `DefaultTaskTemplate`
5. Concrete task plugin
   - subclasses of `eda_tasks.base_job.BaseEDAJob`

## End-to-End Scheduling Flow

### 1) CLI parses YAML and builds DAG

Entry is `src/cellflow/__main__.py`.

- Load YAML mapping.
- Parse `flow/tasks` to `FlowConfig` (Pydantic validation).
- Convert each `TaskConfig` to `TaskNode`.
- Register nodes and dependencies into `DAGManager`.

Relevant code:

- `flow_controller.spec.yaml_parser.YAMLParser`
- `flow_controller.spec.yaml_parser.apply_flow_config_to_dag`
- `flow_controller.spec.yaml_parser._task_config_to_task_node`

### 2) Plugin instantiation (pure plugin model)

During `_task_config_to_task_node`:

- If `task_cfg.job_type` is provided, scheduler resolves plugin class from `JobRegistry`.
- It instantiates the plugin with `job_params`.
- Instance is attached to `TaskNode.job`.

So the node already holds its concrete plugin instance before runtime scheduling starts.

### 3) DAG readiness decision

`DAGManager.get_ready_tasks()` marks task as ready when:

- node status is `Pending`, and
- all upstream nodes are `Success`.

Tasks with no upstream dependencies are ready directly.

### 4) Orchestrator run loop

`LocalFlowOrchestrator.run()` does:

- Prepare workspace for each node (if missing).
- Loop until no ready tasks:
  - Query ready tasks from DAG.
  - Mark them `READY`.
  - `dry_run`: run only input checks and mark status.
  - normal run: execute ready batch concurrently via `asyncio.gather`.

Per-task execution (`_run_one`):

- set `RUNNING`
- call `template.launch(node, mode, wm)`
- update to `SUCCESS` or `FAILED`

### 5) TaskTemplate lifecycle (layer 4)

`DefaultTaskTemplate.launch()` standardizes lifecycle:

1. Input gate:
   - `check_inputs` using `input_checks` (strong checks), or fallback `inputs` glob checks.
2. Plugin lifecycle (if `node.job` exists):
   - `job.pre_check(workspace)`
   - `job.generate_scripts(workspace)`
   - `argv = job.build_command()`
3. Execute through mode:
   - `mode.launch(..., command=argv)`
   - `mode.wait(...)`
4. On success:
   - `job.post_check(workspace)`
   - `check_outputs` via `output_checks` or `outputs` glob checks.
5. Runtime markers:
   - maintain `.running`
   - write `status.json`

### 6) Execution mode adapters

`ExecutionMode` is implemented by:

- `flow_controller.runtime.modes.local_mode.LocalMode`
- `flow_controller.runtime.modes.lsf_mode.LsfMode`

Both support `launch(..., command=None)`:

- If command is provided by plugin `build_command()`, it is used as runtime override.
- Otherwise mode can use its own static mapping.

This keeps scheduling logic stable while isolating environment-specific submit/wait behavior.

## Minimal YAML Example

```yaml
flow:
  name: demo

tasks:
  - id: drc1
    type: DRC
    depends_on: []
    job_type: eda.drc.calibre_dummy
    job_params: {}
    inputs: []
    outputs: []

execution:
  mode: local
  local_settings:
    max_parallel_jobs: 1
```

## Key Design Intent

- Scheduler controls **dependency and state transitions**.
- Template controls **node lifecycle contract**.
- Plugin controls **tool-specific behavior**.
- Mode controls **execution backend details** (local/LSF).

This separation keeps the scheduler generic and makes new EDA tools pluggable without changing DAG core logic.
