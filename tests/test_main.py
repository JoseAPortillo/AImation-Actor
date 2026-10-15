"""Tests for the application entry point (S1, S12).

The event loop itself is a manual check; what is pinned here is that the
production wiring is real and that importing the entry point is safe.
"""

from __future__ import annotations

import importlib

from aimation_actor.adapters.gui.capture_controller import CaptureController
from aimation_actor.adapters.gui.video_player import VideoPlayer
from aimation_actor.main import build_window


def test_the_application_window_uses_the_real_player(qtbot) -> None:
    window = build_window()
    qtbot.addWidget(window)

    assert isinstance(window.controller, CaptureController)
    # The production video pane is the player widget itself, not a placeholder.
    assert isinstance(window.splitter.widget(0), VideoPlayer)


def test_the_application_window_starts_without_a_rig(qtbot) -> None:
    # M4 ships before the production skeleton exists (M5 builds it); the window
    # must run in that state rather than refusing to start (NFR-03).
    window = build_window()
    qtbot.addWidget(window)

    assert window.controller.state.skeleton.joints == ()
    assert "No rig" in window.viewport.notice_label.text()


def test_importing_the_entry_point_does_not_start_the_application() -> None:
    # A top-level `main()` call would start an event loop on import.
    module = importlib.import_module("aimation_actor.main")

    importlib.reload(module)

    assert callable(module.main)
