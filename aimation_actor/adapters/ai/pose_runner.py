"""Off-thread pose extraction: one frame at a time, off the UI thread.

``AIPort`` is blocking by contract, so the capture UI must never call it
directly: a pose inference would freeze the window (NFR-02). This module is the
small piece of infrastructure that keeps the window alive while an engine works —
it runs one extraction on its own ``QThread`` and reports the outcome through
signals (FR-CAP-05).

Two rules it enforces by construction:

- **batch size 1.** At most one extraction is ever in flight. A request that
  arrives while one runs is *refused*, not queued, so holding ``K`` cannot pile
  up GPU work (plan §4, "Atomic Inference").
- **non-fatal failure.** An engine's exception is caught inside the worker,
  turned into a message and reported. It never escapes into the Qt event loop.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from aimation_actor.core.models import FrameImage
from aimation_actor.ports.ai_port import AIPort

__all__ = ["PoseExtractionRunner"]


def _release(engine: object) -> None:
    """Ask an engine to release its resources, when it offers that hook."""
    shutdown = getattr(engine, "shutdown", None)
    if callable(shutdown):
        shutdown()


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


class PoseExtractionRunner(QObject):
    """Runs one blocking engine off the UI thread and reports the outcome.

    ``extracted`` carries the :class:`WorldPose` **together with the frame it
    belongs to**, so a result that lands after the playhead has moved is still
    written to the frame it was extracted from.
    """

    extracted = Signal(int, object)
    failed = Signal(int, str)
    busy_changed = Signal(bool)

    def __init__(self, engine: AIPort, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._thread: QThread | None = None
        self._job: _ExtractionJob | None = None

    @property
    def busy(self) -> bool:
        """Whether an extraction is currently in flight."""
        return self._thread is not None

    def start(self, frame_index: int, image: FrameImage) -> bool:
        """Extract ``image`` off the UI thread.

        Returns ``False`` without starting anything when an extraction is already
        running (batch size 1, S4).
        """
        if self._thread is not None:
            return False

        job = _ExtractionJob(self._engine, frame_index, image)
        thread = QThread(self)
        job.moveToThread(thread)

        thread.started.connect(job.run)
        # Rebroadcast: the signal crosses back to the receiver's thread (queued)
        # because this object lives where the UI built it.
        job.extracted.connect(self.extracted)
        job.failed.connect(self.failed)
        # Either outcome ends the worker loop.
        job.extracted.connect(thread.quit)
        job.failed.connect(thread.quit)
        thread.finished.connect(self._on_thread_finished)

        # The job must stay referenced until the thread ends: collecting the
        # Python wrapper while its slot is still queued would drop the work.
        self._job = job
        self._thread = thread
        self.busy_changed.emit(True)
        thread.start()
        return True

    def shutdown(self) -> None:
        """Stop the worker and wait for it.

        Called when the capture window closes: a ``QThread`` destroyed while
        still running would abort the process. Waiting blocks, which is
        acceptable exactly once, on teardown.

        The engine's own lifecycle (an out-of-process worker, its checkpoint
        loaded once) ends here too: the runner owns it at teardown because the
        window does not know whether the injected engine keeps processes.
        """
        thread = self._thread
        if thread is None:
            _release(self._engine)
            return
        thread.quit()
        thread.wait()
        _release(self._engine)

    @Slot()
    def _on_thread_finished(self) -> None:
        thread, self._thread = self._thread, None
        self._job = None
        if thread is not None:
            thread.deleteLater()
        self.busy_changed.emit(False)
