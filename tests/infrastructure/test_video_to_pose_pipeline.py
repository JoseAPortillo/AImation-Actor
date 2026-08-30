"""Integration test: video-source → pose-2d → pose-3d graph execution."""

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from aimation_actor_core.domain.animation.keypoints import Keypoints2D
from aimation_actor_core.domain.animation.keypoints3d import Keypoints3D
from aimation_actor_core.domain.pipeline.graph import Edge, Graph, GraphNode, PortRef
from aimation_actor_core.infrastructure.virtual.executor import SynchronousGraphExecutor
from aimation_actor_core.infrastructure.virtual.node_registry import seeded_node_registry


class TestVideoToPosePipeline:
    """Test video-source → pose-2d graph execution."""

    @pytest.mark.asyncio
    async def test_video_source_to_pose_2d_graph(self) -> None:
        """Should execute video-source → pose-2d graph end-to-end."""
        # Create a temporary video file
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "test_video.mp4"

            # Create a synthetic video using OpenCV
            import cv2

            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            out = cv2.VideoWriter(str(video_path), fourcc, 25.0, (64, 64))
            for _ in range(5):
                frame = np.zeros((64, 64, 3), dtype=np.uint8)
                out.write(frame)
            out.release()

            # Build graph: video-source → pose-2d
            # Use relative path (video_path must be relative to media_root)
            graph = Graph(
                version="1.0",
                nodes=[
                    GraphNode(
                        id="video",
                        type="video-source",
                        params={"video_path": "test_video.mp4"},
                    ),
                    GraphNode(
                        id="pose",
                        type="pose-2d",
                        params={"model": "synthetic"},
                    ),
                ],
                edges=[
                    Edge(
                        id="e1",
                        source=PortRef(node="video", port="frames"),
                        target=PortRef(node="pose", port="frames"),
                    ),
                ],
            )

            # Execute graph
            registry = seeded_node_registry(media_root=Path(tmpdir))
            executor = SynchronousGraphExecutor()
            result = await executor.run(graph, registry)

            # Verify result
            assert "pose" in result.outputs
            pose_output = result.outputs["pose"]
            assert "keypoints" in pose_output
            keypoints_list = pose_output["keypoints"]

            # Should have keypoints for each frame
            assert isinstance(keypoints_list, list)
            assert len(keypoints_list) > 0

            # Each item should be a Keypoints2D (or dict representation)
            for kp_item in keypoints_list:
                # If it's a dict (JSON-serialized), convert to check structure
                if isinstance(kp_item, dict):
                    assert "frame_index" in kp_item
                    assert "keypoints" in kp_item
                    assert isinstance(kp_item["keypoints"], list)
                elif isinstance(kp_item, Keypoints2D):
                    assert kp_item.frame_index >= 0
                    assert isinstance(kp_item.keypoints, list)

    @pytest.mark.asyncio
    async def test_video_source_to_pose_3d_graph(self) -> None:
        """Should execute video-source → pose-2d → pose-3d end-to-end (REQ-6).

        The whole typed pipeline runs through ``SynchronousGraphExecutor`` with
        both AI stages synthetic: the 3D output must be one bounded
        :class:`Keypoints3D` per input frame, with ``frame_index`` aligned to
        the source frames and JSON-serializable containers.
        """
        # Create a temporary video file
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "test_video.mp4"

            # Create a synthetic video using OpenCV
            import cv2

            fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # type: ignore[attr-defined]
            out = cv2.VideoWriter(str(video_path), fourcc, 25.0, (64, 64))
            for _ in range(5):
                frame = np.zeros((64, 64, 3), dtype=np.uint8)
                out.write(frame)
            out.release()

            # Build graph: video-source → pose-2d → pose-3d
            graph = Graph(
                version="1.0",
                nodes=[
                    GraphNode(
                        id="video",
                        type="video-source",
                        params={"video_path": "test_video.mp4"},
                    ),
                    GraphNode(
                        id="pose",
                        type="pose-2d",
                        params={"model": "synthetic"},
                    ),
                    GraphNode(
                        id="lift",
                        type="pose-3d",
                        params={"model": "synthetic"},
                    ),
                ],
                edges=[
                    Edge(
                        id="e1",
                        source=PortRef(node="video", port="frames"),
                        target=PortRef(node="pose", port="frames"),
                    ),
                    Edge(
                        id="e2",
                        source=PortRef(node="pose", port="keypoints"),
                        target=PortRef(node="lift", port="keypoints"),
                    ),
                ],
            )

            # Execute graph
            registry = seeded_node_registry(media_root=Path(tmpdir))
            executor = SynchronousGraphExecutor()
            result = await executor.run(graph, registry)

            # Verify result
            assert "lift" in result.outputs
            lift_output = result.outputs["lift"]
            assert "keypoints_3d" in lift_output
            keypoints_3d = lift_output["keypoints_3d"]

            # Bounded: one Keypoints3D per source frame, never more.
            assert isinstance(keypoints_3d, list)
            assert len(keypoints_3d) == 5
            assert all(isinstance(item, (Keypoints3D, dict)) for item in keypoints_3d)

            # frame_index aligned with the source frames.
            frame_indices: list[int] = []
            for item in keypoints_3d:
                if isinstance(item, Keypoints3D):
                    frame_indices.append(item.frame_index)
                    assert len(item.keypoints) > 0
                else:
                    frame_indices.append(item["frame_index"])
            assert frame_indices == [0, 1, 2, 3, 4]

            # JSON-serializable containers (REQ-6).
            payload = [
                item.model_dump() if isinstance(item, Keypoints3D) else item
                for item in keypoints_3d
            ]
            json.dumps(payload)
