# AImation Actor — Agent Guide

AImation Actor is a standalone desktop tool for professional 3D animators. It
extracts **Golden Poses** (key poses) from a reference video frame by frame,
imports/exports `.fbx` with **sparse (stepped) keyframes**, and fills the empty
gaps with a 3D motion diffusion model (**CondMDI**).

- **Python 3.14+**, PySide6 desktop application.
- Target: Windows production workstations with **≤ 10 GB VRAM**.
- **Source of truth:** `docs/Plan_AImation_Actor_EN.md` is the full functional
  spec. This file is the quick summary for agents. Where they disagree, the plan
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
    ├── io/                     # fbx_adapter.py (external Blender subprocess)
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
| **3D I/O**     | **Blender 5.2 LTS as an external subprocess** (see below)      |
| Pose capture   | GVHMR (world-grounded human motion recovery)                  |
| AI backend     | PyTorch 2.x (CUDA build)                                      |
| Inbetweening   | CondMDI (MVP); MDM / LAFAN1 on roadmap                        |
| Tooling        | `venv` + pip; Ruff (lint/format); pytest (+ pytest-qt)        |

### FBX backend decision (supersedes the plan)

The plan proposes the Autodesk FBX Python SDK. **This project uses Blender
instead**, invoked as an external process:

- Call `blender --background --python <script>` and drive
  `bpy.ops.import_scene.fbx` / `bpy.ops.export_scene.fbx`.
- Rationale: Blender's FBX importer/exporter is the most battle-tested in the
  industry, needs no Autodesk SDK, and keeps the Python version unconstrained.
- Running Blender as a **subprocess** isolates both the GPL and any Blender crash
  from the Qt app. Do **not** `import bpy` into the application process.
- Blender path on this machine: `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`.

## Domain invariants (do not break)

- **SMPL → production hierarchy** is remapped under a ground root bone `Main`.
- **Global motion** (scene translation X,Y,Z) lives on `Main`.
- **Pelvis** stores height only: local X/Y = 0, Z = ground-to-hip distance.
- **Body bones** store **quaternions only** (W, X, Y, Z) — no Euler angles.
- **Sparse keyframing:** keys exist strictly at the user-selected frame indices;
  gaps contain no keys at all.
- **Tangents** are exported **Stepped / Constant** (never auto-interpolated).
- **File format:** binary FBX 2014/2016 (Blender export version `FBX7400`).
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

## Working conventions for agents

- The plan (`docs/Plan_AImation_Actor_EN.md`) wins on behavior/interface
  questions; keep this summary in sync if decisions change.
- Keep `core/` and `ports/` free of third-party imports at all times.
- Add new infrastructure only as an adapter behind a port.
- `tests/` covers `core/` and `ports/` logic — adapters are tested via fakes.
