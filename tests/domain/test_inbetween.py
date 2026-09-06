"""Unit tests for the in-between generation domain math (§12.5 / inbetween-generation).

Slice 1 (PR1) covers Phase 1 — domain timing math:
- :class:`InbetweenParams` parameter validation (VALIDATE).
- :func:`_resample` keyframe-exact cubic/linear resampling, upsample-only,
  with meta updates (RESAMPLE).
- Fused easing curves inside resampling (EASING).

Tests build ``NeutralMotion`` documents directly so every assertion exercises
real production math. The resampler is pure stdlib (``math`` only), mirroring
the temporal-cleanup precedent.
"""

from __future__ import annotations

import pytest

from aimation_actor_core.domain.animation.entities import Frame, Pose, Transform3D
from aimation_actor_core.domain.animation.inbetween import InbetweenParams, _ease, _resample
from aimation_actor_core.domain.animation.neutral_motion import NeutralMeta, NeutralMotion
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