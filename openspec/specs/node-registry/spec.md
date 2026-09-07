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

The composition root MUST seed the registry with the built-in nodes. `pose-2d` (added by the pose-2d change) MUST be the 2D pose-estimation node (category `AI`). `video-source` MUST be the OpenCV frame-extraction node (category `SOURCE`). Since this change was planned, later-archived changes (3D lifting and motion conversion) added more seed nodes to the registry; the pose-2d delta originally specified a five-node registry, and the registry subsequently evolved to seven nodes: `pass-through`, `merge`, `frame-range`, `video-source`, `pose-2d`, `pose-3d`, and `video-to-motion`. The temporal-cleanup change added an eighth seed node, the inbetween-generation change added a ninth, and the retargeting change adds a tenth. The registry MUST seed ten nodes: `pass-through`, `merge`, `frame-range`, `video-source`, `pose-2d`, `pose-3d`, `video-to-motion`, `temporal-cleanup`, `inbetween-generation`, and `retarget-map` (the rigging node, category `RIGGING`). Each MUST declare a valid `NodeSchema` (typed input/output ports).
(Previously: the registry seeded nine nodes without `retarget-map`.)

#### Scenario: Seed nodes are present

- GIVEN the application's DI container is built
- WHEN the registry's schemas are listed
- THEN `pass-through`, `merge`, `frame-range`, `video-source`, `pose-2d`, `pose-3d`, `video-to-motion`, `temporal-cleanup`, `inbetween-generation`, and `retarget-map` are present

#### Scenario: Seed nodes declare typed ports

- GIVEN each seed node's `NodeSchema`
- WHEN the schema is inspected
- THEN every input/output port carries a `DataType`

#### Scenario: temporal-cleanup is the CLEANUP node

- GIVEN the `temporal-cleanup` node in the registry
- WHEN its category and port types are inspected
- THEN its category is `CLEANUP` and it consumes/emits `NEUTRAL_ANIMATION`

#### Scenario: inbetween-generation is the ENRICHMENT node

- GIVEN the `inbetween-generation` node in the registry
- WHEN its category and port types are inspected
- THEN its category is `ENRICHMENT` and it consumes/emits `NEUTRAL_ANIMATION`

#### Scenario: retarget-map is the RIGGING node

- GIVEN the `retarget-map` node in the registry
- WHEN its category and port types are inspected
- THEN its category is `RIGGING` and it consumes/emits `NEUTRAL_ANIMATION`

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
