"""Tests for the model provisioner (license gate → verified download → install).

Uses an injected in-memory opener (dict url→bytes), so no network is ever
touched. Covers: verified install, hash-mismatch rejection with no residue,
TOFU rejection without an explicit opt-in (and without calling the opener),
TOFU hash recording into a rewritten manifest, license gating before any
download, missing-URL rejection, and zip+extract (archive_inner) mode.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from aimation_actor_core.infrastructure.models.provisioner import (
    ModelProvisioner,
    ModelProvisionError,
)
from aimation_actor_core.infrastructure.models.registry import ModelRegistry

PAYLOAD = b"fake onnx bytes for tests"
URL = "https://example.invalid/rtmpose.onnx"
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


class _RecordingOpener:
    """In-memory opener serving canned payloads and recording every call."""

    def __init__(self, payloads: dict[str, bytes]) -> None:
        self._payloads = payloads
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        try:
            return self._payloads[url]
        except KeyError as exc:
            raise OSError(f"no payload recorded for {url}") from exc


def _write_manifest(root: Path, models: list[dict[str, object]]) -> None:
    """Write a schema_version-1 manifest with the given model entries."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "models": models}, indent=2),
        encoding="utf-8",
    )


def _rtmpose_entry(**overrides: object) -> dict[str, object]:
    """A minimal RTMPose-like catalog entry with url + sha256 by default."""
    entry: dict[str, object] = {
        "name": "rtmpose-light",
        "kind": "pose-2d",
        "version": "s_20230709",
        "file": "rtmpose.onnx",
        "url": URL,
        "sha256": DIGEST,
        "license": "Apache-2.0",
        "description": "test entry",
    }
    entry.update(overrides)
    return entry


def _provisioner(root: Path, opener: _RecordingOpener) -> ModelProvisioner:
    return ModelProvisioner(ModelRegistry(root), opener=opener)


def test_install_with_hash_writes_and_verifies(tmp_path: Path) -> None:
    """Verified install: file lands at the expected path, content intact."""
    _write_manifest(tmp_path, [_rtmpose_entry()])
    opener = _RecordingOpener({URL: PAYLOAD})
    registry = ModelRegistry(tmp_path)
    provisioner = ModelProvisioner(registry, opener=opener)

    target = provisioner.install(
        registry.get("rtmpose-light"),
        accept_license="Apache-2.0",
    )

    assert target == tmp_path / "rtmpose.onnx"
    assert target.read_bytes() == PAYLOAD
    assert registry.status(registry.get("rtmpose-light")) == "installed"
    assert not (tmp_path / "rtmpose.onnx.part").exists()
    assert opener.calls == [URL]


def test_install_hash_mismatch_rejects_and_leaves_no_residue(tmp_path: Path) -> None:
    """Wrong expected hash → error, no .part residue, no installed file."""
    _write_manifest(tmp_path, [_rtmpose_entry(sha256="f" * 64)])
    opener = _RecordingOpener({URL: PAYLOAD})
    registry = ModelRegistry(tmp_path)
    provisioner = ModelProvisioner(registry, opener=opener)

    with pytest.raises(ModelProvisionError, match="hash mismatch"):
        provisioner.install(registry.get("rtmpose-light"), accept_license="Apache-2.0")

    assert not (tmp_path / "rtmpose.onnx.part").exists()
    assert not (tmp_path / "rtmpose.onnx").exists()


def test_install_unverified_rejected_before_opener_without_tofu(tmp_path: Path) -> None:
    """No sha256 + no TOFU → rejection before the opener is ever called."""
    _write_manifest(tmp_path, [_rtmpose_entry(sha256="")])
    opener = _RecordingOpener({URL: PAYLOAD})
    registry = ModelRegistry(tmp_path)
    provisioner = ModelProvisioner(registry, opener=opener)

    with pytest.raises(ModelProvisionError, match="trust-on-first-use"):
        provisioner.install(registry.get("rtmpose-light"), accept_license="Apache-2.0")

    assert opener.calls == []
    assert not (tmp_path / "rtmpose.onnx.part").exists()


def test_install_tofu_records_hash_in_rewritten_manifest(tmp_path: Path) -> None:
    """TOFU install: file lands and the observed hash is persisted per entry."""
    _write_manifest(
        tmp_path,
        [_rtmpose_entry(sha256=""), _rtmpose_entry(name="motionbert", kind="pose-3d", sha256="")],
    )
    opener = _RecordingOpener({URL: PAYLOAD})
    registry = ModelRegistry(tmp_path)
    provisioner = ModelProvisioner(registry, opener=opener)

    spec = registry.get("rtmpose-light")
    target = provisioner.install(
        spec,
        accept_license="Apache-2.0",
        trust_on_first_use=True,
    )

    assert target.read_bytes() == PAYLOAD
    stored = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert stored["schema_version"] == 1
    by_name = {entry["name"]: entry for entry in stored["models"]}
    assert by_name["rtmpose-light"]["sha256"] == DIGEST
    # The untouched entry keeps its (empty) sha256 — catalog preserved.
    assert by_name["motionbert"]["sha256"] == ""
    assert registry.status(registry.get("rtmpose-light")) == "installed"


def test_install_wrong_license_rejected_without_network(tmp_path: Path) -> None:
    """License gate: wrong acceptance → error with the expected license, no I/O."""
    _write_manifest(tmp_path, [_rtmpose_entry()])
    opener = _RecordingOpener({URL: PAYLOAD})
    registry = ModelRegistry(tmp_path)
    provisioner = ModelProvisioner(registry, opener=opener)

    with pytest.raises(ModelProvisionError, match="license not accepted: expected Apache-2.0"):
        provisioner.install(registry.get("rtmpose-light"), accept_license="MIT")

    assert opener.calls == []
    assert not (tmp_path / "rtmpose.onnx").exists()


def test_install_missing_url_rejected(tmp_path: Path) -> None:
    """An entry without a recorded URL is rejected with a clear message."""
    _write_manifest(tmp_path, [_rtmpose_entry(url="")])
    opener = _RecordingOpener({})
    registry = ModelRegistry(tmp_path)
    provisioner = ModelProvisioner(registry, opener=opener)

    with pytest.raises(ModelProvisionError, match="no download URL recorded for rtmpose-light"):
        provisioner.install(registry.get("rtmpose-light"), accept_license="Apache-2.0")

    assert opener.calls == []


def test_verify_installed_delegates_to_registry_status(tmp_path: Path) -> None:
    """verify_installed is False for missing/corrupt, True otherwise."""
    _write_manifest(tmp_path, [_rtmpose_entry()])
    registry = ModelRegistry(tmp_path)
    provisioner = ModelProvisioner(registry, opener=_RecordingOpener({}))
    spec = registry.get("rtmpose-light")

    assert provisioner.verify_installed(spec) is False  # missing

    (tmp_path / "rtmpose.onnx").write_bytes(PAYLOAD)
    assert provisioner.verify_installed(spec) is True  # installed


# ---------------------------------------------------------------------------
# archive_inner (zip+extract) tests
# ---------------------------------------------------------------------------

MEMBER_PATH = "rtmpose-ort/rtmdet-nano/end2end.onnx"
MEMBER_CONTENT = b"extracted onnx payload for archive_inner test"
MEMBER_DIGEST = hashlib.sha256(MEMBER_CONTENT).hexdigest()
ZIP_URL = "https://example.invalid/rtmpose-cpu.zip"


def _build_zip(*members: tuple[str, bytes]) -> bytes:
    """Build an in-memory zip archive containing the given members."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in members:
            zf.writestr(name, content)
    return buf.getvalue()


def _zip_entry(**overrides: object) -> dict[str, object]:
    """An RTMDet-nano-like catalog entry with archive_inner set."""
    entry: dict[str, object] = {
        "name": "rtmdet-nano",
        "kind": "person-detector",
        "version": "coco-person_20230504",
        "file": "rtmdet-nano.onnx",
        "url": ZIP_URL,
        "sha256": MEMBER_DIGEST,
        "license": "Apache-2.0",
        "description": "test zip+extract entry",
        "archive_inner": MEMBER_PATH,
    }
    entry.update(overrides)
    return entry


def test_install_archive_inner_extracts_and_verifies(tmp_path: Path) -> None:
    """zip+extract: the extracted member lands at target with correct hash."""
    zip_bytes = _build_zip((MEMBER_PATH, MEMBER_CONTENT))
    _write_manifest(tmp_path, [_zip_entry()])
    opener = _RecordingOpener({ZIP_URL: zip_bytes})
    registry = ModelRegistry(tmp_path)
    provisioner = ModelProvisioner(registry, opener=opener)

    target = provisioner.install(
        registry.get("rtmdet-nano"),
        accept_license="Apache-2.0",
    )

    assert target == tmp_path / "rtmdet-nano.onnx"
    assert target.read_bytes() == MEMBER_CONTENT
    assert registry.status(registry.get("rtmdet-nano")) == "installed"
    # Both temp files cleaned up.
    assert not (tmp_path / "rtmdet-nano.onnx.part").exists()
    assert not (tmp_path / "rtmdet-nano.onnx.part-extracted").exists()
    assert opener.calls == [ZIP_URL]


def test_install_archive_inner_hash_mismatch_cleans_both_temps(tmp_path: Path) -> None:
    """zip+extract hash mismatch → error, both .part and .part-extracted removed."""
    zip_bytes = _build_zip((MEMBER_PATH, MEMBER_CONTENT))
    _write_manifest(tmp_path, [_zip_entry(sha256="f" * 64)])
    opener = _RecordingOpener({ZIP_URL: zip_bytes})
    registry = ModelRegistry(tmp_path)
    provisioner = ModelProvisioner(registry, opener=opener)

    with pytest.raises(ModelProvisionError, match="hash mismatch"):
        provisioner.install(registry.get("rtmdet-nano"), accept_license="Apache-2.0")

    assert not (tmp_path / "rtmdet-nano.onnx.part").exists()
    assert not (tmp_path / "rtmdet-nano.onnx.part-extracted").exists()
    assert not (tmp_path / "rtmdet-nano.onnx").exists()


def test_install_archive_inner_malicious_traversal_rejected(tmp_path: Path) -> None:
    """Member with ../traversal → ModelProvisionError, nothing written outside root."""
    malicious_member = "../evil"
    zip_bytes = _build_zip((malicious_member, b"evil payload"))
    _write_manifest(tmp_path, [_zip_entry(archive_inner=malicious_member, sha256="")])
    opener = _RecordingOpener({ZIP_URL: zip_bytes})
    registry = ModelRegistry(tmp_path)
    provisioner = ModelProvisioner(registry, opener=opener)

    with pytest.raises(ModelProvisionError, match="traversal"):
        provisioner.install(
            registry.get("rtmdet-nano"),
            accept_license="Apache-2.0",
            trust_on_first_use=True,
        )

    # No file should escape the root.
    assert not (tmp_path.parent / "evil").exists()
    assert not (tmp_path / "rtmdet-nano.onnx").exists()


def test_install_archive_inner_malicious_absolute_rejected(tmp_path: Path) -> None:
    """Member with absolute path → ModelProvisionError, no files written."""
    absolute_member = "/etc/evil"
    zip_bytes = _build_zip((absolute_member, b"evil payload"))
    _write_manifest(tmp_path, [_zip_entry(archive_inner=absolute_member, sha256="")])
    opener = _RecordingOpener({ZIP_URL: zip_bytes})
    registry = ModelRegistry(tmp_path)
    provisioner = ModelProvisioner(registry, opener=opener)

    with pytest.raises(ModelProvisionError, match="absolute"):
        provisioner.install(
            registry.get("rtmdet-nano"),
            accept_license="Apache-2.0",
            trust_on_first_use=True,
        )


def test_install_archive_inner_missing_member_raises_and_cleans(tmp_path: Path) -> None:
    """Member doesn't exist in zip → ModelProvisionError, both temps cleaned."""
    zip_bytes = _build_zip(("other/file.onnx", b"data"))
    _write_manifest(tmp_path, [_zip_entry()])
    opener = _RecordingOpener({ZIP_URL: zip_bytes})
    registry = ModelRegistry(tmp_path)
    provisioner = ModelProvisioner(registry, opener=opener)

    with pytest.raises(ModelProvisionError, match="not found in archive"):
        provisioner.install(registry.get("rtmdet-nano"), accept_license="Apache-2.0")

    assert not (tmp_path / "rtmdet-nano.onnx.part").exists()
    assert not (tmp_path / "rtmdet-nano.onnx.part-extracted").exists()
    assert not (tmp_path / "rtmdet-nano.onnx").exists()


def test_install_without_archive_inner_unchanged(tmp_path: Path) -> None:
    """A spec without archive_inner still follows the direct-byte path."""
    _write_manifest(tmp_path, [_rtmpose_entry()])
    opener = _RecordingOpener({URL: PAYLOAD})
    registry = ModelRegistry(tmp_path)
    provisioner = ModelProvisioner(registry, opener=opener)

    target = provisioner.install(
        registry.get("rtmpose-light"),
        accept_license="Apache-2.0",
    )

    assert target.read_bytes() == PAYLOAD
    assert not (tmp_path / "rtmpose.onnx.part").exists()
    assert not (tmp_path / "rtmpose.onnx.part-extracted").exists()