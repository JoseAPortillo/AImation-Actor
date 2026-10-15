"""Application entry point for AImation Actor.

The entry point stays thin on purpose: it creates the Qt application, builds the
window and hands control to the event loop. Everything the capture surface does
lives behind ``MainWindow`` and its controller, so this module is not a place
where behavior can hide.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from aimation_actor.adapters.gui.main_window import MainWindow

__all__ = ["build_window", "main"]


def build_window() -> MainWindow:
    """The application's window, wired to the real video player.

    The rig is deliberately left empty. The production skeleton arrives with the
    GVHMR pipeline (M5); inventing one here would put invented joint data behind
    the production mapping, which is worse than an honest empty pane. Until then
    the 3D pane names the reason it is blank.
    """
    return MainWindow()


def main(argv: list[str] | None = None) -> int:
    """Run the capture application and return its exit code."""
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("AImation Actor")
    window = build_window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
