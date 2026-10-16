"""Tests for the Qt Multimedia video player (FR-CAP-01, FR-CAP-02, FR-CAP-03).

Real playback needs a media backend and a real clip, so it stays a manual check
(as with Blender, NFR-04). What is pinned here is what can be pinned: the frame
rate the clip reports, the boundary handling, and that the widget really is a
video source for the capture controller.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtMultimedia import QMediaMetaData, QMediaPlayer
from PySide6.QtWidgets import QApplication

from aimation_actor.adapters.gui.capture_controller import CaptureController
from aimation_actor.adapters.gui.video_player import (
    VideoPlayer,
    frame_index_of,
    frame_rate_of,
    frame_time_ms,
    to_frame_image,
)
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


# --------------------------------------------------------------------------- #
# The frame the engine receives (M5 S2, S8 · FR-CAP-05)
# --------------------------------------------------------------------------- #


def _image(width: int, height: int, color: tuple[int, int, int]) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(*color))
    return image


def test_a_frame_becomes_a_flat_rgb_buffer() -> None:
    frame = to_frame_image(_image(2, 2, (10, 20, 30)))

    assert (frame.width, frame.height) == (2, 2)
    assert len(frame.rgb) == 2 * 2 * 3
    assert set(frame.rgb) == {10, 20, 30}


def test_a_frame_of_an_odd_width_keeps_its_rows_aligned() -> None:
    # The trap: Qt pads an RGB888 scanline to a 4-byte boundary, so a 3-pixel row
    # is stored in 12 bytes, not 9. A flat read would splice that padding into
    # the picture and shift every row — this pins the row-by-row copy.
    image = QImage(3, 2, QImage.Format.Format_RGB32)
    image.fill(QColor(0, 0, 0))
    image.setPixelColor(0, 0, QColor(255, 0, 0))
    image.setPixelColor(1, 1, QColor(0, 255, 0))

    frame = to_frame_image(image)

    assert len(frame.rgb) == 3 * 2 * 3
    # Row 0, pixel 0 is red; row 1, pixel 1 is green. If padding leaked in, the
    # second row would start at the wrong offset and neither would hold.
    assert frame.rgb[0:3] == bytes((255, 0, 0))
    row_1 = 3 * 3
    assert frame.rgb[row_1 + 3 : row_1 + 6] == bytes((0, 255, 0))


def test_a_player_with_no_frame_yet_gives_none(qtbot) -> None:
    # Nothing has been decoded, so there is nothing to hand an engine. The
    # controller reports that rather than extracting from an empty buffer.
    player = VideoPlayer()
    qtbot.addWidget(player)

    assert player.grab_frame(24.0) is None


# --------------------------------------------------------------------------- #
# The frame belongs to the position asked for (M5 S8)
#
# A seek is asynchronous: setPosition returns before the decoder delivers
# anything, so the frame on screen right after a scrub is still the previous
# position's. Handing that to the engine would extract a pose the animator is
# not looking at, with nothing downstream able to tell.
# --------------------------------------------------------------------------- #


def test_a_seek_targets_the_middle_of_the_frame_slot() -> None:
    # The slot's start is a boundary, and a boundary resolves to the previous
    # frame: on this 24 fps clip, asking for 208 ms showed the frame ending at
    # 208.33 ms (frame 4), not the frame starting there (frame 5).
    assert frame_time_ms(5, 24.0) == 229
    assert frame_time_ms(12, 24.0) == 521
    assert frame_time_ms(0, 24.0) == 21


def test_a_seek_never_lands_on_a_slot_boundary() -> None:
    # The rule, not the examples: for every frame of a 24 fps clip the target
    # must fall strictly inside that frame's slot.
    duration_ms = 1000.0 / 24.0
    for frame in range(200):
        target = frame_time_ms(frame, 24.0)
        assert frame * duration_ms < target < (frame + 1) * duration_ms


def _timed_frame(start_us: int, end_us: int):
    from PySide6.QtMultimedia import QVideoFrame

    frame = QVideoFrame(_image(2, 2, (10, 20, 30)))
    frame.setStartTime(start_us)
    frame.setEndTime(end_us)
    return frame


def test_the_frame_for_the_seek_is_handed_over(qtbot) -> None:
    player = VideoPlayer()
    qtbot.addWidget(player)

    player.seek_frame(12, 24.0)  # 521 ms -> the slot [500000, 541667) us
    player._on_frame(_timed_frame(500000, 541667))

    captured = player.grab_frame(24.0)

    assert captured is not None
    assert captured.frame_index == 12


def test_the_previous_positions_frame_is_not_handed_over(qtbot) -> None:
    # This is the bug the real clip exposed: the scrub to frame 12 has not been
    # decoded yet, so the frame still on screen is frame 4's.
    player = VideoPlayer()
    qtbot.addWidget(player)

    player.seek_frame(12, 24.0)
    player._on_frame(_timed_frame(166667, 208334))

    assert player.grab_frame(24.0) is None


def test_a_frame_without_timestamps_is_not_blocked(qtbot) -> None:
    # Degrade rather than refuse: a backend that reports no timestamps must still
    # be able to hand a frame over. It cannot say which frame it is, though, so
    # the index is left unknown for the caller to resolve.
    player = VideoPlayer()
    qtbot.addWidget(player)

    player.seek_frame(12, 24.0)
    player._on_frame(_timed_frame(-1, -1))

    captured = player.grab_frame(24.0)

    assert captured is not None
    assert captured.frame_index is None


def test_frames_become_live_again_once_the_seek_landed(qtbot) -> None:
    # After the seek lands, playback keeps delivering later frames; they must not
    # be refused for not covering a position that is already past.
    player = VideoPlayer()
    qtbot.addWidget(player)

    player.seek_frame(12, 24.0)
    player._on_frame(_timed_frame(500000, 541667))

    assert player.grab_frame(24.0) is not None
    player._on_frame(_timed_frame(541667, 583334))
    assert player.grab_frame(24.0) is not None


def test_playback_makes_the_frame_on_screen_the_answer_again(qtbot) -> None:
    player = VideoPlayer()
    qtbot.addWidget(player)

    player.seek_frame(12, 24.0)
    player.play()  # the animator asked for live playback
    player._on_frame(_timed_frame(2000000, 2041667))

    assert player.grab_frame(24.0) is not None


def test_a_live_frame_is_the_frame_it_says_it_is_not_the_seek_target(qtbot) -> None:
    # The playback half of the attribution problem (M5 verification, S12). While
    # playing, the seek guard is off on purpose — the frame on screen is the
    # answer — but the playhead only follows the backend's *position* events,
    # which are far rarer than frames. So the pane can be showing frame 48 while
    # the timeline still says 12. The frame must say which frame it is; otherwise
    # the key lands wherever the playhead happened to lag to.
    player = VideoPlayer()
    qtbot.addWidget(player)

    player.seek_frame(12, 24.0)
    player.play()
    player._on_frame(_timed_frame(2000000, 2041667))  # frame 48

    captured = player.grab_frame(24.0)

    assert captured is not None
    assert captured.frame_index == 48


def test_the_index_is_left_unknown_without_a_frame_rate() -> None:
    # A clip whose frame rate the backend never reported cannot be indexed; the
    # caller falls back to its own playhead rather than receiving a guess.
    assert frame_index_of(2000000, 0.0) is None


def test_a_delivered_frame_reports_its_own_index(qtbot) -> None:
    # S13: the controller follows this instead of the backend's position events,
    # which are far rarer than frames. The frame rate is what the clip reported,
    # read back through the same path the player uses (``_announce_loaded``).
    player = VideoPlayer()
    qtbot.addWidget(player)
    player._fps = 24.0
    shown: list[int] = []
    player.frame_shown.connect(shown.append)

    player._on_frame(_timed_frame(2000000, 2041667))  # frame 48

    assert shown == [48]


def test_a_frame_without_timestamps_reports_no_index(qtbot) -> None:
    # No timestamps means no provable index, so nothing is claimed and the
    # controller keeps resolving the playhead its own way.
    player = VideoPlayer()
    qtbot.addWidget(player)
    player._fps = 24.0
    shown: list[int] = []
    player.frame_shown.connect(shown.append)

    player._on_frame(_timed_frame(-1, -1))

    assert shown == []


def test_the_frame_index_is_derived_from_the_slot_the_frame_occupies() -> None:
    assert frame_index_of(500000, 24.0) == 12
    assert frame_index_of(2000000, 24.0) == 48
    assert frame_index_of(0, 24.0) == 0
    # No usable timestamps: the index is unknown, never invented.
    assert frame_index_of(-1, 24.0) is None


# --------------------------------------------------------------------------- #
# Priming the first frame (M5 S8)
#
# These drive the adapter's own event handlers directly — the only way to pin
# them without a media backend — so they call private slots on purpose. What is
# pinned is the contract, not the wiring.
# --------------------------------------------------------------------------- #


def _video_frame(color: tuple[int, int, int] = (10, 20, 30)):
    from PySide6.QtMultimedia import QVideoFrame

    return QVideoFrame(_image(2, 2, color))


def test_a_primed_player_hands_the_animator_its_first_frame(qtbot) -> None:
    # Measured against the real backend: a freshly loaded clip delivers no frames
    # at all until playback has started once, so without this the pane stays blank
    # and the animator's first K finds nothing to grab.
    player = VideoPlayer()
    qtbot.addWidget(player)

    player._on_media_status(QMediaPlayer.MediaStatus.LoadedMedia)
    player._on_frame(_video_frame())

    captured = player.grab_frame(24.0)
    assert captured is not None
    assert (captured.image.width, captured.image.height) == (2, 2)


def test_a_priming_nudge_is_not_reported_as_playback(qtbot) -> None:
    # The nudge really does play for a moment. Reporting it would walk the
    # playhead off frame 0 — the controller follows the player's position only
    # while it believes playback is running — and flip the toolbar on every clip
    # open. A repeat of a state the controller already holds is a no-op there, so
    # what has to be silent is the nudge itself.
    player = VideoPlayer()
    qtbot.addWidget(player)
    reported: list[bool] = []
    player.playback_changed.connect(reported.append)

    player._on_media_status(QMediaPlayer.MediaStatus.LoadedMedia)
    player._on_playback_state(QMediaPlayer.PlaybackState.PlayingState)

    assert reported == []

    # The first frame ends the nudge and the player pauses itself; the clip must
    # still be capturable afterwards.
    player._on_frame(_video_frame())
    assert player.grab_frame(24.0) is not None


def test_an_explicit_play_is_reported_once_priming_is_over(qtbot) -> None:
    # Priming must never swallow the animator's own press of Space.
    player = VideoPlayer()
    qtbot.addWidget(player)
    reported: list[bool] = []
    player.playback_changed.connect(reported.append)

    player._on_media_status(QMediaPlayer.MediaStatus.LoadedMedia)
    player.play()
    player._on_playback_state(QMediaPlayer.PlaybackState.PlayingState)

    assert reported == [True]


# --------------------------------------------------------------------------- #
# S12/S13 regression additions (verifier probes)
# --------------------------------------------------------------------------- #


def test_the_frame_index_boundaries() -> None:
    # S12: the named boundaries of ``frame_index_of``, plus the no-answer cases.
    assert frame_index_of(500000, 24.0) == 12
    assert frame_index_of(2000000, 24.0) == 48
    assert frame_index_of(0, 24.0) == 0
    assert frame_index_of(-1, 24.0) is None
    assert frame_index_of(2000000, 0.0) is None
    assert frame_index_of(500000, -24.0) is None


def test_the_seek_targets_predate_the_fix_and_must_not_move() -> None:
    # S10: these values are from the baseline commit and are unchanged.
    assert frame_time_ms(0, 24.0) == 21
    assert frame_time_ms(5, 24.0) == 229
    assert frame_time_ms(12, 24.0) == 521
    assert frame_time_ms(199, 24.0) == 8312


def test_a_live_frame_without_a_frame_rate_reports_no_index(qtbot) -> None:
    # S12: degrade, never refuse — the caller falls back to its own playhead.
    player = VideoPlayer()
    qtbot.addWidget(player)

    player.play()
    player._on_frame(_timed_frame(2000000, 2041667))

    captured = player.grab_frame(0.0)

    assert captured is not None
    assert captured.frame_index is None
