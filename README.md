# AImation Actor

Standalone desktop tool for professional 3D animators. It extracts **Golden
Poses** (key poses) from a reference video frame by frame, imports/exports
`.fbx` with **sparse (stepped) keyframes**, and fills the empty gaps with a 3D
motion diffusion model (**CondMDI**).

> Status: early scaffolding. The architecture and pipeline are specified in
> [`docs/Plan_AImation_Actor_EN.md`](docs/Plan_AImation_Actor_EN.md); the
> agent-facing summary is in [`docs/AGENTS.md`](docs/AGENTS.md).

## Requirements

- **Windows** (primary target), Python **3.14+**
- **Blender 5.2 LTS** installed — used as an external subprocess for FBX I/O
  (default path: `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`)
- **NVIDIA GPU** with ~10 GB VRAM (CUDA) for the AI stages

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt --index-url https://download.pytorch.org/whl/cu130
```

PyTorch must be installed from the CUDA index (`cu130`); the default PyPI wheel
on Windows is CPU-only. Use `cu126` if your NVIDIA driver is older.

## Usage

```powershell
.\.venv\Scripts\python.exe -m aimation_actor.main
```

(GUI not implemented yet — see the plan for the MVP pipeline.)

## Development

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest
```

## Project layout

Hexagonal (ports & adapters) monolith. The animation core is kept free of any
external dependency.

```text
aimation_actor/
├── main.py        # entry point
├── core/          # domain logic (0 external deps)
├── ports/         # abstract contracts
└── adapters/      # PySide6 GUI, FBX-via-Blender, PyTorch AI
tests/
assets/
docs/
```
