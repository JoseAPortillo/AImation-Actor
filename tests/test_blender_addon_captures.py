"""Capture discovery for the Blender transposition add-on.

The add-on package imports ``bpy``, so the pure modules are loaded by path
instead of by package import. That keeps ``pytest`` runnable without Blender —
the same policy the FBX read bridge follows.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_ADDON = Path(__file__).resolve().parents[1] / "blender_addon" / "aimation_transpose"


def _load(name: str) -> ModuleType:
    path = _ADDON / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"aimation_transpose_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


captures = _load("captures")


def test_capture_names_keeps_only_fbx() -> None:
    names = captures.capture_names(["take_01.fbx", "notes.txt", "take_02.FBX", "folder"])

    assert names == ("take_01.fbx", "take_02.FBX")


def test_capture_names_sorts_case_insensitively() -> None:
    names = captures.capture_names(["Take_B.fbx", "take_a.fbx", "TAKE_C.fbx"])

    assert names == ("take_a.fbx", "Take_B.fbx", "TAKE_C.fbx")


def test_capture_names_in_lists_the_folder(tmp_path: Path) -> None:
    (tmp_path / "b_take.fbx").write_bytes(b"")
    (tmp_path / "a_take.fbx").write_bytes(b"")
    (tmp_path / "ignore.me").write_bytes(b"")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "deep.fbx").write_bytes(b"")

    assert captures.capture_names_in(tmp_path) == ("a_take.fbx", "b_take.fbx")


@pytest.mark.parametrize("directory", [None, "", "does-not-exist"])
def test_capture_names_in_is_empty_without_a_readable_folder(directory: str | None) -> None:
    assert captures.capture_names_in(directory) == ()


def test_capture_path_joins_folder_and_name(tmp_path: Path) -> None:
    assert captures.capture_path(tmp_path, "take.fbx") == tmp_path / "take.fbx"


@pytest.mark.parametrize(("directory", "name"), [(None, "take.fbx"), ("", "take.fbx"), ("/c", "")])
def test_capture_path_needs_both_parts(directory: str | None, name: str) -> None:
    assert captures.capture_path(directory, name) is None
