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


def test_frame_changes_push_the_controller_snapshot_onto_the_overlay(qtbot) -> None:
    # pose-video-overlay T3: the playhead's frame selects the held capture and
    # the window hands it to the overlay over the video pane.
    window = build_window()
    qtbot.addWidget(window)

    snapshot = (((),), ())
    window.controller.overlay_snapshot_at = lambda frame: snapshot
    window.controller.frame_changed.emit(15)

    assert window._video_overlay.snapshot is snapshot


def test_reloading_media_clears_the_overlay(qtbot) -> None:
    window = build_window()
    qtbot.addWidget(window)

    window._video_overlay.set_snapshot((((),), ()))
    window.controller.media_changed.emit()

    assert window._video_overlay.snapshot is None


def test_the_application_window_starts_without_a_rig(qtbot) -> None:
    # M4 ships before the production skeleton exists (M5 builds it); the window
    # must run in that state rather than refusing to start (NFR-03).
    window = build_window()
    qtbot.addWidget(window)

    assert window.controller.state.skeleton.joints == ()
    assert "No rig" in window.viewport.notice_label.text()


def test_the_old_3d_viewport_is_hidden_until_the_overlay_proves_out(qtbot) -> None:
    # S5: the video overlay replaces the pane for now; the viewport's code
    # stays untouched for its later re-enable.
    window = build_window()
    qtbot.addWidget(window)

    assert window.viewport.isHidden()
    assert window.splitter.widget(1) is window.viewport  # still composed, just hidden


def test_the_application_window_ships_the_real_fbx_writer(qtbot) -> None:
    # M8 final export (FR-GEN-04): the production composition wires the real
    # Blender-backed FBX adapter behind the export action.
    from PySide6.QtGui import QKeySequence

    from aimation_actor.adapters.io.fbx_adapter import BlenderFbxAdapter

    window = build_window()
    qtbot.addWidget(window)

    assert isinstance(window.exporter, BlenderFbxAdapter)
    assert window.action_export.shortcut() == QKeySequence("Ctrl+E")


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


def test_the_window_wires_both_factory_engines(qtbot) -> None:
    """FR-GEN-02: the window asks the Model Factory by name, for both engines.

    Both engines are lazy (a construction spawns nothing), so the window opens
    without weights, GPU or workers (T1).
    """
    from aimation_actor.adapters.ai.condmdi_adapter import CondMDIAdapter
    from aimation_actor.adapters.ai.hmr2_adapter import Hmr2Adapter
    from aimation_actor.adapters.ai.inbetween_runner import InbetweeningRunner

    window = build_window()
    qtbot.addWidget(window)

    assert isinstance(window.extractor._engine, Hmr2Adapter)
    assert isinstance(window.filler, InbetweeningRunner)
    assert isinstance(window.filler._engine, CondMDIAdapter)
    window.close()  # both runners shut down idempotently here


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
