"""Unit tests for the in-between generation domain math (§12.5 / inbetween-generation).

Slice 1 (PR1): domain timing math — :class:`InbetweenParams` (VALIDATE),
:func:`_resample` keyframe-exact upsample (RESAMPLE), fused easing (EASING).

Slice 2 (PR2) adds Phase 2 — domain trajectory math:
- :func:`_apply_rotation_filter` quaternion sign canonicalization + shortest-arc
  slerp with nlerp fallback (ROT).
- :func:`_apply_tangent_smooth` centered-box smoothing on translation axes only
  (SMOOTH).
- :func:`enrich_motion` fixed-stage pipeline with determinism and invariants
  (ORDER).

Tests build ``NeutralMotion`` documents directly so every assertion exercises
real production math. The math is pure stdlib (``math`` only), mirroring the
temporal-cleanup precedent.
"""

from __future__ import annotations

import math

import pytest

from aimation_actor_core.domain.animation import inbetween as inbetween_module
from aimation_actor_core.domain.animation.entities import Frame, Pose, Transform3D
from aimation_actor_core.domain.animation.inbetween import (
    InbetweenParams,
    _apply_rotation_filter,
    _apply_tangent_smooth,
    _ease,
    _resample,
    _slerp,
    enrich_motion,
)
from aimation_actor_core.domain.animation.neutral_motion import (
    ContactFeed,
    FootContact,
    KeyPose,
    NeutralMeta,
    NeutralMotion,
    TrackingInfo,
)
from aimation_actor_core.domain.animation.skeleton import Bone, Skeleton

# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


def _single_bone_skeleton() -> Skeleton:
    """A minimal one-root-bone skeleton (no parent -> root)."""
    return Skeleton(bones={"B": Bone(name="B", parent=None, rest_position=(0.0, 0.0, 0.0))})


def _make_motion(
    fps: float,
    xs: list[float],
    rotations: list[tuple[float, float, float, float]] | None = None,
) -> NeutralMotion:
    """Build a NeutralMotion with a single bone moving along X at ``fps``.

    Frame numbers run 1..n and ``time`` follows the producer convention
    ``time=frame/fps``, exactly like ``test_cleanup.py``.
    """
    if rotations is None:
        rotations = [(1.0, 0.0, 0.0, 0.0)] * len(xs)
    frames = [
        Frame(
            frame=i + 1,
            time=(i + 1) / fps,
            pose=Pose(
                transforms={
                    "B": Transform3D(
                        translation=(xs[i], 0.0, 0.0),
                        rotation=rotations[i],
                    )
                }
            ),
        )
        for i in range(len(xs))
    ]
    motion = NeutralMotion(
        skeleton=_single_bone_skeleton(), meta=NeutralMeta(fps=fps), frames=frames
    )
    motion.validate_invariants()
    return motion


def _xs(motion: NeutralMotion) -> list[float]:
    """Extract the single bone's X track across all frames."""
    return [f.pose.transforms["B"].translation[0] for f in motion.frames]


def _times(motion: NeutralMotion) -> list[float]:
    """Extract the per-frame time values."""
    return [f.time for f in motion.frames]


def _meta(motion: NeutralMotion) -> tuple[float, int]:
    """Return (fps, duration_frames) metadata."""
    return motion.meta.fps, motion.meta.duration_frames


def _rotations(motion: NeutralMotion) -> list[tuple[float, float, float, float]]:
    """Extract the single bone's rotation track across all frames."""
    return [f.pose.transforms["B"].rotation for f in motion.frames]


def _quat_dot(
    qa: tuple[float, float, float, float], qb: tuple[float, float, float, float]
) -> float:
    """Dot product of two quaternions ``(w, x, y, z)``."""
    return qa[0] * qb[0] + qa[1] * qb[1] + qa[2] * qb[2] + qa[3] * qb[3]


def _quat_norm(q: tuple[float, float, float, float]) -> float:
    """Euclidean norm of a quaternion."""
    return math.sqrt(sum(c * c for c in q))


# --------------------------------------------------------------------------- #
# ROT — task 2.1 (RED: _slerp / _apply_rotation_filter do not exist yet)
# --------------------------------------------------------------------------- #


class TestRotationFilter:
    """Sign canonicalization and shortest-arc slerp (ROT)."""

    def test_alternating_signs_canonicalized_to_positive_dot(self) -> None:
        """Consecutive q / -q source rotations get positive dot product."""
        rotations = [(1.0, 0.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0)]
        motion = _make_motion(fps=30.0, xs=[0.0, 1.0, 2.0], rotations=rotations)
        out = _apply_rotation_filter(motion, enabled=True)
        seq = _rotations(out)
        for i in range(len(seq) - 1):
            assert _quat_dot(seq[i], seq[i + 1]) > 0.0

    def test_filter_disabled_passes_rotations_through(self) -> None:
        """euler_filter=false leaves rotation samples byte-identical."""
        rotations = [(1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.0)]
        motion = _make_motion(fps=30.0, xs=[0.0, 1.0, 2.0], rotations=rotations)
        out = _apply_rotation_filter(motion, enabled=False)
        assert out is motion
        assert _rotations(out) == rotations

    def test_slerp_shortest_arc_canonicalizes_negative_dot_pair(self) -> None:
        """Slerping the negated 120°-about-z quaternion follows the 60° short arc."""
        q_rot = (0.5, 0.0, 0.0, math.sqrt(3.0) / 2.0)  # 120° about z
        q_neg = (-q_rot[0], -q_rot[1], -q_rot[2], -q_rot[3])  # same rotation, dot<0
        assert _quat_dot((1.0, 0.0, 0.0, 0.0), q_neg) < 0.0
        mid = _slerp((1.0, 0.0, 0.0, 0.0), q_neg, 0.5)
        # Short arc: identity -> 120°-about-z passes through 60°-about-z.
        expected = (math.cos(math.radians(30.0)), 0.0, 0.0, math.sin(math.radians(30.0)))
        assert mid == pytest.approx(expected, abs=1e-6)

    def test_slerp_antipodal_uses_nlerp_no_nan(self) -> None:
        """Near-antipodal pair falls back to nlerp: finite, unit norm, no NaN."""
        q0 = (1.0, 0.0, 0.0, 0.0)
        w = -(1.0 - 1e-7)
        z = math.sqrt(1.0 - w * w)
        q1 = (w, 0.0, 0.0, z)  # dot(q0, q1) ≈ -1 -> nlerp path
        mid = _slerp(q0, q1, 0.5)
        assert all(math.isfinite(c) for c in mid)
        assert _quat_norm(mid) == pytest.approx(1.0, abs=1e-6)
        # nlerp(t=0.5) of the canonicalized pair: mid stays near the start quaternion.
        assert mid[0] == pytest.approx(1.0, abs=1e-4)

    def test_slerp_endpoint_consistency(self) -> None:
        """Slerp reproduces its endpoints: t=0 -> q0, t=1 -> canonical q1."""
        q0 = (1.0, 0.0, 0.0, 0.0)
        q1 = (0.0, 0.0, 0.0, 1.0)
        assert _slerp(q0, q1, 0.0) == pytest.approx(q0)
        assert _slerp(q0, q1, 1.0) == pytest.approx(q1, abs=1e-6)

    def test_resample_then_filter_positive_dot_unit_norm(self) -> None:
        """Composition: slerped resample + post filter keep dots positive, unit norm."""
        rotations = [
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
            (-1.0, 0.0, 0.0, 0.0),
        ]
        motion = _make_motion(fps=30.0, xs=[0.0, 5.0, 20.0], rotations=rotations)
        resampled = _resample(motion, target_fps=60.0, method="cubic", easing="none")
        assert len(resampled.frames) == 5
        out = _apply_rotation_filter(resampled, enabled=True)
        seq = _rotations(out)
        for i in range(len(seq) - 1):
            assert _quat_dot(seq[i], seq[i + 1]) > 0.0
        for r in seq:
            assert _quat_norm(r) == pytest.approx(1.0, abs=1e-6)


# --------------------------------------------------------------------------- #
# SMOOTH — task 2.3 (RED: _apply_tangent_smooth does not exist yet)
# --------------------------------------------------------------------------- #


def _translations(motion: NeutralMotion) -> list[tuple[float, float, float]]:
    """Extract the single bone's translation track across all frames."""
    return [f.pose.transforms["B"].translation for f in motion.frames]


def _axis_jitter_variance(motion: NeutralMotion, axis: int) -> float:
    """Population variance of the per-axis first-difference (tangent) track.

    SMOOTH defines the guarantee over the trajectory *tangents* — the first
    differences — which is exactly the high-frequency jitter the box filter is
    meant to reduce ("per-joint variance does not increase" == tangent-track
    variance does not increase).
    """
    track = [t[axis] for t in _translations(motion)]
    diffs = [track[i + 1] - track[i] for i in range(len(track) - 1)]
    n = len(diffs)
    mean = sum(diffs) / n
    return sum((v - mean) * (v - mean) for v in diffs) / n


def _make_jittered_motion(
    x_vals: list[float], y_vals: list[float], z_vals: list[float]
) -> NeutralMotion:
    """Build a one-bone motion with independent per-axis translation tracks."""
    frames = [
        Frame(
            frame=i + 1,
            time=(i + 1) / 30.0,
            pose=Pose(
                transforms={
                    "B": Transform3D(
                        translation=(x_vals[i], y_vals[i], z_vals[i]),
                        rotation=(1.0, 0.0, 0.0, 0.0),
                    )
                }
            ),
        )
        for i in range(len(x_vals))
    ]
    motion = NeutralMotion(
        skeleton=_single_bone_skeleton(), meta=NeutralMeta(fps=30.0), frames=frames
    )
    motion.validate_invariants()
    return motion


class TestTangentSmooth:
    """Centered-box smoothing: identity at 0, jitter variance non-increasing."""

    JITTER_X = [0.0, 8.0, 1.0, 7.0, 2.0, 6.0, 3.0, 5.0, 4.0, 4.0]
    JITTER_Y = [3.0, 4.0, 3.0, 5.0, 4.0, 5.0, 3.0, 4.0, 3.0, 5.0]
    JITTER_Z = [1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0]

    def _motion(self) -> NeutralMotion:
        return _make_jittered_motion(self.JITTER_X, self.JITTER_Y, self.JITTER_Z)

    def test_zero_intensity_is_identity(self) -> None:
        """tangent_smoothing=0 returns the motion unchanged."""
        motion = self._motion()
        out = _apply_tangent_smooth(motion, intensity=0.0)
        assert out is motion
        assert _translations(out) == _translations(motion)

    def test_smoothing_reduces_jitter_variance(self) -> None:
        """A positive intensity lowers the jittered axis's tangent variance."""
        motion = self._motion()
        var_in = _axis_jitter_variance(motion, 0)
        out = _apply_tangent_smooth(motion, intensity=0.9)
        var_out = _axis_jitter_variance(out, 0)
        assert var_out < var_in

    @pytest.mark.parametrize(
        ("a", "b"),
        [(0.2, 0.9), (0.4, 0.8), (0.334, 0.667)],
    )
    def test_higher_intensity_does_not_add_variance(self, a: float, b: float) -> None:
        """For a < b, every axis's tangent variance is non-increasing."""
        motion = self._motion()
        out_a = _apply_tangent_smooth(motion, intensity=a)
        out_b = _apply_tangent_smooth(motion, intensity=b)
        for axis in range(3):
            var_a = _axis_jitter_variance(out_a, axis)
            var_b = _axis_jitter_variance(out_b, axis)
            assert var_b <= var_a + 1e-9

    def test_rotations_untouched_by_smoothing(self) -> None:
        """Smoothing operates on translation axes only; rotations stay identical."""
        motion = _make_motion(
            fps=30.0,
            xs=[0.0, 8.0, 1.0, 7.0, 2.0, 6.0, 3.0, 5.0, 4.0, 4.0],
            rotations=[(0.0, 1.0, 0.0, 0.0)] * 10,
        )
        out = _apply_tangent_smooth(motion, intensity=0.9)
        assert _rotations(out) == _rotations(motion)


# --------------------------------------------------------------------------- #
# VALIDATE — task 1.1 (RED: InbetweenParams does not exist yet)
# --------------------------------------------------------------------------- #


class TestInbetweenParamsValidation:
    """``InbetweenParams`` must reject invalid params and accept defaults."""

    def test_defaults_are_valid(self) -> None:
        p = InbetweenParams()
        assert p.interpolation_method == "cubic"
        assert p.target_fps == 30
        assert p.easing == "none"
        assert p.euler_filter is True
        assert p.tangent_smoothing == 0.0

    def test_all_valid_values_construct(self) -> None:
        p = InbetweenParams(
            interpolation_method="linear",
            target_fps=60,
            easing="ease-in-out",
            euler_filter=False,
            tangent_smoothing=0.5,
        )
        assert p.interpolation_method == "linear"
        assert p.target_fps == 60
        assert p.easing == "ease-in-out"
        assert p.euler_filter is False
        assert p.tangent_smoothing == 0.5

    @pytest.mark.parametrize("method", ["spline", "bezier", ""])
    def test_invalid_interpolation_method_rejected(self, method: str) -> None:
        with pytest.raises(ValueError):
            InbetweenParams(interpolation_method=method)

    @pytest.mark.parametrize("easing", ["bounce", "spring", ""])
    def test_invalid_easing_rejected(self, easing: str) -> None:
        with pytest.raises(ValueError):
            InbetweenParams(easing=easing)

    @pytest.mark.parametrize("smoothing", [1.5, -0.1, 1.0001, -1e-9])
    def test_out_of_range_smoothing_rejected(self, smoothing: float) -> None:
        with pytest.raises(ValueError):
            InbetweenParams(tangent_smoothing=smoothing)

    @pytest.mark.parametrize("fps", [0, -30, -1])
    def test_non_positive_fps_rejected(self, fps: float) -> None:
        with pytest.raises(ValueError):
            InbetweenParams(target_fps=fps)

    def test_boundary_smoothing_accepted(self) -> None:
        assert InbetweenParams(tangent_smoothing=0.0).tangent_smoothing == 0.0
        assert InbetweenParams(tangent_smoothing=1.0).tangent_smoothing == 1.0


# --------------------------------------------------------------------------- #
# RESAMPLE — task 1.3 (RED: _resample does not exist yet)
# --------------------------------------------------------------------------- #


class TestResample:
    """Keyframe-exact, upsample-only resampling with meta updates."""

    def test_upsample_30_to_60_gives_5_frames_keys_exact(self) -> None:
        """3 frames @30fps -> 5 frames @60fps; keys exact; first/last equal."""
        motion = _make_motion(fps=30.0, xs=[0.0, 5.0, 20.0])
        out = _resample(motion, target_fps=60.0, method="cubic", easing="none")

        assert len(out.frames) == 5
        xs = _xs(out)
        assert xs[0] == pytest.approx(0.0)  # first source key
        assert xs[2] == pytest.approx(5.0)  # interior source key at its position
        assert xs[4] == pytest.approx(20.0)  # last source key
        assert _meta(out) == (60.0, 5)
        # Frame numbers are 1..5, times strictly increasing on the 60fps grid.
        frames = [f.frame for f in out.frames]
        assert frames == [1, 2, 3, 4, 5]
        out.validate_invariants()

    def test_linear_upsample_matches_piecewise_segments(self) -> None:
        """Linear mode is piecewise-linear between exact keys."""
        motion = _make_motion(fps=30.0, xs=[0.0, 10.0, 0.0])
        out = _resample(motion, target_fps=60.0, method="linear", easing="none")
        xs = _xs(out)
        assert xs == pytest.approx([0.0, 5.0, 10.0, 5.0, 0.0])

    def test_cubic_c1_linear_c0_at_interior_key(self) -> None:
        """Cubic keeps matching one-sided derivatives; linear kinks (C0 only)."""
        src = _make_motion(fps=30.0, xs=[0.0, 5.0, 20.0])

        def one_sided_slopes(method: str) -> tuple[float, float]:
            out = _resample(src, target_fps=300.0, method=method, easing="none")
            xs = _xs(out)
            dt = 1.0 / 300.0
            key_idx = 10  # interior key sits at xi=0.5 -> k=(n_out-1)/2
            d_left = (3.0 * xs[key_idx] - 4.0 * xs[key_idx - 1] + xs[key_idx - 2]) / (2.0 * dt)
            d_right = (
                -3.0 * xs[key_idx] + 4.0 * xs[key_idx + 1] - xs[key_idx + 2]
            ) / (2.0 * dt)
            return d_left, d_right

        dL_c, dR_c = one_sided_slopes("cubic")
        dL_l, dR_l = one_sided_slopes("linear")

        # Cubic is C1: left/right derivative estimates agree within ~2%.
        assert abs(dL_c - dR_c) / max(abs(dL_c), abs(dR_c)) < 0.05
        # Linear is C0 only: the kink makes the one-sided slopes disagree.
        assert abs(dL_l - dR_l) / max(abs(dL_l), abs(dR_l)) > 0.5

    def test_no_downsample_passthrough(self) -> None:
        """target_fps <= meta.fps -> unchanged frames and meta.fps."""
        motion = _make_motion(fps=30.0, xs=[0.0, 5.0, 20.0])
        out = _resample(motion, target_fps=24.0, method="cubic", easing="none")
        assert out is motion
        assert _xs(out) == [0.0, 5.0, 20.0]
        assert _meta(out) == (30.0, 0)  # meta untouched on passthrough

    def test_equal_fps_passthrough(self) -> None:
        """target_fps == meta.fps -> passthrough (no resample)."""
        motion = _make_motion(fps=30.0, xs=[0.0, 5.0, 20.0])
        out = _resample(motion, target_fps=30.0, method="cubic", easing="none")
        assert out is motion

    def test_single_frame_passthrough(self) -> None:
        """A single-frame motion passes through unchanged."""
        motion = _make_motion(fps=30.0, xs=[7.0])
        out = _resample(motion, target_fps=60.0, method="cubic", easing="none")
        assert out is motion
        assert _xs(out) == [7.0]
        assert _meta(out) == (30.0, 0)  # single frame: no duration update

    def test_interior_source_frame_value_appears_exactly(self) -> None:
        """Every source key value appears exactly at its timeline position."""
        src_vals = [3.0, -7.0, 12.0, 2.0]
        motion = _make_motion(fps=30.0, xs=src_vals)
        out = _resample(motion, target_fps=120.0, method="cubic", easing="none")
        xs = _xs(out)
        # Source key i sits at output index i * (n_out-1) / (n_in-1).
        n_out = len(out.frames)
        n_in = len(motion.frames)
        for i, expected in enumerate(src_vals):
            idx = round(i * (n_out - 1) / (n_in - 1))
            assert xs[idx] == pytest.approx(expected)


# --------------------------------------------------------------------------- #
# EASING — task 1.5 (RED: _ease does not exist yet)
# --------------------------------------------------------------------------- #


class TestEasing:
    """Easing curves fused into resampling; monotonic; f(0)=0, f(1)=1."""

    def test_ease_function_endpoints_and_monotonic(self) -> None:
        """Every easing curve has f(0)=0, f(1)=1 and is monotonic on [0,1]."""
        for easing in ("ease-in", "ease-out", "ease-in-out"):
            assert _ease(0.0, easing) == 0.0
            assert _ease(1.0, easing) == 1.0
            prev = -1.0
            for i in range(101):
                t = i / 100.0
                v = _ease(t, easing)
                assert v >= prev - 1e-12
                prev = v

    def test_none_is_identity(self) -> None:
        assert _ease(0.0, "none") == 0.0
        assert _ease(0.37, "none") == 0.37
        assert _ease(1.0, "none") == 1.0

    def _segment_speeds(self, easing: str) -> list[float]:
        """Per-output-segment speeds on a constant-velocity source (300fps grid).

        The source is [0,10,20] @30fps, so the resampled easing curves are the
        only thing perturbing the otherwise-uniform speed.
        """
        motion = _make_motion(fps=30.0, xs=[0.0, 10.0, 20.0])
        out = _resample(motion, target_fps=300.0, method="linear", easing=easing)
        xs = _xs(out)
        times = _times(out)
        return [
            (xs[i + 1] - xs[i]) / (times[i + 1] - times[i]) for i in range(len(xs) - 1)
        ]

    def test_ease_in_slows_interval_start(self) -> None:
        """speed(first half of interval) < speed(second half) for ease-in."""
        speeds = self._segment_speeds("ease-in")
        # Interval 0 spans xi in [0, 0.5] -> output segments 0..9 (of 20).
        first_half = speeds[0:5]
        second_half = speeds[5:10]
        assert sum(first_half) / len(first_half) < sum(second_half) / len(second_half)

    def test_ease_out_slows_interval_end(self) -> None:
        """speed(second half) < speed(first half) for ease-out."""
        speeds = self._segment_speeds("ease-out")
        first_half = speeds[0:5]
        second_half = speeds[5:10]
        assert sum(second_half) / len(second_half) < sum(first_half) / len(first_half)

    def test_ease_in_out_midpoint_peak(self) -> None:
        """speed at interval midpoint exceeds speed near both interval ends."""
        speeds = self._segment_speeds("ease-in-out")
        mid = speeds[5]  # segment straddling xi=0.25 (interval midpoint)
        near_start = speeds[0]
        near_end = speeds[9]
        assert mid > near_start
        assert mid > near_end

    def test_keys_stay_exact_with_easing(self) -> None:
        """Easing never moves keyframe values (f(0)=0, f(1)=1 preserve keys)."""
        motion = _make_motion(fps=30.0, xs=[0.0, 5.0, 20.0])
        out = _resample(motion, target_fps=60.0, method="cubic", easing="ease-in-out")
        xs = _xs(out)
        assert xs[0] == pytest.approx(0.0)
        assert xs[2] == pytest.approx(5.0)
        assert xs[4] == pytest.approx(20.0)


# --------------------------------------------------------------------------- #
# ORDER — task 2.5 (RED: enrich_motion does not exist yet)
# --------------------------------------------------------------------------- #


class TestEnrichMotion:
    """Fixed-stage pipeline: order, determinism, invariants, passthrough fields."""

    def test_stage_order_resample_rotation_smooth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each sub-stage consumes the previous one's output, in fixed order."""
        calls: list[str] = []
        real_resample = inbetween_module._resample
        real_rotation = inbetween_module._apply_rotation_filter
        real_smooth = inbetween_module._apply_tangent_smooth

        def spy_resample(
            motion: NeutralMotion, target_fps: float, method: str, easing: str
        ) -> NeutralMotion:
            calls.append("resample")
            return real_resample(motion, target_fps, method, easing)

        def spy_rotation(motion: NeutralMotion, enabled: bool) -> NeutralMotion:
            calls.append("rotation")
            return real_rotation(motion, enabled)

        def spy_smooth(motion: NeutralMotion, intensity: float) -> NeutralMotion:
            calls.append("smooth")
            return real_smooth(motion, intensity)

        monkeypatch.setattr(inbetween_module, "_resample", spy_resample)
        monkeypatch.setattr(inbetween_module, "_apply_rotation_filter", spy_rotation)
        monkeypatch.setattr(inbetween_module, "_apply_tangent_smooth", spy_smooth)

        motion = _make_motion(fps=30.0, xs=[0.0, 5.0, 20.0])
        out = enrich_motion(
            motion,
            InbetweenParams(
                target_fps=60, easing="ease-in", euler_filter=True, tangent_smoothing=0.5
            ),
        )
        assert calls == ["resample", "rotation", "smooth"]
        assert len(out.frames) == 5  # the pipeline really ran end to end

    def test_run_twice_is_byte_identical(self) -> None:
        """Same input + params -> byte-identical outputs on repeated runs."""
        motion = _make_motion(fps=30.0, xs=[0.0, 5.0, 20.0])
        params = InbetweenParams(
            target_fps=60, easing="ease-in-out", euler_filter=True, tangent_smoothing=0.6
        )
        out1 = enrich_motion(motion, params)
        out2 = enrich_motion(motion, params)
        assert out1.model_dump_json() == out2.model_dump_json()

    def test_output_passes_invariants(self) -> None:
        """Enriched output satisfies NeutralMotion invariants (frames increasing)."""
        motion = _make_motion(fps=30.0, xs=[0.0, 5.0, 20.0, 2.0])
        out = enrich_motion(
            motion, InbetweenParams(target_fps=60, tangent_smoothing=0.7)
        )
        out.validate_invariants()  # must not raise
        frames = [f.frame for f in out.frames]
        assert frames == sorted(frames)
        assert len(set(frames)) == len(frames)

    def test_meta_updated_on_upsample(self) -> None:
        """enrich_motion writes meta.fps and duration_frames after upsample."""
        motion = _make_motion(fps=30.0, xs=[0.0, 5.0, 20.0])
        out = enrich_motion(motion, InbetweenParams(target_fps=60))
        assert _meta(out) == (60.0, 5)

    def test_new_frames_have_confidence_none(self) -> None:
        """Resampled frames drop confidence; output frames are all None."""
        motion = _make_motion(fps=30.0, xs=[0.0, 5.0, 20.0])
        motion = motion.model_copy(
            update={
                "frames": [
                    f.model_copy(update={"confidence": 0.5}) for f in motion.frames
                ]
            }
        )
        out = enrich_motion(motion, InbetweenParams(target_fps=60))
        assert all(f.confidence is None for f in out.frames)
        # The source document itself is untouched (immutability + copy semantics).
        assert all(f.confidence == 0.5 for f in motion.frames)

    def test_tracking_contacts_keyposes_passthrough(self) -> None:
        """contacts / keyposes / tracking pass through unmodified (MVP)."""
        motion = _make_motion(fps=30.0, xs=[0.0, 5.0, 20.0])
        motion = motion.model_copy(
            update={
                "contacts": {
                    "left_foot": ContactFeed(
                        samples=[FootContact(frame=1, contact=True)]
                    )
                },
                "keyposes": [KeyPose(frame=1, weight=1.0)],
                "tracking": TrackingInfo(confidence_per_frame=[0.5, 0.6, 0.7]),
            }
        )
        out = enrich_motion(motion, InbetweenParams(target_fps=60))
        assert out.contacts == motion.contacts
        assert out.keyposes == motion.keyposes
        assert out.tracking == motion.tracking

    def test_euler_filter_disabled_preserves_rotation_track(self) -> None:
        """euler_filter=false leaves the (resampled) rotation track unflipped."""
        rotations = [
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
            (-0.5, 0.0, 0.0, -math.sqrt(3.0) / 2.0),
        ]
        motion = _make_motion(fps=30.0, xs=[0.0, 5.0, 20.0], rotations=rotations)
        out = enrich_motion(motion, InbetweenParams(target_fps=60, euler_filter=False))
        # With the filter off, no sign canonicalization happens anywhere, so the
        # middle key's rotation keeps its original sign at its timeline position.
        assert out.frames[2].pose.transforms["B"].rotation == rotations[1]