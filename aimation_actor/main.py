"""Application entry point for AImation Actor.

The entry point stays thin on purpose: it creates the Qt application, builds the
window and hands control to the event loop. Everything the capture surface does
lives behind ``MainWindow`` and its controller, so this module is not a place
where behavior can hide.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from aimation_actor.adapters.ai.hmr2_adapter import Hmr2Adapter
from aimation_actor.adapters.gui.main_window import MainWindow
from aimation_actor.core.production_skeleton import production_skeleton

__all__ = ["build_window", "main"]


def build_window() -> MainWindow:
    """The application's window: real player, real engine, real production rig.

    The rig is still not invented here (the M4 refusal stands): its bind offsets
    are real body-model data the engine reports with its ready line, so the
    window adopts the rig at the first successful extraction through the
    ``skeleton_source``. Until then the 3D pane names the reason it is blank.
    """
    engine = Hmr2Adapter()
    return MainWindow(engine=engine, skeleton_source=_engine_rig_of(engine))


def _engine_rig_of(engine: Hmr2Adapter):
    """Where the window's rig comes from: the engine's own template report."""
    def rig():
        offsets = engine.bind_offsets()
        if offsets is None:
            return None
        return production_skeleton(offsets)

    rig.__doc__ = "Build the production skeleton from the engine's bind offsets."
    return rig


def main(argv: list[str] | None = None) -> int:
    """Run the capture application and return its exit code."""
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("AImation Actor")
    window = build_window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
