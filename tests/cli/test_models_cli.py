"""Tests for the ``aimation-models`` local CLI (``main`` entry point).

Runs ``main([...])`` against a tmp models root: list succeeds, install without
an accepted license exits 1 with a stderr message (and never touches the
network), and verify on a missing file exits 1.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aimation_actor_core.models_cli import main


def _write_manifest(root: Path) -> None:
    """Write a catalog with one unverified model entry (no sha256, no url)."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "models": [
                    {
                        "name": "rtmpose-light",
                        "kind": "pose-2d",
                        "version": "s_20230709",
                        "file": "rtmpose.onnx",
                        "url": "",
                        "sha256": "",
                        "license": "Apache-2.0",
                        "description": "test entry",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_list_prints_catalog_table(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``list`` exits 0 and prints the model name with its status."""
    _write_manifest(tmp_path)
    exit_code = main(["--root", str(tmp_path), "list"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "rtmpose-light" in captured.out
    assert "missing" in captured.out


def test_install_without_license_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``install`` without --accept-license exits 1 with a clear stderr message."""
    _write_manifest(tmp_path)
    exit_code = main(["--root", str(tmp_path), "install", "rtmpose-light"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "license not accepted" in captured.err


def test_install_wrong_license_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``install`` with the wrong SPDX identifier also exits 1."""
    _write_manifest(tmp_path)
    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "install",
            "rtmpose-light",
            "--accept-license",
            "MIT",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "license not accepted: expected Apache-2.0" in captured.err


def test_verify_missing_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``verify`` on a model with no file on disk exits 1 and prints 'missing'."""
    _write_manifest(tmp_path)
    exit_code = main(["--root", str(tmp_path), "verify", "rtmpose-light"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "missing" in captured.out


def test_unknown_model_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown model name is reported cleanly on stderr."""
    _write_manifest(tmp_path)
    exit_code = main(["--root", str(tmp_path), "verify", "does-not-exist"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "not found in manifest" in captured.err