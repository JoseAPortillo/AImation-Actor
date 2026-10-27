"""Off-thread pose extraction: one frame at a time, off the UI thread.

``AIPort`` is blocking by contract, so the capture UI must never call it
directly: a pose inference would freeze the window (NFR-02). This runner
is that engine's slice of the shared batch-1 lifecycle
(``thread_runner.ThreadedEngineRunner``) — it runs one extraction on its
own ``QThread`` and reports the outcome through signals (FR-CAP-05). The
two rules that lifecycle enforces by construction (batch size 1,
non-fatal failure) are pinned there; this module adds only the
extraction-specific part: the frame index rides along with the result,
so a pose that lands after the playhead has moved is still written to
the frame it was extracted from.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from aimation_actor.adapters.ai.thread_runner import ThreadedEngineRunner
from aimation_actor.core.models import FrameImage
from aimation_actor.ports.ai_port import AIPort

__all__ = ["PoseExtractionRunner"]


class _ExtractionJob(QObject):
    """One extraction, living on the worker thread until it finishes."""

    extracted = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, engine: AIPort, frame_index: int, image: FrameImage) -> None:
        super().__init__()
        self._engine = engine
        self._frame_index = frame_index
        self._image = image

    @Slot()
    def run(self) -> None:
        try:
            pose = self._engine.extract_pose(self._image, frame_index=self._frame_index)
        except Exception as error:  # an engine failure is non-fatal (FR-CAP-07)
            # ``str`` of a bare exception can be empty; the type always names it.
            self.failed.emit(self._frame_index, str(error) or type(error).__name__)
            return
        self.extracted.emit(self._frame_index, pose)


class PoseExtractionRunner(ThreadedEngineRunner):
    """Runs one blocking engine off the UI thread and reports the outcome.

    ``extracted`` carries the :class:`WorldPose` **together with the frame it
    belongs to**, so a result that lands after the playhead has moved is still
    written to the frame it was extracted from.
    """

    extracted = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, engine: AIPort, parent: QObject | None = None) -> None:
        super().__init__(engine, parent)

    def start(self, frame_index: int, image: FrameImage) -> bool:
        """Extract ``image`` off the UI thread.

        Returns ``False`` without starting anything when an extraction is
        already running (batch size 1, S4).
        """
        job = _ExtractionJob(self._engine, frame_index, image)
        return self._launch(
            job,
            success=job.extracted,
            failure=job.failed,
            relay_success=self.extracted,
            relay_failure=self.failed,
        )
