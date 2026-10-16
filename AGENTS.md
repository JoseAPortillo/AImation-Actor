# AImation Actor — Agent Guide

AImation Actor is a standalone desktop tool for professional 3D animators. It
extracts **Golden Poses** (key poses) from a reference video frame by frame,
imports/exports `.fbx` with **sparse (stepped) keyframes**, and fills the empty
gaps with a 3D motion diffusion model (**CondMDI**).

- **Python 3.14+**, PySide6 desktop application. The pose engine runs in its own
  Python 3.10 environment, outside this process (see «Pose engine decision»).
- Target: Windows production workstations with **≤ 10 GB VRAM**.
- **Source of truth:** `docs/Plan_AImation_Actor_EN.md` is the full functional
  spec. `spec.md` holds the implementable, ID-tagged requirements (SDD layer).
  This file is the quick summary for agents. Where they disagree, the plan
  wins — **except** for the FBX backend and pose engine decisions below.

## Architecture: Hexagonal Monolith (Ports & Adapters)

External dependencies (PySide6, PyTorch, Blender) must never leak into the
animation core.

- **Dependency direction is one-way:** `adapters → ports → core`. Never import
  adapters from `core` or `ports`.
- `core/` — pure domain logic. **Zero external dependencies** (no Qt, no torch,
  no Blender).
- `ports/` — abstract contracts only. No implementations, no third-party imports.
- `adapters/` — all concrete integrations, isolated behind ports.

### Directory structure

```text
aimation_actor/
├── main.py                     # Application entry point
├── core/                       # DOMAIN LAYER — pure logic, 0 external deps
│   ├── models.py               # TimelineState, Keyframe, JointData
│   └── services.py             # key management, offset calculation
├── ports/                      # INTERFACE LAYER — abstract contracts
│   ├── io_port.py              # FBX read/write contract
│   └── ai_port.py              # pose-engine + inbetweening contract
└── adapters/                   # INFRASTRUCTURE LAYER — concrete integrations
    ├── gui/                    # main_window.py, video_player.py, viewport_3d.py
    ├── io/                     # fbx_adapter.py — the IOPort implementation
    │   └── fbx/                # pure-Python FBX writer + Blender read bridge
    └── ai/                     # hmr2_adapter.py, condmdi_adapter.py
tests/                          # unit tests for core and ports
assets/                         # icons, styles, sample data
```

## Tech stack

| Concern        | Choice                                                        |
| -------------- | ------------------------------------------------------------- |
| Language / GUI | Python 3.14+, PySide6 6.12 (Qt6)                               |
| Video          | `QtMultimedia` / `QtMultimediaWidgets` (streaming)            |
| 3D viewport    | `QOpenGLWidget` + PyOpenGL (or QtQuick3D)                     |
| **3D I/O**     | **Custom pure-Python FBX writer** + **Blender 5.2 for reading** |
| Pose capture   | **HMR2.0** — single-image SMPL regression, out-of-process      |
| AI backend     | PyTorch 2.x (CUDA build)                                      |
| Inbetweening   | CondMDI (MVP); MDM / LAFAN1 on roadmap                        |
| Tooling        | `venv` + pip; Ruff (lint/format); pytest (+ pytest-qt)        |

### FBX backend decision (supersedes the plan)

The plan proposes the Autodesk FBX Python SDK. **This project avoids it entirely**,
splitting the read and write paths:

- **Writing — a custom, pure-Python binary FBX writer** (`adapters/io/fbx/`):
  a node codec (`binary.py`) plus a `TimelineState` → node-tree builder
  (`document.py`). It emits only the subset we need (a `LimbNode` skeleton and
  constant-interpolation curves), so **sparse, stepped keys survive verbatim**.
  Blender's exporter is not used to write: it bakes one key per frame and
  renumbers the frame range, which destroys the tool's core requirement.
- **Reading — Blender 5.2 as an external subprocess**:
  `blender --background --factory-startup --python <bridge> -- IN OUT`
  (`adapters/io/fbx/blender_import.py`) imports the file and dumps the animation
  to JSON. Blender's importer is the most battle-tested, needs no SDK, and the
  subprocess isolates both the GPL and any Blender crash from the Qt app.
  **Do not `import bpy` into the application process.**
- Blender path: `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`
  (override with the `AIMATION_BLENDER` env var or the adapter's
  `blender_executable` argument).

### FBX conventions (writer ↔ reader)

- **Axes:** the domain is **Z-up** right-handed centimetres; FBX output is
  **Y-up** right-handed centimetres. Translations and rotations are conjugated by
  `A = R_x(-90°)` (see `adapters/io/fbx/transform.py`). Rotations are written as
  **Euler XYZ degrees** (`RotationOrder = XYZ`); stepped keys make this lossless.
- **Time:** `time = frame / fps * KTIME`, i.e. FBX time 0 = frame 0. Blender only
  *appears* off by one because its importer defaults to the 1-based
  `anim_offset = 1.0` — validate with `anim_offset = 0.0`.
- **Read bridge:** emits raw armature-space (FBX-space) local transforms plus the
  armature object's `matrix_world` quaternion and scale; the adapter converts
  them (`t_domain = rotate(q_world, t) * scale * 100`,
  `q_domain = q_world ⊗ q ⊗ q_world⁻¹`). Sampled frames are the union of all
  fcurve keyframe times, each recorded as a full pose snapshot.
- **Precision:** Blender keeps transforms in float32, so a read/write round trip
  is exact only to ~1 ULP of the magnitude (~1.2e-4 at 1000 cm).
- **Limitation:** `JointData.rest_translation` is a parent-frame `Lcl` offset and
  the domain assumes identity bind rotations. Animation round-trips exactly, but a
  foreign rig with rotated bind orientations has no faithful bind *pose* here.

### Pose engine decision (supersedes the plan)

The plan names **GVHMR** as the capture engine. **This project uses HMR2.0**
(`shubham-goel/4D-Humans`). The plan's premise — FR-CAP-05's *"GVHMR processes
**only** that isolated frame"* — is false as written, and the correction is the
whole reason for the switch: GVHMR is **sequence-native**. Its world trajectory
starts at `[0,0,0]` and accumulates per-frame root velocities, its foot-locking
updates frame by frame, and its camera frame comes from visual odometry. At one
frame — exactly what marking a Golden Pose produces — those mechanisms are
undefined, not merely weakened.

Its own ablation says the temporal machinery serves the **world**, not the
joints: removing foot-locking leaves local `PA-MPJPE`/`MPJPE` unchanged
(`39.5`/`66.0`) while only the world metrics degrade (`WA-MPJPE100` `78.8 →
89.3`). This tool discards world placement anyway (`Main` ships in place), so
GVHMR's advantage is **unreachable here** — while costing ViTPose (~2.55 GB), a
detector, and a much heavier pipeline.

- **Engine: HMR2.0** — single-image by design, MIT code, ~2.7 GB checkpoint.
  Accuracy, 3DPW `PA-MPJPE`: `44.5 mm` for the `a` variant, **`54.3 mm` for the
  released `b` checkpoint**. GVHMR's `36.2 mm` is *with 120 frames of context*,
  which is not available at one frame. **Budget an animator cleanup pass per
  Golden Pose**; `PCK@0.05` on `LSP-Ext` is only `0.53`.
- **Out of process, like Blender.** HMR2.0's stack pins versions this project's
  interpreter does not carry, so it runs in its own **Python 3.10** environment
  and the adapter talks to it across a process boundary.
  **Never import the engine into the application process** — same isolation
  reasons as `bpy` (FR-IMP-03).
- **No `detectron2`, no `chumpy`.** `detectron2` only produces bounding boxes
  (the model and its dataset class consume boxes directly) and the animator
  already chooses the frame, so a manual box — or any detector — replaces it.
  `chumpy` is needed only to unpickle the SMPL `.pkl`, converted once offline.
- **Weights are user-supplied, never vendored.** The checkpoint and the SMPL body
  model are downloaded and registered by the user; no weight file is tracked.
- **Licensing — do not lose this.** The *code* is MIT, but the runtime needs
  `smplx` and the **SMPL body model**, both **non-commercial-only and
  non-redistributable**. Personal use is covered. **Distributing or selling this
  tool requires a commercial licence from Meshcapade/Max-Planck** — and no
  permissively-licensed body-model estimator exists (HybrIK, OSX, SMPLer-X,
  TokenHMR, Multi-HMR and VideoPose3D all inherit the same terms). Only landmark
  models such as MediaPipe BlazePose (Apache-2.0) avoid it, and they ship no body
  model and publish no 3D accuracy metric at all. See `spec.md` §4.14.
- **Open, not yet measured:** the absolute **hip height** comes from a
  weak-perspective estimate, so monocular scale is a learned guess rather than a
  measurement; and no VRAM/latency figure is published for HMR2.0. Both are
  measured before the adapter is specified in detail (`spec.md` §4.13).

## Domain invariants (do not break)

- **SMPL → production hierarchy** is remapped under a ground root bone `Main`.
- **`Main` is the animator's world control.** The capture never writes it: the
  blocking export ships **in place**, with `Main` at `(0, 0, 0)` and identity
  rotation, and the horizontal displacement the engine recovers is deliberately
  dropped. Moving `Main` never rewrites the captured local coordinates of its
  children, so world placement stays independent from the captured pose.
- **Pelvis** stores height only: local X/Y = 0, Z = ground-to-hip distance.
- **Pose translations are offsets from each joint's `rest_translation`**, not
  absolute locals: the FBX writer adds the bind back when it emits
  `Lcl Translation` (`adapters/io/fbx/document.py`).
- **Body bones** store **quaternions only** (W, X, Y, Z) — no Euler angles.
- **Sparse keyframing:** keys exist strictly at the user-selected frame indices;
  gaps contain no keys at all.
- **Tangents** are exported **Stepped / Constant** (never auto-interpolated).
- **File format:** binary FBX 7.4 (`FBX7400`), written by the in-repo writer and
  read back through Blender.
- Imported "Refined FBX": hierarchy must include `Main`; the tool extracts pose
  snapshots from keyed frames and ignores Bézier/Linear interpolation types.

## Execution & performance rules

- All AI inference runs in a `QThread`, **batch size = 1**, isolated from the UI.
- Use **FP16** to halve model memory; call `torch.cuda.empty_cache()` after each
  successful inference.
- Video is **streamed**, never fully decoded into RAM; a single RGB frame buffer
  is captured only when the user presses `K`. The engine holds no frame history
  either — it is single-image by design, so the captured buffer is the only image
  in memory.
- Keep AI engines behind a **Model Factory** so they can be swapped from the GUI
  (CondMDI MVP; MDM and LAFAN1 later).

## Pipeline (MVP, condensed)

1. **Selective extraction** — animator marks Golden Poses; the pose engine
   processes only that frame; the 3D viewer shows the skeleton; export is a clean
   blocked FBX.
2. **Artistic filter** — animator refines the FBX in Maya/Blender and re-exports.
3. **Generative inbetweening** — tool locks human keys as hard constraints, the
   diffusion model fills the gaps, then IK cleanup pins feet (no sliding) before
   the final FBX export.

## Environment & commands

Interpreter: `.venv` at the repo root (Python 3.14). Use it by full path — no
need to activate:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt --index-url https://download.pytorch.org/whl/cu130
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest
```

## Engineering principles (required)

Every change must respect these principles. They are not optional polish — they
are the bar for a change to be acceptable.

### SOLID (applied to ports & adapters)

- **S — Single Responsibility.** One module/class, one reason to change:
  `core/models.py` holds data, `core/services.py` holds logic, each adapter wraps
  exactly one integration.
- **O — Open/Closed.** Extend behavior with new adapters/ports, not by editing
  existing ones. A new AI backend is a new adapter + model-factory entry, with no
  edits to `core/`.
- **L — Liskov Substitution.** Any port implementation must be drop-in
  replaceable; keep port contracts honest and never tighten preconditions or
  weaken postconditions in an adapter.
- **I — Interface Segregation.** Ports stay small and focused (I/O vs AI). Never
  force an adapter to implement methods it does not need.
- **D — Dependency Inversion.** High-level policy (`core/`) depends on
  abstractions (`ports/`), never on concretions (`adapters/`, Qt, torch, Blender).
  This is the same one-way rule as the architecture section.

### SDD — Spec-Driven Development

- The spec is the source of truth: `docs/Plan_AImation_Actor_EN.md` (functional
  spec) and this file (agent-facing summary). Resolve behavior/interface
  questions from the spec, not from improvisation.
- Spec first, code second: when a change alters behavior or interfaces, update the
  spec (and this summary) in the same change set that touches the code.
- Every implementation must be traceable to a spec requirement. If it is not in
  the spec, propose the spec change before writing the code.
- Where spec and code disagree, the spec wins for behavior — the FBX backend
  decision in this file is the standing exception.

### General good practices

- Small, focused changes in reviewable units; keep tests and docs next to the code
  they describe.
- Explicit over implicit; pure functions in `core/`; no hidden global state.
- Fail fast with clear errors; validate at the boundaries (adapters) and keep the
  domain free of defensive checks it should not need.
- Boy-scout rule: leave code you touch at least as clean as you found it.
- Keep the automated gates green: `ruff check` and `pytest`.

## Working conventions for agents

- Apply the engineering principles above (SOLID, SDD, good practices) to every
  change; the plan (`docs/Plan_AImation_Actor_EN.md`) wins on behavior/interface
  questions; keep this summary in sync if decisions change.
- Keep `core/` and `ports/` free of third-party imports at all times.
- Add new infrastructure only as an adapter behind a port.
- `tests/` covers `core/`, `ports/`, and the pure-Python parts of the FBX
  adapter (codec, node tree, conversions, JSON → domain). The Blender subprocess
  path needs a Blender install, so it is exercised manually, not in CI.
