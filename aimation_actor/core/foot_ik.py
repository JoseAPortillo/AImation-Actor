"""Analytic foot IK: the pin pass that holds planted contacts in place (M7).

Standard library only: this module may import the domain (``core.models``,
``core.kinematics``, ``core.foot_contacts``) and nothing from ``ports/`` or
``adapters/``, and no third-party package (NFR-01).

FR-IK-01's contract, per ``odd/tasks/m7-ik-foot-pinning.md`` S3 and the
animator's threshold answer (spec.md open question 8, the balanced option):

- the pinned point is the FOOT (toe ball) - the same joint detection reads -
  landed at one robust contact target for each continuous planted run; the
  target is the coordinate-wise median of that run's original-key readings,
  which prevents HMR key noise from making consecutive spans tremble. A run
  whose median reading penetrates the ground has its target lifted to the
  ground plane, which is the pass's penetration correction;
- the leg solves with analytic two-bone IK; the knee pole comes from the
  frame's own knee direction so a bent leg bends the way it already bends;
- planted rows use one stable ankle-roll quaternion per continuous contact run;
  original key poses remain untouched, while noisy generated-row roll is
  smoothed so a planted foot does not visibly vibrate;
- the pelvis is lowered only when BOTH feet must be solved in the same span,
  and only as far as a chain needs to reach its pinned position;
- an unreachable target (the frame's own pelvis pose puts the contact beyond
  the leg's reach) is clamped along the target direction to full leg reach
  and NAMED in the pass's report instead of failing the fill;
- the original key poses stay byte-untouched (the S1 pattern of M6); the
  detection tolerance is the drift the animator accepts at the far key by
  construction.

The exact solve. With the ankle's roll frozen, forward kinematics factors
the toe's position in a way two separate segments cannot: the toe hangs off
the KNEE's frame through one effective rigid vector - the shin's offset plus
the frame-frozen toe offset (the ankle's local rotation applied to the toe
offset). The leg is then a textbook two-bone chain whose end point is the
toe itself: hip rotation carries the thigh onto the first segment's world
direction, and one knee rotation carries the effective shin onto the
remainder. The solution is closed-form (law of cosines), so the pass runs
one solve per frame per foot with no iteration - important because a
planted leg stands at full reach, where an iterative scheme would sit on
the two-bone singularity instead of the exact answer.
"""

from __future__ import annotations

import dataclasses
import math
from statistics import median

from aimation_actor.core.foot_contacts import contact_spans
from aimation_actor.core.kinematics import (
    compose,
    inverse,
    joint_transforms,
    quaternion_between_directions,
    rotate,
    rotate_about_axis,
)
from aimation_actor.core.models import (
    JointData,
    JointPose,
    Quaternion,
    Skeleton,
    TimelineState,
    Vector3,
)

__all__ = ["POST_PIN_HOLD_CM", "PinReport", "pin_foot_contacts"]

#: Open question 8 (the balanced option): the pinned toe holds its contact
#: target within this much across each corrected span.
POST_PIN_HOLD_CM = 0.5

#: The hair of slack that keeps the law-of-cosines triangle off its
#: degenerate edge (a straight leg means the knee-at-reach envelope, and the
#: acos argument must stay strictly inside [-1, 1]).
_SLACK = 1e-9


@dataclasses.dataclass(frozen=True, slots=True)
class PinReport:
    """What the pass did: spans corrected, feet pinned, anything clamped."""

    spans_pinned: tuple[tuple[int, int], ...] = ()
    feet_pinned: tuple[str, ...] = ()
    frames_corrected: int = 0
    clamped: tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# The pin pass
# --------------------------------------------------------------------------- #


def pin_foot_contacts(
    timeline: TimelineState,
    original_key_frames: tuple[int, ...],
    *,
    ground_z: float = 0.0,
) -> tuple[TimelineState, PinReport]:
    """Hold every detected planted foot across its span; keys stay untouched.

    ``original_key_frames`` lists the pre-fill human keys - detection's input,
    because after a fill the dense keyframes are indistinguishable from the
    generated ones. Returns the corrected timeline and a :class:`PinReport`.

    The timeline itself is never mutated: poses are copied per frame and a new
    state is composed, so callers can compare keyframe equality freely and the
    original ``Keyframe`` objects survive for untouched frames.
    """
    spans = contact_spans(timeline, original_key_frames, ground_z=ground_z)
    skeleton = timeline.skeleton
    active = [(span, feet) for span, feet in sorted(spans.items()) if feet]
    if active:
        _validate_chains(skeleton, {foot for _span, feet in active for foot in feet})

    poses = {keyframe.frame: dict(keyframe.pose) for keyframe in timeline.keyframes}
    spans_pinned: list[tuple[int, int]] = []
    feet_pinned: set[str] = set()
    clamped: set[str] = set()
    frames_corrected = 0

    targets_by_span = _stable_targets(
        skeleton, poses, active, ground_z=ground_z
    )
    poles_by_span = _stable_poles(skeleton, poses, active)
    rolls_by_span = _stable_rolls(skeleton, poses, active)
    for (left, right), feet in active:
        targets = {foot: targets_by_span[((left, right), foot)] for foot in sorted(feet)}
        spans_pinned.append((left, right))
        feet_pinned.update(targets)

        for frame in range(left + 1, right):
            pose = poses[frame]
            before = dict(pose)
            for foot in sorted(feet):
                _foot, ankle, _knee, _hip = _chain(skeleton, foot)
                pose[ankle.name] = dataclasses.replace(
                    pose[ankle.name],
                    rotation=rolls_by_span[((left, right), foot)],
                )
            if len(targets) >= 2:
                # Only a span with both feet pinned may trade pelvis height
                # for reach; a single planted foot never moves the pelvis.
                _lower_pelvis_to_reach(skeleton, pose, targets)
            for foot, target in targets.items():
                if _pin_toe_of(
                    pose, skeleton, foot, target, pole=poles_by_span[((left, right), foot)]
                ):
                    clamped.add(foot)
            if pose != before:
                frames_corrected += 1

    keyframes = tuple(
        keyframe
        if poses[keyframe.frame] == keyframe.pose
        else dataclasses.replace(keyframe, pose=poses[keyframe.frame])
        for keyframe in timeline.keyframes
    )
    return (
        dataclasses.replace(timeline, keyframes=keyframes),
        PinReport(
            spans_pinned=tuple(spans_pinned),
            feet_pinned=tuple(sorted(feet_pinned)),
            frames_corrected=frames_corrected,
            clamped=tuple(sorted(clamped)),
        ),
    )


def _stable_targets(
    skeleton: Skeleton,
    poses: dict[int, dict[str, JointPose]],
    active: list[tuple[tuple[int, int], set[str]]],
    *,
    ground_z: float,
) -> dict[tuple[tuple[int, int], str], Vector3]:
    """Use one robust contact target across each continuous planted run.

    HMR key readings contain centimetre-scale noise. Choosing each span's
    left key independently makes a planted toe jump whenever a new span
    starts. A continuous run of planted spans is one physical contact, so its
    key readings share one coordinate-wise median target. The median rejects
    isolated capture noise while preserving the existing ground correction.
    """
    key_world = {
        frame: joint_transforms(skeleton, poses[frame])[0]
        for span, _feet in active
        for frame in span
    }
    grouped: dict[str, list[list[tuple[int, int]]]] = {}
    for (left, right), feet in active:
        for foot in feet:
            runs = grouped.setdefault(foot, [])
            if runs and runs[-1][-1][1] == left:
                runs[-1].append((left, right))
            else:
                runs.append([(left, right)])

    result: dict[tuple[tuple[int, int], str], Vector3] = {}
    for foot, runs in grouped.items():
        for run in runs:
            frames = [run[0][0], *[right for _left, right in run]]
            readings = [key_world[frame][foot] for frame in frames]
            target = Vector3(
                x=median(reading.x for reading in readings),
                y=median(reading.y for reading in readings),
                z=max(ground_z, median(reading.z for reading in readings)),
            )
            for span in run:
                result[(span, foot)] = target
    return result


def _stable_poles(
    skeleton: Skeleton,
    poses: dict[int, dict[str, JointPose]],
    active: list[tuple[tuple[int, int], set[str]]],
) -> dict[tuple[tuple[int, int], str], Vector3]:
    """Use one knee-pole direction across each continuous planted run.

    Recomputing the pole from every noisy generated row changes which side of
    the two-bone solution is selected and makes the foot orientation vibrate
    even when the toe target is fixed. Original key knee directions are the
    animator's stable reference for the run; their component-wise median gives
    the same noise resistance as the contact target.
    """
    transforms = {
        frame: joint_transforms(skeleton, poses[frame])
        for span, _feet in active
        for frame in span
    }
    result: dict[tuple[tuple[int, int], str], Vector3] = {}
    for foot, runs in _contact_runs(active).items():
        _foot, _ankle, knee, hip = _chain(skeleton, foot)
        for run in runs:
            directions = []
            for frame in [run[0][0], *[right for _left, right in run]]:
                positions, _rotations = transforms[frame]
                direction = _sub(positions[knee.name], positions[hip.name])
                directions.append(_unit(direction))
            pole = _unit(
                Vector3(
                    x=median(direction.x for direction in directions),
                    y=median(direction.y for direction in directions),
                    z=median(direction.z for direction in directions),
                )
            )
            for span in run:
                result[(span, foot)] = pole
    return result


def _stable_rolls(
    skeleton: Skeleton,
    poses: dict[int, dict[str, JointPose]],
    active: list[tuple[tuple[int, int], set[str]]],
) -> dict[tuple[tuple[int, int], str], Quaternion]:
    """Use one averaged ankle-local roll across each planted contact run."""
    result: dict[tuple[tuple[int, int], str], Quaternion] = {}
    for foot, runs in _contact_runs(active).items():
        _foot, ankle, _knee, _hip = _chain(skeleton, foot)
        for run in runs:
            frames = [run[0][0], *[right for _left, right in run]]
            reference = poses[frames[0]][ankle.name].rotation
            aligned: list[Quaternion] = []
            for frame in frames:
                rotation = poses[frame][ankle.name].rotation
                dot = _quaternion_dot(reference, rotation)
                aligned.append(rotation if dot >= 0.0 else _negate_quaternion(rotation))
            roll = _average_quaternions(aligned)
            for span in run:
                result[(span, foot)] = roll
    return result


def _quaternion_dot(left: Quaternion, right: Quaternion) -> float:
    return left.w * right.w + left.x * right.x + left.y * right.y + left.z * right.z


def _negate_quaternion(value: Quaternion) -> Quaternion:
    return Quaternion(w=-value.w, x=-value.x, y=-value.y, z=-value.z)


def _average_quaternions(values: list[Quaternion]) -> Quaternion:
    """Average nearby, hemisphere-aligned unit quaternions and renormalize."""
    w = sum(value.w for value in values)
    x = sum(value.x for value in values)
    y = sum(value.y for value in values)
    z = sum(value.z for value in values)
    length = math.sqrt(w * w + x * x + y * y + z * z)
    if length <= 1e-12:
        return Quaternion.identity()
    return Quaternion(w=w / length, x=x / length, y=y / length, z=z / length)


def _contact_runs(
    active: list[tuple[tuple[int, int], set[str]]],
) -> dict[str, list[list[tuple[int, int]]]]:
    """Group active spans into contiguous planted runs, per foot."""
    grouped: dict[str, list[list[tuple[int, int]]]] = {}
    for (left, right), feet in active:
        for foot in feet:
            runs = grouped.setdefault(foot, [])
            if runs and runs[-1][-1][1] == left:
                runs[-1].append((left, right))
            else:
                runs.append([(left, right)])
    return grouped


# --------------------------------------------------------------------------- #
# Chain access and validation
# --------------------------------------------------------------------------- #


def _chain(skeleton: Skeleton, foot: str) -> tuple[JointData, JointData, JointData, JointData]:
    """The (foot, ankle, knee, hip) joints of a foot's leg chain."""
    by_name = {joint.name: joint for joint in skeleton.joints}
    foot_joint = by_name.get(foot)
    if foot_joint is None:
        raise ValueError(f"the pin pass needs the foot joint {foot!r} in the skeleton")
    ankle_joint = by_name.get(foot_joint.parent)
    if ankle_joint is None:
        raise ValueError(f"{foot!r} has no parent: the leg chain is incomplete")
    knee_joint = by_name.get(ankle_joint.parent)
    if knee_joint is None:
        raise ValueError(f"{ankle_joint.name} has no parent: the leg chain is incomplete")
    hip_joint = by_name.get(knee_joint.parent)
    if hip_joint is None:
        raise ValueError(f"{knee_joint.name} has no parent: the leg chain is incomplete")
    return foot_joint, ankle_joint, knee_joint, hip_joint


def _chain_pelvis(skeleton: Skeleton, foot: str) -> JointData:
    """The pelvis joint above a foot's leg chain."""
    _foot, _ankle, _knee, hip = _chain(skeleton, foot)
    if hip.parent is None:
        raise ValueError(f"{hip.name} has no parent; the pin pass needs a pelvis above the leg")
    by_name = {joint.name: joint for joint in skeleton.joints}
    pelvis = by_name.get(hip.parent)
    if pelvis is None:
        raise ValueError(f"{hip.name}'s parent {hip.parent!r} is not in the skeleton")
    return pelvis


def _validate_chains(skeleton: Skeleton, feet: set[str]) -> None:
    """Every pinned foot must have a complete leg chain up to a pelvis."""
    for foot in sorted(feet):
        _chain(skeleton, foot)
        _chain_pelvis(skeleton, foot)


# --------------------------------------------------------------------------- #
# Vector helpers (pure stdlib, local to this module's math)
# --------------------------------------------------------------------------- #


def _add(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(x=left.x + right.x, y=left.y + right.y, z=left.z + right.z)


def _sub(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(x=left.x - right.x, y=left.y - right.y, z=left.z - right.z)


def _scale(vector: Vector3, factor: float) -> Vector3:
    return Vector3(x=vector.x * factor, y=vector.y * factor, z=vector.z * factor)


def _norm(vector: Vector3) -> float:
    return math.sqrt(vector.x**2 + vector.y**2 + vector.z**2)


def _unit(vector: Vector3) -> Vector3:
    return _scale(vector, 1.0 / max(_norm(vector), 1e-12))


def _cross(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(
        x=left.y * right.z - left.z * right.y,
        y=left.z * right.x - left.x * right.z,
        z=left.x * right.y - left.y * right.x,
    )


def _dot(left: Vector3, right: Vector3) -> float:
    return left.x * right.x + left.y * right.y + left.z * right.z


def _perpendicular(vector: Vector3) -> Vector3:
    """A unit vector perpendicular to the near-unit ``vector``."""
    component = min((abs(vector.x), "x"), (abs(vector.y), "y"), (abs(vector.z), "z"))[1]
    third = Vector3(**{component: 1.0})
    return _unit(_cross(vector, third))


# --------------------------------------------------------------------------- #
# The toe solve (analytic two-bone on the effective shin)
# --------------------------------------------------------------------------- #


def _pin_toe_of(
    pose: dict[str, JointPose],
    skeleton: Skeleton,
    foot: str,
    toe_target: Vector3,
    *,
    pole: Vector3,
) -> bool:
    """Drive one foot's toe onto ``toe_target``; report whether it was clamped.

    An unreachable target (the frame's pelvis puts the contact beyond the
    leg's reach) is clamped along the target direction to full leg reach, and
    the caller records the foot in the report. The ankle's local rotation
    has already been stabilized for this contact run. Exact: one closed-form
    solve, no iteration.
    """
    foot_j, ankle_j, knee_j, hip_j = _chain(skeleton, foot)
    pelvis_j = _chain_pelvis(skeleton, foot)
    positions, rotations = joint_transforms(skeleton, pose)
    hip_pos = positions[hip_j.name]
    pelvis_rot = rotations[pelvis_j.name]

    knee_off = knee_j.rest_translation
    ankle_off = ankle_j.rest_translation
    toe_off = foot_j.rest_translation
    thigh = _norm(knee_off)
    toe_in_knee = rotate(pose[ankle_j.name].rotation, toe_off)
    effective_shin = _add(ankle_off, toe_in_knee)
    combination = _norm(effective_shin)
    if combination <= 1e-9:
        raise ValueError(
            f"{foot!r}'s effective shin is degenerate (shank and toe offsets cancel)"
        )
    reach = thigh + combination

    vector = _sub(toe_target, hip_pos)
    clamped = False
    if _norm(vector) > reach:
        clamped = True
        vector = _scale(vector, reach / _norm(vector))
    vector = _scale(vector, 1.0) if _norm(vector) > 0 else Vector3(x=0.0, y=0.0, z=-1.0)
    # Keep the law-of-cosines argument strictly inside its envelope.
    distance = max(min(_norm(vector), reach * (1.0 - _SLACK)), 1e-9)
    vector = _scale(_unit(vector), distance)

    e_unit = _unit(vector)
    axis = _cross(e_unit, pole)
    axis = _unit(axis) if _norm(axis) > 1e-6 else _perpendicular(e_unit)
    alpha = math.acos(
        min(
            1.0,
            max(-1.0, (thigh**2 + distance**2 - combination**2) / (2.0 * thigh * distance)),
        )
    )
    near_side = rotate_about_axis(e_unit, axis, alpha)
    far_side = rotate_about_axis(e_unit, axis, -alpha)
    thigh_dir = near_side if _dot(near_side, pole) >= _dot(far_side, pole) else far_side

    # Hip: the world rotation carrying the hip-local thigh offset onto the
    # chosen thigh direction; the local form drops pelvis's own rotor out.
    hip_world = quaternion_between_directions(_unit(knee_off), thigh_dir)
    hip_local = compose(inverse(pelvis_rot), hip_world)
    shin_dir_world = _unit(_sub(vector, _scale(thigh_dir, thigh)))
    knee_local = quaternion_between_directions(
        _unit(effective_shin), rotate(inverse(hip_world), shin_dir_world)
    )
    pose[hip_j.name] = dataclasses.replace(pose[hip_j.name], rotation=hip_local)
    pose[knee_j.name] = dataclasses.replace(pose[knee_j.name], rotation=knee_local)
    return clamped


# --------------------------------------------------------------------------- #
# Pelvis reach handling (both feet planted)
# --------------------------------------------------------------------------- #


def _lower_pelvis_to_reach(
    skeleton: Skeleton, pose: dict[str, JointPose], targets: dict[str, Vector3]
) -> None:
    """Lower the pelvis only as far as a leg chain needs to reach its pin.

    Horizontal hip offsets and pinned z targets are fixed, so a pelvis z shift
    moves the whole leg chain rigidly and the reach condition is one vertical
    inequality per chain. The largest of the required shifts wins; a chain
    that cannot reach even flat-out (target beyond horizontal reach) gets no
    relief here - its solve will clamp instead.
    """
    shift = 0.0
    pelvis_name = ""
    for foot, target in sorted(targets.items()):
        foot_j, ankle_j, knee_j, hip_j = _chain(skeleton, foot)
        pelvis_j = _chain_pelvis(skeleton, foot)
        pelvis_name = pelvis_j.name
        positions, _rotations = joint_transforms(skeleton, pose)
        hip_pos = positions[hip_j.name]
        toe_in_knee = rotate(pose[ankle_j.name].rotation, foot_j.rest_translation)
        reach = _norm(knee_j.rest_translation) + _norm(_add(ankle_j.rest_translation, toe_in_knee))
        rho2 = (target.x - hip_pos.x) ** 2 + (target.y - hip_pos.y) ** 2
        if rho2 >= reach**2:
            # Hopeless horizontally: the solve clamps; no pelvis relief helps.
            continue
        allowed = math.sqrt(reach**2 - rho2)
        overshot = hip_pos.z - target.z - allowed
        if overshot > shift:
            shift = overshot
    if shift <= 0.0:
        return
    pelvis_pose = pose.get(pelvis_name)
    if pelvis_pose is None:
        return
    pose[pelvis_name] = dataclasses.replace(
        pelvis_pose,
        translation=Vector3(
            x=pelvis_pose.translation.x,
            y=pelvis_pose.translation.y,
            z=pelvis_pose.translation.z - shift,
        ),
    )
