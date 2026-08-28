# Architecture Decision Records — graph-executor

## ADR-001: Align `Graph` payload contract with the `.aimgraph` format now

**Status**: Accepted (product decision, proposal question round)

**Context**

The future `.aimgraph` file format will be the canonical serialization for node graphs. Building a minimal, throwaway `Graph` model now would force a breaking migration later when `.aimgraph` lands.

**Decision**

Define the `Graph`/`GraphNode`/`Edge` Pydantic models with field names and JSON shape aligned to the planned `.aimgraph` format from the start. Subsequent `.aimgraph` work extends this model rather than replacing it.

**Consequences**

- `Graph` model is a stable contract from day one; no schema migration for the executor.
- Requires a small upfront investment to infer `.aimgraph` field naming before the format is fully specified; minor rework risk if the format drifts.

## ADR-002: Synchronous in-request execution for the first slice

**Status**: Accepted (product decision, proposal question round)

**Context**

`INode.execute` is async, but `JobStore.submit()` is synchronous. A full background-async execution system (approaches 1 and 3) is overkill while the node catalog is empty and only demo nodes exist.

**Decision**

For the first slice, `submit()` for `GRAPH_EXECUTE` runs the graph's async node coroutines to completion synchronously within the request (e.g. running the coroutines via an event-loop run), returning a terminal job snapshot (`SUCCEEDED`/`FAILED`).

**Consequences**

- Submitters receive a terminal state directly rather than polling; simpler client and test contract.
- Request latency is bounded by the slowest node (bounded by per-node timeout, SDD §4.3).
- Revisit when real CPU/GPU nodes introduce long-running work; then move to background async execution (deferred approach 3).
