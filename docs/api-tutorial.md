# AImation Actor — Usage Tutorial

Practical, verified walkthrough for driving the AImation Actor Core from the
terminal. The **`aimation` CLI** is the primary, ergonomic way to use the
service; the underlying **REST API** is documented as an advanced reference at
the end. Every command below was exercised against a live server — the full
pipeline graph runs to `succeeded`.

---

## CLI usage

The `aimation` CLI (defined in `aimation_actor_core/cli.py`, entry point
`aimation` in `pyproject.toml`) wraps the REST API. It needs no token for
`health`; every other command reads `AIMATION_TOKEN` from the environment,
mirroring the server's startup config:

```powershell
$env:AIMATION_URL   = "http://127.0.0.1:8765"   # optional — this is the default
$env:AIMATION_TOKEN = "mi-token-12345"           # must match AIMATION_SESSION_TOKEN
```

If you have not installed the package, invoke the module instead of the
`aimation` binary:

```powershell
python -m aimation_actor_core.cli run sample.avi
# ...is equivalent to...
aimation run sample.avi
```

---

## 1. Prerequisites

- Project dependencies installed (`.venv/` present; `uvicorn`, `opencv-python`,
  `httpx`).
- A reference video file under `media/` (see [Test video](#12-test-video)).

---

## 2. Starting the server

All endpoints except `/health` require the Bearer token. If you do not set
`AIMATION_SESSION_TOKEN`, the server generates a random token at startup that
you cannot see — so **set a fixed token** in the environment before launching
to make terminal usage reproducible.

```powershell
cd D:\DEEP_CAVE_WORKS\CODE_WORKS\AImation_Actor

# Fix the token BEFORE startup
$env:AIMATION_SESSION_TOKEN = "mi-token-12345"

# Start the server (loopback only, per SDD §4.2)
.\.venv\Scripts\python.exe -m uvicorn aimation_actor_core.main:app `
    --host 127.0.0.1 --port 8765
```

Leave that terminal running; the server stays alive for the rest of the
session. In a **second** terminal, set the CLI env vars (shown in [CLI
usage](#cli-usage)) and you are ready.

---

## 3. Run the full pipeline (pose-2d → pose-3d → motion)

The graph `video-source → pose-2d → pose-3d → video-to-motion` turns a
reference video into a **NeutralMotion** document (the skeleton + frames that a
DCC plugin consumes). With the CLI this is a one-liner.

### 3.1 Check the server is up

```powershell
aimation health
```
```json
{ "status": "ok", "models": "none", "video": "loaded", "pose": "synthetic", "pose3d": "synthetic" }
```

### 3.2 Test video

A `media/sample.avi` (20 frames, moving circle) is used here. To regenerate it:

```powershell
.\.venv\Scripts\python.exe -c @"
import cv2, numpy as np
vw=cv2.VideoWriter('media/sample.avi',cv2.VideoWriter_fourcc(*'MJPG'),10,(128,128))
for i in range(20):
    f=np.zeros((128,128,3),np.uint8); cv2.circle(f,(64+i,64),20,(0,200,255),-1); vw.write(f)
vw.release()
"@
```

### 3.3 Run the pipeline

```powershell
aimation run sample.avi --end 5 --output motion.json
```
```
job <uuid>: succeeded
```

On success this writes `v2m.motion` (the NeutralMotion) as pretty JSON to
`motion.json`. The document has the keys
`meta, skeleton, frames, contacts, keyposes, tracking`. On failure it prints the
server per-node log lines instead.

Options:
- `--end <N>` — extract frames up to index `N` (default `5`).
- `--height-cm <X>` — optional actor height used to upscale keypoints.
- `--output <file>` — write the motion JSON to a file (omit to only print status).

---

## 4. Inspect a job

Every `aimation run`/`graph` call submits a job. Inspect it by id:

```powershell
aimation job <job_id>                  # job snapshot: status, error if any
aimation job <job_id> result           # full result JSON (per-node outputs)
aimation job <job_id> logs             # per-node log lines
```

---

## 5. Other CLI commands

### Node catalog (the editor palette source)

```powershell
aimation nodes
```
```
pass-through     [logic]   in=1 out=1
merge            [logic]   in=2 out=1
frame-range      [source]  in=0 out=1
video-source     [source]  in=0 out=2
pose-2d          [ai]      in=1 out=1
pose-3d          [ai]      in=1 out=1
video-to-motion  [output]  in=1 out=1
```

### Execute a graph from a file

```powershell
aimation graph mygraph.json --output result.json
```

`mygraph.json` uses the `.aimgraph` graph shape shown in the [advanced
reference](#api-http-reference-advanced). The full result (all node outputs) is
written to `--output` on success.

### Fail-fast behaviour

A missing `AIMATION_TOKEN` on a token-required command fails fast with a clear
`error: AIMATION_TOKEN not set`; server HTTP errors are echoed to stderr and
exit non-zero.

---

## 6. Gotchas (learned while validating)

- **`graph/execute` requires real input.** A graph with only `pose-2d` and no
  `video-source` **fails** — the `frames` input is missing. Use the full
  pipeline in §3 as the minimal graph that reaches `succeeded`.
- **`video_path` is relative to `media/`.** Absolute paths and `../` escapes are
  rejected by the media-root allowlist (security, SDD §4.3).
- **Synthetic backend.** Without `onnxruntime` the pose nodes use the
  deterministic `synthetic` backend — great for exercising the pipeline, but it
  does not perform real pose estimation yet. `/health` reports
  `"pose": "synthetic"`.
- **Server must stay up.** The CLI is a thin HTTP client — start the server
  (§2) and keep it running in its own terminal. A background `Start-Process`
  server dies when its parent shell command returns.

---

# API HTTP reference (advanced)

The CLI is a thin wrapper over this REST API. Use these calls directly when you
need finer control (custom graphs, scripting, cross-language clients).

Auth: `Authorization: Bearer <token>` on every request except `/health`. Use
the same `$token`/`$base` defined below:

```powershell
$token = "Bearer mi-token-12345"
$base  = "http://127.0.0.1:8765"
```

> The examples use PowerShell `Invoke-RestMethod`. The endpoints are the same
> with `curl` — just add `-H "Authorization: $token"`.

## Health (no token)

```powershell
Invoke-RestMethod "$base/health"
```

## Node catalog

```powershell
Invoke-RestMethod "$base/nodes/types" -Headers @{ Authorization = $token }
```

## Submit and poll a graph

```powershell
$graph = @{
  version = "1.0"
  nodes   = @(
    @{ id="src"; type="video-source";    params=@{ video_path="sample.avi"; end=5; resize=64 } }
    @{ id="p2d"; type="pose-2d";         params=@{ model="synthetic" } }
    @{ id="p3d"; type="pose-3d";         params=@{ model="synthetic" } }
    @{ id="v2m"; type="video-to-motion"; params=@{} }
  )
  edges   = @(
    @{ id="e1"; source=@{node="src";port="frames"};       target=@{node="p2d";port="frames"} }
    @{ id="e2"; source=@{node="p2d";port="keypoints"};    target=@{node="p3d";port="keypoints"} }
    @{ id="e3"; source=@{node="p3d";port="keypoints_3d"}; target=@{node="v2m";port="keypoints_3d"} }
  )
} | ConvertTo-Json -Depth 8

$job = Invoke-RestMethod "$base/jobs/graph/execute" -Method Post `
  -Headers @{ Authorization = $token } -ContentType "application/json" -Body $graph
$job.job_id   # note this id

# Poll
Invoke-RestMethod "$base/jobs/$($job.job_id)"        -Headers @{ Authorization = $token }
Invoke-RestMethod "$base/jobs/$($job.job_id)/result" -Headers @{ Authorization = $token }
Invoke-RestMethod "$base/jobs/$($job.job_id)/logs"   -Headers @{ Authorization = $token }
```

The `/result` shape is `result.outputs.<node_id>.<port>`; `outputs.v2m.motion`
is the **NeutralMotion** output.

## Other endpoints

```powershell
# Job submission routers (free-form payload)
Invoke-RestMethod "$base/jobs/video-to-motion"    -Method Post -Headers @{ Authorization=$token } -ContentType "application/json" -Body '{}'
Invoke-RestMethod "$base/jobs/blocking-to-motion" -Method Post -Headers @{ Authorization=$token } -ContentType "application/json" -Body '{}'

# Cancel a job
Invoke-RestMethod "$base/jobs/$jid/cancel" -Method Post -Headers @{ Authorization=$token }

# DCC sessions (currently a skeleton)
Invoke-RestMethod "$base/sessions" -Headers @{ Authorization=$token }
```

### Node catalog (full reference)

```
  pass-through  [logic]      in=1 out=1
  merge         [logic]      in=2 out=1
  frame-range   [source]     in=0 out=1
  video-source  [source]     in=0 out=2
  pose-2d       [ai]         in=1 out=1
  pose-3d       [ai]         in=1 out=1
  video-to-motion [output]   in=1 out=1
```
