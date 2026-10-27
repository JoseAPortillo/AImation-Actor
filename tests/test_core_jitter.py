"""Jitter damping on generated rows (R3).

The user's diagnosis (2026-10-27, verbatim): the noise happens when
generating inbetweens, not with the Golden Poses — and it is option 1:
frame-to-frame tremor. The engine's free rows vibrate around their own
trend. The tool's answer is the rotational analog of M8's root smoothing:
blend each FREE row's joint rotations toward a binomial kernel of its
neighbours, never touching the anchors themselves.

Pinned here at the pure-function level: anchor survival (S2), the
neighbour kernel with sign-aligned quaternions and the decay-free blend
(S3), the untouched channels (S4), the fully-present window requirement,
and the damped-frame count. Radius/strength defaults are provisional
until the R3 T3 probe measures them (odd/tasks/r3-generated-jitter.md).
"""

from __future__ import annotations

import math

from aimation_actor.core.jitter import damp_generated_jitter
from aimation_actor.core.models import (
    JointData,
    JointPose,
    Keyframe,
    Quaternion,
    Skeleton,
    TimelineState,
    Vector3,
)


def _qz(angle_deg: float) -> Quaternion:
    half = math.radians(angle_deg) / 2.0
    return Quaternion(w=math.cos(half), x=0.0, y=0.0, z=math.sin(half))


def _negated(q: Quaternion) -> Quaternion:
    """The same rotation, opposite sign — the double-cover trap."""
    return Quaternion(w=-q.w, x=-q.x, y=-q.y, z=-q.z)


def _angle_to(value: Quaternion, reference: Quaternion) -> float:
    dot = abs(
        value.w * reference.w + value.x * reference.x
        + value.y * reference.y + value.z * reference.z
    )
    return math.degrees(2.0 * math.acos(min(1.0, max(-1.0, dot))))


def _skeleton() -> Skeleton:
    return Skeleton(
        joints=(
            JointData(name="Main", parent=None),
            JointData(name="Pelvis", parent="Main", rest_translation=Vector3(z=100.0)),
        )
    )


def _pose(rotation: Quaternion, translation: Vector3 | None = None) -> dict:
    return {
        "Main": JointPose(rotation=Quaternion.identity(), translation=Vector3()),
        "Pelvis": JointPose(rotation=rotation, translation=translation or Vector3()),
    }


def _state(poses: dict[int, dict], frame_end: int) -> TimelineState:
    return TimelineState(
        skeleton=_skeleton(),
        keyframes=tuple(
            Keyframe(frame=frame, pose=pose)
            for frame, pose in sorted(poses.items())
        ),
        fps=24.0,
        frame_end=frame_end,
    )


def _rows(state: TimelineState) -> dict[int, dict]:
    return {key.frame: key.pose for key in state.keyframes}


def test_anchor_rows_survive_byte_identical() -> None:
    """S2: keys and guides are untouchable — same objects, same values."""
    anchors = (0, 6)
    poses = {frame: _pose(_qz(0.0)) for frame in anchors}
    poses.update({frame: _pose(_qz(60.0 if frame % 2 else 20.0)) for frame in (1, 2, 3, 4, 5)})
    state = _state(poses, 6)

    damped, _count = damp_generated_jitter(state, anchors, radius=2, strength=0.75)

    by_frame = {kf.frame: kf for kf in damped.keyframes}
    assert by_frame[0] is state.keyframes[0]  # untouched rows keep identity
    assert by_frame[6] is state.keyframes[-1]
    assert by_frame[0].pose["Pelvis"].rotation == _qz(0.0)
    assert by_frame[6].pose["Pelvis"].rotation == _qz(0.0)


def test_alternating_tremor_is_damped() -> None:
    """S1/S3: a period-2 zigzag between two anchors settles toward its mean."""
    baseline = _qz(30.0)  # the trend the tremor oscillates around
    poses = {0: _pose(baseline), 10: _pose(baseline)}
    poses.update(
        {frame: _pose(_qz(30.0 + (30.0 if frame % 2 else -30.0))) for frame in range(1, 10)}
    )
    state = _state(poses, 10)

    damped, count = damp_generated_jitter(state, (0, 10), radius=2, strength=0.75)

    rows = _rows(damped)
    deviations = [
        _angle_to(rows[frame]["Pelvis"].rotation, baseline) for frame in range(1, 10)
    ]
    # Raw zigzag sits 30 deg off the trend everywhere; damping must pull the
    # interior rows measurably closer without moving the anchors.
    assert all(dev < 30.0 - 5.0 for dev in deviations)
    assert count == 9


def test_constant_velocity_motion_barely_moves() -> None:
    """S3: a smooth arc is (near) its own kernel mean — damping must not
    crush it. Rows with a full symmetric window do not move at all; the two
    rows beside the sequence edge see a renormalized one-sided kernel and
    drift slightly toward the trend — still far under one frame's step."""
    step = 5.0
    poses = {frame: _pose(_qz(step * frame)) for frame in range(0, 11)}
    state = _state(poses, 10)

    damped, count = damp_generated_jitter(state, (0, 10), radius=2, strength=0.75)

    rows = _rows(damped)
    for frame in range(2, 9):
        moved = _angle_to(rows[frame]["Pelvis"].rotation, _qz(step * frame))
        assert moved < 0.01  # symmetric binomial mean of a linear arc = center
    for frame in (1, 9):
        moved = _angle_to(rows[frame]["Pelvis"].rotation, _qz(step * frame))
        assert moved < step  # edge drift stays well under one frame's motion
    assert count == 2  # only the one-sided edge rows were rewritten


def test_a_negated_quaternion_is_the_same_rotation() -> None:
    """S3 sign alignment: an already-smooth series stored with flipped
    signs must not be dragged toward a cancelled mean."""
    smooth = _qz(20.0)
    poses = {frame: _pose(smooth) for frame in range(0, 7)}
    poses[3] = _pose(_negated(smooth))  # identical rotation, opposite sign
    state = _state(poses, 6)

    damped, count = damp_generated_jitter(state, (0, 6), radius=2, strength=0.75)

    rows = _rows(damped)
    assert _angle_to(rows[3]["Pelvis"].rotation, smooth) < 1.0
    assert count == 0


def test_a_row_without_two_neighbours_is_left_untouched() -> None:
    """S3: fewer than three samples in the window (centre + 2 neighbours) is
    not a trend — filtering that would just drag the row toward one point."""
    poses = {0: _pose(_qz(0.0)), 1: _pose(_qz(60.0))}
    state = _state(poses, 1)

    damped, count = damp_generated_jitter(state, (0,), radius=1, strength=0.75)

    assert count == 0
    assert damped is state


def test_edge_rows_still_damp_with_a_renormalised_kernel() -> None:
    """S3: the window may hang off the sequence edge — the binomial weights
    renormalise over the present neighbours instead of skipping the row."""
    poses = {
        0: _pose(_qz(30.0)),  # anchor
        1: _pose(_qz(60.0)),  # free, at the very edge of the sequence
        2: _pose(_qz(30.0)),
        3: _pose(_qz(60.0)),
    }
    state = _state(poses, 3)

    damped, count = damp_generated_jitter(state, (), radius=2, strength=0.75)

    rows = _rows(damped)
    assert _angle_to(rows[1]["Pelvis"].rotation, _qz(60.0)) > 0.01  # it moved
    assert _angle_to(rows[1]["Pelvis"].rotation, _qz(30.0)) < 30.0  # toward the mean
    assert count == 4


def test_the_root_is_never_filtered_and_translations_never_move() -> None:
    """S4: Main's rotation is identity by invariant; translations belong
    to the root-smoothing and pinning passes."""
    poses = {
        0: _pose(_qz(0.0)),
        1: {
            "Main": JointPose(rotation=_qz(120.0), translation=Vector3(1.0, 2.0, 3.0)),
            "Pelvis": JointPose(rotation=_qz(60.0), translation=Vector3(4.0, 5.0, 6.0)),
        },
        2: _pose(_qz(0.0)),
    }
    state = _state(poses, 2)

    damped, count = damp_generated_jitter(state, (0, 2), radius=1, strength=0.75)

    row = _rows(damped)[1]
    assert row["Main"].rotation == _qz(120.0)  # untouched
    assert row["Main"].translation == Vector3(1.0, 2.0, 3.0)
    assert row["Pelvis"].translation == Vector3(4.0, 5.0, 6.0)
    assert _angle_to(row["Pelvis"].rotation, _qz(0.0)) < 60.0  # rotations damp
    assert count == 1


def test_joints_missing_from_the_window_are_skipped() -> None:
    poses = {
        0: _pose(_qz(0.0)),
        1: {**_pose(_qz(60.0)), "Hand": JointPose(rotation=_qz(80.0))},
        2: _pose(_qz(0.0)),
    }
    state = _state(poses, 2)

    damped, _count = damp_generated_jitter(state, (0, 2), radius=1, strength=0.75)

    row = _rows(damped)[1]
    assert row["Hand"].rotation == _qz(80.0)  # no window value to average with


def test_degenerate_settings_are_noops() -> None:
    poses = {frame: _pose(_qz(60.0 if frame % 2 else 0.0)) for frame in range(0, 7)}
    state = _state(poses, 6)

    for kwargs in ({"radius": 0}, {"radius": -1}, {"strength": 0.0}):
        damped, count = damp_generated_jitter(state, (0, 6), **kwargs)
        assert count == 0
        assert damped is state
