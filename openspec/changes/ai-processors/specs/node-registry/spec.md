# Delta for node-registry

## MODIFIED Requirements

### Requirement: Seed nodes

The composition root MUST seed the registry with four nodes: `pass-through`, `merge`, `frame-range`, and `video-source`. Each MUST declare a valid `NodeSchema` (typed input/output ports). `video-source` MUST be the new OpenCV frame-extraction node (category `SOURCE`).
(Previously: the registry seeded exactly three nodes — `pass-through`, `merge`, `frame-range`.)

#### Scenario: Seed nodes are present

- GIVEN the application's DI container is built
- WHEN the registry's schemas are listed
- THEN `pass-through`, `merge`, `frame-range`, and `video-source` are present

#### Scenario: Seed nodes declare typed ports

- GIVEN each seed node's `NodeSchema`
- WHEN the schema is inspected
- THEN every input/output port carries a `DataType`
