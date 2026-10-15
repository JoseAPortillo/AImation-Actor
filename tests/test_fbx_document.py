"""Structural tests for the FBX node tree built from a timeline."""

from __future__ import annotations

import dataclasses

import pytest

from aimation_actor.adapters.io.fbx import binary, document
from aimation_actor.adapters.io.fbx.binary import FBXNode
from aimation_actor.core.models import TimelineState


def _parse(state: TimelineState) -> dict[str, FBXNode]:
    nodes = binary.parse(binary.serialize(document.build_document(state)))
    return {node.name: node for node in nodes}


def _time(frame: int, fps: float) -> int:
    return round(frame / fps * document.KTIME)


def _models(objects: FBXNode) -> dict[str, FBXNode]:
    return {
        node.props[1].value.split("\x00")[0]: node for node in objects.find_all("Model")
    }


def _links(connections: FBXNode) -> list[FBXNode]:
    return connections.find_all("C")


def _property(node: FBXNode, name: str) -> FBXNode:
    return next(child for child in node.children if child.props[0].value == name)


def _global_setting(parsed: dict[str, FBXNode], name: str):
    properties = parsed["GlobalSettings"].find("Properties70")
    return _property(properties, name).props[-1].value


def _animation_channels(
    parsed: dict[str, FBXNode],
) -> dict[str, dict[str, dict[str, tuple[float, ...]]]]:
    """``joint -> property -> component -> key values`` for the whole document."""
    objects, connections = parsed["Objects"], parsed["Connections"]
    ids = {name: node.props[0].value for name, node in _models(objects).items()}
    name_by_id = {value: name for name, value in ids.items()}
    curves = {node.props[0].value: node for node in objects.find_all("AnimationCurve")}

    channels: dict[int, tuple[str, str]] = {}
    for node in _links(connections):
        if node.props[0].value == "OP" and node.props[2].value in name_by_id:
            channels[node.props[1].value] = (name_by_id[node.props[2].value], node.props[3].value)

    result: dict[str, dict[str, dict[str, tuple[float, ...]]]] = {}
    for node in _links(connections):
        if node.props[0].value != "OP" or node.props[2].value not in channels:
            continue
        joint, property_name = channels[node.props[2].value]
        component = node.props[3].value
        values = tuple(curves[node.props[1].value].find("KeyValueFloat").props[0].value)
        result.setdefault(joint, {}).setdefault(property_name, {})[component] = values
    return result


def test_header_and_global_settings(sample_state: TimelineState) -> None:
    parsed = _parse(sample_state)

    assert parsed["FBXHeaderExtension"].find("FBXVersion").props[0].value == 7400
    assert _global_setting(parsed, "UpAxis") == 1  # Y-up
    assert _global_setting(parsed, "FrontAxis") == 2  # Z-forward
    assert _global_setting(parsed, "UnitScaleFactor") == pytest.approx(1.0)  # centimetres


def test_models_follow_the_hierarchy_root_first(sample_state: TimelineState) -> None:
    parsed = _parse(sample_state)
    objects = parsed["Objects"]
    ids = {name: node.props[0].value for name, node in _models(objects).items()}

    assert list(_models(objects)) == ["Main", "Pelvis", "Spine_1", "Spine_2", "Head"]
    links = {
        (node.props[0].value, node.props[1].value, node.props[2].value)
        for node in _links(parsed["Connections"])
    }
    assert ("OO", ids["Pelvis"], ids["Main"]) in links
    assert ("OO", ids["Spine_1"], ids["Pelvis"]) in links
    assert ("OO", ids["Head"], ids["Spine_2"]) in links
    assert ("OO", ids["Main"], 0) in links


def test_pelvis_rest_translation_is_mapped_to_y_up(sample_state: TimelineState) -> None:
    model = _models(_parse(sample_state)["Objects"])["Pelvis"]
    translation = _property(model.find("Properties70"), "Lcl Translation")
    assert [prop.value for prop in translation.props[-3:]] == pytest.approx([0.0, 100.0, 0.0])


def test_keys_are_sparse_sorted_and_stepped(sample_state: TimelineState) -> None:
    objects = _parse(sample_state)["Objects"]
    times = [_time(15, 24.0), _time(42, 24.0)]

    curves = objects.find_all("AnimationCurve")
    assert curves
    for curve in curves:
        assert list(curve.find("KeyTime").props[0].value) == times
        assert list(curve.find("KeyAttrFlags").props[0].value) == [24836]  # constant


def test_only_animated_channels_are_written(sample_state: TimelineState) -> None:
    channels = _animation_channels(_parse(sample_state))

    assert set(channels) == {"Main", "Spine_1", "Head"}  # Spine_2 never moves.
    assert set(channels["Main"]) == {"Lcl Translation"}
    assert set(channels["Spine_1"]) == {"Lcl Rotation"}


def test_channel_values_match_the_domain_poses(sample_state: TimelineState) -> None:
    channels = _animation_channels(_parse(sample_state))

    # Main: domain (10, 0, 0) then (20, 5, 0) -> FBX (x, z, -y).
    assert channels["Main"]["Lcl Translation"]["d|X"] == pytest.approx((10.0, 20.0))
    assert channels["Main"]["Lcl Translation"]["d|Y"] == pytest.approx((0.0, 0.0))
    assert channels["Main"]["Lcl Translation"]["d|Z"] == pytest.approx((0.0, -5.0))
    # Spine_1: Z 30 deg then the 120-deg (1, 1, 1) rotation -> FBX Euler (0,30,0) and (90,90,0).
    assert channels["Spine_1"]["Lcl Rotation"]["d|Y"] == pytest.approx((30.0, 90.0))
    # Head: only keyed at frame 42 (identity at frame 15).
    assert channels["Head"]["Lcl Rotation"]["d|X"] == pytest.approx((0.0, 60.0))


def test_definitions_list_only_real_object_types(sample_state: TimelineState) -> None:
    definitions = _parse(sample_state)["Definitions"]
    object_types = {
        node.props[0].value: node.find("Count").props[0].value
        for node in definitions.find_all("ObjectType")
    }

    # ``GlobalSettings`` is a top-level section, never an FBX object.
    assert "GlobalSettings" not in object_types
    assert object_types["Model"] == 5  # Main, Pelvis, Spine_1, Spine_2, Head.
    assert object_types["NodeAttribute"] == 5
    # The declared total must match the sum of the per-type counts.
    assert definitions.find("Count").props[0].value == sum(object_types.values())


def test_build_document_rejects_duplicate_frames(sample_state: TimelineState) -> None:
    duplicated = dataclasses.replace(
        sample_state, keyframes=(*sample_state.keyframes, sample_state.keyframes[0])
    )

    with pytest.raises(ValueError, match="duplicated frames: \\[15\\]"):
        document.build_document(duplicated)
