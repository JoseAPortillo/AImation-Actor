# video-preprocessing Specification

## Purpose

A real OpenCV video-preprocessing node that decodes a video file into frames. This is the first genuine stage of the AI pipeline (plan §12). It conforms to the existing `INode` contract and runs through the current graph executor unchanged.

## Requirements

### Requirement: Frame extraction node contract

The system MUST provide `FrameExtractorNode` with schema type `video-source` and category `SOURCE`. It MUST declare a required param `video_path` of `DataType.VIDEO_PATH`, an output port `frames` of `DataType.FRAMES` and an output port `fps` of `DataType.NUMBER`, and params `start`, `end`, and `resize` (all optional), each with a valid `DataType`. The source path is supplied as a param (not an input port): a SOURCE node carries no feeding edge, so its seed value arrives via `params` per the `GraphNode` contract.

#### Scenario: Node declares its catalog schema

- GIVEN the `FrameExtractorNode` type
- WHEN `get_schema()` is called
- THEN `type` is `video-source`, `category` is `SOURCE`, the `video_path` is a required param of type `VIDEO_PATH`, and the `frames`/`fps` output ports are typed `FRAMES`/`NUMBER`

#### Scenario: Params govern decode window and scale

- GIVEN `start`, `end`, and `resize` params
- WHEN the node is executed with those params
- THEN only frames within `[start, end]` are emitted and each frame is resized per `resize`

### Requirement: FPS detection

The system MUST read frame rate metadata from the source via `cv2.VideoCapture` and expose it on the decoded output.

#### Scenario: FPS reported from source metadata

- GIVEN a video fixture with a known frame rate
- WHEN the node decodes it
- THEN the output reports the source FPS

### Requirement: Non-blocking decode offload

The node MUST NOT stall the asyncio event loop while decoding. Blocking decode work MUST be offloaded from the event loop (decision D1).

#### Scenario: Event loop stays responsive during decode

- GIVEN a large video being decoded
- WHEN `execute` is awaited from an asyncio loop
- THEN the loop remains responsive and the blocking read does not run inline on the loop thread

### Requirement: Source path validation

`VIDEO_PATH` is user-supplied and MUST be validated before any file is opened. The node MUST resolve the path under an allowlisted media root and MUST reject disallowed paths before `cv2.VideoCapture` reads them. It MUST NOT read arbitrary filesystem paths outside the defined contract.

#### Scenario: Allowed path decodes

- GIVEN a video path inside the allowlisted media root
- WHEN the node executes
- THEN the video is decoded without path rejection

#### Scenario: Disallowed path rejected before read

- GIVEN a `VIDEO_PATH` outside the allowlist (e.g. an absolute path elsewhere or a traversal path)
- WHEN the node validates it
- THEN validation fails and no read is attempted

### Requirement: No external code execution

The node MUST NOT execute any external code or shell, and it MUST NOT register anything from user input. Registration remains static at import time (SDD §4.3).

#### Scenario: Untrusted input cannot trigger code execution

- GIVEN a `VIDEO_PATH` or param that attempts to invoke an executable or shell
- WHEN the node processes the request
- THEN no external process is spawned and the input is treated strictly as a file path
