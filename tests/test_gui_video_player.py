"""Tests for the Qt Multimedia video player (FR-CAP-01, FR-CAP-02, FR-CAP-03).

Real playback needs a media backend and a real clip, so it stays a manual check
(as with Blender, NFR-04). What is pinned here is what can be pinned: the frame
rate the clip reports, the boundary handling, and that the widget really is a
video source for the capture controller.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtMultimedia import QMediaMetaData
from PySide6.QtWidgets import QApplication

from aimation_actor.adapters.gui.capture_controller import CaptureController
from aimation_actor.adapters.gui.video_player import VideoPlayer, frame_rate_of
from aimation_actor.core.models import TimelineState


def test_the_clip_frame_rate_comes_from_the_metadata() -> None:
    metadata = QMediaMetaData()
    metadata.insert(QMediaMetaData.Key.VideoFrameRate, 25.0)

    assert frame_rate_of(metadata) == pytest.approx(25.0)


def test_a_clip_that_reports_no_frame_rate_is_zero() -> None:
    # ``0.0`` is the "not reported" signal: the timeline keeps its own default.
    assert frame_rate_of(QMediaMetaData()) == pytest.approx(0.0)


def test_the_player_widget_can_be_built(
    qtbot,
    qapp: QApplication,  # noqa: ARG001 - ensures a QApplication exists
) -> None:
    player = VideoPlayer()
    qtbot.addWidget(player)

    assert player.source_path is None


def test_the_player_stays_silent(qtbot) -> None:
    player = VideoPlayer()
    qtbot.addWidget(player)

    # No audio output is attached on purpose: a reference clip is a visual
    # reference for pose capture, not a soundtrack.
    assert player.media_player.audioOutput() is None


def test_opening_a_missing_file_fails_fast_without_touching_the_backend(
    workspace: Path, qtbot
) -> None:
    player = VideoPlayer()
    qtbot.addWidget(player)
    failures: list[str] = []
    player.failed.connect(failures.append)

    player.open(str(workspace / "missing.mp4"))

    assert len(failures) == 1
    assert "missing.mp4" in failures[0]
    assert player.source_path is None


def test_opening_an_existing_file_hands_it_to_the_backend(workspace: Path, qtbot) -> None:
    clip = workspace / "reference.mp4"
    clip.write_bytes(b"placeholder for a reference clip")

    player = VideoPlayer()
    qtbot.addWidget(player)

    player.open(str(clip))

    assert player.source_path == clip


def test_the_widget_is_a_video_source_for_the_controller(
    workspace: Path, qtbot, sample_state: TimelineState
) -> None:
    player = VideoPlayer()
    qtbot.addWidget(player)
    controller = CaptureController(player, sample_state)
    failures: list[str] = []
    controller.failed.connect(failures.append)

    controller.open_video(str(workspace / "missing.mp4"))

    # The failure travels through the seam, and the controller does not claim a
    # clip is loaded (FR-CAP-01).
    assert len(failures) == 1
    assert controller.has_media is False
