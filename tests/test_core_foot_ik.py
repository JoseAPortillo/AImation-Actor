"""Tests for the analytic foot-IK pin pass (M7, FR-IK-01, S1/S2/S3/S4).

The pass corrects every non-original frame of a detected contact span: it
rotates hip and knee (analytic two-bone), smooths generated-row ankle roll
across the contact run, lifts penetrating targets, lowers the pelvis only when
both feet must be solved, and never touches the original keys.
The same minimal leg rig as ``test_core_foot_contacts.py`` stands in for the
production skeleton, since the pass is name-driven.

The pin target is the FOOT (toe ball) - the contact point detection reads -
landed at the first key's world contact position ("post-pin hold": within
POST_PIN_HOLD_CM of it, exactly z=0 on the ground for a penetration lift).
Reach follows the leg chain: thigh 40 + shank 40 + toe-offset 25 = 105 cm
of total reach from each hip joint.
"""

from __future__ import annotations

import pytest
from fbx_helpers import rotation_x

from aimation_actor.core.foot_ik import POST_PIN_HOLD_CM, PinReport, pin_foot_contacts
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

_BIND_HIP = 100.0
_TOE = Vector3(y=15.0, z=-20.0)


def _skeleton() -> Skeleton:
    return Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main", rest_translation=Vector3(z=_BIND_HIP)),
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


def _pose(**overrides: JointPose) -> dict[str, JointPose]:
    """A full pose at the bind, with per-joint rotations as given."""
    return {
        joint.name: overrides.get(joint.name, JointPose(rotation=Quaternion.identity()))
        for joint in _skeleton().joints
    }


def _state(keyframes: list[Keyframe]) -> TimelineState:
    return TimelineState(
        skeleton=_skeleton(),
        keyframes=tuple(keyframes),
        frame_start=0,
        frame_end=max(keyframe.frame for keyframe in keyframes),
    )


def _key(frame: int, pose: dict[str, JointPose]) -> Keyframe:
    return Keyframe(frame=frame, pose=pose)


def _stand() -> dict[str, JointPose]:
    """Standing flat: both toes resting on z=0, everything at bind."""
    return _pose()


def _pose_at(pin: TimelineState, frame: int) -> dict[str, JointPose]:
    return next(keyframe.pose for keyframe in pin.keyframes if keyframe.frame == frame)


def _toe(pin: TimelineState, frame: int, name: str) -> Vector3:
    return joint_world_positions(pin.skeleton, _pose_at(pin, frame))[name]


def _dense(
    drifted: dict[str, JointPose] | None = None, *, left_key: int = 46, right_key: int = 71
) -> TimelineState:
    """A post-fill shape: human keys at both ends, generated frames between.

    The drifted frame (a generated row) stands at the bind by default with a
    tiny pelvis pitch: it contains a rotation the pass has no right to keep
    once the pin runs, and it is clearly not a byte-copy of either key.
    """
    if drifted is None:
        drifted = _pose(Pelvis=JointPose(rotation=rotation_x(2.0)))
    keyframes = [_key(left_key, _stand())]
    for frame in range(left_key + 1, right_key):
        keyframes.append(_key(frame, drifted))
    keyframes.append(_key(right_key, _stand()))
    return _state(keyframes)


# --------------------------------------------------------------------------- #
# The pinned contract
# --------------------------------------------------------------------------- #


def test_pin_lands_every_interior_toe_on_the_first_keys_contact() -> None:
    state = _dense()
    before = joint_world_positions(state.skeleton, next(
        keyframe.pose for keyframe in state.keyframes if keyframe.frame == 46
    ))["L_Foot"]

    pinned, _report = pin_foot_contacts(state, (46, 71))

    for frame in range(47, 71):
        toe = _toe(pinned, frame, "L_Foot")
        assert (toe.x, toe.y, toe.z) == pytest.approx(
            (before.x, before.y, before.z), abs=POST_PIN_HOLD_CM
        )


def test_pin_uses_one_stable_target_across_a_noisy_contact_run() -> None:
    """Consecutive planted keys must not make the pinned target walk."""
    key_positions = (0.0, 2.0, 4.0, 6.0)
    key_poses = [
        _pose(Main=JointPose(rotation=Quaternion.identity(), translation=Vector3(x=x)))
        for x in key_positions
    ]
    keyframes = []
    for index, frame in enumerate((0, 2, 4, 6)):
        keyframes.append(_key(frame, key_poses[index]))
    for frame in (1, 3, 5):
        keyframes.append(_key(frame, _stand()))
    state = _state(sorted(keyframes, key=lambda keyframe: keyframe.frame))

    pinned, report = pin_foot_contacts(state, (0, 2, 4, 6))

    assert report.spans_pinned == ((0, 2), (2, 4), (4, 6))
    for frame in (1, 3, 5):
        toe = _toe(pinned, frame, "L_Foot")
        assert toe.x == pytest.approx(-7.0, abs=1e-6)


def test_pin_uses_one_stable_knee_pole_across_noisy_generated_rows() -> None:
    """Generated-row knee noise must not change the planted foot orientation."""
    poses = {
        0: _stand(),
        1: _pose(L_Hip=JointPose(rotation=rotation_x(3.0))),
        2: _pose(L_Hip=JointPose(rotation=rotation_x(-3.0))),
        3: _pose(L_Hip=JointPose(rotation=rotation_x(2.0))),
        4: _stand(),
    }
    state = _state([_key(frame, pose) for frame, pose in poses.items()])

    pinned, _report = pin_foot_contacts(state, (0, 4))

    interior = [_pose_at(pinned, frame) for frame in (1, 2, 3)]
    assert interior[0]["L_Hip"].rotation == interior[1]["L_Hip"].rotation
    assert interior[1]["L_Hip"].rotation == interior[2]["L_Hip"].rotation
    assert interior[0]["L_Knee"].rotation == interior[1]["L_Knee"].rotation


def test_pin_uses_one_stable_ankle_roll_across_noisy_generated_rows() -> None:
    """Planted contact rows use one stable foot-roll orientation."""
    poses = {
        0: _stand(),
        1: _pose(
            L_Ankle=JointPose(rotation=rotation_x(3.0)),
            L_Foot=JointPose(rotation=rotation_x(4.0)),
        ),
        2: _pose(
            L_Ankle=JointPose(rotation=rotation_x(-3.0)),
            L_Foot=JointPose(rotation=rotation_x(-4.0)),
        ),
        3: _pose(
            L_Ankle=JointPose(rotation=rotation_x(2.0)),
            L_Foot=JointPose(rotation=rotation_x(3.0)),
        ),
        4: _stand(),
    }
    state = _state([_key(frame, pose) for frame, pose in poses.items()])

    pinned, _report = pin_foot_contacts(state, (0, 4))

    interior = [_pose_at(pinned, frame) for frame in (1, 2, 3)]
    assert interior[0]["L_Ankle"].rotation == interior[1]["L_Ankle"].rotation
    assert interior[1]["L_Ankle"].rotation == interior[2]["L_Ankle"].rotation
    assert interior[0]["L_Foot"].rotation == interior[1]["L_Foot"].rotation
    assert interior[1]["L_Foot"].rotation == interior[2]["L_Foot"].rotation


def test_pin_keeps_the_original_keys_byte_identical() -> None:
    state = _dense()
    keys_before = [keyframe for keyframe in state.keyframes if keyframe.frame in (46, 71)]

    pinned, _report = pin_foot_contacts(state, (46, 71))

    keys_after = [keyframe for keyframe in pinned.keyframes if keyframe.frame in (46, 71)]
    assert keys_after == keys_before


def test_pin_smooths_generated_ankle_roll_but_keeps_keys_untouched() -> None:
    drift_ankle = JointPose(rotation=rotation_x(7.0))
    state = _dense(_pose(L_Ankle=drift_ankle))

    pinned, _report = pin_foot_contacts(state, (46, 71))

    after = _pose_at(pinned, 55)
    assert after["L_Ankle"].rotation == Quaternion.identity()


def test_pin_lifts_a_penetrating_span_and_lands_the_toe_on_ground() -> None:
    """A crouch the capture mis-estimates: the KEYS read toes at z=-40.

    The target is the first key's toe LIFTED to the ground plane (the pass's
    penetration correction): x/y stay at the key's contact, z lands exactly
    0. Generated-row ankle roll is smoothed from the original contact run;
    the effective-shin solve still places the toe exactly.
    """
    pen = _pose(
        Pelvis=JointPose(rotation=Quaternion.identity(), translation=Vector3(z=-40.0))
    )
    keyframes = [_key(10, pen)]
    for frame in range(11, 20):
        keyframes.append(_key(frame, pen))
    keyframes.append(_key(20, pen))
    state = _state(keyframes)

    pinned, report = pin_foot_contacts(state, (10, 20))

    assert report.clamped == ()
    for frame in range(11, 20):
        toe = _toe(pinned, frame, "L_Foot")
        assert (toe.x, toe.y, toe.z) == pytest.approx((-10.0, 15.0, 0.0), abs=POST_PIN_HOLD_CM)


def test_a_single_planted_foot_never_moves_the_pelvis() -> None:
    """The right toe is off the ground at the second key: only the left is a
    contact. The interior frames ride a pelvis 200 above bind, so the left
    contact target sits beyond the leg's reach: clamped (named, never a
    failure) while the pelvis itself stays where each frame put it.
    """
    stand = _stand()
    interior = _pose(
        Pelvis=JointPose(rotation=Quaternion.identity(), translation=Vector3(z=200.0)),
        R_Hip=JointPose(rotation=rotation_x(45.0)),
    )
    keyframes = [_key(46, stand)]
    for frame in range(47, 71):
        keyframes.append(_key(frame, interior))
    keyframes.append(_key(71, _pose(R_Hip=JointPose(rotation=rotation_x(45.0)))))
    state = _state(keyframes)
    pelvis_before = _pose_at(state, 55)["Pelvis"]

    pinned, report = pin_foot_contacts(state, (46, 71))

    after = _pose_at(pinned, 55)
    assert after["Pelvis"] == pelvis_before
    assert report.clamped == ("L_Foot",)
    # The clamped toe lies on the hip-target ray at the chain's full reach:
    # far above the ground, but the best the leg can do for that frame.
    toe = _toe(pinned, 55, "L_Foot")
    assert toe.z > 10.0  # nowhere near the pinned z; clamped, and named


def test_both_feet_lower_the_pelvis_only_as_far_as_the_leg_chains_need() -> None:
    high = _pose(Pelvis=JointPose(rotation=Quaternion.identity(), translation=Vector3(z=200.0)))
    state = _dense(high)
    pelvis_before = _pose_at(state, 55)["Pelvis"]

    pinned, report = pin_foot_contacts(state, (46, 71))

    after = _pose_at(pinned, 55)
    assert after["Pelvis"].translation.x == pytest.approx(pelvis_before.translation.x)
    assert after["Pelvis"].translation.y == pytest.approx(pelvis_before.translation.y)
    assert after["Pelvis"].translation.z < pelvis_before.translation.z  # lowered, not raised
    assert report.clamped == ()
    for frame in range(47, 71):
        assert _toe(pinned, frame, "L_Foot").z == pytest.approx(0.0, abs=POST_PIN_HOLD_CM)
        assert _toe(pinned, frame, "R_Foot").z == pytest.approx(0.0, abs=POST_PIN_HOLD_CM)


def test_a_span_without_planted_feet_changes_nothing() -> None:
    """A span whose KEYS hold both feet off the ground: no contacts, no edit.

    Detection reads the keys only - the interior frames may swing freely - so
    the keys themselves must swing for the span to carry no contact.
    """
    swing = _pose(
        L_Hip=JointPose(rotation=rotation_x(45.0)),
        R_Hip=JointPose(rotation=rotation_x(-45.0)),
    )
    keyframes = [_key(46, swing)]
    for frame in range(47, 71):
        keyframes.append(_key(frame, swing))
    keyframes.append(_key(71, swing))
    state = _state(keyframes)
    before = list(state.keyframes)

    pinned, report = pin_foot_contacts(state, (46, 71))

    assert report.frames_corrected == 0
    assert [keyframe.pose for keyframe in pinned.keyframes] == [
        keyframe.pose for keyframe in before
    ]


def test_the_report_names_what_was_pinned() -> None:
    state = _dense()

    pinned, report = pin_foot_contacts(state, (46, 71))

    assert isinstance(report, PinReport)
    assert report.spans_pinned == ((46, 71),)
    assert report.feet_pinned == ("L_Foot", "R_Foot")
    assert report.frames_corrected == 24
    assert report.clamped == ()


def test_pin_is_idempotent() -> None:
    state = _dense()

    once, _ = pin_foot_contacts(state, (46, 71))
    second, report = pin_foot_contacts(once, (46, 71))

    assert [keyframe.pose for keyframe in second.keyframes] == [
        keyframe.pose for keyframe in once.keyframes
    ]
    assert report.frames_corrected == 0


def test_pin_without_rig_knowledge_reports_nothing_to_correct() -> None:
    """A timeline with fewer than two original keys: nothing is a span."""
    state = _dense()

    pinned, report = pin_foot_contacts(state, (46,))

    assert [keyframe.pose for keyframe in pinned.keyframes] == [
        keyframe.pose for keyframe in state.keyframes
    ]
    assert report.frames_corrected == 0


def test_pin_refuses_a_non_keyed_original() -> None:
    state = _dense()

    with pytest.raises(ValueError):
        pin_foot_contacts(state, (46, 72))
