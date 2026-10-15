"""Embedded 3D viewport adapter (QOpenGLWidget + PyOpenGL).

Draws the current pose as bone segments (plan §3.B, "central 3D viewer"). Two
things are deliberately small here:

- the **math lives in ``core.kinematics``** — this widget only fits the result to
  the screen and draws lines, so the pose logic stays testable without a display;
- the **view is fixed**: orbiting and zooming were never requested for the MVP,
  and a camera nobody asked for is a feature with its own bugs. The projection is
  written so a later camera is a change of matrix, not of drawing.

Axis note: the domain is Z-up (``AGENTS.md``) and OpenGL's screen is Y-up, so
vertices are rotated by ``R_x(-90°)`` — the same conjugation the FBX writer uses.
GL coordinates are ``(x, z, -y)``; that keeps the figure upright and, unlike a
plain axis swap, does not mirror it.

If the driver cannot do fixed-function drawing (an ANGLE backend, for example)
the pane says so instead of showing an empty frame: a silent blank view would
read as "the rig failed to load" (NFR-03).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from OpenGL import GL
from PySide6.QtCore import Qt
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from aimation_actor.core.kinematics import bone_segments
from aimation_actor.core.models import JointPose, Skeleton, Vector3

__all__ = ["SkeletonViewport", "fit_view"]

#: The smallest half-size a view may collapse to, in centimeters. Without a
#: floor a figure that is a single point would produce a zero-width projection.
_MIN_HALF_SIZE = 1.0

_FIXED_FUNCTION_NOTICE = (
    "This OpenGL driver has no fixed-function pipeline, so the 3D preview is unavailable."
)
_NO_CONTEXT_NOTICE = "No OpenGL context is available, so the 3D preview is unavailable."


def fit_view(points: Iterable[Vector3], *, margin: float = 0.1) -> tuple[Vector3, float]:
    """The centre and half-size of a cube that holds ``points``.

    ``margin`` is a fraction of the half-size added as breathing room. The
    half-size never drops below :data:`_MIN_HALF_SIZE`, so an empty figure, or a
    rig that collapses to one point, still yields a usable projection.
    """
    coordinates = [(point.x, point.y, point.z) for point in points]
    if not coordinates:
        return Vector3(), _MIN_HALF_SIZE

    xs = [coordinate[0] for coordinate in coordinates]
    ys = [coordinate[1] for coordinate in coordinates]
    zs = [coordinate[2] for coordinate in coordinates]
    center = Vector3(
        x=(min(xs) + max(xs)) / 2.0,
        y=(min(ys) + max(ys)) / 2.0,
        z=(min(zs) + max(zs)) / 2.0,
    )
    half_size = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) / 2.0
    return center, max(half_size * (1.0 + margin), _MIN_HALF_SIZE)


class SkeletonViewport(QOpenGLWidget):
    """The 3D pane: bone segments of the current pose, fitted to the view."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._segments: tuple[tuple[Vector3, Vector3], ...] = ()
        self._ready = False

        self.notice_label = QLabel(self)
        self.notice_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.notice_label.setWordWrap(True)
        self.notice_label.hide()

        layout = QVBoxLayout(self)
        layout.addWidget(self.notice_label)
        self.setMinimumSize(240, 240)

    # -- what the window drives -------------------------------------------- #

    @property
    def segments(self) -> tuple[tuple[Vector3, Vector3], ...]:
        """The bone segments currently drawn, in hierarchy order."""
        return self._segments

    def set_pose(self, skeleton: Skeleton, pose: Mapping[str, JointPose]) -> None:
        """Show ``pose`` on ``skeleton``.

        A session can legitimately have no rig yet (until M5 supplies the
        production skeleton), in which case there are simply no segments to draw.
        """
        self._segments = bone_segments(skeleton, pose)
        self.update()

    # -- OpenGL ------------------------------------------------------------ #

    def initializeGL(self) -> None:
        self._ready = self._probe_fixed_function()
        red, green, blue, _ = self.palette().window().color().getRgbF()
        GL.glClearColor(red, green, blue, 1.0)

    def resizeGL(self, width: int, height: int) -> None:
        if self._ready:
            GL.glViewport(0, 0, max(1, width), max(1, height))

    def paintGL(self) -> None:
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        if not self._ready or not self._segments:
            return

        center, half_size = fit_view(point for segment in self._segments for point in segment)
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glLoadIdentity()
        GL.glOrtho(
            center.x - half_size,
            center.x + half_size,
            center.z - half_size,
            center.z + half_size,
            center.y - half_size,
            center.y + half_size,
        )
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadIdentity()

        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glLineWidth(2.0)
        GL.glColor3f(0.85, 0.87, 0.90)
        GL.glBegin(GL.GL_LINES)
        for start, end in self._segments:
            GL.glVertex3f(start.x, start.z, -start.y)
            GL.glVertex3f(end.x, end.z, -end.y)
        GL.glEnd()

    def _probe_fixed_function(self) -> bool:
        """Whether this context can draw the immediate-mode subset we use."""
        context = self.context()
        if context is None or not context.isValid():
            self._show_notice(_NO_CONTEXT_NOTICE)
            return False
        try:
            GL.glBegin(GL.GL_LINES)
            GL.glEnd()
        except Exception:  # noqa: BLE001 - any GL failure means "cannot draw"
            self._show_notice(_FIXED_FUNCTION_NOTICE)
            return False
        self._show_notice("")
        return True

    def _show_notice(self, text: str) -> None:
        self.notice_label.setText(text)
        self.notice_label.setVisible(bool(text))
