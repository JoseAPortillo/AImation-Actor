"""The shared batch-1 QThread lifecycle of the two AI runners (R4).

Both ports are blocking by contract, so the GUI must never call them
directly: a pose inference or a diffusion fill would freeze the window
(NFR-02). ``PoseExtractionRunner`` and ``InbetweeningRunner`` each keep
one engine call off the UI thread with the same thread and signal
lifecycle — until this extraction the lifecycles were near-mirror copies
(spec.md's parked after-MVP refactor: "the two runners are near-mirrors —
one shared worker-bridge/runner extraction"). This base owns the
mechanics; the concrete runners keep their typed ``start(...)``, their
jobs and their outcome signals, so whoever wires them sees exactly the
public surface pinned by their test suites.

Two rules the base enforces by construction (the same two the concrete
runners enforced before the extraction):

- **batch size 1.** At most one engine call is ever in flight. A request
  that arrives while one runs is *refused*, not queued, so holding ``K``
  or repeating the fill shortcut cannot pile up GPU work (plan §4,
  "Atomic Inference", FR-CAP-05/FR-GEN-02's isolation).
- **non-fatal failure.** The job catches the engine's exception inside
  the worker thread and reports it through the failure signal; nothing
  escapes into the Qt event loop (FR-CAP-07, FR-GEN-03).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

__all__ = ["ThreadedEngineRunner"]


def _release(engine: object) -> None:
    """Ask an engine to release its resources, when it offers that hook."""
    shutdown = getattr(engine, "shutdown", None)
    if callable(shutdown):
        shutdown()


class ThreadedEngineRunner(QObject):
    """One blocking engine call at a time, off the UI thread.

    Subclasses define their outcome signals and build their job; the
    base owns the thread's wiring, the busy state and the teardown.
    """

    busy_changed = Signal(bool)

    def __init__(self, engine: object, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._thread: QThread | None = None
        self._job: QObject | None = None

    @property
    def busy(self) -> bool:
        """Whether an engine call is currently in flight."""
        return self._thread is not None

    def _launch(
        self,
        job: QObject,
        *,
        success: Signal,
        failure: Signal,
        relay_success: Signal,
        relay_failure: Signal,
    ) -> bool:
        """Run ``job`` on its own thread, refusing to overlap (batch 1).

        ``success``/``failure`` are the job's outcome signals; they are
        rebroadcast through ``relay_success``/``relay_failure`` (the
        runner's own signals) so the payload crosses back to the
        receiver's thread (queued), because this object lives where the
        UI built it. Either outcome ends the worker loop. Returns
        ``False`` without starting anything when a call is already in
        flight.
        """
        if self._thread is not None:
            return False

        thread = QThread(self)
        job.moveToThread(thread)

        thread.started.connect(job.run)
        success.connect(relay_success)
        failure.connect(relay_failure)
        success.connect(thread.quit)
        failure.connect(thread.quit)
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

        Called when the capture window closes: a ``QThread`` destroyed
        while still running would abort the process. Waiting blocks,
        which is acceptable exactly once, on teardown.

        The engine's own lifecycle (an out-of-process worker, its
        checkpoint loaded once) ends here too: the runner owns it at
        teardown because the window does not know whether the injected
        engine keeps processes.
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
