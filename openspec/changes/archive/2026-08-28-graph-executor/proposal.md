# Proposal: Real Node-Graph Executor

## Intent

Replace the stub execution path with a real node-graph executor: validated `Graph` payload → `NodeRegistry` allowlist check → topological execution → `JobStore` status transitions. Today `InMemoryJobStore.submit()` short-circuits every job to `SUCCEEDED` with a canned echo, `StaticNodeRegistry` is instantiated empty (so `/nodes/types` returns `[]`), and `JobStatus` never transitions. `POST /jobs/graph/execute` takes a raw `dict` — no validated `Graph` model, no topological sort, no cycle detection, no `GraphExecutor` protocol exist.

## Scope

### In Scope
- `Graph`/`GraphNode`/`Edge` Pydantic models: unique ids, DAG + cycle detection, port typing, node allowlist.
- `GraphExecutor` domain protocol + `SynchronousGraphExecutor` concrete adapter.
- Topological sort + async node execution collected synchronously.
- `InMemoryJobStore` delegates `GRAPH_EXECUTE`; real `QUEUED → RUNNING → SUCCEEDED/FAILED` transitions + per-node logs.
- Seed `StaticNodeRegistry` with 2–3 demo nodes; `/nodes/types` returns them.
- `POST /jobs/graph/execute` consumes a validated `Graph`, not raw `dict`.
- Composition-root DI wiring in `main.py`; unit + integration tests.

### Out of Scope
- Full node catalog (AI/cleanup/output/rigging nodes).
- Real CPU/GPU model execution, file, or network I/O.
- Durable storage (in-memory loss on restart acceptable this phase).
- Background async task system / cancellation beyond existing `JobStore.cancel`.

## Capabilities

### New Capabilities
- `graph-model`: `Graph`/`GraphNode`/`Edge` models + DAG validation (topo sort, cycle detection, port typing, allowlist).
- `graph-execution`: `GraphExecutor` protocol + sync executor; node dispatch, result + log aggregation.
- `node-registry`: read-only allowlist + 2–3 seed nodes surfaced via `/nodes/types`.
- `job-lifecycle`: `JobStore` `QUEUED → RUNNING → terminal` transitions + per-node log accumulation.

### Modified Capabilities
- None (no existing `openspec/specs/`).

## Approach

**Recommended — separate `GraphExecutor` service (Approach 2).** Protocol in `domain/pipeline/executor.py`; `SynchronousGraphExecutor` in `infrastructure/virtual/executor.py`, injected into `InMemoryJobStore`. Store owns job snapshots; executor owns graph semantics.

Alternatives: (1) evolve `InMemoryJobStore` in place — rejected (SRP/ISP, hard to swap); (3) async background executor — deferred (overkill for empty catalog; revisit with AI/GPU loads).

Async boundary: `INode.execute` is async, `submit()` is sync → first slice runs coroutines synchronously in-request (recorded as ADR).

## Affected Areas

| Area | Impact |
|------|--------|
| `domain/pipeline/` (graph.py, executor.py) | New |
| `domain/job/job.py` | Modified |
| `infrastructure/virtual/` (executor.py, stores.py, node_registry.py) | Modified |
| `api/routers/jobs.py` | Modified |
| `main.py` | Modified |
| `tests/domain/test_pipeline.py`, `tests/api/test_api.py` | New/Modified |

## Security — SDD §4.3 + Threat Model

Node graph = arbitrary code execution (severity **Critical**). Unknown node types MUST be rejected before execution (allowlist-only registry). Per-node timeout bounds execution; port-typing validation blocks mismatched data between nodes.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Empty registry → untestable executor | High | Seed 2–3 nodes first slice |
| Graph payload contract undefined | Med | Canonical `Graph` model + ADR |
| Layer-rule violation (domain→infrastructure) | Med | Protocol in domain, adapter in infra |
| Async-boundary confusion | Med | Sync-run; document ADR |

## Rollback Plan

Feature branch `feat/graph-executor`; revert = `git revert <merge>`. Stub `InMemoryJobStore` preserved in history; registry/executor are additive wiring behind DI.

## Dependencies

- None external.

## Success Criteria

- [ ] `POST /jobs/graph/execute` runs a real 2–3 node DAG end-to-end with correct `SUCCEEDED` + logs.
- [ ] `/nodes/types` returns seeded nodes.
- [ ] Unknown node type rejected (not executed) with error.
- [ ] Cycle rejected.
- [ ] import-linter passes (domain pure, `api` ↛ `infrastructure`).

## Proposal question round

Open product decisions needing user review before spec/design:

1. Should the `Graph` payload contract align now with the future `.aimgraph` format, or stay minimal and migrate later?
   - **RESOLVED**: Align the `Graph` model with the future `.aimgraph` format now (recorded as ADR).
2. Is synchronous in-request execution acceptable for the first slice, or must submitters see `QUEUED` + poll?
   - **RESOLVED**: Synchronous in-request execution for the first slice (submit runs the graph and returns a terminal state).
3. Which 2–3 seed nodes (pass-through, merge, frame-range, …) best represent the first real pipeline?
   - **RESOLVED**: Seed nodes = pass-through, merge, frame-range.
