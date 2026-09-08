# node-registry — Delta Specs

== Capability: node-registry (MODIFIED) ==

## MODIFIED Requirements

### Requirement: Seed nodes

The composition root MUST seed the registry with the built-in nodes. `pose-2d` (added by the pose-2d change) MUST be the 2D pose-estimation node (category `AI`). `video-source` MUST be the OpenCV frame-extraction node (category `SOURCE`). Since this change was planned, later-archived changes (3D lifting and motion conversion) added more seed nodes to the registry; the pose-2d delta originally specified a five-node registry, and the registry subsequently evolved to seven nodes: `pass-through`, `merge`, `frame-range`, `video-source`, `pose-2d`, `pose-3d`, and `video-to-motion`. The temporal-cleanup change added an eighth seed node, the inbetween-generation change added a ninth, and the retargeting change added a tenth. The blocking-inbetween change adds an eleventh. The registry MUST seed eleven nodes: `pass-through`, `merge`, `frame-range`, `video-source`, `pose-2d`, `pose-3d`, `video-to-motion`, `temporal-cleanup`, `inbetween-generation` (the enrichment node, category `ENRICHMENT`), `retarget-map` (the rigging node, category `RIGGING`), and `blocking-input` (the blocking source node, category `SOURCE`, output `NEUTRAL_ANIMATION`). Each MUST declare a valid `NodeSchema` (typed input/output ports).
(Previously: the registry seeded ten nodes without `blocking-input`.)

#### Scenario: Seed nodes are present

- GIVEN the application's DI container is built
- WHEN the registry's schemas are listed
- THEN `pass-through`, `merge`, `frame-range`, `video-source`, `pose-2d`, `pose-3d`, `video-to-motion`, `temporal-cleanup`, `inbetween-generation`, `retarget-map`, and `blocking-input` are present

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

#### Scenario: blocking-input is the blocking SOURCE node

- GIVEN the `blocking-input` node in the registry
- WHEN its category and port types are inspected
- THEN its category is `SOURCE` and it emits `motion: NEUTRAL_ANIMATION`

### Requirement: Node types endpoint

`GET /nodes/types` MUST return the allowlisted node schemas derived from the registry.

#### Scenario: Endpoint returns seed schemas

- GIVEN the seeded registry
- WHEN `GET /nodes/types` is called
- THEN the response lists the seed node schemas including `blocking-input` (not an empty array)

#### Scenario: Empty registry returns empty list

- GIVEN an unseeded registry
- WHEN `GET /nodes/types` is called
- THEN the response is an empty list without error
