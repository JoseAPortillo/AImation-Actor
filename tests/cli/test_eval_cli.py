"""Tests for the ``aimation-eval`` quality-metrics CLI.

``report`` over a small version-0.3 motion JSON exits 0 and prints the metric
table (and writes a JSON report with --out); an unreadable input file exits 1
with a clear stderr message.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aimation_actor_core.eval_cli import main


def _write_motion(path: Path) -> None:
    """Write a minimal valid version-0.3 motion (Root drifts 1 unit on x)."""
    path.write_text(
        json.dumps(
            {
                "meta": {"version": "0.3", "fps": 24.0, "duration_frames": 2},
                "skeleton": {
                    "bones": {
                        "Root": {
                            "name": "Root",
                            "parent": None,
                            "rest_position": [0.0, 0.0, 0.0],
                            "rest_rotation": [1.0, 0.0, 0.0, 0.0],
                        }
                    }
                },
                "frames": [
                    {
                        "frame": 1,
                        "time": 0.0,
                        "pose": {"transforms": {"Root": {"translation": [0.0, 0.0, 0.0]}}},
                    },
                    {
                        "frame": 2,
                        "time": 1 / 24,
                        "pose": {"transforms": {"Root": {"translation": [1.0, 0.0, 0.0]}}},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_report_prints_metrics(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``report --motion <json>`` exits 0 and prints the metric table."""
    motion = tmp_path / "motion.json"
    _write_motion(motion)
    exit_code = main(["report", "--motion", str(motion)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "jitter_score" in captured.out
    assert "foot_sliding_score" in captured.out
    assert "root_drift" in captured.out
    assert "frames" in captured.out


def test_report_writes_json_output(tmp_path: Path) -> None:
    """``--out`` persists a pretty JSON report next to the table."""
    motion = tmp_path / "motion.json"
    _write_motion(motion)
    out = tmp_path / "report.json"
    exit_code = main(["report", "--motion", str(motion), "--out", str(out)])

    assert exit_code == 0
    stored = json.loads(out.read_text(encoding="utf-8"))
    assert stored["frames"] == 2
    assert stored["duration_frames"] == 2
    assert stored["root_drift"] == 1.0


def test_report_missing_file_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A nonexistent motion file exits 1 with a clear stderr message."""
    missing = tmp_path / "nope.json"
    exit_code = main(["report", "--motion", str(missing)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "cannot read motion file" in captured.err


def test_report_invalid_json_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Invalid JSON exits 1 on stderr."""
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    exit_code = main(["report", "--motion", str(broken)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "invalid JSON" in captured.err