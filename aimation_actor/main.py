"""Application entry point for AImation Actor.

The entry point stays thin on purpose: it creates the Qt application, builds the
window and hands control to the event loop. Everything the capture surface does
lives behind ``MainWindow`` and its controller, so this module is not a place
where behavior can hide.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication

from aimation_actor.adapters.ai.model_factory import capture_engine, inbetweening_engine
from aimation_actor.adapters.gui.main_window import MainWindow
from aimation_actor.adapters.io.fbx_adapter import BlenderFbxAdapter
from aimation_actor.core.production_skeleton import production_skeleton

if TYPE_CHECKING:
    from aimation_actor.adapters.ai.hmr2_adapter import Hmr2Adapter

__all__ = ["build_window", "main"]


def build_window() -> MainWindow:
    """The application's window: real player, real engines, real production rig.

    The engines are named, not imported: the Model Factory builds the capture
    engine (``hmr2``) and the inbetweening engine (its MVP default ``condmdi``,
    FR-GEN-02), so swapping one is a registry edit. The rig is still not
    invented here (the M4 refusal stands): its bind offsets are real body-model
    data the capture engine reports with its ready line, so the window adopts
    the rig at the first successful extraction through the ``skeleton_source``.
    Until then the 3D pane names the reason it is blank.
    """
    engine = capture_engine("hmr2")
    inbetween_engine = inbetweening_engine()  # MVP: condmdi (FR-GEN-02)
    return MainWindow(
        engine=engine,
        inbetween_engine=inbetween_engine,
        skeleton_source=_engine_rig_of(engine),
        exporter=BlenderFbxAdapter(),  # final generative export (FR-GEN-04)
    )


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
