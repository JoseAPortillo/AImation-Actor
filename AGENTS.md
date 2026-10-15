# AImation Actor — Agent Guide

AImation Actor is a standalone desktop tool for professional 3D animators. It
extracts **Golden Poses** (key poses) from a reference video frame by frame,
imports/exports `.fbx` with **sparse (stepped) keyframes**, and fills the empty
gaps with a 3D motion diffusion model (**CondMDI**).

- **Python 3.14+**, PySide6 desktop application.
- Target: Windows production workstations with **≤ 10 GB VRAM**.
- **Source of truth:** `docs/Plan_AImation_Actor_EN.md` is the full functional
  spec. `spec.md` holds the implementable, ID-tagged requirements (SDD layer).
  This file is the quick summary for agents. Where they disagree, the plan
  wins — **except** for the FBX backend decision below.

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
│   └── ai_port.py              # GVHMR + CondMDI contract
└── adapters/                   # INFRASTRUCTURE LAYER — concrete integrations
    ├── gui/                    # main_window.py, video_player.py, viewport_3d.py
    ├── io/                     # fbx_adapter.py — the IOPort implementation
    │   └── fbx/                # pure-Python FBX writer + Blender read bridge
    └── ai/                     # gvhmr_adapter.py, condmdi_adapter.py
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
| Pose capture   | GVHMR (world-grounded human motion recovery)                  |
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

## Domain invariants (do not break)

- **SMPL → production hierarchy** is remapped under a ground root bone `Main`.
- **Global motion** (scene translation X,Y,Z) lives on `Main`.
- **Pelvis** stores height only: local X/Y = 0, Z = ground-to-hip distance.
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
  is captured only when the user presses `K` (GVHMR needs ≥ 6 GB VRAM).
- Keep AI engines behind a **Model Factory** so they can be swapped from the GUI
  (CondMDI MVP; MDM and LAFAN1 later).

## Pipeline (MVP, condensed)

1. **Selective extraction** — animator marks Golden Poses; GVHMR processes only
   that frame; the 3D viewer shows the skeleton; export is a clean blocked FBX.
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
