# Delta for video-preprocessing

## MODIFIED Requirements

### Requirement: Source path validation

`VIDEO_PATH` is user-supplied and MUST be validated before any file is opened. The node MUST resolve the path through the shared `resolve_media_path(media_root, relative_path)` utility, which rejects absolute and traversal paths and enforces the `media_root` allowlist, before `cv2.VideoCapture` reads the file. It MUST NOT read arbitrary filesystem paths outside the defined contract. The node MUST use the same security boundary as the media frame-serving endpoint (decision D3).
(Previously: the node used its own inline `_resolve_video_path()` allowlist check.)

#### Scenario: Allowed path decodes

- GIVEN a video path inside the allowlisted media root
- WHEN the node executes
- THEN the video is decoded without path rejection

#### Scenario: Disallowed path rejected before read

- GIVEN a `VIDEO_PATH` outside the allowlist (e.g. an absolute path elsewhere or a traversal path)
- WHEN the node validates it
- THEN validation fails and no read is attempted

#### Scenario: Shared boundary with media serving

- GIVEN the shared resolver used by the media frame-serving endpoint
- WHEN the node validates the same path
- THEN both call sites enforce the identical allowlist