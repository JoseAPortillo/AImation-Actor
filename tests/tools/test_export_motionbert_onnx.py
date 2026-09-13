"""Tests for the build-time MotionBERT ONNX exporter (pure parts only).

The exporter requires PyTorch, which is NOT a runtime dependency of this
project. These tests cover only the pure, torch-free surface (provenance
hashes, weight-prefix normalization, manifest recording, architecture pins);
the torch export path is exercised manually in a dedicated build venv (see
tools/export_motionbert_onnx.py).
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from tools.export_motionbert_onnx import (
    MODEL_KWARGS,
    ONNX_OPSET,
    SOURCE_FILES,
    record_manifest,
    sha256_bytes,
    sha256_file,
    strip_module_prefix,
)


def test_sha256_bytes_matches_hashlib() -> None:
    """Digest helper rounds with the standard library."""
    payload = b"motionbert fixture"
    assert sha256_bytes(payload) == sha256(payload).hexdigest()


def test_sha256_file_reads_bytes(tmp_path: Path) -> None:
    """File digest helper reads bytes from disk."""
    path = tmp_path / "blob.bin"
    path.write_bytes(b"hello motionbert")

    assert sha256_file(path) == sha256(b"hello motionbert").hexdigest()


def test_model_kwargs_match_published_architecture() -> None:
    """Architecture hyper-parameters mirror MB_ft_h36m_global_lite.yaml."""
    assert MODEL_KWARGS == {
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


def test_onnx_opset_is_18() -> None:
    """Exporter pins opset 18 for native LayerNormalization support."""
    assert ONNX_OPSET == 18


def test_source_files_are_pinned_and_small() -> None:
    """Upstream sources are pinned by path with non-empty SHA-256 digests."""
    assert set(SOURCE_FILES) == {
        "lib/model/DSTformer.py",
        "lib/model/drop.py",
        "LICENSE",
    }
    for digest in SOURCE_FILES.values():
        assert len(digest) == 64


def test_strip_module_prefix_removes_dataparallel_prefix() -> None:
    """GPU checkpoints (module.* keys) normalize to the plain module keys."""
    state = {"module.head.weight": 1, "module.blocks_st.0": 2}

    normalized = strip_module_prefix(state)

    assert set(normalized) == {"head.weight", "blocks_st.0"}
    assert normalized["head.weight"] == 1


def test_strip_module_prefix_keeps_plain_keys_unchanged() -> None:
    """CPU checkpoints without the prefix return the same mapping object."""
    state = {"head.weight": 1}

    assert strip_module_prefix(state) is state


def test_record_manifest_updates_only_motionbert(tmp_path: Path) -> None:
    """Manifest recording sets the motionbert sha and preserves other entries."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "models": [
                    {"name": "rtmpose-light", "sha256": "old", "description": "keep"},
                    {"name": "motionbert", "sha256": "", "description": "export pending"},
                ],
            }
        ),
        encoding="utf-8",
    )

    record_manifest(manifest, "a" * 64)

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    by_name = {entry["name"]: entry for entry in payload["models"]}
    assert by_name["motionbert"]["sha256"] == "a" * 64
    assert by_name["motionbert"]["description"].startswith("MotionBERT-Lite")
    assert by_name["rtmpose-light"]["sha256"] == "old"
    assert by_name["rtmpose-light"]["description"] == "keep"


def test_record_manifest_missing_entry_raises(tmp_path: Path) -> None:
    """Recording without a motionbert entry fails loudly."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": 1, "models": []}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="motionbert entry not found"):
        record_manifest(manifest, "a" * 64)