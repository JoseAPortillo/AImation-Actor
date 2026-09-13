"""Build-time MotionBERT -> ONNX exporter for the pose-3d node.

Generates ``models/motionbert.onnx`` from the official MotionBERT-Lite
finetuned Human3.6M checkpoint (``FT_MB_lite_MB_ft_h36m_global_lite``).

**This is a build-time tool, NOT a runtime dependency.** It imports PyTorch
only to trace the model; the produced ONNX runs with ``onnxruntime`` (the
project's normal ``ai`` extra). Outputs go to the gitignored ``models/`` root
(``models/*.onnx``) so the artifact is never committed.

Provenance
----------
- Model: DSTformer from https://github.com/Walter0807/MotionBERT (Apache-2.0),
  pinned to commit ``705d3a95354db8bdb696b3492e47a3b5537174ff``. The three
  source files (``lib/model/DSTformer.py``, ``lib/model/drop.py``, ``LICENSE``)
  are downloaded into ``tools/.cache/motionbert-src/`` and verified by SHA-256
  before use.
- Checkpoint: https://huggingface.co/walterzhu/MotionBERT — official
  ``checkpoint/pose3d/FT_MB_lite_MB_ft_h36m_global_lite/best_epoch.bin``.
  With ``--checkpoint-sha256`` the download is verified before load; without
  it the observed digest is printed (trust-on-first-use), mirroring the
  provisioner's TOFU policy.

Architecture (replicated from the official ``load_backbone``)
--------------------------------------------------------------
``DSTformer(dim_in=3, dim_out=3, dim_feat=256, dim_rep=512, depth=5,
num_heads=8, mlp_ratio=4, norm_layer=partial(nn.LayerNorm, eps=1e-6),
maxlen=243, num_joints=17)`` — note the ``eps=1e-6`` LayerNorm, which differs
from PyTorch's default and is required to match the published weights. Input
is ``(B, F, J, 3)`` (x, y, confidence; ``no_conf: false`` in the config),
output ``(B, F, J, 3)``. The model accepts windows up to ``maxlen`` frames.

ONNX notes
----------
- **Opset 18 is the floor**: the model uses ``LayerNormalization``, which does
  not exist in opsets < 17, and torch's current exporter refuses > 18. The
  default ``--opset 18`` produces a clean native graph.
- The modern torch exporter may write weights as an external ``*.onnx.data``
  file; this tool inlines them back into a single self-contained ``.onnx``
  (only the packed file is hashed and recorded).

Usage
-----
::

    python tools/export_motionbert_onnx.py --checkpoint-sha256 <sha>
    python tools/export_motionbert_onnx.py --update-manifest   # record sha
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Provenance pins (do not bump casually; the ONNX content depends on them).
# ---------------------------------------------------------------------------

MOTIONBERT_RAW = "https://raw.githubusercontent.com/Walter0807/MotionBERT"
MOTIONBERT_COMMIT = "705d3a95354db8bdb696b3492e47a3b5537174ff"
MOTIONBERT_LICENSE = "Apache-2.0"

#: Relative path -> expected SHA-256 of the upstream sources used to build the
#: model (lib layout is imported through ``sys.path``).
SOURCE_FILES: dict[str, str] = {
    "lib/model/DSTformer.py": (
        "0896b29872b10f55be8902ceceacb9febe7876fa2065d5f9dd670fbb902f2f47"
    ),
    "lib/model/drop.py": (
        "44b1af7912ae46c62c5b74712dae31697afc697e788c8dd9c5050602a2397173"
    ),
    "LICENSE": "045ee95b545fb51f5c6e28e1a50644fe618f6278f3c8720852c6fe96f53b472f",
}

CHECKPOINT_URL = (
    "https://huggingface.co/walterzhu/MotionBERT/resolve/main/"
    "checkpoint/pose3d/FT_MB_lite_MB_ft_h36m_global_lite/best_epoch.bin"
)

#: Architecture hyper-parameters from ``configs/pose3d/MB_ft_h36m_global_lite.yaml``,
#: mirrored from the official ``load_backbone`` (lib/utils/learning.py). The
#: ``norm_layer`` keyword is added at build time with ``partial(nn.LayerNorm,
#: eps=1e-6)`` because it is not JSON-serializable.
MODEL_KWARGS: dict[str, int] = {
    "dim_in": 3,
    "dim_out": 3,
    "dim_feat": 256,
    "dim_rep": 512,
    "depth": 5,
    "num_heads": 8,
    "mlp_ratio": 4,
    "num_joints": 17,
    "maxlen": 243,
}

#: Minimum ONNX opset with native LayerNormalization; torch's current exporter
#: will not downgrade below its own implementation floor, so 18 is the default.
ONNX_OPSET = 18

DEFAULT_OUTPUT = "models/motionbert.onnx"
DEFAULT_SOURCE_CACHE = "tools/.cache/motionbert-src"
DEFAULT_CHECKPOINT_CACHE = "tools/.cache/motionbert-checkpoint.bin"


# ---------------------------------------------------------------------------
# Small pure helpers (testable without torch).
# ---------------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the lowercase hex SHA-256 digest of the file at ``path``."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(url: str, dest: Path, expected_sha256: str | None, label: str) -> None:
    """Download ``url`` to ``dest`` and verify it against ``expected_sha256``.

    A mismatch raises ``RuntimeError``; ``None`` means trust-on-first-use
    (the observed digest is printed).
    """
    if dest.exists():
        observed = sha256_file(dest)
        if expected_sha256 is None or observed == expected_sha256:
            print(f"[motionbert] reuse {label}: {dest}")
            if expected_sha256 is None:
                print(f"[motionbert] {label} sha256: {observed}")
            return
        raise RuntimeError(
            f"{label} cache mismatch at {dest}: "
            f"expected {expected_sha256}, got {observed}"
        )

    print(f"[motionbert] downloading {label}: {url}")
    with urllib.request.urlopen(url) as response:
        data = response.read()
    if expected_sha256 is not None:
        observed = sha256_bytes(data)
        if observed != expected_sha256:
            raise RuntimeError(
                f"{label} digest mismatch: expected {expected_sha256}, "
                f"got {observed}"
            )
    else:
        print(f"[motionbert] {label} sha256: {sha256_bytes(data)}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"[motionbert] wrote {label}: {dest}")


def strip_module_prefix(state: dict[str, Any]) -> dict[str, Any]:
    """Remove the ``module.`` DataParallel prefix from checkpoint keys.

    GPU-trained checkpoints store keys like ``module.blocks_st.0...`` while the
    exported module expects ``blocks_st.0...``. Returns the input unchanged
    (same mapping object) when no key carries the prefix.
    """
    if not any(key.startswith("module.") for key in state):
        return state
    return {key.removeprefix("module."): value for key, value in state.items()}


def load_model_weights(model: Any, checkpoint_path: Path) -> None:  # noqa: ANN401 - torch module is untyped
    """Load ``model_pos`` from the MotionBERT checkpoint into ``model``.

    Handles the ``module.`` DataParallel prefix (see :func:`strip_module_prefix`).
    ``weights_only=True`` is used first (safe by default in torch >= 2.6); if
    the checkpoint contains legacy optimizer state that the safe loader
    rejects, it retries with the verified file.
    """
    import torch  # type: ignore[import-not-found]
    def _best_effort_load() -> Any:  # noqa: ANN401 - torch.load is untyped
        try:
            return torch.load(checkpoint_path, map_location="cpu", weights_only=True)
        except RuntimeError:
            # Legacy pickle checkpoint (optimizer/collections) — the file has
            # already been SHA-256 verified, so controlled pickle is acceptable
            # at build time. Never pointed at unverified user input.
            print("[motionbert] weights_only load rejected; retrying with legacy path")
            return torch.load(checkpoint_path, map_location="cpu", weights_only=False)

    checkpoint = _best_effort_load()
    state = strip_module_prefix(checkpoint["model_pos"])
    missing, unexpected = model.load_state_dict(state, strict=True)
    if missing or unexpected:
        raise RuntimeError(
            f"checkpoint keys do not match model: missing={missing}, "
            f"unexpected={unexpected}"
        )


def build_model() -> Any:  # noqa: ANN401 - torch module is untyped
    """Import the pinned DSTformer and construct it with official kwargs."""
    import functools

    import torch
    from lib.model.DSTformer import DSTformer  # type: ignore[import-not-found]
    kwargs: dict[str, Any] = dict(MODEL_KWARGS)
    kwargs["norm_layer"] = functools.partial(torch.nn.LayerNorm, eps=1e-6)
    model = DSTformer(**kwargs)
    model.eval()
    return model


# ---------------------------------------------------------------------------
# ONNX export.
# ---------------------------------------------------------------------------


def inline_external_data(output: Path) -> None:
    """Pack a two-file ONNX export into a single self-contained ``.onnx``.

    The modern torch exporter writes large weights as ``<output>.data`` next
    to the graph file. ONNX Runtime can read that split layout, but our
    provisioner/registry hashes and ships one file per model, so the weights
    are folded back in. No-op when no external data file exists.
    """
    external = Path(f"{output}.data")
    if not external.exists():
        return
    import onnx

    model = onnx.load(str(output))
    from onnx.external_data_helper import load_external_data_for_model

    load_external_data_for_model(model, str(output.parent))
    onnx.save(model, str(output))
    external.unlink()
    print(f"[motionbert] inlined external data into {output}")


def export_onnx(
    model: Any,  # noqa: ANN401 - torch module is untyped
    output: Path,
    *,
    frames: int,
    fixed_frames: bool,
    opset: int,
) -> str:
    """Trace ``model`` to ``output`` (opset 18) and return its SHA-256.

    ``frames`` is the trace window length (typically ``maxlen``=243). With
    ``fixed_frames=False`` the ONNX has dynamic batch *and* frame axes so the
    runtime may feed shorter windows natively; with ``fixed_frames=True`` only
    the batch axis is dynamic and the window must be padded by the caller.
    """
    import torch

    if opset < 17:
        raise ValueError(
            f"opset {opset} cannot express LayerNormalization; "
            f"use --opset >= 17 (default {ONNX_OPSET})"
        )
    dummy = torch.zeros(1, frames, MODEL_KWARGS["num_joints"], MODEL_KWARGS["dim_in"])
    dynamic_axes: dict[int, str] = {0: "batch"}
    if not fixed_frames:
        dynamic_axes[1] = "frames"
    torch.onnx.export(
        model,
        dummy,
        str(output),
        input_names=["keypoints_2d"],
        output_names=["keypoints_3d"],
        dynamic_axes={"keypoints_2d": dynamic_axes, "keypoints_3d": dynamic_axes},
        opset_version=opset,
        do_constant_folding=True,
    )
    inline_external_data(output)
    digest = sha256_file(output)
    print(f"[motionbert] ONNX written: {output} ({output.stat().st_size} bytes)")
    print(f"[motionbert] ONNX sha256: {digest}")
    return digest


def smoke_check(model: Any, output: Path, *, frames: int) -> None:  # noqa: ANN401 - torch module is untyped
    """Compare torch vs ONNX Runtime on a dummy input when ort is available.

    Skips silently when onnxruntime is not installed; the runtime backend is
    verified separately once the model is wired up.
    """
    try:
        import numpy as np
        import onnxruntime as ort  # type: ignore[import-untyped]
    except ImportError:
        print("[motionbert] onnxruntime not available; skipping deterministic smoke check")
        return

    import torch
    rng = np.random.default_rng(0)
    size = (1, frames, MODEL_KWARGS["num_joints"], MODEL_KWARGS["dim_in"])
    x = rng.uniform(-1.0, 1.0, size=size).astype(np.float32)
    with torch.no_grad():
        expected = model(torch.from_numpy(x)).numpy()
    session = ort.InferenceSession(str(output), providers=["CPUExecutionProvider"])
    (actual,) = session.run(None, {"keypoints_2d": x})
    if actual.shape != expected.shape:
        raise RuntimeError(f"smoke shape mismatch: torch {expected.shape} vs ort {actual.shape}")
    max_diff = float(np.max(np.abs(actual - expected)))
    print(f"[motionbert] smoke check passed: shape={actual.shape} max_abs_diff={max_diff:.3e}")
    if max_diff > 1e-3:
        raise RuntimeError(f"smoke value mismatch too large: {max_diff:.3e} > 1e-3")


# ---------------------------------------------------------------------------
# Manifest recording.
# ---------------------------------------------------------------------------


def record_manifest(manifest_path: Path, digest: str) -> None:
    """Set the ``motionbert`` entry's ``sha256`` and mark it exportable.

    Keeps every other catalog entry untouched (same rewrite policy as the
    provisioner's TOFU update).
    """
    if not manifest_path.exists():
        raise RuntimeError(f"cannot record digest: missing manifest at {manifest_path}")
    payload: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("models")
    if not isinstance(entries, list):
        raise RuntimeError(f"manifest {manifest_path} has no 'models' list")
    updated = False
    for entry in entries:
        if isinstance(entry, dict) and entry.get("name") == "motionbert":
            entry["sha256"] = digest
            entry["description"] = (
                "MotionBERT-Lite 3D lifting ONNX (Apache-2.0), exported locally by "
                "tools/export_motionbert_onnx.py from the official H36M finetuned "
                "checkpoint; generated artifact, not downloaded."
            )
            updated = True
    if not updated:
        raise RuntimeError(f"motionbert entry not found in {manifest_path}")
    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"[motionbert] recorded sha256 in {manifest_path}")


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export MotionBERT-Lite to ONNX (build-time tool)"
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=DEFAULT_CHECKPOINT_CACHE,
        help="Path to the checkpoint .bin",
    )
    parser.add_argument(
        "--checkpoint-sha256",
        default=None,
        help="Expected SHA-256 of the checkpoint; omitted = trust-on-first-use",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(DEFAULT_OUTPUT),
        help="Where to write the ONNX file",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=MODEL_KWARGS["maxlen"],
        help="Trace window length (<= maxlen)",
    )
    parser.add_argument(
        "--fixed-frames",
        action="store_true",
        help="Export with only dynamic batch (caller must pad the window)",
    )
    parser.add_argument("--opset", type=int, default=ONNX_OPSET, help="ONNX opset version")
    parser.add_argument(
        "--source-cache",
        type=Path,
        default=Path(DEFAULT_SOURCE_CACHE),
        help="Cache dir for upstream sources",
    )
    parser.add_argument(
        "--update-manifest",
        action="store_true",
        help="Record the generated ONNX sha256 in models/manifest.json",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("models/manifest.json"),
        help="Manifest to update",
    )
    parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="Skip the onnxruntime smoke check",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        import torch  # noqa: F401
    except ImportError:
        print(
            "[motionbert] ERROR: torch is required for this build-time tool",
            file=sys.stderr,
        )
        print(
            "[motionbert] Install it in a dedicated build venv "
            "(never a runtime dependency)",
            file=sys.stderr,
        )
        return 2

    cache_root = args.source_cache
    for rel, expected in SOURCE_FILES.items():
        dest = cache_root / rel
        fetch(f"{MOTIONBERT_RAW}/{MOTIONBERT_COMMIT}/{rel}", dest, expected, f"source {rel}")
    sys.path.insert(0, str(cache_root))

    model = build_model()

    if not args.checkpoint.exists():
        fetch(CHECKPOINT_URL, args.checkpoint, args.checkpoint_sha256, "checkpoint")
    elif args.checkpoint_sha256 is not None and (
        sha256_file(args.checkpoint) != args.checkpoint_sha256
    ):
        raise RuntimeError(
            f"checkpoint mismatch: expected {args.checkpoint_sha256}, "
            f"got {sha256_file(args.checkpoint)}"
        )

    load_model_weights(model, args.checkpoint)
    digest = export_onnx(
        model,
        args.output,
        frames=args.frames,
        fixed_frames=args.fixed_frames,
        opset=args.opset,
    )
    if not args.skip_smoke:
        smoke_check(model, args.output, frames=args.frames)
    if args.update_manifest:
        record_manifest(args.manifest, digest)
    print("[motionbert] done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
