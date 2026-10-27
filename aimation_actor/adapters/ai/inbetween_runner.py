"""Off-thread inbetweening: the gap fill runs off the UI thread.

``InbetweeningPort`` is blocking by contract, so the GUI must never call it
directly: a diffusion fill takes seconds to minutes and a call on the UI thread
would freeze the window (NFR-02). This runner is that engine's slice of the
shared batch-1 lifecycle (``thread_runner.ThreadedEngineRunner``) — the same
thread and signal mechanics the capture runner uses, with the whole
``TimelineState`` as both the request and the result, so the two engines behave
predictably alike for whoever wires them.

The result is returned **as a whole**: the port's contract guarantees the keys
came back byte-identical, so there is nothing to attribute per-frame here —
unlike extraction, the playhead's position cannot fling a result onto the wrong
frame.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from aimation_actor.adapters.ai.thread_runner import ThreadedEngineRunner
from aimation_actor.core.models import JointPose, TimelineState
from aimation_actor.ports.ai_port import InbetweeningPort

__all__ = ["InbetweeningRunner"]


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


class InbetweeningRunner(ThreadedEngineRunner):
    """Runs one blocking fill off the UI thread and reports the outcome.

    ``filled`` carries the filled :class:`TimelineState` the engine returned —
    keys untouched, gaps filled — for the window to adopt wholesale.
    """

    filled = Signal(object)
    failed = Signal(str)

    def __init__(self, engine: InbetweeningPort, parent: QObject | None = None) -> None:
        super().__init__(engine, parent)

    def start(
        self,
        timeline: TimelineState,
        guides: dict[int, dict[str, JointPose]] | None = None,
    ) -> bool:
        """Fill ``timeline``'s gaps off the UI thread.

        ``guides`` (S6, optional) ride along: the engine conditions on the
        captured poses between the keys. Returns ``False`` without starting
        anything when a fill is already running (batch size 1).
        """
        job = _InbetweenJob(self._engine, timeline, guides)
        return self._launch(
            job,
            success=job.filled,
            failure=job.failed,
            relay_success=self.filled,
            relay_failure=self.failed,
        )
