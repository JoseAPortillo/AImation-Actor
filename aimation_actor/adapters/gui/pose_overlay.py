"""The video pane's skeleton overlay (pose-video-overlay T3, S1..S4).

A transparent widget that sits over the video surface and draws the
captured figure the controller hands it: ``(segments, dots)`` in the
engine's full-frame pixels (``CaptureController.overlay_snapshot_at``).
The widget owns nothing about poses or skeletons — it maps source pixels
onto itself with the same letterbox rule the video surface draws the
frame by (:func:`display_transform`), paints the side colors and dots
``core.overlay`` pinned, and draws nothing it cannot map honestly: no
snapshot, or a snapshot without the displayed frame's native size, is no
drawing at all. It is transparent to the mouse so the pane beneath keeps
every click.
"""

from __future__ import annotations

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

__all__ = ["PoseOverlay", "display_transform"]

_BONE_WIDTH_PX = 3.0
_DOT_RADIUS_PX = 5.0

_Segments = tuple[tuple[tuple[float, float], tuple[float, float], tuple[int, int, int]], ...]
_Dots = tuple[tuple[tuple[float, float], tuple[int, int, int], tuple[int, int, int]], ...]


def display_transform(
    native_width: int, native_height: int, widget_width: int, widget_height: int
) -> tuple[float, float, float]:
    """The letterbox rule the video surface draws frames by.

    Returns ``(scale, offset_x, offset_y)``: the full frame fits the widget
    keeping its aspect ratio, centered — the same math ``_VideoSurface``
    applies to its ``QImage``, so overlay pixels land exactly on the video
    pixels they belong to.
    """
    if native_width <= 0 or native_height <= 0 or widget_width <= 0 or widget_height <= 0:
        return (0.0, 0.0, 0.0)
    scale = min(widget_width / native_width, widget_height / native_height)
    return (
        scale,
        (widget_width - native_width * scale) / 2.0,
        (widget_height - native_height * scale) / 2.0,
    )


class PoseOverlay(QWidget):
    """Draws the held capture's figure over the video, side-colored (S1..S4)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Painting over the video must never darken it nor eat its events.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._snapshot: tuple[_Segments, _Dots] | None = None
        self._native_size: tuple[int, int] | None = None

    def set_snapshot(self, snapshot: tuple[_Segments, _Dots] | None) -> None:
        """Show ``(segments, dots)`` — ``overlay_snapshot_at``'s answer — or nothing."""
        self._snapshot = snapshot
        self.update()

    @property
    def snapshot(self) -> tuple[_Segments, _Dots] | None:
        """The figure currently held (read-back for the window's wiring)."""
        return self._snapshot

    def set_frame_size(self, width: int, height: int) -> None:
        """The displayed frame's native pixel size (the letterbox's source)."""
        self._native_size = (int(width), int(height)) if width > 0 and height > 0 else None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's naming, not ours
        if self._snapshot is None or self._native_size is None:
            return
        native_w, native_h = self._native_size
        scale, offset_x, offset_y = display_transform(
            native_w, native_h, self.width(), self.height()
        )
        if scale <= 0.0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        segments, dots = self._snapshot
        pen = QPen()
        pen.setWidthF(_BONE_WIDTH_PX)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for (start, end, color) in segments:
            pen.setColor(QColor(*color))
            painter.setPen(pen)
            painter.drawLine(
                QLineF(
                    QPointF(start[0] * scale + offset_x, start[1] * scale + offset_y),
                    QPointF(end[0] * scale + offset_x, end[1] * scale + offset_y),
                )
            )
        for (center, border, fill) in dots:
            painter.setPen(QPen(QColor(*border), 2.0))
            painter.setBrush(QColor(*fill))
            radius = _DOT_RADIUS_PX
            painter.drawEllipse(QRectF(center[0] * scale + offset_x - radius,
                                       center[1] * scale + offset_y - radius,
                                       radius * 2.0, radius * 2.0))
