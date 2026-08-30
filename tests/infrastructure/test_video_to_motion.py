"""Tests for VideoToMotionNode (REQ-2)."""

from typing import Any

import pytest

from aimation_actor_core.domain.animation.keypoints3d import Keypoints3D
from aimation_actor_core.domain.animation.neutral_motion import NeutralMotion
from aimation_actor_core.domain.pipeline.node import ExecutionContext
from aimation_actor_core.domain.pipeline.schema import DataType, NodeCategory
from aimation_actor_core.infrastructure.ai_models.video_to_motion import VideoToMotionNode

# A raw job-store-style serialized frame: plain dicts, exactly as the
# persisted 3D keypoints payload deserializes before hitting the node.
RAW_KEYPOINTS: list[dict[str, Any]] = [
    {
        "frame_index": 0,
        "keypoints": [
            {"label": "nose", "x": 0.5, "y": 0.2, "z": 0.5, "confidence": 0.95},
            {"label": "left_shoulder", "x": 0.4, "y": 0.35, "z": 0.5, "confidence": 0.95},
            {"label": "right_shoulder", "x": 0.6, "y": 0.35, "z": 0.5, "confidence": 0.95},
            {"label": "left_hip", "x": 0.45, "y": 0.6, "z": 0.5, "confidence": 0.95},
            {"label": "right_hip", "x": 0.55, "y": 0.6, "z": 0.5, "confidence": 0.95},
            {"label": "left_ankle", "x": 0.45, "y": 0.9, "z": 0.5, "confidence": 0.95},
        ],
    },
    {
        "frame_index": 1,
        "keypoints": [
            {"label": "nose", "x": 0.5, "y": 0.2, "z": 0.5, "confidence": 0.95},
        ],
    },
]


def _model_frames() -> list[Keypoints3D]:
    """Build the same frames as :data:`RAW_KEYPOINTS` as Keypoints3D models."""
    return [Keypoints3D.model_validate(frame) for frame in RAW_KEYPOINTS]


class TestVideoToMotionNodeSchema:
    """Test VideoToMotionNode catalog schema."""

    def test_schema_type(self) -> None:
        """Should declare type 'video-to-motion'."""
        schema = VideoToMotionNode.get_schema()
        assert schema.type == "video-to-motion"

    def test_schema_category(self) -> None:
        """Should be an OUTPUT node."""
        schema = VideoToMotionNode.get_schema()
        assert schema.category == NodeCategory.OUTPUT

    def test_schema_inputs(self) -> None:
        """Should declare keypoints_3d: POSE_3D input port."""
        schema = VideoToMotionNode.get_schema()
        assert len(schema.inputs) == 1
        assert schema.inputs[0].name == "keypoints_3d"
        assert schema.inputs[0].data_type == DataType.POSE_3D

    def test_schema_outputs(self) -> None:
        """Should declare motion: NEUTRAL_ANIMATION output port."""
        schema = VideoToMotionNode.get_schema()
        assert len(schema.outputs) == 1
        assert schema.outputs[0].name == "motion"
        assert schema.outputs[0].data_type == DataType.NEUTRAL_ANIMATION

    def test_schema_params(self) -> None:
        """Should declare person_height_cm and only_local params with defaults."""
        schema = VideoToMotionNode.get_schema()
        param_names = [p.name for p in schema.params]
        assert param_names == ["person_height_cm", "only_local"]

        height_param = next(p for p in schema.params if p.name == "person_height_cm")
        assert height_param.data_type == DataType.NUMBER
        assert not height_param.required
        assert height_param.default == 172.0

        local_param = next(p for p in schema.params if p.name == "only_local")
        assert local_param.data_type == DataType.BOOLEAN
        assert not local_param.required
        assert local_param.default is True


class TestVideoToMotionNodeExecute:
    """Test VideoToMotionNode execution."""

    @pytest.fixture
    def context(self) -> ExecutionContext:
        """Create an execution context."""
        return ExecutionContext(trace_id="test-trace")

    @pytest.mark.asyncio
    async def test_execute_returns_neutral_motion(self, context: ExecutionContext) -> None:
        """Should return a populated NeutralMotion from Keypoints3D models."""
        node = VideoToMotionNode()
        result = await node.execute(
            inputs={"keypoints_3d": _model_frames()},
            params={},
            context=context,
        )
        motion = result.values["motion"]
        assert isinstance(motion, NeutralMotion)
        # Two input frames -> two 1-based frames.
        assert [frame.frame for frame in motion.frames] == [1, 2]
        assert len(motion.frames[0].pose.transforms) > 0

    @pytest.mark.asyncio
    async def test_execute_dict_inputs_coerce_to_keypoints3d(
        self, context: ExecutionContext
    ) -> None:
        """Should coerce raw dict frames (job-store serialized path) into Keypoints3D."""
        node = VideoToMotionNode()
        result = await node.execute(
            inputs={"keypoints_3d": RAW_KEYPOINTS},
            params={},
            context=context,
        )
        motion = result.values["motion"]
        assert [frame.frame for frame in motion.frames] == [1, 2]

    @pytest.mark.asyncio
    async def test_execute_invalid_label_skips_bone_never_fails(
        self, context: ExecutionContext
    ) -> None:
        """Should ignore unknown/misspelled labels without raising."""
        node = VideoToMotionNode()
        bad = [
            {
                "frame_index": 0,
                "keypoints": [
                    {"label": "nose", "x": 0.5, "y": 0.2, "z": 0.5, "confidence": 0.95},
                    {"label": "not_a_real_bone", "x": 0.1, "y": 0.1, "z": 0.1, "confidence": 0.9},
                    {"label": "eyes", "x": 0.5, "y": 0.2, "z": 0.5, "confidence": 0.9},
                ],
            }
        ]
        result = await node.execute(inputs={"keypoints_3d": bad}, params={}, context=context)
        motion = result.values["motion"]
        assert len(motion.frames) == 1
        assert motion.frames[0].frame == 1

    @pytest.mark.asyncio
    async def test_execute_empty_input_returns_empty_motion_with_skeleton(
        self, context: ExecutionContext
    ) -> None:
        """Should return an empty NeutralMotion carrying the default skeleton."""
        node = VideoToMotionNode()
        result = await node.execute(inputs={"keypoints_3d": []}, params={}, context=context)
        motion = result.values["motion"]
        assert isinstance(motion, NeutralMotion)
        assert motion.frames == []
        # The empty motion still carries the default neutral skeleton.
        assert len(motion.skeleton.bones) > 0

    @pytest.mark.asyncio
    async def test_execute_output_is_json_safe(self, context: ExecutionContext) -> None:
        """Should yield valid JSON via model_dump_json (REQ-2 JSON-safe)."""
        node = VideoToMotionNode()
        result = await node.execute(
            inputs={"keypoints_3d": _model_frames()},
            params={},
            context=context,
        )
        motion = result.values["motion"]
        import json

        payload = json.loads(motion.model_dump_json())
        assert len(payload["frames"]) == 2

    @pytest.mark.asyncio
    async def test_uses_asyncio_to_thread(self, context: ExecutionContext) -> None:
        """Should offload the conversion to a worker thread via asyncio.to_thread."""
        import asyncio

        node = VideoToMotionNode()
        original_to_thread = asyncio.to_thread
        calls: list[tuple[Any, tuple[Any, ...]]] = []

        async def mock_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            calls.append((func, args))
            return await original_to_thread(func, *args, **kwargs)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(asyncio, "to_thread", mock_to_thread)
        try:
            result = await node.execute(
                inputs={"keypoints_3d": _model_frames()},
                params={},
                context=context,
            )
            assert len(calls) > 0
            assert calls[0][0].__name__ == "convert_keypoints_to_motion"
            assert len(result.values["motion"].frames) == 2
        finally:
            monkeypatch.undo()


class TestVideoToMotionNodeValidate:
    """Test VideoToMotionNode parameter validation (D6).

    ``person_height_cm`` — when provided — must be a positive number;
    booleans and non-numeric values are rejected. ``only_local`` must be a
    boolean when provided. Omitted params are always OK (both optional).
    """

    @pytest.mark.asyncio
    async def test_validate_empty_params(self) -> None:
        """Should accept empty params (all params are optional)."""
        node = VideoToMotionNode()
        result = await node.validate({})
        assert result.valid
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_validate_accepts_positive_height(self) -> None:
        """Should accept a positive person_height_cm number."""
        node = VideoToMotionNode()
        result = await node.validate({"person_height_cm": 185.0})
        assert result.valid
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_validate_rejects_non_positive_height(self) -> None:
        """Should reject a non-positive person_height_cm value."""
        node = VideoToMotionNode()
        for value in (0, -1, 0.0):
            result = await node.validate({"person_height_cm": value})
            assert not result.valid, value
            assert result.errors

    @pytest.mark.asyncio
    async def test_validate_rejects_non_numeric_height(self) -> None:
        """Should reject a non-numeric person_height_cm value."""
        node = VideoToMotionNode()
        result = await node.validate({"person_height_cm": "tall"})
        assert not result.valid
        assert result.errors

    @pytest.mark.asyncio
    async def test_validate_rejects_boolean_height(self) -> None:
        """Should reject a boolean person_height_cm value (bool is not a number)."""
        node = VideoToMotionNode()
        result = await node.validate({"person_height_cm": True})
        assert not result.valid
        assert result.errors

    @pytest.mark.asyncio
    async def test_validate_accepts_boolean_only_local(self) -> None:
        """Should accept a boolean only_local value."""
        node = VideoToMotionNode()
        result = await node.validate({"only_local": True})
        assert result.valid
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_validate_rejects_non_boolean_only_local(self) -> None:
        """Should reject a non-boolean only_local value."""
        node = VideoToMotionNode()
        result = await node.validate({"only_local": "yes"})
        assert not result.valid
        assert result.errors
