"""Round-trip tests for the binary FBX codec."""

from __future__ import annotations

import pytest

from aimation_actor.adapters.io.fbx import binary
from aimation_actor.adapters.io.fbx.binary import FBXNode


def test_round_trip_preserves_names_props_and_children() -> None:
    objects = FBXNode("Objects")
    model = objects.child("Model").add(binary.int64(1), binary.string("Main"))
    model.child("Version").add(binary.int32(232))
    model.child("Shading").add(binary.char(b"\x00"))

    parsed = binary.parse(binary.serialize([objects, FBXNode("Connections")]))

    assert [node.name for node in parsed] == ["Objects", "Connections"]
    (parsed_model,) = parsed[0].children
    assert parsed_model.name == "Model"
    assert parsed_model.props[0].value == 1
    assert parsed_model.props[1].value == "Main"
    assert parsed_model.find("Version").props[0].value == 232
    assert parsed_model.find("Shading").props[0].value == b"\x00"


def test_round_trip_preserves_typed_arrays() -> None:
    ints = list(range(500))  # > 128 bytes, so it takes the zlib-compressed path.
    floats = [value / 3.0 for value in range(200)]
    node = FBXNode("KeyTime").add(binary.int64_array(ints), binary.float32_array(floats))

    parsed = binary.parse(binary.serialize([node]))

    assert list(parsed[0].props[0].value) == ints
    assert list(parsed[0].props[1].value) == pytest.approx(floats)


def test_parse_rejects_a_foreign_magic() -> None:
    with pytest.raises(ValueError, match="magic"):
        binary.parse(b"not an fbx file, not at all........")


@pytest.mark.parametrize(
    ("factory", "value"),
    [
        (binary.int16, 2**15),
        (binary.int16, -(2**15) - 1),
        (binary.int32, 2**31),
        (binary.int32, -(2**31) - 1),
        (binary.int64, 2**63),
        (binary.int64, -(2**63) - 1),
    ],
)
def test_integer_properties_reject_out_of_range_values(factory, value: int) -> None:
    with pytest.raises(ValueError, match="does not fit"):
        factory(value)


def test_integer_arrays_reject_out_of_range_values() -> None:
    with pytest.raises(ValueError, match="does not fit"):
        binary.int32_array([0, 2**31])
    with pytest.raises(ValueError, match="does not fit"):
        binary.int64_array([0, 2**63])


def test_coerce_rejects_integers_beyond_int64() -> None:
    with pytest.raises(ValueError, match="does not fit"):
        binary.coerce(2**63)
    # In-range values keep their int32/int64 tagging.
    assert binary.coerce(7).tag == binary.int32(0).tag
    assert binary.coerce(2**32).tag == binary.int64(0).tag
