# video-media-serving Specification

## Purpose

HTTP endpoints that serve individual video frames and accept video uploads, plus the shared media path resolver that enforces the media allowlist for every media access (SDD §4.3).

## Requirements

### Requirement: Frame serving endpoint

The system MUST provide `GET /media/frame` returning a single video frame as a JPEG image. The endpoint MUST require authentication via `require_token`, MUST accept a video reference relative to `media_root` and a 1-based frame index, and MAY accept a width for resizing. It MUST resolve the video path through the shared `resolve_media_path()` allowlist utility and MUST reject absolute or traversal paths before any file is opened. Frame decode MUST NOT run inline on the event loop thread.

#### Scenario: Authenticated request returns a frame

- GIVEN an authenticated request for a valid video and frame index
- WHEN `GET /media/frame` is called
- THEN the response is a JPEG of the requested frame

#### Scenario: Out-of-range frame rejected

- GIVEN a frame index beyond the video length
- WHEN the endpoint is called
- THEN the request fails without returning a JPEG

#### Scenario: Traversal or absolute path rejected

- GIVEN a video reference containing traversal components or an absolute path
- WHEN the endpoint is called
- THEN the request fails before any file read

#### Scenario: Unauthenticated request rejected

- GIVEN a request without a valid token
- WHEN the endpoint is called
- THEN the request is rejected with an authentication error

### Requirement: Video upload endpoint

The system MUST provide `POST /media/upload` accepting a multipart video upload. It MUST require authentication, MUST reject files larger than `max_video_bytes`, and MUST store the file only under `media_root`, validating the target with the shared resolver so no path escapes the allowlist.

#### Scenario: Valid upload stored under media root

- GIVEN an authenticated request with a video file at or below `max_video_bytes`
- WHEN the endpoint is called
- THEN the file is stored under `media_root` and a reference is returned

#### Scenario: Oversized upload rejected

- GIVEN a file larger than `max_video_bytes`
- WHEN the endpoint is called
- THEN the upload is rejected and nothing is stored

#### Scenario: Unauthenticated upload rejected

- GIVEN an upload without a valid token
- WHEN the endpoint is called
- THEN the upload is rejected with an authentication error

### Requirement: Shared media path resolver

The system MUST provide `resolve_media_path(media_root, relative_path)` in the shared layer. It MUST reject absolute paths and traversal components, MUST return a path under `media_root`, and MUST reject references to files outside the allowlist. It MUST be the single security boundary used by both the frame-serving endpoint and `FrameExtractorNode` (decision D3).

#### Scenario: Relative path inside media root resolves

- GIVEN a relative path inside `media_root`
- WHEN the resolver validates it
- THEN the resolved path is returned and the file may be read

#### Scenario: Path escaping media root rejected

- GIVEN a path that resolves outside `media_root` (absolute or traversal)
- WHEN the resolver validates it
- THEN resolution fails and no file is read