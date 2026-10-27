"""Qt Multimedia video player: streams the reference clip (FR-CAP-01, FR-CAP-02).

The clip is played through ``QMediaPlayer``, which streams and decodes on demand
(plan §5.A): this adapter never decodes the file itself, so peak memory does not
scale with the clip's length (FR-CAP-02).

Frames reach the screen through a ``QVideoSink`` rather than a ``QVideoWidget``,
because a widget owns the player's only video output and never exposes what it
decoded. The sink hands us each frame, we draw it ourselves, and the frame the
animator is looking at stays available for capture — which is what lets the
engine receive a single temporary bitmap on demand (plan §4: *"The AI only
accesses a temporary bitmap when the capture key is pressed"*; FR-CAP-05).

One backend quirk drives the priming below, and it was measured rather than
guessed: a freshly loaded player delivers **no frames at all** until playback has
started once — the pane stays blank and the first capture has nothing to grab.
Seeking does not prime it either. Playing just long enough to receive one frame,
then pausing, does. What works once primed: every seek delivers exactly one frame,
the frame at the new position, even from ``EndOfMedia``.

It is a ``VideoSource`` for the capture controller: it exposes ``open``,
``play``, ``pause``, ``seek_frame`` and ``grab_frame``, plus the ``media_loaded``,
``position_changed``, ``frame_shown``, ``playback_changed`` and ``failed`` signals
the controller listens to.

Two deliberate choices:

- **silent.** No audio output is attached: the reference clip is a visual
  reference for pose capture, not a soundtrack.
- **the frame rate is a report, not a promise.** ``QMediaPlayer`` exposes the
  clip's frame rate as optional metadata, so ``0.0`` means "not reported" and
  the timeline keeps its own default (FR-CAP-03).

Real playback needs a media backend and a real clip, so the streaming path is
verified manually; the behavior pinned by tests is the boundary handling, the
frame conversion and the seam.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtMultimedia import QMediaMetaData, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import QVBoxLayout, QWidget

from aimation_actor.core.models import CapturedFrame, FrameImage

__all__ = [
    "VideoPlayer",
    "frame_index_of",
    "frame_rate_of",
    "frame_time_ms",
    "to_frame_image",
]


def frame_rate_of(metadata: QMediaMetaData) -> float:
    """The clip's frame rate, or ``0.0`` when the backend does not report one."""
    reported = metadata.value(QMediaMetaData.Key.VideoFrameRate)
    if isinstance(reported, (int, float)) and reported > 0:
        return float(reported)
    return 0.0


def frame_time_ms(frame: int, fps: float) -> int:
    """The millisecond to seek to for ``frame``: the middle of its time slot.

    Targeting the slot's *start* lands on a boundary, and a boundary resolves to
    the previous frame (measured: on a 24 fps clip, asking for 208 ms shows the
    frame that ends at 208.33 ms — frame 4 — not the one that starts there, frame
    5). The middle of the slot has no such ambiguity at any frame rate.
    """
    return round((frame + 0.5) / fps * 1000.0)


def frame_index_of(start_us: int, fps: float) -> int | None:
    """The index of the frame that starts at ``start_us``, or ``None`` if unknown.

    Frame ``n`` occupies the slot starting at ``n * 1e6 / fps`` microseconds, so
    inverting that gives the frame that is on screen. ``round`` absorbs the
    decoder's own timebase drift up to half a slot, while a negative timestamp or
    a frame rate the backend never reported means there is no answer — and no
    index is invented for it: the caller falls back to its own playhead.
    """
    if start_us < 0 or fps <= 0.0:
        return None
    return round(start_us * fps / 1_000_000.0)


def to_frame_image(image: QImage) -> FrameImage:
    """Convert a Qt image into the domain's flat RGB frame buffer.

    The format is forced to ``RGB888`` because that is what
    :class:`~aimation_actor.core.models.FrameImage` promises; a decoder's own
    format varies per clip.

    Qt pads every scanline of an ``RGB888`` image to a 4-byte boundary, so
    ``bytesPerLine()`` is **not** ``width * 3`` whenever the width is not a
    multiple of 4. Reading the buffer flat would then splice that padding into
    the picture and shift the image, so padded rows are copied one by one.
    """
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    width, height = rgb.width(), rgb.height()
    stride = rgb.bytesPerLine()
    buffer = bytes(rgb.constBits())
    if stride == width * 3:
        return FrameImage(width=width, height=height, rgb=buffer[: width * height * 3])
    packed = b"".join(
        buffer[row * stride : row * stride + width * 3] for row in range(height)
    )
    return FrameImage(width=width, height=height, rgb=packed)


class _VideoSurface(QWidget):
    """Draws the frame the sink delivered last, aspect-fitted on black."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image: QImage | None = None
        self.setMinimumSize(320, 180)

    def set_image(self, image: QImage) -> None:
        """Show ``image`` as the current frame."""
        self._image = image
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's naming, not ours
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        image = self._image
        if image is None or image.isNull():
            return
        # Nearest-neighbour on purpose: this runs per displayed frame, and the
        # animator reads the pose from the 3D pane, not from the video's grain.
        scaled = image.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        painter.drawImage(
            (self.width() - scaled.width()) // 2,
            (self.height() - scaled.height()) // 2,
            scaled,
        )


class VideoPlayer(QWidget):
    """A streaming reference-video player, driven by the capture controller."""

    media_loaded = Signal(float, int)
    position_changed = Signal(int)
    # The frame index of a delivered frame, emitted only when the clip's own
    # timestamps and frame rate can prove it (see ``frame_index_of``). The
    # controller follows this instead of ``position_changed`` once it arrives:
    # position events are far rarer than frames, which is what lets the timeline
    # lag the pane by a frame or three.
    frame_shown = Signal(int)
    playback_changed = Signal(bool)
    failed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source_path: Path | None = None
        self._announced = False
        self._fps = 0.0
        self._image: QImage | None = None
        self._seen_frame = False
        self._priming = False
        self._user_playing = False
        # The position a seek asked for, in microseconds, until the decoder
        # delivers the frame that covers it; and the span of the frame on screen.
        self._wanted_us: int | None = None
        self._span: tuple[int, int] | None = None

        self._player = QMediaPlayer(self)
        self._sink = QVideoSink(self)
        self._surface = _VideoSurface(self)
        self._player.setVideoSink(self._sink)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._surface)

        self._sink.videoFrameChanged.connect(self._on_frame)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.durationChanged.connect(self._on_duration_changed)
        # ``positionChanged`` carries a ``qlonglong``: a Qt detail that must not
        # leak into the seam, so it is re-emitted as a plain ``int``.
        self._player.positionChanged.connect(self._on_position)
        self._player.playbackStateChanged.connect(self._on_playback_state)
        self._player.errorOccurred.connect(self._on_error)

    # -- what the controller sees ------------------------------------------ #

    @property
    def source_path(self) -> Path | None:
        """The clip handed to the backend, or ``None``."""
        return self._source_path

    @property
    def media_player(self) -> QMediaPlayer:
        """The underlying ``QMediaPlayer`` (Qt-facing, not part of the seam)."""
        return self._player

    def open(self, path: str) -> None:
        """Load ``path``; a path that is not a file fails fast and is reported."""
        candidate = Path(path)
        if not candidate.is_file():
            self._source_path = None
            self._announced = False
            self.failed.emit(f"{candidate.name}: no such file ({candidate})")
            return
        self._source_path = candidate
        self._announced = False
        self._fps = 0.0
        self._image = None
        self._seen_frame = False
        self._priming = False
        self._user_playing = False
        self._wanted_us = None
        self._span = None
        self._surface.set_image(QImage())  # drop the previous clip's frame
        self._player.setSource(QUrl.fromLocalFile(str(candidate)))

    def play(self) -> None:
        """Start playback."""
        self._user_playing = True
        # An explicit play supersedes a priming nudge, so the animator can always
        # take control even if the backend never handed us that first frame.
        self._priming = False
        # Live playback means live frames: whatever is on screen is the answer.
        self._wanted_us = None
        self._player.play()

    def pause(self) -> None:
        """Pause playback."""
        self._user_playing = False
        self._player.pause()

    def seek_frame(self, frame: int, fps: float) -> None:
        """Seek to ``frame``; the frame is reached at the middle of its slot."""
        if fps <= 0.0:
            return
        target_ms = frame_time_ms(frame, fps)
        self._wanted_us = target_ms * 1000
        self._player.setPosition(target_ms)

    def grab_frame(self, fps: float) -> CapturedFrame | None:
        """The frame on screen with the frame index it belongs to, or ``None``.

        Only this one frame is ever converted, and only when asked, so the engine
        receives a single temporary bitmap (FR-CAP-05).

        A seek is asynchronous — ``setPosition`` returns before the decoder has
        delivered anything — so the frame on screen right after a scrub can still
        be the *previous* position's. Handing that over would extract the pose of
        a frame the animator is not looking at, and nothing downstream could tell.
        Every delivered frame carries its own clip timestamps, so it is handed
        over only when it covers the position that was asked for; a frame without
        usable timestamps is passed through rather than blocked, with its index
        left unknown for the caller to resolve.

        The index comes from the frame's own timestamps, never from the
        controller's position: while the player plays, position events arrive far
        less often than frames, so the timeline lags the pane by up to a few
        frames and the key would land on the neighbour of the pose shown.
        """
        image = self._image
        if image is None or image.isNull():
            return None
        wanted = self._wanted_us
        span = self._span
        if wanted is not None and span is not None and not (span[0] <= wanted <= span[1]):
            return None
        index = None if span is None else frame_index_of(span[0], fps)
        return CapturedFrame(image=to_frame_image(image), frame_index=index)

    # -- player events ----------------------------------------------------- #

    def _on_frame(self, frame) -> None:
        """Keep and show the newest decoded frame; end a priming nudge.

        The pause happens before ``_priming`` is cleared so the state change it
        emits is still recognized as ours and stays out of ``playback_changed``.
        """
        image = frame.toImage()
        if image.isNull():
            return
        self._seen_frame = True
        start, end = frame.startTime(), frame.endTime()
        if start >= 0 and end > start:
            self._span = (start, end)
            if self._wanted_us is not None and start <= self._wanted_us <= end:
                self._wanted_us = None  # the seek landed; frames are live again
        else:
            # No usable timestamps: the attribution check in ``grab_frame`` is
            # skipped rather than refusing every frame.
            self._span = None
        if self._span is not None:
            index = frame_index_of(start, self._fps)
            if index is not None:
                # The frame just delivered says which frame it is, so the
                # timeline can follow the pane instead of the backend's much
                # rarer position events.
                self.frame_shown.emit(index)
        if self._priming:
            if not self._user_playing:
                self._player.pause()
            self._priming = False
        self._image = image
        self._surface.set_image(image)

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            self._announce_loaded()
            self._prime_first_frame()

    def _prime_first_frame(self) -> None:
        """Coax one frame out of a backend that will not decode until it plays.

        Measured against the real backend, not assumed: a freshly loaded player
        delivers no frames at all — seeking does not help — so without this the
        pane stays blank and the animator's first ``K`` finds nothing to grab.
        One frame is enough, and the pause lands in :meth:`_on_frame`.
        """
        if self._seen_frame or self._priming or self._user_playing:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            return
        self._priming = True
        self._player.play()

    def _on_duration_changed(self, duration: int) -> None:
        if duration > 0:
            self._announce_loaded()

    def _announce_loaded(self) -> None:
        """Report the clip once, when its duration is known (FR-CAP-03)."""
        duration = self._player.duration()
        if self._announced or self._source_path is None or duration <= 0:
            return
        self._announced = True
        self._fps = frame_rate_of(self._player.metaData())
        self.media_loaded.emit(self._fps, duration)

    def _on_position(self, position: int) -> None:
        """Re-emit the player's position as a plain ``int``."""
        self.position_changed.emit(int(position))

    def _on_playback_state(self, state: QMediaPlayer.PlaybackState) -> None:
        if self._priming:
            # The nudge is not the animator pressing play: reporting it would move
            # the playhead and flip the toolbar for a moment on every clip open.
            return
        self.playback_changed.emit(state == QMediaPlayer.PlaybackState.PlayingState)

    def _on_error(self, error: QMediaPlayer.Error, error_string: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        name = self._source_path.name if self._source_path is not None else "video"
        detail = error_string or error.name
        self._announced = False
        self.failed.emit(f"{name}: {detail}")
