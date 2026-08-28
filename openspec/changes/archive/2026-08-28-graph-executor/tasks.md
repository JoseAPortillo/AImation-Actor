# Tasks: Real Node-Graph Executor

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~700–850 additions |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 2 → PR 3 |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|----|----------------------|-----------------|-------------------|
| 1 | Domain graph model + validation | PR 1 | `.\venv\Scripts\python.exe -m pytest tests/domain/test_graph_model.py` | N/A — pure domain, no runtime | delete `graph.py`/`executor.py` + test; revert `pipeline/__init__.py` |
| 2 | Sync executor + seed nodes | PR 2 | `.\venv\Scripts\python.exe -m pytest tests/infrastructure/test_executor.py` | `.\venv\Scripts\python.exe -m pytest` (asyncio) | delete `executor.py`/`nodes.py` + test; revert `virtual/__init__.py` |
| 3 | Job lifecycle + API + DI | PR 3 | `.\venv\Scripts\python.exe -m pytest tests/domain/test_job_lifecycle.py tests/api/test_api.py` | `uvicorn` run `POST /jobs/graph/execute` | revert `stores.py`/`jobs.py`/`main.py` |

## Phase 1: Domain graph model (validation)

- [x] 1.1 RED `tests/domain/test_graph_model.py`: dup id, dangling edge, cycle, port mismatch, unknown type, `extra="allow"` round-trip.
- [x] 1.2 GREEN `domain/pipeline/graph.py`: `Graph`/`GraphNode`/`Edge`/`PortRef` + topo sort, cycle detection, port typing (`a==b or ANY`), allowlist via `NodeRegistry`.
- [x] 1.3 `domain/pipeline/executor.py`: `GraphExecutor` protocol + `GraphExecutionResult`.
- [x] 1.4 `domain/pipeline/__init__.py`: re-export graph + executor symbols.

## Phase 2: Synchronous executor + seed nodes

- [x] 2.1 RED `tests/infrastructure/test_executor.py`: topo order, timeout, failure isolation, log order, allowlist reject.
- [x] 2.2 `infrastructure/virtual/nodes.py`: `PassThroughNode` (ANY→ANY), `MergeNode` (FRAME_STREAM×2→FRAME_STREAM), `FrameRangeNode` (∅→FRAME_STREAM, params start/end NUMBER).
- [x] 2.3 `infrastructure/virtual/executor.py`: `SynchronousGraphExecutor` — topo dispatch, `asyncio.wait_for` per-node timeout, result+log aggregation.
- [x] 2.4 `infrastructure/virtual/__init__.py`: export executor + nodes.

## Phase 3: Job store lifecycle

- [x] 3.1 RED `tests/domain/test_job_lifecycle.py`: `QUEUED→RUNNING→terminal`, observable RUNNING snapshot (blocking node variant), cancel semantics.
- [x] 3.2 `infrastructure/virtual/stores.py`: `InMemoryJobStore` delegates `GRAPH_EXECUTE`; inject `(executor, registry)`; re-validate via `Graph.model_validate`; real transitions + per-node logs.

## Phase 4: API + DI wiring

- [x] 4.1 `api/routers/jobs.py`: `graph_execute` accepts `Graph` body (`model_dump()` to store), `status_code=200`.
- [x] 4.2 `main.py`: DI — registry → seed 3 nodes → executor → store.
- [x] 4.3 `tests/api/test_api.py`: 3-node DAG → SUCCEEDED + logs; unknown type/cycle → FAILED; `/nodes/types` lists 3.
- [x] 4.4 Run import-linter; confirm domain pure, `api` ↛ `infrastructure`.
