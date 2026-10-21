"""Off-thread inbetweening: the gap fill runs off the UI thread.

``InbetweeningPort`` is blocking by contract, so the GUI must never call it
directly: a diffusion fill takes seconds to minutes and a call on the UI thread
would freeze the window (NFR-02). This runner mirrors the capture engine's
``PoseExtractionRunner`` — the same thread and signal lifecycle, with the whole
``TimelineState`` as both the request and the result — so the two engines behave
predictably alike for whoever wires them.

Two rules it enforces by construction (the same two the pose runner enforces):

- **batch size 1.** At most one fill is ever in flight. A request that arrives
  while one runs is *refused*, not queued, so repeated shortcuts cannot pile up
  GPU work (FR-GEN-02's isolation).
- **non-fatal failure.** An engine's exception is caught inside the worker,
  turned into a message and reported (FR-GEN-03). It never escapes into the Qt
  event loop, and the timeline's keys survive untouched (S1).

The result is returned **as a whole**: the port's contract guarantees the keys
came back byte-identical, so there is nothing to attribute per-frame here —
unlike extraction, the playhead's position cannot fling a result onto the wrong
frame.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from aimation_actor.core.models import JointPose, TimelineState
from aimation_actor.ports.ai_port import InbetweeningPort

__all__ = ["InbetweeningRunner"]


def _release(engine: object) -> None:
    """Ask an engine to release its resources, when it offers that hook."""
    shutdown = getattr(engine, "shutdown", None)
    if callable(shutdown):
        shutdown()


class _InbetweenJob(QObject):
    """One fill, living on the worker thread until it finishes."""

    filled = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        engine: InbetweeningPort,
        timeline: TimelineState,
        guides: dict[int, dict[str, JointPose]] | None = None,
    ) -> None:
        super().__init__()
        self._engine = engine
        self._timeline = timeline
        self._guides = guides

    @Slot()
    def run(self) -> None:
        try:
            filled = self._engine.inbetween(self._timeline, guides=self._guides)
        except Exception as error:  # an engine failure is non-fatal (FR-GEN-03)
            # ``str`` of a bare exception can be empty; the type always names it.
            self.failed.emit(str(error) or type(error).__name__)
            return
        self.filled.emit(filled)


class InbetweeningRunner(QObject):
    """Runs one blocking fill off the UI thread and reports the outcome.

    ``filled`` carries the filled :class:`TimelineState` the engine returned —
    keys untouched, gaps filled — for the window to adopt wholesale.
    """

    filled = Signal(object)
    failed = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, engine: InbetweeningPort, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._thread: QThread | None = None
        self._job: _InbetweenJob | None = None

    @property
    def busy(self) -> bool:
        """Whether a fill is currently in flight."""
        return self._thread is not None

    def start(
        self,
        timeline: TimelineState,
        guides: dict[int, dict[str, JointPose]] | None = None,
    ) -> bool:
        """Fill ``timeline``'s gaps off the UI thread.

        ``guides`` (S6, optional) rides along: the engine conditions on the
        captured poses between the keys. Returns ``False`` without starting
        anything when a fill is already running (batch size 1).
        """
        if self._thread is not None:
            return False

        job = _InbetweenJob(self._engine, timeline, guides)
        thread = QThread(self)
        job.moveToThread(thread)

        thread.started.connect(job.run)
        # Rebroadcast: the signal crosses back to the receiver's thread (queued)
        # because this object lives where the UI built it.
        job.filled.connect(self.filled)
        job.failed.connect(self.failed)
        # Either outcome ends the worker loop.
        job.filled.connect(thread.quit)
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

        Called when the window closes: a ``QThread`` destroyed while still
        running would abort the process. Waiting blocks, which is acceptable
        exactly once, on teardown.

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
