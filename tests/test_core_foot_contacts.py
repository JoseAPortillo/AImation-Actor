"""Tests for planted-foot detection (M7, FR-IK-01 detection half, S1/S4).

Detection reads the FOOT joints' world positions at the two bounding ORIGINAL
keys of each span and flags a foot planted when both readings sit at ground
contact and agree within the planting tolerance. The thresholds are what
open question 8 was resolved to (2026-10-23, the balanced option: 4.0 cm
between keys, 6.0 cm above the ground).

The rig is a minimal production-shaped leg chain named exactly like the real
one (Hip -> Knee -> Ankle -> Foot under Pelvis), so detection is exercised on
the names and hierarchy it will meet in production. By construction the bind
pose stands flat with both toes resting on the ground: pelvis z = 100, thigh
40, shank 40, and the toe ball (``L_Foot``) settles at z = 0.

Swing and drift poses come from real joint rotations (body joints carry
rotation only in the domain), not from invented translations: a 45-degree
hip pitch lifts the left toe to z ~ 40, and a 2-degree pelvis pitch drifts
both toes ~ 3.5 cm horizontally — inside the 4.0 cm threshold.
"""

from __future__ import annotations

import pytest
from fbx_helpers import rotation_x

from aimation_actor.core.foot_contacts import (
    GROUND_CONTACT_HEIGHT_CM,
    PLANT_POSITION_TOLERANCE_CM,
    contact_spans,
)
from aimation_actor.core.models import (
    JointData,
    JointPose,
    Keyframe,
    Quaternion,
    Skeleton,
    TimelineState,
    Vector3,
)

_BIND_HIP = 100.0
_THIGH = 40.0
_SHANK = 40.0
_FOOT_BALL = 15.0
_TOE_DROP = 20.0
_TOE = Vector3(y=_FOOT_BALL, z=-_TOE_DROP)  # the toe: 15 ahead, its 20-drop lands it on z=0


def _skeleton() -> Skeleton:
    return Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main", rest_translation=Vector3(z=_BIND_HIP)),
            JointData(name="L_Hip", parent="Pelvis", rest_translation=Vector3(x=-10.0)),
            JointData(name="L_Knee", parent="L_Hip", rest_translation=Vector3(z=-_THIGH)),
            JointData(name="L_Ankle", parent="L_Knee", rest_translation=Vector3(z=-_SHANK)),
            JointData(name="L_Foot", parent="L_Ankle", rest_translation=_TOE),
            JointData(name="R_Hip", parent="Pelvis", rest_translation=Vector3(x=10.0)),
            JointData(name="R_Knee", parent="R_Hip", rest_translation=Vector3(z=-_THIGH)),
            JointData(name="R_Ankle", parent="R_Knee", rest_translation=Vector3(z=-_SHANK)),
            JointData(name="R_Foot", parent="R_Ankle", rest_translation=_TOE),
        )
    )


def _pose(**overrides: JointPose) -> dict[str, JointPose]:
    """A full pose at the bind, with per-joint rotations as given."""
    return {
        joint.name: overrides.get(joint.name, JointPose(rotation=Quaternion.identity()))
        for joint in _skeleton().joints
    }


def _timeline(*keyframes: Keyframe) -> TimelineState:
    return TimelineState(
        skeleton=_skeleton(),
        keyframes=keyframes,
        frame_start=0,
        frame_end=max(keyframe.frame for keyframe in keyframes),
    )


def _key(frame: int, pose: dict[str, JointPose]) -> Keyframe:
    return Keyframe(frame=frame, pose=pose)


def _stand() -> dict[str, JointPose]:
    """Standing flat: both toes resting on z=0, everything at bind."""
    return _pose()


def test_a_foot_planted_across_a_span_is_reported() -> None:
    """Both bounding keys hold the foot on the ground and in place: planted."""
    state = _timeline(_key(46, _stand()), _key(71, _stand()))

    spans = contact_spans(state, (46, 71))

    assert spans == {(46, 71): {"L_Foot", "R_Foot"}}


def test_a_foot_that_moves_beyond_the_tolerance_is_not_planted() -> None:
    """A 45-degree hip pitch swings the left toe far away and off the ground."""
    state = _timeline(
        _key(46, _stand()),
        _key(71, _pose(L_Hip=JointPose(rotation=rotation_x(45.0)))),
    )

    spans = contact_spans(state, (46, 71))

    assert spans == {(46, 71): {"R_Foot"}}


def test_a_foot_off_the_ground_at_either_key_is_not_planted() -> None:
    """Ground contact at BOTH bounding keys is required, not either one."""
    floating = _pose(
        Pelvis=JointPose(rotation=rotation_x(45.0)),
        L_Hip=JointPose(rotation=rotation_x(45.0)),
    )
    state = _timeline(_key(46, _stand()), _key(71, floating))

    spans = contact_spans(state, (46, 71))

    assert spans == {(46, 71): set()}


def test_a_foot_floating_constant_is_not_planted() -> None:
    """Same position but high above the ground: never a contact."""
    floating = _pose(
        Pelvis=JointPose(rotation=rotation_x(45.0)),
        L_Hip=JointPose(rotation=rotation_x(45.0)),
    )
    state = _timeline(_key(46, floating), _key(71, floating))

    spans = contact_spans(state, (46, 71))

    assert spans == {(46, 71): set()}


def test_a_foot_penetrating_the_ground_still_counts_as_planted() -> None:
    """A foot below the ground plane is a contact too (the pin pass fixes it).

    The pelvis rides 40 cm below its bind (a crouch the capture miss-estimates:
    `Pelvis` carries the height offset), so both toes sit at z = -40: below
    the ground, still planted.
    """
    penetrating = _pose(
        Pelvis=JointPose(rotation=Quaternion.identity(), translation=Vector3(z=-40.0))
    )
    state = _timeline(_key(46, penetrating), _key(71, penetrating))

    spans = contact_spans(state, (46, 71))

    assert spans == {(46, 71): {"L_Foot", "R_Foot"}}


def test_drift_within_the_tolerance_stays_planted() -> None:
    """The measured capture noise (~3-6 cm per frame) stays inside 4.0 cm.

    A 2-degree pelvis pitch drifts the 100 cm leg chain's toe ~ 3.5 cm
    horizontally while keeping it at ground height: still planted.
    """
    noisy = _pose(Pelvis=JointPose(rotation=rotation_x(2.0)))
    state = _timeline(_key(46, noisy), _key(71, noisy))

    spans = contact_spans(state, (46, 71))

    assert spans == {(46, 71): {"L_Foot", "R_Foot"}}


def test_a_footless_gap_is_not_reported() -> None:
    """Adjacent original keys share no interior: no spans, no contacts."""
    state = _timeline(_key(46, _stand()), _key(47, _stand()))

    assert contact_spans(state, (46, 47)) == {}


def test_the_thresholds_match_open_question_8() -> None:
    """The balanced option (2026-10-23): 4.0 cm between keys, 6.0 cm ground."""
    assert (PLANT_POSITION_TOLERANCE_CM, GROUND_CONTACT_HEIGHT_CM) == (4.0, 6.0)


def test_detection_does_not_mutate_the_timeline() -> None:
    state = _timeline(_key(46, _stand()), _key(71, _stand()))
    before = state.keyframes

    contact_spans(state, (46, 71))

    assert state.keyframes == before


def test_a_missing_key_report_is_a_value_error() -> None:
    """An original key that the timeline does not carry is a caller bug."""
    state = _timeline(_key(46, _stand()), _key(71, _stand()))

    with pytest.raises(ValueError):
        contact_spans(state, (46, 72))


def test_single_original_key_has_no_span_to_compare() -> None:
    """One original key gives no span: detection reports nothing (no crash)."""
    state = _timeline(_key(46, _stand()), _key(71, _stand()))

    assert contact_spans(state, (46,)) == {}
