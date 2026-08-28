# graph-execution Specification

## Purpose

Node-graph execution: the `GraphExecutor` domain protocol and the `SynchronousGraphExecutor` concrete adapter. Owns topological dispatch, per-node result collection, and aggregated result + log output. Protocol lives in `domain`; the adapter lives in `infrastructure`.

## Requirements

### Requirement: GraphExecutor protocol

The domain MUST define a `GraphExecutor` protocol with a method to execute a validated `Graph` and return an aggregated execution result (outputs + logs). The protocol MUST NOT import infrastructure or framework code.

#### Scenario: Protocol is framework-free

- GIVEN the `GraphExecutor` protocol definition
- WHEN the domain layer is imported without infrastructure
- THEN the import succeeds and no FastAPI/uvicorn symbols are referenced

#### Scenario: Concrete adapter satisfies protocol

- GIVEN `SynchronousGraphExecutor` in `infrastructure`
- WHEN type-checked against the `GraphExecutor` protocol
- THEN it satisfies the protocol statically

### Requirement: Topological execution order

The executor MUST run nodes in topological order so that every node's input dependencies are computed before the node executes.

#### Scenario: Dependent node runs after producer

- GIVEN a graph with node A feeding node B
- WHEN the graph executes
- THEN A completes before B begins

### Requirement: Node dispatch via allowlist

The executor MUST resolve each node's `type` to a registered `INode` through the `NodeRegistry` allowlist. An unknown or missing type MUST fail before any node runs.

#### Scenario: Unknown node fails fast

- GIVEN a graph containing a node type not in the registry
- WHEN execution is requested
- THEN execution fails with an unknown-node-type error and no node is executed

### Requirement: Per-node timeout

Each node execution MUST be bounded by a per-node timeout; exceeding it MUST fail that node (SDD §4.3).

#### Scenario: Node exceeding timeout fails

- GIVEN a node whose execution exceeds its timeout budget
- WHEN the graph executes
- THEN the job fails with a timeout error for that node

### Requirement: Result aggregation

On success, the executor MUST aggregate node outputs into a final result keyed so the terminal node's outputs are retrievable.

#### Scenario: Successful graph returns terminal outputs

- GIVEN an acyclic graph whose nodes all succeed
- WHEN the graph executes
- THEN the result contains the terminal node's output values

### Requirement: Log aggregation

The executor MUST produce per-node log lines identically ordered with execution, appended to the job's logs.

#### Scenario: Logs reflect execution order

- GIVEN a graph with multiple nodes
- WHEN the graph executes
- THEN the job logs list each node's emission in execution order

### Requirement: Failure isolation and propagation

A failing node MUST stop execution and surface a failure reason; downstream nodes MUST NOT run.

#### Scenario: Mid-graph failure halts downstream nodes

- GIVEN a graph where node B fails
- WHEN the graph executes
- THEN no node downstream of B executes and the job reports the failure

### Requirement: Synchronous in-request execution

For the first slice, `submit()` MUST run the graph's async node coroutines to completion synchronously within the request, returning a terminal state (ADR-002).

#### Scenario: Submit returns terminal state

- GIVEN a valid graph submitted to `GRAPH_EXECUTE`
- WHEN the submit call returns
- THEN the returned job has a terminal status (SUCCEEDED or FAILED), not QUEUED
