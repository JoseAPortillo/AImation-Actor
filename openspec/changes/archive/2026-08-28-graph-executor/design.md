# Design: Real Node-Graph Executor (graph-executor)

## Technical Approach

Replace the stub `InMemoryJobStore.submit()` short-circuit with a real graph path: validated `Graph` payload → allowlist/port/cycle validation → topological execution → terminal job state. A domain `GraphExecutor` protocol is implemented by `SynchronousGraphExecutor` in infrastructure and injected into `InMemoryJobStore`. ADR-002: `submit()` (sync, runs in FastAPI's threadpool via `def` handler) drives async node coroutines with `asyncio.run`, returning a terminal snapshot.

## Architecture Decisions

| # | Option | Tradeoff | Decision |
|---|--------|----------|----------|
| D1 | RUNNING observability | (a) production-only transition hook — synthetic; (b) injected blocking node + cross-thread snapshot poll — honest, no test-only prod code | **Inject a blocking seed-node variant** whose `execute` awaits an `asyncio.Event`; unit test polls `store.get(id).status` from another thread until `RUNNING`, then releases |
| D2 | Seed-node port types | leave untyped — port-typing untestable | **Pin**: pass-through `ANY→ANY`; merge `FRAME_STREAM×2→FRAME_STREAM`; frame-range `∅→FRAME_STREAM` (params `start/end: NUMBER`) |
| D3 | `.aimgraph` drift (ADR-001) | rewriting model on change vs absorbing | **`ConfigDict(extra="allow")`** on all graph models + explicit `version` field → unknown future fields round-trip losslessly; executor only reads its known fields |
| D4 | Validation location | executor-only vs model-owned | **Domain `graph.py` owns validation** (topo sort, cycle, port compatibility, allowlist) taking a `NodeRegistry` domain protocol + schemas — keeps domain pure |
| D5 | JobStore `submit` contract | typed `Graph` vs keep `dict` | **Keep `dict[str, Any]`**; router `model_dump()`s the validated `Graph`, store re-validates via `Graph.model_validate` (kind-agnostic store) |
| D6 | Port compatibility | strict equality vs wildcard | **`a==b or a==ANY or b==ANY`** — enables universal relay nodes |

## Data Flow

```
POST /jobs/graph/execute (Graph)
  → jobs.graph_execute (def, threadpool)
    → store.submit(GRAPH_EXECUTE, graph.model_dump())
        Job(QUEUED)  → persist
        Job(RUNNING) → persist
        asyncio.run(executor.run(graph, registry))
            validate allowlist + ports + cycle (reject → raise)
            topo sort
            for n in order: await wait_for(n.execute(…), timeout) + append log
            → GraphExecutionResult(outputs, logs)
        Job(terminal, result, logs) → persist
    → return Job
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `domain/pipeline/graph.py` | Create | `Graph`, `GraphNode`, `Edge`, `PortRef` models + pure validation (topo sort, cycle, port typing, allowlist, data-type compatibility) |
| `domain/pipeline/executor.py` | Create | `GraphExecutor` protocol + `GraphExecutionResult` |
| `domain/pipeline/__init__.py` | Modify | Re-export graph + executor symbols |
| `infrastructure/virtual/executor.py` | Create | `SynchronousGraphExecutor` (topo dispatch, `asyncio.wait_for` timeout, log/result aggregation) |
| `infrastructure/virtual/nodes.py` | Create | `PassThroughNode`, `MergeNode`, `FrameRangeNode` (concrete `INode`) |
| `infrastructure/virtual/stores.py` | Modify | `InMemoryJobStore` delegates `GRAPH_EXECUTE`; real `QUEUED→RUNNING→terminal`; deps `(executor, registry)` |
| `infrastructure/virtual/__init__.py` | Modify | Export executor + nodes |
| `api/routers/jobs.py` | Modify | `graph_execute` accepts `Graph` body, `status_code=200` (terminal inline, ADR-002) |
| `main.py` | Modify | DI: build registry → seed nodes → executor → store |

## Interfaces / Contracts

```python
# domain/pipeline/graph.py
class Graph(BaseModel):
    model_config = ConfigDict(extra="allow")  # .aimgraph drift (ADR-001)
    version: str
    nodes: list[GraphNode]
    edges: list[Edge] = []


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str  # unique, non-empty
    type: str  # allowlisted node type
    params: dict[str, Any] = {}


class PortRef(BaseModel):
    node: str
    port: str


class Edge(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    source: PortRef
    target: PortRef
```

```python
# domain/pipeline/executor.py
class GraphExecutionResult(BaseModel):
    outputs: dict[str, Any]  # terminal node outputs
    logs: list[str]


class GraphExecutor(Protocol):
    async def run(self, graph: Graph, registry: NodeRegistry) -> GraphExecutionResult: ...
```

## Seed Nodes

| Node | Category | Inputs | Outputs | Params | Behavior |
|------|----------|--------|---------|--------|----------|
| `pass-through` | LOGIC | `input: ANY` | `output: ANY` | — | forwards input value |
| `merge` | LOGIC | `input_a: FRAME_STREAM`, `input_b: FRAME_STREAM` | `merged: FRAME_STREAM` | — | concatenates both streams |
| `frame-range` | SOURCE | — | `frames: FRAME_STREAM` | `start: NUMBER`, `end: NUMBER` | emits frame indices `[start, end)` |

## Layer / import-linter Compliance

- `Graph`/`executor.py` depend only on Pydantic + stdlib + existing domain (`schema`, `registry` Protocols) → domain stays pure.
- `SynchronousGraphExecutor` + seed nodes import only domain → infrastructure→domain allowed.
- Router imports only `domain.pipeline.graph.Graph` → `api ↛ infrastructure` holds.
- `main.py` (package root) wires infrastructure into `app.state` → composition root, exempt per pyproject note.

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit (domain) | model validation: dup ids, dangling edge, cycle, port mismatch, unknown type, `extra="allow"` round-trip | `tests/domain/test_graph_model.py` |
| Unit (infra) | topo order, timeout, failure isolation, log order, RUNNING snapshot, allowlist reject | `tests/infrastructure/test_executor.py` + `tests/domain/test_job_lifecycle.py` |
| Integration | `POST /jobs/graph/execute` 3-node DAG → SUCCEEDED + logs; unknown type/cycle → FAILED; `/nodes/types` lists 3 | `tests/api/test_api.py` |

## Threat Matrix

`N/A` — no shell commands, subprocesses, VCS/PR automation, executable-file classification, or process-integration boundary. (Security boundary here is the *allowlist-only* node registry + per-node timeout + port typing, all covered by specs and RED tests above, not the routing/shell matrix.)

## Migration / Rollout

No migration. Additive: `InMemoryJobStore` gains `GRAPH_EXECUTE` delegation; non-graph kinds keep stub behavior (out of scope). Feature branch `feat/graph-executor`; revert = `git revert`.

## Open Questions

- [ ] Exact `.aimgraph` `version` string and any `metadata` block — `extra="allow"` absorbs; pin when spec lands.
