"""HMR2.0 adapter: atomic single-frame 3D pose extraction.

The engine is **HMR2.0** (``shubham-goel/4D-Humans``), not the plan's GVHMR —
see «Pose engine decision» in ``AGENTS.md`` for why, and ``spec.md`` §4.12-4.14
for the decision, the unmeasured properties and the licensing posture.

Landing this adapter is a bounded task of its own, because the engine stack is
not part of this interpreter: HMR2.0 runs in its own **Python 3.10** environment
and this module talks to it across a process boundary, the same shape as the
Blender read path (``adapters/io/fbx/blender_import.py``). Never import the
engine into the application process.

Nothing imports this module yet, and nothing should until it has an
implementation: an importable stub that silently did nothing would be worse than
an honest absence (``FR-CAP-07``).
"""
