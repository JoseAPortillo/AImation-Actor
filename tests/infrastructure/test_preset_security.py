"""Security negatives for the retarget preset loader (REQ §14 "Safe preset ingestion").

The spec-mandated verification suite for the ``retarget-map`` preset ingestion
boundary (SDD §4.2 new row): path traversal (``..``, absolute, symlink
escape), the 262 KiB size cap enforced *before* parsing, malformed/unknown
preset content, and the static no-``eval`` scan proving only
:func:`yaml.safe_load` / :func:`json.load` are reachable from preset input.

These are approval-style negatives: task 3.2 ships the loader with the
design-mandated controls; this suite locks every control in with a failing
assertion when it regresses.
"""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from aimation_actor_core.infrastructure.ai_models.retarget_map import (
    MAX_PRESET_BYTES,
    PresetError,
    RetargetMapNode,
)

VALID_PRESET = """\
mapping:
  LeftArm: arm_l_ctrl
  LeftUpLeg: upLeg_l_ctrl
use_root_translation: true
foot_ik: false
scale_source_height: false
preserve_keyframes: false
"""


def _preset_root(tmp_path: Path) -> Path:
    """Create a preset root with one valid preset and return the root."""
    preset_root = tmp_path / "presets"
    preset_root.mkdir(exist_ok=True)
    (preset_root / "identity.yaml").write_text(VALID_PRESET, encoding="utf-8")
    return preset_root


class TestPathTraversal:
    """SDD §4.3 — reject disallowed preset paths BEFORE any read/parse."""

    def test_relative_traversal_rejected(self, tmp_path: Path) -> None:
        node = RetargetMapNode(preset_root=_preset_root(tmp_path))
        with pytest.raises(PresetError):
            node._resolve_preset_path("../secret.yaml")

    def test_deep_traversal_rejected(self, tmp_path: Path) -> None:
        node = RetargetMapNode(preset_root=_preset_root(tmp_path))
        with pytest.raises(PresetError):
            node._resolve_preset_path("a/../../../etc/passwd.yaml")

    def test_backslash_traversal_rejected(self, tmp_path: Path) -> None:
        node = RetargetMapNode(preset_root=_preset_root(tmp_path))
        with pytest.raises(PresetError):
            node._resolve_preset_path("..\\secret.yaml")

    def test_absolute_path_rejected(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.yaml"
        outside.write_text(VALID_PRESET, encoding="utf-8")
        node = RetargetMapNode(preset_root=_preset_root(tmp_path))
        with pytest.raises(PresetError):
            node._resolve_preset_path(str(outside))

    def test_nonexistent_file_rejected(self, tmp_path: Path) -> None:
        node = RetargetMapNode(preset_root=_preset_root(tmp_path))
        with pytest.raises(PresetError):
            node._resolve_preset_path("no-such-preset.yaml")

    def test_directory_rejected(self, tmp_path: Path) -> None:
        preset_root = _preset_root(tmp_path)
        (preset_root / "subdir").mkdir(exist_ok=True)
        node = RetargetMapNode(preset_root=preset_root)
        with pytest.raises(PresetError):
            node._resolve_preset_path("subdir")

    def test_disallowed_extension_rejected(self, tmp_path: Path) -> None:
        preset_root = _preset_root(tmp_path)
        (preset_root / "preset.txt").write_text(VALID_PRESET, encoding="utf-8")
        node = RetargetMapNode(preset_root=preset_root)
        with pytest.raises(PresetError):
            node._resolve_preset_path("preset.txt")

    def test_symlink_escape_rejected(self, tmp_path: Path) -> None:
        """A symlink inside the root pointing outside must be rejected."""
        outside = tmp_path / "secret.yaml"
        outside.write_text(VALID_PRESET, encoding="utf-8")
        preset_root = _preset_root(tmp_path)
        link = preset_root / "escape.yaml"
        try:
            os.symlink(outside, link)
        except OSError:
            pytest.skip("symlink creation not permitted on this platform")
        node = RetargetMapNode(preset_root=preset_root)
        with pytest.raises(PresetError):
            node._resolve_preset_path("escape.yaml")

    def test_symlink_inside_root_allowed(self, tmp_path: Path) -> None:
        """A symlink whose target stays inside the root remains allowed."""
        preset_root = _preset_root(tmp_path)
        link = preset_root / "alias.yaml"
        try:
            os.symlink(preset_root / "identity.yaml", link)
        except OSError:
            pytest.skip("symlink creation not permitted on this platform")
        node = RetargetMapNode(preset_root=preset_root)
        resolved = node._resolve_preset_path("alias.yaml")
        assert resolved.is_relative_to(preset_root.resolve())
        assert resolved.is_file()

    def test_non_string_preset_rejected(self, tmp_path: Path) -> None:
        node = RetargetMapNode(preset_root=_preset_root(tmp_path))
        for bad in (42, None, ["identity.yaml"]):
            with pytest.raises(PresetError):
                node._resolve_preset_path(bad)  # type: ignore[arg-type]


class TestSizeCap:
    """The size cap MUST fire before any content is parsed."""

    def test_oversized_preset_rejected_before_parse(self, tmp_path: Path) -> None:
        """A >262 KiB file is rejected by the cap, not by a YAML parse error.

        The content is deliberately NOT valid YAML: if the loader tried to
        parse it we would observe a ``yaml.YAMLError``; observing
        :class:`PresetError` proves the stat-based cap fired first.
        """
        preset_root = _preset_root(tmp_path)
        oversized = preset_root / "huge.yaml"
        oversized.write_text(
            "mapping: [" + "x" * (MAX_PRESET_BYTES + 1), encoding="utf-8"
        )
        assert oversized.stat().st_size > MAX_PRESET_BYTES
        node = RetargetMapNode(preset_root=preset_root)
        with pytest.raises(PresetError):
            node._read_preset(oversized.resolve())

    def test_at_cap_file_still_parsed_and_validated(self, tmp_path: Path) -> None:
        """A file of exactly the cap size is not rejected by the size gate."""
        preset_root = _preset_root(tmp_path)
        raw = (VALID_PRESET + "\n").encode("utf-8")
        assert len(raw) < MAX_PRESET_BYTES
        # Pad with a YAML comment to EXACTLY the cap (byte-exact).
        pad = MAX_PRESET_BYTES - len(raw)
        padded_file = preset_root / "padded.yaml"
        padded_file.write_bytes(raw + b"#" + b" " * (pad - 1))
        assert padded_file.stat().st_size == MAX_PRESET_BYTES
        node = RetargetMapNode(preset_root=preset_root)
        data = node._read_preset(padded_file.resolve())
        assert isinstance(data, dict)
        assert "LeftArm" in data["mapping"]


class TestMalformedPreset:
    """Malformed or unknown preset content is rejected before execution."""

    def test_malformed_yaml_rejected(self, tmp_path: Path) -> None:
        preset_root = _preset_root(tmp_path)
        bad = preset_root / "bad.yaml"
        bad.write_text("mapping: [unclosed", encoding="utf-8")
        node = RetargetMapNode(preset_root=preset_root)
        with pytest.raises(yaml.YAMLError):
            node._read_preset(bad.resolve())

    def test_malformed_json_rejected(self, tmp_path: Path) -> None:
        preset_root = _preset_root(tmp_path)
        bad = preset_root / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        node = RetargetMapNode(preset_root=preset_root)
        with pytest.raises(json.JSONDecodeError):
            node._read_preset(bad.resolve())

    def test_empty_preset_rejected(self, tmp_path: Path) -> None:
        preset_root = _preset_root(tmp_path)
        empty = preset_root / "empty.yaml"
        empty.write_text("", encoding="utf-8")
        node = RetargetMapNode(preset_root=preset_root)
        with pytest.raises(PresetError):
            node._read_preset(empty.resolve())

    def test_list_preset_rejected(self, tmp_path: Path) -> None:
        preset_root = _preset_root(tmp_path)
        lst = preset_root / "list.yaml"
        lst.write_text("- mapping\n- 1\n", encoding="utf-8")
        node = RetargetMapNode(preset_root=preset_root)
        with pytest.raises(PresetError):
            node._read_preset(lst.resolve())

    def test_unknown_top_level_field_rejected(self, tmp_path: Path) -> None:
        """extra="forbid": no field is silently ignored."""
        preset_root = _preset_root(tmp_path)
        rogue = preset_root / "rogue.yaml"
        rogue.write_text(
            VALID_PRESET + "bogus_field: 42\n", encoding="utf-8"
        )
        node = RetargetMapNode(preset_root=preset_root)
        data: dict[str, Any] = node._read_preset(rogue.resolve())
        with pytest.raises(ValidationError):
            node._build_retarget_map(data, {})

    def test_unknown_source_bone_rejected(self, tmp_path: Path) -> None:
        """A mapping key absent from the neutral skeleton fails validation."""
        preset_root = _preset_root(tmp_path)
        ghost = preset_root / "ghost.yaml"
        ghost.write_text(
            VALID_PRESET.replace("LeftArm: arm_l_ctrl", "NotABone: arm_l_ctrl"),
            encoding="utf-8",
        )
        node = RetargetMapNode(preset_root=preset_root)
        data: dict[str, Any] = node._read_preset(ghost.resolve())
        with pytest.raises(ValueError):
            node._build_retarget_map(data, {})


class TestNoEval:
    """Static scan: no eval/exec/unsafe-load path reachable from presets."""

    _FORBIDDEN = (
        "eval(",
        "exec(",
        "yaml.load(",
        "yaml.full_load(",
        "yaml.unsafe_load(",
        "pickle.",
        "__import__(",
    )

    def test_loader_source_has_no_eval_exec_or_unsafe_yaml_load(self) -> None:
        source_file = inspect.getsourcefile(RetargetMapNode)
        assert source_file is not None
        source = Path(source_file).read_text(encoding="utf-8")
        for token in self._FORBIDDEN:
            assert token not in source, f"forbidden token {token!r} found in loader"

    def test_loader_uses_safe_load_and_size_cap(self) -> None:
        """Positive control: the safe loader and the cap are actually present."""
        source_file = inspect.getsourcefile(RetargetMapNode)
        assert source_file is not None
        source = Path(source_file).read_text(encoding="utf-8")
        assert "yaml.safe_load" in source
        assert "json.loads" in source
        assert "MAX_PRESET_BYTES" in source