"""Timeline scrubber: the playhead, the frame readout and the golden-pose markers.

A ``QSlider`` carries the interaction (dragging, arrow keys, accessibility) and a
thin ``KeyStrip`` draws the markers the plan asks for — "draw a key marker on the
timeline" (plan §3.A). The widget is presentational: it never touches the
timeline or the playhead, it reports what the user asked for and shows what the
controller reports.

That split is what keeps the capture loop open: only the user moving the slider
emits ``frame_requested``. Programmatic updates — the controller reporting that
the playhead moved, which happens *because* of a seek — are signal-blocked, so
they cannot bounce back into another seek.
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

__all__ = ["KeyStrip", "TimelineBar", "frame_x"]


def frame_x(frame: int, start: int, end: int, width: int) -> float:
    """The x position of ``frame`` across a ``width``-pixel strip.

    A range that spans a single frame, or a strip with no width, collapses to the
    left edge instead of dividing by zero.
    """
    if end <= start or width <= 0:
        return 0.0
    return (frame - start) / (end - start) * width


class KeyStrip(QWidget):
    """Marks, on a thin strip, the frames that carry a golden pose."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(10)
        self._keys: tuple[int, ...] = ()
        self._start = 0
        self._end = 0

    @property
    def keys(self) -> tuple[int, ...]:
        """The frames currently marked."""
        return self._keys

    def set_range(self, start: int, end: int) -> None:
        """Set the frame span the markers are laid out across."""
        self._start, self._end = start, end
        self.update()

    def set_keys(self, frames: Iterable[int]) -> None:
        """Replace the marked frames."""
        self._keys = tuple(frames)
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().base())
        painter.setPen(self.palette().highlight().color())
        bottom = self.height() - 1
        for frame in self._keys:
            x = round(frame_x(frame, self._start, self._end, self.width() - 1))
            painter.drawLine(x, 0, x, bottom)


class TimelineBar(QWidget):
    """The scrubber: current/total frames, the clip's frame rate, and the keys."""

    frame_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._start = 0
        self._end = 0
        self._frame = 0

        self.frame_label = QLabel("Frame 0 / 1", self)
        self.frame_label.setObjectName("frame_readout")
        self.fps_label = QLabel("24 fps", self)
        self.fps_label.setObjectName("fps_readout")
        self.key_strip = KeyStrip(self)
        self.slider = QSlider(Qt.Orientation.Horizontal, self)

        top = QHBoxLayout()
        top.addWidget(self.frame_label)
        top.addStretch(1)
        top.addWidget(self.fps_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(top)
        layout.addWidget(self.key_strip)
        layout.addWidget(self.slider)

        self.slider.valueChanged.connect(self.frame_requested.emit)

    # -- what the user sees ------------------------------------------------ #

    @property
    def frame(self) -> int:
        """The frame the readout currently shows."""
        return self._frame

    @property
    def total_frames(self) -> int:
        """How many frames the range spans, at least one."""
        return max(1, self._end - self._start + 1)

    def set_timeline(self, *, frame_start: int, frame_end: int, fps: float) -> None:
        """Adopt a clip's range and frame rate."""
        self._start, self._end = frame_start, frame_end
        self._frame = min(max(self._frame, frame_start), frame_end)
        # The range must widen first: setting the value against the old range
        # would clamp it there and fight the new one.
        self.slider.setRange(frame_start, frame_end)
        self._set_slider_value(self._frame)
        self.key_strip.set_range(frame_start, frame_end)
        self.fps_label.setText(f"{fps:g} fps")
        self._refresh_readout()

    def set_frame(self, frame: int) -> None:
        """Show ``frame``, clamped to the range, without asking for it."""
        self._frame = min(max(frame, self._start), self._end)
        self._set_slider_value(self._frame)
        self._refresh_readout()

    def set_keys(self, frames: Iterable[int]) -> None:
        """Mark the given frames as carrying a golden pose."""
        self.key_strip.set_keys(frames)

    def _set_slider_value(self, frame: int) -> None:
        """Move the handle without reporting a request: this is not user input."""
        blocked = self.slider.blockSignals(True)
        self.slider.setValue(frame)
        self.slider.blockSignals(blocked)

    def _refresh_readout(self) -> None:
        self.frame_label.setText(f"Frame {self._frame} / {self.total_frames}")
