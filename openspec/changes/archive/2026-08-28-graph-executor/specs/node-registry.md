# node-registry Specification

## Purpose

The read-only node allowlist and its seed nodes, surfaced via `/nodes/types`. Nodes are registered statically at import time, never from user input (SDD §4.3).

## Requirements

### Requirement: Allowlist-only node lookup

The registry MUST expose lookup (`get`), membership (`contains`), and schema listing (`list_schemas`) over a static set of node types. Unknown types MUST resolve to "not found" and MUST be rejected before execution, never executed.

#### Scenario: Unknown type not found

- GIVEN a registry seeded with known node types
- WHEN `contains("UnknownNode")` is called
- THEN it returns `False` and `get` returns `None`

#### Scenario: Known type resolves

- GIVEN a registered node type
- WHEN `get("<type>")` is called
- THEN the matching `INode` instance is returned

### Requirement: Static registration only

Node types MUST be registered at import/composition-root time. User-supplied input MUST NOT be able to register a node type.

#### Scenario: Registry has no user-driven registration path

- GIVEN the registry interface
- WHEN an API request attempts to add a node type
- THEN no such operation exists or is reachable through the allowlist

### Requirement: Seed nodes

The composition root MUST seed the registry with three nodes: `pass-through`, `merge`, and `frame-range`. Each MUST declare a valid `NodeSchema` (typed input/output ports).

#### Scenario: Seed nodes are present

- GIVEN the application's DI container is built
- WHEN the registry's schemas are listed
- THEN `pass-through`, `merge`, and `frame-range` are present

#### Scenario: Seed nodes declare typed ports

- GIVEN each seed node's `NodeSchema`
- WHEN the schema is inspected
- THEN every input/output port carries a `DataType`

### Requirement: Node types endpoint

`GET /nodes/types` MUST return the allowlisted node schemas derived from the registry.

#### Scenario: Endpoint returns seed schemas

- GIVEN the seeded registry
- WHEN `GET /nodes/types` is called
- THEN the response lists the seed node schemas (not an empty array)

#### Scenario: Empty registry returns empty list

- GIVEN an unseeded registry
- WHEN `GET /nodes/types` is called
- THEN the response is an empty list without error
