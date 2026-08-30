# AImation Actor — API Usage Tutorial

Practical, verified walkthrough for using the AImation Actor Core REST API from
a terminal. Every request below was exercised against a live server; the full
pipeline graph executes to `succeeded`.

---

## CLI usage

The `aimation` CLI (installed with the project) wraps the API above. It needs
no token for `health`; every other command reads `AIMATION_TOKEN` from the
environment, mirroring the server's startup config:

```powershell
$env:AIMATION_URL   = "http://127.0.0.1:8765"   # optional — this is the default
$env:AIMATION_TOKEN = "mi-token-12345"
```

- `aimation health` — prints the `/health` JSON (works without a token).
- `aimation nodes` — compact node catalog: `type  [category]  in=N out=N`.
- `aimation run <video> [--end N] [--height-cm X] [--output file.json]` —
  submits the full pipeline (`video-source → pose-2d → pose-3d →
  video-to-motion`), polls until terminal, and writes `v2m.motion` to
  `--output` on success (logs are printed on failure).
- `aimation job <job_id>` — job snapshot; add `result` or `logs` for those
  endpoints.
- `aimation graph <file.json> [--output file.json]` — runs a graph file (the
  §3 shape) and saves the full result JSON.

A missing `AIMATION_TOKEN` on a token-required command fails fast with a clear
error; server HTTP errors are echoed to stderr and exit non-zero.

---

## 1. Prerequisites

- Project dependencies installed (`.venv/` present; `uvicorn`, `opencv-python`).
- A reference video file under `media/` (see [Test video](#31-test-video)).

---

## 2. Starting the server

All endpoints except `/health` require a Bearer token. If you do not set
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

In a **second** terminal, define the token and base once so every request below
reuses them:

```powershell
$token = "Bearer mi-token-12345"
$base  = "http://127.0.0.1:8765"
```

> The examples use PowerShell `Invoke-RestMethod`. The endpoints are the same
> with `curl` — just add `-H "Authorization: $token"`.

---

## 3. Executing the full pipeline (pose-2d → pose-3d → motion)

The graph `video-source → pose-2d → pose-3d → video-to-motion` turns a
reference video into a **NeutralMotion** document (the skeleton + frames that a
DCC plugin consumes).

### 3.1 Test video

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

### 3.2 Submit the graph

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
```

### 3.3 Poll the job

```powershell
$jid = $job.job_id

# Job status
Invoke-RestMethod "$base/jobs/$jid" -Headers @{ Authorization = $token }

# Result — outputs per node: result.outputs.<node_id>
Invoke-RestMethod "$base/jobs/$jid/result" -Headers @{ Authorization = $token }

# Per-node logs
Invoke-RestMethod "$base/jobs/$jid/logs" -Headers @{ Authorization = $token }
```

The result shape is:

```json
{
  "status": "succeeded",
  "result": {
    "outputs": {
      "src": { "frames": [...], "fps": 10.0 },
      "p2d": { "keypoints": [...] },
      "p3d": { "keypoints_3d": [...] },
      "v2m": { "motion": { "skeleton": [...], "frames": [...] } }
    },
    "logs": [...]
  }
}
```

`result.outputs.v2m.motion` is the **NeutralMotion** animation output.

---

## 4. Other endpoints

### Node catalog (the editor palette source)

```powershell
Invoke-RestMethod "$base/nodes/types" -Headers @{ Authorization = $token } |
  ForEach-Object { "  {0}  [{1}]  in={2} out={3}" -f $_.type, $_.category, $_.inputs.Count, $_.outputs.Count }
```

```
  pass-through  [logic]      in=1 out=1
  merge         [logic]      in=2 out=1
  frame-range   [source]     in=0 out=1
  video-source  [source]     in=0 out=2
  pose-2d       [ai]         in=1 out=1
  pose-3d       [ai]         in=1 out=1
  video-to-motion [output]   in=1 out=1
```

### Health (no token required)

```powershell
Invoke-RestMethod "$base/health"
```

### Job submission routers

Accept a free-form payload; execution is delegated to the injected job store.

```powershell
Invoke-RestMethod "$base/jobs/video-to-motion"    -Method Post -Headers @{ Authorization=$token } -ContentType "application/json" -Body '{}'
Invoke-RestMethod "$base/jobs/blocking-to-motion" -Method Post -Headers @{ Authorization=$token } -ContentType "application/json" -Body '{}'
```

### Cancel a job

```powershell
Invoke-RestMethod "$base/jobs/$jid/cancel" -Method Post -Headers @{ Authorization=$token }
```

### DCC sessions (currently a skeleton)

```powershell
Invoke-RestMethod "$base/sessions" -Headers @{ Authorization=$token }
```

---

## 5. Gotchas (learned while validating)

- **`graph/execute` requires real input.** A graph with only `pose-2d` and no
  `video-source` **fails** — the `frames` input is missing. Use the full
  pipeline in §3 as the minimal graph that reaches `succeeded`.
- **`video_path` is relative to `media/`.** Absolute paths and `../` escapes are
  rejected by the media-root allowlist (security, SDD §4.3).
- **Synthetic backend.** Without `onnxruntime` the pose nodes use the
  deterministic `synthetic` backend — great for exercising the pipeline, but it
  does not perform real pose estimation yet. `/health` reports
  `"pose": "synthetic"`.
- **Start server and request in the same flow.** A background `Start-Process`
  server dies when its parent shell command returns; launch it and hit the
  endpoint within the same command (or keep the server terminal open).
