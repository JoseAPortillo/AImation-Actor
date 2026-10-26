"""Seam feathering between captured anchors and generated rows (R2).

M9's probe measured the defect on the real clip: a captured anchor row at
164.8 deg (arm from vertical) and the engine's first content row at 114.5 —
a ~50 deg snap the animator sees as a pop at every anchor boundary. The
tool's remedy (S1): blend the FREE rows adjacent to an anchor toward that
anchor over a short window at adoption, never touching the anchors
themselves (S2 — keys and guides are byte-exact by contract), never moving
what other passes own (root rotation and translations, S4), and never
twitching content that is already continuous (the threshold, S3).

Pinned here, at the pure-function level: anchor survival, the window, the
decay, the nearest-boundary choice, the threshold, the untouched channels
and the corrected-frame count. The measured defaults for window/strength/
threshold are adopted from the R2 T3 probe (odd/tasks/r2-anchor-seam.md).
"""

from __future__ import annotations

import math

from aimation_actor.core.models import (
    JointData,
    JointPose,
    Keyframe,
    Quaternion,
    Skeleton,
    TimelineState,
    Vector3,
)
from aimation_actor.core.seam import feather_anchor_seams


def _qz(angle_deg: float) -> Quaternion:
    half = math.radians(angle_deg) / 2.0
    return Quaternion(w=math.cos(half), x=0.0, y=0.0, z=math.sin(half))


def _angle_to(value: Quaternion, reference: Quaternion) -> float:
    """The rotation angle between two unit quaternions, in degrees."""
    dot = abs(value.w * reference.w + value.x * reference.x
              + value.y * reference.y + value.z * reference.z)
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


def _state(anchor_left: dict, anchor_right: dict, interior: list[dict]) -> TimelineState:
    frames = [0, *range(1, len(interior) + 1), len(interior) + 1]
    poses = [anchor_left, *interior, anchor_right]
    keyframes = tuple(
        Keyframe(frame=frame, pose=pose)
        for frame, pose in zip(frames, poses, strict=True)
    )
    return TimelineState(
        skeleton=_skeleton(), keyframes=keyframes, fps=24.0, frame_end=frames[-1]
    )


def _rows(state: TimelineState) -> dict[int, dict]:
    return {key.frame: key.pose for key in state.keyframes}


def test_anchor_rows_survive_byte_identical() -> None:
    """S2: keys and guides are untouchable — same objects, same values."""
    anchor_l = _pose(_qz(0.0))
    anchor_r = _pose(_qz(0.0))
    state = TimelineState(
        skeleton=_skeleton(),
        keyframes=(
            Keyframe(frame=0, pose=anchor_l),
            Keyframe(frame=1, pose=_pose(_qz(60.0))),
            Keyframe(frame=2, pose=_pose(_qz(60.0))),
            Keyframe(frame=3, pose=anchor_r),
        ),
        fps=24.0,
        frame_end=3,
    )
    feathered, _count = feather_anchor_seams(
        state, (0, 3), window=1, strength=0.9, threshold_deg=30.0
    )
    assert feathered.keyframes[0] is state.keyframes[0]  # untouched rows keep identity
    assert feathered.keyframes[3] is state.keyframes[3]
    assert feathered.keyframes[0].pose["Pelvis"].rotation == _qz(0.0)
    assert feathered.keyframes[3].pose["Pelvis"].rotation == _qz(0.0)


def test_rows_inside_the_window_blend_toward_their_anchor() -> None:
    anchor = _qz(0.0)
    state = _state(_pose(anchor), _pose(anchor), [_pose(_qz(60.0))] * 5)

    feathered, count = feather_anchor_seams(
        state, (0, 6), window=2, strength=0.9, threshold_deg=30.0
    )

    rows = _rows(feathered)
    first = _angle_to(rows[1]["Pelvis"].rotation, anchor)
    second = _angle_to(rows[2]["Pelvis"].rotation, anchor)
    assert 0.0 < first < 60.0  # pulled toward the anchor
    assert first < second  # S3: the decay — nearer rows move further
    assert rows[3]["Pelvis"].rotation == _qz(60.0)  # outside both windows
    assert _angle_to(rows[4]["Pelvis"].rotation, anchor) < 60.0  # right side too
    assert count == 4  # two rows per boundary


def test_the_right_boundary_anchors_the_rows_before_it() -> None:
    anchor = _qz(0.0)
    state = _state(_pose(anchor), _pose(anchor), [_pose(_qz(60.0))] * 5)

    feathered, _count = feather_anchor_seams(
        state, (0, 6), window=2, strength=0.9, threshold_deg=30.0
    )

    rows = _rows(feathered)
    near_right = _angle_to(rows[5]["Pelvis"].rotation, anchor)
    assert near_right < 60.0
    # Nearest-boundary wins: row 5 is 1 from the right anchor, 5 from the left.
    assert near_right < _angle_to(rows[1]["Pelvis"].rotation, anchor) or (
        near_right == _angle_to(rows[1]["Pelvis"].rotation, anchor)
    )
    assert near_right <= 60.0 * (1.0 - 0.9 * (1.0 - 1.0 / 3.0)) + 1e-9


def test_already_continuous_rows_are_untouched() -> None:
    """S3 threshold: a 10 deg difference under a 30 deg bar does not twitch."""
    anchor = _qz(0.0)
    content = _pose(_qz(10.0))
    state = _state(_pose(anchor), _pose(anchor), [content, dict(content)])

    feathered, count = feather_anchor_seams(
        state, (0, 3), window=2, strength=0.9, threshold_deg=30.0
    )

    assert count == 0
    assert feathered is state or _rows(feathered)[1]["Pelvis"].rotation == _qz(10.0)


def test_the_root_is_never_rotated_and_translations_never_move() -> None:
    """S4: Main's rotation is identity by invariant; translations belong to
    the root-smoothing and pinning passes, not to feathering."""
    anchor_pose = _pose(_qz(0.0))
    odd_root = {
        "Main": JointPose(rotation=_qz(120.0), translation=Vector3(1.0, 2.0, 3.0)),
        "Pelvis": JointPose(rotation=_qz(60.0), translation=Vector3(4.0, 5.0, 6.0)),
    }
    state = TimelineState(
        skeleton=_skeleton(),
        keyframes=(
            Keyframe(frame=0, pose=anchor_pose),
            Keyframe(frame=1, pose=odd_root),
            Keyframe(frame=2, pose=anchor_pose),
        ),
        fps=24.0,
        frame_end=2,
    )

    feathered, count = feather_anchor_seams(
        state, (0, 2), window=1, strength=0.9, threshold_deg=30.0
    )

    row = _rows(feathered)[1]
    assert row["Main"].rotation == _qz(120.0)  # untouched
    assert row["Main"].translation == Vector3(1.0, 2.0, 3.0)
    assert row["Pelvis"].translation == Vector3(4.0, 5.0, 6.0)  # translations stay
    assert _angle_to(row["Pelvis"].rotation, _qz(0.0)) < 60.0  # but rotations blend
    assert count == 1


def test_joints_missing_from_the_anchor_pose_are_skipped() -> None:
    anchor_pose = _pose(_qz(0.0))
    content_pose = _pose(_qz(60.0))
    content_pose["Hand"] = JointPose(rotation=_qz(80.0))
    state = TimelineState(
        skeleton=_skeleton(),
        keyframes=(
            Keyframe(frame=0, pose=anchor_pose),
            Keyframe(frame=1, pose=content_pose),
            Keyframe(frame=2, pose=anchor_pose),
        ),
        fps=24.0,
        frame_end=2,
    )

    feathered, _count = feather_anchor_seams(
        state, (0, 2), window=1, strength=0.9, threshold_deg=30.0
    )

    row = _rows(feathered)[1]
    assert row["Hand"].rotation == _qz(80.0)  # no anchor value to blend toward


def test_anchors_outside_the_state_and_unsorted_input_are_fine() -> None:
    """Only frames present as rows are boundaries; the anchor list arrives
    unsorted (keys tuple + guides dict) and must not disturb the result."""
    anchor = _qz(0.0)
    state = _state(_pose(anchor), _pose(anchor), [_pose(_qz(60.0))] * 3)

    feathered, count = feather_anchor_seams(
        state, (4, 99, 0), window=1, strength=0.9, threshold_deg=30.0
    )

    rows = _rows(feathered)
    assert _angle_to(rows[1]["Pelvis"].rotation, anchor) < 60.0  # left blend
    assert _angle_to(rows[3]["Pelvis"].rotation, anchor) < 60.0  # right blend
    assert rows[2]["Pelvis"].rotation == _qz(60.0)  # outside the window
    assert count == 2
