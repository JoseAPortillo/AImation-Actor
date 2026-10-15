"""Qt Multimedia video player: streams the reference clip (FR-CAP-01, FR-CAP-02).

The clip is played through ``QMediaPlayer`` / ``QVideoWidget``, which stream and
decode on demand (plan §5.A): this adapter never reads frames itself, so peak
memory does not scale with the clip's length, and it only hands the engine a
frame buffer when the capture key is pressed (M5, FR-CAP-05).

It is a ``VideoSource`` for the capture controller: it exposes ``open``,
``play``, ``pause`` and ``seek_frame``, plus the ``media_loaded``,
``position_changed``, ``playback_changed`` and ``failed`` signals the controller
listens to.

Two deliberate choices:

- **silent.** No audio output is attached: the reference clip is a visual
  reference for pose capture, not a soundtrack.
- **the frame rate is a report, not a promise.** ``QMediaPlayer`` exposes the
  clip's frame rate as optional metadata, so ``0.0`` means "not reported" and
  the timeline keeps its own default (FR-CAP-03).

Real playback needs a media backend and a real clip, so it is verified manually;
the behavior pinned by tests is the boundary handling and the seam.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtMultimedia import QMediaMetaData, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QVBoxLayout, QWidget

__all__ = ["VideoPlayer", "frame_rate_of"]


def frame_rate_of(metadata: QMediaMetaData) -> float:
    """The clip's frame rate, or ``0.0`` when the backend does not report one."""
    reported = metadata.value(QMediaMetaData.Key.VideoFrameRate)
    if isinstance(reported, (int, float)) and reported > 0:
        return float(reported)
    return 0.0


class VideoPlayer(QWidget):
    """A streaming reference-video player, driven by the capture controller."""

    media_loaded = Signal(float, int)
    position_changed = Signal(int)
    playback_changed = Signal(bool)
    failed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source_path: Path | None = None
        self._announced = False

        self._player = QMediaPlayer(self)
        self._view = QVideoWidget(self)
        self._player.setVideoOutput(self._view)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

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
        self._player.setSource(QUrl.fromLocalFile(str(candidate)))

    def play(self) -> None:
        """Start playback."""
        self._player.play()

    def pause(self) -> None:
        """Pause playback."""
        self._player.pause()

    def seek_frame(self, frame: int, fps: float) -> None:
        """Seek to ``frame`` at ``fps``; the player seeks by millisecond."""
        if fps <= 0.0:
            return
        self._player.setPosition(round(frame / fps * 1000.0))

    # -- player events ----------------------------------------------------- #

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            self._announce_loaded()

    def _on_duration_changed(self, duration: int) -> None:
        if duration > 0:
            self._announce_loaded()

    def _announce_loaded(self) -> None:
        """Report the clip once, when its duration is known (FR-CAP-03)."""
        duration = self._player.duration()
        if self._announced or self._source_path is None or duration <= 0:
            return
        self._announced = True
        self.media_loaded.emit(frame_rate_of(self._player.metaData()), duration)

    def _on_position(self, position: int) -> None:
        """Re-emit the player's position as a plain ``int``."""
        self.position_changed.emit(int(position))

    def _on_playback_state(self, state: QMediaPlayer.PlaybackState) -> None:
        self.playback_changed.emit(state == QMediaPlayer.PlaybackState.PlayingState)

    def _on_error(self, error: QMediaPlayer.Error, error_string: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        name = self._source_path.name if self._source_path is not None else "video"
        detail = error_string or error.name
        self._announced = False
        self.failed.emit(f"{name}: {detail}")
