"""Tests for InbetweenGenerationNode (REQ inbetween-generation / §12.5).

Mirrors the ``TemporalCleanupNode`` test pattern: catalog schema assertions,
``execute`` returns a :class:`NeutralMotion` (with dict coercion for the
job-store serialized path and ``asyncio.to_thread`` offload to
``enrich_motion``), and ``validate`` enforces the five enrichment params with
their defaults and rejects invalid enum/range/fps/bool values (VALIDATE).
"""

from __future__ import annotations

from typing import Any

import pytest

from aimation_actor_core.domain.animation.entities import Frame, Pose, Transform3D
from aimation_actor_core.domain.animation.neutral_motion import NeutralMotion
from aimation_actor_core.domain.animation.skeleton_presets import DEFAULT_NEUTRAL_SKELETON
from aimation_actor_core.domain.pipeline.node import ExecutionContext
from aimation_actor_core.domain.pipeline.schema import DataType, NodeCategory
from aimation_actor_core.infrastructure.ai_models.inbetween_generation import (
    InbetweenGenerationNode,
)


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


class TestInbetweenGenerationNodeSchema:
    """Test InbetweenGenerationNode catalog schema."""

    def test_schema_type(self) -> None:
        """Should declare type 'inbetween-generation'."""
        schema = InbetweenGenerationNode.get_schema()
        assert schema.type == "inbetween-generation"

    def test_schema_category(self) -> None:
        """Should be an ENRICHMENT node."""
        schema = InbetweenGenerationNode.get_schema()
        assert schema.category == NodeCategory.ENRICHMENT

    def test_schema_inputs(self) -> None:
        """Should declare motion: NEUTRAL_ANIMATION input port."""
        schema = InbetweenGenerationNode.get_schema()
        assert len(schema.inputs) == 1
        assert schema.inputs[0].name == "motion"
        assert schema.inputs[0].data_type == DataType.NEUTRAL_ANIMATION

    def test_schema_outputs(self) -> None:
        """Should declare motion: NEUTRAL_ANIMATION output port."""
        schema = InbetweenGenerationNode.get_schema()
        assert len(schema.outputs) == 1
        assert schema.outputs[0].name == "motion"
        assert schema.outputs[0].data_type == DataType.NEUTRAL_ANIMATION

    def test_schema_params(self) -> None:
        """Should declare the five enrichment params with their defaults."""
        schema = InbetweenGenerationNode.get_schema()
        param_names = [p.name for p in schema.params]
        assert param_names == [
            "interpolation_method",
            "target_fps",
            "easing",
            "euler_filter",
            "tangent_smoothing",
        ]
        defaults = {p.name: p.default for p in schema.params}
        assert defaults["interpolation_method"] == "cubic"
        assert defaults["target_fps"] == 30.0
        assert defaults["easing"] == "none"
        assert defaults["euler_filter"] is True
        assert defaults["tangent_smoothing"] == 0.0


class TestInbetweenGenerationNodeExecute:
    """Test InbetweenGenerationNode execution."""

    @pytest.fixture
    def context(self) -> ExecutionContext:
        """Create an execution context."""
        return ExecutionContext(trace_id="test-trace")

    @pytest.mark.asyncio
    async def test_execute_returns_enriched_neutral_motion(self, context: ExecutionContext) -> None:
        """Should return an enriched NeutralMotion (upto target_fps)."""
        node = InbetweenGenerationNode()
        result = await node.execute(
            inputs={"motion": _motion()},
            params={"target_fps": 120.0},
            context=context,
        )
        motion = result.values["motion"]
        assert isinstance(motion, NeutralMotion)
        # 2 frames at 24fps -> 6 frames at 120fps (upsample ran).
        assert [f.frame for f in motion.frames] == [1, 2, 3, 4, 5, 6]
        # The motion must still satisfy the neutral-motion invariants.
        motion.validate_invariants()

    @pytest.mark.asyncio
    async def test_execute_dict_inputs_coerce_to_neutral_motion(
        self, context: ExecutionContext
    ) -> None:
        """Should coerce raw dict motion (job-store serialized path) into NeutralMotion."""
        node = InbetweenGenerationNode()
        raw = _motion().model_dump()
        result = await node.execute(
            inputs={"motion": raw}, params={"target_fps": 120.0}, context=context
        )
        motion = result.values["motion"]
        assert isinstance(motion, NeutralMotion)
        assert [f.frame for f in motion.frames] == [1, 2, 3, 4, 5, 6]

    @pytest.mark.asyncio
    async def test_uses_asyncio_to_thread(self, context: ExecutionContext) -> None:
        """Should offload enrichment to a worker thread via asyncio.to_thread."""
        import asyncio

        node = InbetweenGenerationNode()
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
                params={"target_fps": 120.0},
                context=context,
            )
            assert len(calls) > 0
            assert calls[0][0].__name__ == "enrich_motion"
            assert isinstance(result.values["motion"], NeutralMotion)
        finally:
            monkeypatch.undo()


class TestInbetweenGenerationNodeValidate:
    """Test InbetweenGenerationNode parameter validation (VALIDATE).

    ``interpolation_method`` in {"linear","cubic"}, ``easing`` in
    {"none","ease-in","ease-out","ease-in-out"}, ``euler_filter`` boolean,
    ``tangent_smoothing`` in [0,1], ``target_fps`` positive. Omitted params
    are OK (defaults apply).
    """

    @pytest.mark.asyncio
    async def test_validate_empty_params(self) -> None:
        """Should accept empty params (defaults are valid)."""
        node = InbetweenGenerationNode()
        result = await node.validate({})
        assert result.valid
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_validate_accepts_valid_params(self) -> None:
        """Should accept valid enum/range/fps/bool params."""
        node = InbetweenGenerationNode()
        result = await node.validate(
            {
                "interpolation_method": "linear",
                "easing": "ease-in-out",
                "euler_filter": False,
                "tangent_smoothing": 0.5,
                "target_fps": 60,
            }
        )
        assert result.valid
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_validate_rejects_invalid_enum(self) -> None:
        """Should reject unknown interpolation/easing enum values."""
        node = InbetweenGenerationNode()
        for key, value in (("interpolation_method", "spline"), ("easing", "bounce")):
            result = await node.validate({key: value})
            assert not result.valid, f"{key}={value}"
            assert result.errors

    @pytest.mark.asyncio
    async def test_validate_rejects_out_of_range_smoothing(self) -> None:
        """Should reject tangent_smoothing outside [0, 1]."""
        node = InbetweenGenerationNode()
        for value in (1.5, -0.1):
            result = await node.validate({"tangent_smoothing": value})
            assert not result.valid, value
            assert result.errors

    @pytest.mark.asyncio
    async def test_validate_rejects_non_positive_fps(self) -> None:
        """Should reject target_fps <= 0."""
        node = InbetweenGenerationNode()
        for value in (0, -30):
            result = await node.validate({"target_fps": value})
            assert not result.valid, value
            assert result.errors

    @pytest.mark.asyncio
    async def test_validate_rejects_bool_as_numeric(self) -> None:
        """Should reject booleans where a number is required (bool is int)."""
        node = InbetweenGenerationNode()
        for key in ("tangent_smoothing", "target_fps"):
            result = await node.validate({key: True})
            assert not result.valid, f"{key}=True"
            assert result.errors

    @pytest.mark.asyncio
    async def test_validate_rejects_non_bool_euler_filter(self) -> None:
        """Should reject a non-boolean euler_filter."""
        node = InbetweenGenerationNode()
        result = await node.validate({"euler_filter": "yes"})
        assert not result.valid
        assert result.errors
