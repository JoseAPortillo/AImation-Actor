"""Tests for the model catalog registry (``models/manifest.json`` reader).

Covers load/get behavior, manifest error paths, and the four on-disk status
classifications (missing / corrupt / installed / installed-unverified), the
latter with real bytes written to the tmp root and a known hash.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aimation_actor_core.infrastructure.models.registry import (
    ModelManifestError,
    ModelNotFoundError,
    ModelRegistry,
    ModelSpec,
)

PAYLOAD = b"fake onnx bytes for tests"


def _write_manifest(root: Path, models: list[dict[str, object]]) -> None:
    """Write a schema_version-1 manifest with the given model entries."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "models": models}, indent=2),
        encoding="utf-8",
    )


def _rtmpose_entry(**overrides: object) -> dict[str, object]:
    """A minimal valid RTMPose-like catalog entry."""
    entry: dict[str, object] = {
        "name": "rtmpose-light",
        "kind": "pose-2d",
        "version": "s_20230709",
        "file": "rtmpose.onnx",
        "url": "https://example.invalid/rtmpose.onnx",
        "sha256": hashlib.sha256(PAYLOAD).hexdigest(),
        "license": "Apache-2.0",
        "description": "test entry",
    }
    entry.update(overrides)
    return entry


def test_load_returns_validated_models(tmp_path: Path) -> None:
    """A schema_version-1 manifest loads into validated ModelSpec objects."""
    _write_manifest(tmp_path, [_rtmpose_entry()])
    specs = ModelRegistry(tmp_path).load()
    assert len(specs) == 1
    spec = specs[0]
    assert isinstance(spec, ModelSpec)
    assert spec.name == "rtmpose-light"
    assert spec.kind == "pose-2d"
    assert spec.file == "rtmpose.onnx"
    assert spec.license == "Apache-2.0"


def test_get_returns_matching_spec(tmp_path: Path) -> None:
    """get() resolves by name; unknown names raise ModelNotFoundError."""
    _write_manifest(tmp_path, [_rtmpose_entry()])
    registry = ModelRegistry(tmp_path)
    assert registry.get("rtmpose-light").name == "rtmpose-light"
    with pytest.raises(ModelNotFoundError, match="rtmpose-other"):
        registry.get("rtmpose-other")


def test_load_missing_manifest_raises(tmp_path: Path) -> None:
    """A missing manifest is a hard error with the path in the message."""
    registry = ModelRegistry(tmp_path)
    with pytest.raises(ModelManifestError, match="missing manifest"):
        registry.load()


def test_load_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    """schema_version != 1 is rejected."""
    _write_manifest(tmp_path, [])
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": 2, "models": []}), encoding="utf-8")
    with pytest.raises(ModelManifestError, match="schema_version"):
        ModelRegistry(tmp_path).load()


def test_load_rejects_invalid_entry_shape(tmp_path: Path) -> None:
    """A malformed model entry (missing required field) is rejected."""
    _write_manifest(tmp_path, [{"name": "broken"}])
    with pytest.raises(ModelManifestError, match="invalid model entry"):
        ModelRegistry(tmp_path).load()


def test_status_missing_when_file_absent(tmp_path: Path) -> None:
    """No file on disk → 'missing'."""
    _write_manifest(tmp_path, [_rtmpose_entry()])
    registry = ModelRegistry(tmp_path)
    assert registry.status(registry.get("rtmpose-light")) == "missing"


def test_status_installed_with_matching_hash(tmp_path: Path) -> None:
    """Real bytes + matching sha256 → 'installed'."""
    _write_manifest(tmp_path, [_rtmpose_entry()])
    registry = ModelRegistry(tmp_path)
    (tmp_path / "rtmpose.onnx").write_bytes(PAYLOAD)
    assert registry.status(registry.get("rtmpose-light")) == "installed"


def test_status_corrupt_on_hash_mismatch(tmp_path: Path) -> None:
    """Real bytes + wrong recorded hash → 'corrupt'."""
    _write_manifest(tmp_path, [_rtmpose_entry(sha256="0" * 64)])
    registry = ModelRegistry(tmp_path)
    (tmp_path / "rtmpose.onnx").write_bytes(PAYLOAD)
    assert registry.status(registry.get("rtmpose-light")) == "corrupt"


def test_status_installed_unverified_without_hash(tmp_path: Path) -> None:
    """File present + empty sha256 → 'installed-unverified' (TOFU state)."""
    _write_manifest(tmp_path, [_rtmpose_entry(sha256="")])
    registry = ModelRegistry(tmp_path)
    (tmp_path / "rtmpose.onnx").write_bytes(PAYLOAD)
    assert registry.status(registry.get("rtmpose-light")) == "installed-unverified"


def test_installed_path_resolves_under_root(tmp_path: Path) -> None:
    """installed_path joins the models root with the entry's file name."""
    _write_manifest(tmp_path, [_rtmpose_entry()])
    registry = ModelRegistry(tmp_path)
    assert registry.installed_path(registry.get("rtmpose-light")) == tmp_path / "rtmpose.onnx"


def test_default_root_is_models() -> None:
    """The registry defaults to a relative 'models' root."""
    assert ModelRegistry().root == Path("models")
    assert ModelRegistry().manifest_path == Path("models") / "manifest.json"