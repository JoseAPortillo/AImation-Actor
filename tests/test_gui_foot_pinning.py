"""Tests for the controller-side pin wiring (M7 T3, FR-IK-01, S1/S3).

The pin pass is pure domain math (``core/foot_ik.py``); the controller owns the
one thing it cannot know: WHICH frames were the pre-fill human keys. These
tests pin the wiring contract: the fill is adopted corrected (planted contacts
hold their position), a skeleton without complete leg chains degrades the
pinning without failing the fill, and a fill with no planted contacts reports
plain generation like M6 did.
"""

from __future__ import annotations

import pytest
from fbx_helpers import rotation_x
from PySide6.QtCore import QObject, Signal

from aimation_actor.adapters.gui.capture_controller import CaptureController
from aimation_actor.core.foot_ik import POST_PIN_HOLD_CM
from aimation_actor.core.kinematics import joint_world_positions
from aimation_actor.core.models import (
    JointData,
    JointPose,
    Keyframe,
    Quaternion,
    Skeleton,
    TimelineState,
    Vector3,
)

_TOE = Vector3(y=15.0, z=-20.0)


# -- fakes (mirroring test_gui_inbetweening.py's seams) --------------------- #


class _FakeSource(QObject):  # unused by fills; the controller accepts both engines
    media_loaded = Signal(float, int)
    position_changed = Signal(int)
    frame_shown = Signal(int)
    playback_changed = Signal(bool)
    failed = Signal(str)

    def pause(self) -> None: ...


class _FakeInbetweener(QObject):
    """The inbetweening seam: records the request; the test scripts the outcome."""

    filled = Signal(object)
    failed = Signal(str)

    def __init__(self, result: TimelineState | None = None) -> None:
        super().__init__()
        self.requests: list[TimelineState] = []
        self.result = result

    def start(
        self, timeline: TimelineState, guides: dict[int, dict[str, JointPose]] | None = None
    ) -> bool:
        self.requests.append(timeline)
        return True


# -- rigs and states -------------------------------------------------------- #


def _leg_skeleton() -> Skeleton:
    return Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main", rest_translation=Vector3(z=100.0)),
            JointData(name="L_Hip", parent="Pelvis", rest_translation=Vector3(x=-10.0)),
            JointData(name="L_Knee", parent="L_Hip", rest_translation=Vector3(z=-40.0)),
            JointData(name="L_Ankle", parent="L_Knee", rest_translation=Vector3(z=-40.0)),
            JointData(name="L_Foot", parent="L_Ankle", rest_translation=_TOE),
            JointData(name="R_Hip", parent="Pelvis", rest_translation=Vector3(x=10.0)),
            JointData(name="R_Knee", parent="R_Hip", rest_translation=Vector3(z=-40.0)),
            JointData(name="R_Ankle", parent="R_Knee", rest_translation=Vector3(z=-40.0)),
            JointData(name="R_Foot", parent="R_Ankle", rest_translation=_TOE),
        )
    )


def _sparse_skeleton() -> Skeleton:
    """A rig with no legs at all (like the M6 tests'): pinning must degrade."""
    return Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main"),
        )
    )


def _pose(skeleton: Skeleton, **overrides: JointPose) -> dict[str, JointPose]:
    """A full pose at the rig's bind, with per-joint rotations as given."""
    return {
        joint.name: overrides.get(joint.name, JointPose(rotation=Quaternion.identity()))
        for joint in skeleton.joints
    }


def _drifted(skeleton: Skeleton) -> dict[str, JointPose]:
    """A generated row that drifted: a small pelvis pitch the pin must fix."""
    return _pose(skeleton, Pelvis=JointPose(rotation=rotation_x(2.0)))


def _dense(
    skeleton: Skeleton, drifted: dict[str, JointPose], *, left: int = 46, right: int = 71
) -> TimelineState:
    """A post-fill shape: standing keys at both ends, generated rows between."""
    keyframes = [Keyframe(frame=left, pose=_pose(skeleton))]
    for frame in range(left + 1, right):
        keyframes.append(
            Keyframe(
                frame=frame,
                pose=dict(drifted) if frame % 5 == 0 else _pose(skeleton),
            )
        )
    keyframes.append(Keyframe(frame=right, pose=_pose(skeleton)))
    return TimelineState(
        skeleton=skeleton,
        keyframes=tuple(keyframes),
        fps=24.0,
        frame_start=0,
        frame_end=right,
    )


def _keys_only(skeleton: Skeleton, left: int, right: int, pose=None) -> TimelineState:
    """The pre-fill request state: exactly the two golden poses."""
    poses = pose or (_pose(skeleton), _pose(skeleton))
    return TimelineState(
        skeleton=skeleton,
        keyframes=(
            Keyframe(frame=left, pose=poses[0]),
            Keyframe(frame=right, pose=poses[1]),
        ),
        fps=24.0,
        frame_start=0,
        frame_end=right,
    )


def _toe(state: TimelineState, frame: int, name: str) -> Vector3:
    pose = next(k.pose for k in state.keyframes if k.frame == frame)
    return joint_world_positions(state.skeleton, pose)[name]


# -- fixtures --------------------------------------------------------------- #


@pytest.fixture
def source() -> _FakeSource:
    return _FakeSource()


# -- the adopt path --------------------------------------------------------- #


def test_a_fill_is_adopted_with_its_planted_contacts_pinned(
    qtbot, source: _FakeSource
) -> None:
    skeleton = _leg_skeleton()
    filled = _dense(skeleton, _drifted(skeleton))
    filler = _FakeInbetweener(result=filled)
    controller = CaptureController(
        source,
        _keys_only(skeleton, 46, 71),
        inbetweener=filler,
    )
    statuses: list[str] = []
    controller.status_changed.connect(statuses.append)
    keys_before = dict(controller.state.keyframes[0].pose)

    controller.fill_inbetweens()
    filler.filled.emit(filler.result)  # synchronous fake runner

    for foot in ("L_Foot", "R_Foot"):
        held = _toe(filled, 46, foot)  # the first key's contact
        pin = _toe(controller.state, 55, foot)
        assert (pin.x, pin.y, pin.z) == pytest.approx(
            (held.x, held.y, held.z), abs=POST_PIN_HOLD_CM
        )
    assert any("pinned" in message.lower() for message in statuses)
    # The keys survive the pass byte-untouched (S1 pattern).
    assert controller.state.keyframes[0].pose == keys_before


def test_a_fill_without_leg_chains_is_adopted_unpinned(
    qtbot, source: _FakeSource
) -> None:
    skeleton = _sparse_skeleton()
    filled = TimelineState(
        skeleton=skeleton,
        keyframes=tuple(
            Keyframe(frame=frame, pose=_pose(skeleton)) for frame in range(1, 11)
        ),
        fps=24.0,
        frame_start=1,
        frame_end=10,
    )
    filler = _FakeInbetweener(result=filled)
    controller = CaptureController(
        source, _keys_only(skeleton, 1, 10), inbetweener=filler
    )
    failures: list[str] = []
    controller.failed.connect(failures.append)
    statuses: list[str] = []
    controller.status_changed.connect(statuses.append)

    controller.fill_inbetweens()
    filler.filled.emit(filler.result)

    # The fill itself survives: adopted wholesale, pinning silently degraded.
    assert [k.frame for k in controller.state.keyframes] == list(range(1, 11))
    assert failures == []
    assert any("pinning skipped" in message for message in statuses)
    assert not any("pinned" in message for message in statuses)


def test_a_fill_without_planted_contacts_reports_plain_generation(
    qtbot, source: _FakeSource
) -> None:
    skeleton = _leg_skeleton()
    swing = _pose(
        skeleton,
        L_Hip=JointPose(rotation=rotation_x(45.0)),
        R_Hip=JointPose(rotation=rotation_x(-45.0)),
    )
    filled = _dense(skeleton, swing)
    filler = _FakeInbetweener(result=filled)
    controller = CaptureController(
        source, _keys_only(skeleton, 46, 71, pose=(swing, swing)), inbetweener=filler
    )
    statuses: list[str] = []
    controller.status_changed.connect(statuses.append)

    controller.fill_inbetweens()
    filler.filled.emit(filler.result)

    assert any("Generated" in message for message in statuses)
    assert not any("pinned" in message for message in statuses)
