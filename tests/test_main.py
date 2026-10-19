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


def test_the_application_window_runs_the_real_engine_behind_the_real_rig_source(qtbot) -> None:
    from aimation_actor.adapters.ai.hmr2_adapter import Hmr2Adapter
    from aimation_actor.adapters.ai.pose_runner import PoseExtractionRunner

    window = build_window()
    qtbot.addWidget(window)

    assert isinstance(window.extractor, PoseExtractionRunner)
    assert isinstance(window.extractor._engine, Hmr2Adapter)
    # the rig source is wired to the engine's own template report: honest None
    # until the worker reports ready — never an invented rig (T13, S16)
    assert callable(window.controller._skeleton_source)
    assert window.controller._skeleton_source() is None
    window.close()  # the runner's shutdown is an idempotent no-op here


def test_the_real_adapter_construction_spawns_nothing(qtbot) -> None:
    """Ready costs a spawn, not construction: the window opens without the engine."""
    import os as _os

    from aimation_actor.adapters.ai.hmr2_adapter import Hmr2Adapter

    engine = Hmr2Adapter()
    assert engine.bind_offsets() is None  # no worker, no spawn, no ready line
    assert not _os.path.exists(getattr(engine, "_worker", None) or "")


def test_a_rig_source_from_engine_offsets_builds_the_production_skeleton(qtbot) -> None:
    from aimation_actor import main as entry
    from aimation_actor.core.models import Vector3
    from aimation_actor.core.production_skeleton import (
        PRODUCTION_BODY_JOINT_NAMES,
    )

    class _ReadyEngine:
        def bind_offsets(self):
            return {
                "Pelvis": Vector3(x=-0.18, y=-2.822, z=93.851),
                **{name: Vector3(x=1.0, y=0.0, z=-1.0) for name in PRODUCTION_BODY_JOINT_NAMES},
            }

    rig = entry._engine_rig_of(_ReadyEngine())()
    assert rig is not None and rig.names()[0] == "Main" and rig.names()[1] == "Pelvis"
