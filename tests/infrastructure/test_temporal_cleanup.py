"""Tests for TemporalCleanupNode (REQ temporal-cleanup / §12.4).

Mirrors the ``VideoToMotionNode`` test pattern: catalog schema assertions,
``execute`` returns a ``NeutralMotion`` (with dict coercion for the job-store
serialized path and ``asyncio.to_thread`` offload), and ``validate`` enforces
positive thresholds and a positive-integer ``hysteresis_frames``.
"""

from __future__ import annotations

from typing import Any

import pytest

from aimation_actor_core.domain.animation.entities import Frame, Pose, Transform3D
from aimation_actor_core.domain.animation.neutral_motion import NeutralMotion
from aimation_actor_core.domain.animation.skeleton_presets import DEFAULT_NEUTRAL_SKELETON
from aimation_actor_core.domain.pipeline.node import ExecutionContext
from aimation_actor_core.domain.pipeline.schema import DataType, NodeCategory
from aimation_actor_core.infrastructure.ai_models.temporal_cleanup import TemporalCleanupNode


def _motion(n_frames: int = 2) -> NeutralMotion:
    """Build a small valid NeutralMotion over the default skeleton."""
    frames = [
        Frame(
            frame=i + 1,
            time=(i + 1) / 24.0,
            pose=Pose(
                transforms={
                    "Root": Transform3D(translation=(0.0, 0.0, 0.0)),
                    "Hips": Transform3D(translation=(0.0, 95.0, 0.0)),
                    "LFoot": Transform3D(translation=(0.0, -42.0, 0.0)),
                    "RFoot": Transform3D(translation=(0.0, -42.0, 0.0)),
                }
            ),
        )
        for i in range(n_frames)
    ]
    motion = NeutralMotion(skeleton=DEFAULT_NEUTRAL_SKELETON, frames=frames)
    motion.validate_invariants()
    return motion


class TestTemporalCleanupNodeSchema:
    """Test TemporalCleanupNode catalog schema."""

    def test_schema_type(self) -> None:
        """Should declare type 'temporal-cleanup'."""
        schema = TemporalCleanupNode.get_schema()
        assert schema.type == "temporal-cleanup"

    def test_schema_category(self) -> None:
        """Should be a CLEANUP node."""
        schema = TemporalCleanupNode.get_schema()
        assert schema.category == NodeCategory.CLEANUP

    def test_schema_inputs(self) -> None:
        """Should declare motion: NEUTRAL_ANIMATION input port."""
        schema = TemporalCleanupNode.get_schema()
        assert len(schema.inputs) == 1
        assert schema.inputs[0].name == "motion"
        assert schema.inputs[0].data_type == DataType.NEUTRAL_ANIMATION

    def test_schema_outputs(self) -> None:
        """Should declare motion: NEUTRAL_ANIMATION output port."""
        schema = TemporalCleanupNode.get_schema()
        assert len(schema.outputs) == 1
        assert schema.outputs[0].name == "motion"
        assert schema.outputs[0].data_type == DataType.NEUTRAL_ANIMATION

    def test_schema_params(self) -> None:
        """Should declare the five cleanup params with their defaults."""
        schema = TemporalCleanupNode.get_schema()
        param_names = [p.name for p in schema.params]
        assert param_names == [
            "min_cutoff",
            "beta",
            "velocity_threshold",
            "height_threshold",
            "hysteresis_frames",
        ]
        defaults = {p.name: p.default for p in schema.params}
        assert defaults["min_cutoff"] == 1.0
        assert defaults["beta"] == 0.5
        assert defaults["velocity_threshold"] == 5.0
        assert defaults["height_threshold"] == 10.0
        assert defaults["hysteresis_frames"] == 4


class TestTemporalCleanupNodeExecute:
    """Test TemporalCleanupNode execution."""

    @pytest.fixture
    def context(self) -> ExecutionContext:
        """Create an execution context."""
        return ExecutionContext(trace_id="test-trace")

    @pytest.mark.asyncio
    async def test_execute_returns_neutral_motion(self, context: ExecutionContext) -> None:
        """Should return a NeutralMotion output with populated contacts."""
        node = TemporalCleanupNode()
        result = await node.execute(
            inputs={"motion": _motion()},
            params={},
            context=context,
        )
        motion = result.values["motion"]
        assert isinstance(motion, NeutralMotion)
        # The cleanup should have populated foot contact feeds.
        assert "left_foot" in motion.contacts
        assert "right_foot" in motion.contacts
        # Frame count preserved through the chain.
        assert [f.frame for f in motion.frames] == [1, 2]

    @pytest.mark.asyncio
    async def test_execute_dict_inputs_coerce_to_neutral_motion(
        self, context: ExecutionContext
    ) -> None:
        """Should coerce raw dict motion (job-store serialized path) into NeutralMotion."""
        node = TemporalCleanupNode()
        raw = _motion().model_dump()
        result = await node.execute(inputs={"motion": raw}, params={}, context=context)
        motion = result.values["motion"]
        assert isinstance(motion, NeutralMotion)
        assert [f.frame for f in motion.frames] == [1, 2]

    @pytest.mark.asyncio
    async def test_uses_asyncio_to_thread(self, context: ExecutionContext) -> None:
        """Should offload cleanup to a worker thread via asyncio.to_thread."""
        import asyncio

        node = TemporalCleanupNode()
        original_to_thread = asyncio.to_thread
        calls: list[tuple[Any, tuple[Any, ...]]] = []

        async def mock_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            calls.append((func, args))
            return await original_to_thread(func, *args, **kwargs)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(asyncio, "to_thread", mock_to_thread)
        try:
            result = await node.execute(
                inputs={"motion": _motion()},
                params={},
                context=context,
            )
            assert len(calls) > 0
            assert calls[0][0].__name__ == "cleanup_motion"
            assert isinstance(result.values["motion"], NeutralMotion)
        finally:
            monkeypatch.undo()


class TestTemporalCleanupNodeValidate:
    """Test TemporalCleanupNode parameter validation.

    Numeric thresholds (min_cutoff, beta, velocity_threshold, height_threshold)
    must be positive numbers when provided. ``hysteresis_frames`` must be a
    positive integer. Omitted params are always OK (all optional).
    """

    @pytest.mark.asyncio
    async def test_validate_empty_params(self) -> None:
        """Should accept empty params (all params are optional)."""
        node = TemporalCleanupNode()
        result = await node.validate({})
        assert result.valid
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_validate_accepts_positive_values(self) -> None:
        """Should accept all-positive param values."""
        node = TemporalCleanupNode()
        result = await node.validate(
            {
                "min_cutoff": 1.0,
                "beta": 0.5,
                "velocity_threshold": 5.0,
                "height_threshold": 10.0,
                "hysteresis_frames": 4,
            }
        )
        assert result.valid
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_validate_rejects_negative_and_zero_thresholds(self) -> None:
        """Should reject non-positive values for every numeric threshold."""
        node = TemporalCleanupNode()
        for key in ("min_cutoff", "beta", "velocity_threshold", "height_threshold"):
            for value in (0, -1, -0.5, 0.0):
                result = await node.validate({key: value})
                assert not result.valid, f"{key}={value}"
                assert result.errors

    @pytest.mark.asyncio
    async def test_validate_rejects_bool_threshold(self) -> None:
        """Should reject booleans for numeric thresholds (bool is not a number)."""
        node = TemporalCleanupNode()
        result = await node.validate({"min_cutoff": True})
        assert not result.valid
        assert result.errors

    @pytest.mark.asyncio
    async def test_validate_rejects_non_numeric_threshold(self) -> None:
        """Should reject non-numeric threshold values."""
        node = TemporalCleanupNode()
        result = await node.validate({"velocity_threshold": "fast"})
        assert not result.valid
        assert result.errors

    @pytest.mark.asyncio
    async def test_validate_accepts_positive_int_hysteresis(self) -> None:
        """Should accept a positive integer hysteresis_frames."""
        node = TemporalCleanupNode()
        result = await node.validate({"hysteresis_frames": 4})
        assert result.valid
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_validate_rejects_zero_or_negative_hysteresis(self) -> None:
        """Should reject a zero or negative hysteresis_frames."""
        node = TemporalCleanupNode()
        for value in (0, -3):
            result = await node.validate({"hysteresis_frames": value})
            assert not result.valid, value
            assert result.errors

    @pytest.mark.asyncio
    async def test_validate_rejects_float_hysteresis(self) -> None:
        """Should reject a non-integer hysteresis_frames."""
        node = TemporalCleanupNode()
        result = await node.validate({"hysteresis_frames": 2.5})
        assert not result.valid
        assert result.errors
