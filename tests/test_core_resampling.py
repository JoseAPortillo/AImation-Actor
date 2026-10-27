"""The sampling-clock bridge (M6 T2): slerp, resampling, and gap filling.

CondMDI was trained on HumanML3D at 20 fps while the timeline runs at its own
fps (24 for video), so generated motion enters and leaves through a clock
ratio. The bridge is engine-agnostic pure math: it knows only two rates, a
dense pose sequence, and the S1 rule that human keys win over smoothness.

The generated-motion contract: ``dense[i]`` is the pose at dense-clock frame
``i``; target frame ``f`` samples that sequence at the fractional dense index
``(f - frame_start) * source_fps / target_fps``. Key re-assertion is exact by
construction: ``fill_gap_synthetically`` never touches a keyed frame.
"""

from __future__ import annotations

import math

import pytest

from aimation_actor.core.models import JointPose, Keyframe, Quaternion, TimelineState
from aimation_actor.core.production_skeleton import production_skeleton
from aimation_actor.core.resampling import (
    fill_gap_synthetically,
    interpolate_pose,
    resample_dense_poses,
    slerp,
)
from tests.fake_hmr2_worker import _CANNED_BIND_OFFSETS as _FAKE_BIND_OFFSETS

_HALF_PI = math.pi / 2.0


def _qz(angle_radians: float) -> Quaternion:
    """A rotation of ``angle_radians`` about the +Z axis."""
    return Quaternion(
        w=math.cos(angle_radians / 2.0),
        x=0.0,
        y=0.0,
        z=math.sin(angle_radians / 2.0),
    )


def _almost(quaternion: Quaternion, expected: Quaternion, *, tol: float = 1e-9) -> None:
    """Component-wise comparison; Quaternion is a dataclass, so pytest.approx
    cannot be aimed at the whole object."""
    assert quaternion.w == pytest.approx(expected.w, abs=tol)
    assert quaternion.x == pytest.approx(expected.x, abs=tol)
    assert quaternion.y == pytest.approx(expected.y, abs=tol)
    assert quaternion.z == pytest.approx(expected.z, abs=tol)


def _timeline(*frames: int) -> TimelineState:
    """A timeline whose keys are all distinct z-rotations, one per named frame."""
    keys = tuple(
        Keyframe(
            frame=frame,
            pose={"Pelvis": JointPose(rotation=_qz(frame * 0.1))},
        )
        for frame in sorted(frames)
    )
    skeleton = production_skeleton(_FAKE_BIND_OFFSETS)
    return TimelineState(skeleton=skeleton, keyframes=keys, fps=24.0, frame_end=frames[-1])


# -- slerp ------------------------------------------------------------------------ #


def test_slerp_between_the_same_rotation_stays_put() -> None:
    q = _qz(0.7)
    _almost(slerp(q, q, 0.37), q)


def test_slerp_takes_the_short_path_for_antipodal_quaternions() -> None:
    # -q is the *same* rotation as q (double cover); the interpolated midpoint
    # must stay on that rotation, not swing 180 degrees the long way around.
    q = _qz(0.7)
    opposite = Quaternion(w=-q.w, x=-q.x, y=-q.y, z=-q.z)
    _almost(slerp(q, opposite, 0.5), q)


def test_slerp_halfway_between_identity_and_a_quarter_turn_lands_on_an_eighth() -> None:
    midpoint = slerp(Quaternion.identity(), _qz(_HALF_PI), 0.5)
    _almost(midpoint, _qz(_HALF_PI / 2.0))


def test_slerp_survives_a_nearly_axis_aligned_pair_without_exploding() -> None:
    q = _qz(1e-7)
    midway = slerp(q, Quaternion.identity(), 0.5)
    norm = math.sqrt(midway.w**2 + midway.x**2 + midway.y**2 + midway.z**2)
    assert norm == pytest.approx(1.0, abs=1e-6)
    assert math.isfinite(midway.w) and math.isfinite(midway.z)


# -- pose interpolation ------------------------------------------------------------ #


def test_interpolating_a_pose_at_the_endpoints_returns_the_endpoints() -> None:
    origin = JointPose(rotation=_qz(0.2))
    target = JointPose(rotation=_qz(1.4))
    assert interpolate_pose(origin, target, 0.0) == origin
    assert interpolate_pose(origin, target, 1.0) == target


def test_interpolating_a_pose_blends_the_translation_linearly() -> None:
    from aimation_actor.core.models import Vector3

    origin = JointPose(
        rotation=Quaternion.identity(),
        translation=Vector3(x=0.0, y=0.0, z=90.0),
    )
    target = JointPose(
        rotation=_qz(1.0),
        translation=Vector3(x=2.0, y=0.0, z=100.0),
    )
    midway = interpolate_pose(origin, target, 0.5)
    assert midway.translation == Vector3(x=1.0, y=0.0, z=95.0)


# -- clock resampling --------------------------------------------------------------- #


def _constant_motion(samples: int) -> list[dict[str, JointPose]]:
    pose = {"Pelvis": JointPose(rotation=_qz(0.9))}
    return [pose for _ in range(samples)]


def _turning_motion(samples: int, step: float) -> list[dict[str, JointPose]]:
    return [
        {"Pelvis": JointPose(rotation=_qz(index * step))} for index in range(samples)
    ]


def test_resampled_constant_motion_covers_the_span_with_one_pose() -> None:
    # 21 samples at 20 fps span one second, which is exactly frames 0..24 at
    # fps 24; the resample must hit every one of them with the same pose.
    covered = resample_dense_poses(_constant_motion(21), 20.0, 24.0, frame_start=0)
    assert sorted(covered) == list(range(25))
    for pose in covered.values():
        assert pose == covered[0]


def test_resampling_maps_frames_through_the_clock_ratio() -> None:
    # Frame 8 at 24 fps sits at dense index 8*20/24 = 6.6667; the interpolation
    # is fractional, so the angle must be that index times the per-sample step.
    covered = resample_dense_poses(_turning_motion(30, 0.25), 20.0, 24.0, frame_start=0)
    expected = _qz(8.0 * (20.0 / 24.0) * 0.25)
    _almost(covered[8]["Pelvis"].rotation, expected, tol=1e-6)


def test_resampling_never_leaks_outside_the_dense_span() -> None:
    covered = resample_dense_poses(_constant_motion(21), 20.0, 24.0, frame_start=0)
    assert 25 not in covered
    assert -1 not in covered


def test_resampling_honours_a_nonzero_anchor_frame() -> None:
    covered = resample_dense_poses(_constant_motion(21), 20.0, 24.0, frame_start=10)
    assert min(covered) == 10
    assert max(covered) == 34


# -- gap filling (the S1 rule) ------------------------------------------------------- #


def _poses_for(frames: list[int]) -> dict[int, dict[str, JointPose]]:
    generated = {"Pelvis": JointPose(rotation=_qz(3.3))}
    return {frame: generated for frame in frames}


def test_filling_a_gap_writes_every_empty_frame_without_touching_the_keys() -> None:
    state = _timeline(10, 20)
    filled = fill_gap_synthetically(state, 10, 20, _poses_for(range(11, 20)))

    keyed = {keyframe.frame: keyframe for keyframe in filled.keyframes}
    assert set(keyed) == set(range(10, 21))
    # The human keys come back byte-identical (S1: hard constraints).
    assert keyed[10] == state.keyframes[0]
    assert keyed[20] == state.keyframes[1]
    for frame in range(11, 20):
        assert keyed[frame].pose == _poses_for([frame])[frame]
    # Sorted by frame, keys first-anchored, nothing beyond the interval.
    frames = [keyframe.frame for keyframe in filled.keyframes]
    assert frames == sorted(frames)
    assert 21 not in keyed and 9 not in keyed


def test_filling_a_gap_keeps_an_inner_key_untouched() -> None:
    state = _timeline(10, 15, 20)
    filled = fill_gap_synthetically(state, 10, 20, _poses_for(range(11, 20)))
    keyed = {keyframe.frame: keyframe for keyframe in filled.keyframes}
    assert keyed[15] == state.keyframes[1]
    assert 16 in keyed and 11 in keyed


def test_filling_a_gap_refuses_to_silently_leave_a_hole() -> None:
    state = _timeline(10, 20)
    poses = _poses_for(range(11, 20))
    del poses[15]
    with pytest.raises(ValueError, match="15"):
        fill_gap_synthetically(state, 10, 20, poses)


def test_filling_a_degenerate_span_is_a_no_op() -> None:
    state = _timeline(10, 11)
    filled = fill_gap_synthetically(state, 10, 11, {})
    assert filled == state


# -- guide anchors (S6: the real capture inside the gap wins) ------------------------ #


def test_filling_a_gap_honours_anchor_poses_byte_exact() -> None:
    state = _timeline(10, 20)
    anchor = {"Pelvis": JointPose(rotation=_qz(1.0))}
    filled = fill_gap_synthetically(
        state, 10, 20, _poses_for(range(11, 20)), anchors={15: anchor}
    )
    keyed = {keyframe.frame: keyframe for keyframe in filled.keyframes}
    assert keyed[15].pose == anchor
    # Everything else is still the generated fill.
    assert keyed[14].pose == _poses_for([14])[14]
    assert keyed[16].pose == _poses_for([16])[16]
    # The human keys come back byte-identical (S1, unchanged).
    assert keyed[10] == state.keyframes[0]
    assert keyed[20] == state.keyframes[1]


def test_an_anchor_on_a_keyed_frame_is_refused() -> None:
    state = _timeline(10, 20)
    with pytest.raises(ValueError, match="keyed"):
        fill_gap_synthetically(state, 10, 20, _poses_for(range(11, 20)), anchors={10: {}})
    with pytest.raises(ValueError, match="keyed"):
        fill_gap_synthetically(state, 10, 20, _poses_for(range(11, 20)), anchors={20: {}})


def test_an_anchor_outside_the_gap_is_refused() -> None:
    state = _timeline(10, 20)
    with pytest.raises(ValueError, match="outside"):
        fill_gap_synthetically(state, 10, 20, _poses_for(range(11, 20)), anchors={9: {}})
    with pytest.raises(ValueError, match="outside"):
        fill_gap_synthetically(state, 10, 20, _poses_for(range(11, 20)), anchors={21: {}})
