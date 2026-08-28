# graph-model Specification

## Purpose

The validated graph payload contract — `Graph`/`GraphNode`/`Edge` Pydantic models plus DAG validation (topological sort, cycle detection, port typing, node allowlist). This is the single source of truth consumed by `POST /jobs/graph/execute`. Pure domain layer: Pydantic v2 + standard library only.

## Requirements

### Requirement: Graph payload shape aligned with `.aimgraph`

The `Graph` model MUST expose unique node ids, edges, and a version field, and its field names/JSON shape MUST align with the future `.aimgraph` file format (ADR-001). `GraphNode` MUST carry an id, a node `type` string, and optional params. `Edge` MUST reference a source node id and port and a destination node id and port.

#### Scenario: A well-formed graph validates

- GIVEN a `Graph` with unique node ids and edges referencing existing nodes
- WHEN the graph is constructed and validated
- THEN validation succeeds with no errors

#### Scenario: A future `.aimgraph` field set round-trips

- GIVEN a serialized graph using the canonical `.aimgraph` field names
- WHEN it is parsed into the `Graph` model
- THEN every field is preserved through model serialization

### Requirement: Unique node and edge identifiers

Every `GraphNode.id` MUST be non-empty and unique within a graph. Every `Edge` MUST reference node ids that exist in the graph.

#### Scenario: Duplicate node id rejected

- GIVEN a graph containing two nodes with the same id
- WHEN the graph is validated
- THEN validation fails with an error naming the duplicate id

#### Scenario: Edge references missing node

- GIVEN an edge whose source or target id does not match any node
- WHEN the graph is validated
- THEN validation fails with an error naming the dangling reference

### Requirement: Directed acyclic graph (DAG) enforcement

The graph MUST be detected as acyclic via topological sort. A cycle MUST be rejected before execution.

#### Scenario: Acyclic DAG sorts in topological order

- GIVEN an acyclic graph
- WHEN a topological sort is computed
- THEN every node appears ordered such that each edge points from an earlier to a later node

#### Scenario: Cycle rejected before execution

- GIVEN a graph containing a cycle (e.g. A→B→A)
- WHEN the graph is validated
- THEN validation fails with a cycle-detection error and no node is executed

### Requirement: Port typing validation

Each edge connection MUST connect ports whose `DataType` is compatible. Mismatched types MUST be rejected.

#### Scenario: Compatible port connection accepted

- GIVEN an edge connecting an output port and an input port of the same `DataType`
- WHEN the graph is validated
- THEN validation succeeds

#### Scenario: Mismatched port types rejected

- GIVEN an edge connecting ports of incompatible `DataType`
- WHEN the graph is validated
- THEN validation fails with a port-typing error

### Requirement: Node type allowlist validation

Every `GraphNode.type` MUST reference a node type present in the allowlist registry. Unknown types MUST be rejected before execution (SDD §4.3, Critical).

#### Scenario: Unknown node type rejected

- GIVEN a graph whose nodes all have unknown `type` values
- WHEN the graph is validated against the allowlist
- THEN validation fails naming each unknown type and no node is executed
