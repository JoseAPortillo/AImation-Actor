"""Binary FBX 7.4 (``FBX7400``) container encoding and decoding.

An independent implementation of the FBX binary format (header, nested node
records, typed properties, array encoding, and footer). It is deliberately
low-level: it knows nothing about skeletons or animation, only about the
container. :mod:`~aimation_actor.adapters.io.fbx.document` maps the domain onto
this container.

Format notes (FBX 7.4, i.e. versions below 7500):

- Header: 23-byte magic ``Kaydara FBX Binary  \\x00\\x1a\\x00`` then a
  little-endian ``uint32`` version.
- A node record is a 12-byte little-endian ``(end_offset, num_props,
  props_length)``, a ``uint8`` name length, the name, then the typed properties,
  then the nested children.
- Every list of children is terminated by a 13-byte all-zero sentinel record.
  A property-less, child-less node still needs that sentinel unless it is the
  last sibling, so that readers can tell ``P:`` (leaf) from ``P: {}`` (empty
  block). ``AnimationStack``/``AnimationLayer`` are always written as blocks.
- Arrays may be stored raw (encoding ``0``) or zlib-deflated (encoding ``1``).

This module imports only the standard library.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from typing import Any

HEADER_MAGIC = b"Kaydara FBX Binary  \x00\x1a\x00"
FBX_VERSION = 7400

# Fixed FileId / creation time that Autodesk writes when it does not decode the
# file timestamp; mirroring them keeps the output byte-compatible.
DEFAULT_FILE_ID = bytes(
    (0x28, 0xB3, 0x2A, 0xEB, 0xB6, 0x24, 0xCC, 0xC2, 0xBF, 0xC8, 0xB0, 0x2A, 0xA9, 0x2B, 0xFC, 0xF1)
)
DEFAULT_TIME_ID = "1970-01-01 10:00:00:000"

_FOOTER_ID = bytes(
    (0xFA, 0xBC, 0xAB, 0x09, 0xD0, 0xC8, 0xD4, 0x66, 0xB1, 0x76, 0xFB, 0x83, 0x1C, 0xF7, 0x26, 0x7E)
)
_FOOTER_TAIL = bytes(
    (0xF8, 0x5A, 0x8C, 0x6A, 0xDE, 0xF5, 0xD9, 0x7E, 0xEC, 0xE9, 0x0C, 0xE3, 0x75, 0x8F, 0x29, 0x0B)
)

_META = struct.Struct("<3I")
_SENTINEL = b"\x00" * 13

# Node names that must be written as (possibly empty) blocks.
_ALWAYS_BLOCK = frozenset({"AnimationStack", "AnimationLayer"})

# Property type tags.
_T_BOOL = ord("B")
_T_CHAR = ord("C")
_T_I8 = ord("Z")
_T_I16 = ord("Y")
_T_I32 = ord("I")
_T_I64 = ord("L")
_T_F32 = ord("F")
_T_F64 = ord("D")
_T_RAW = ord("R")
_T_STR = ord("S")
_T_I32A = ord("i")
_T_I64A = ord("l")
_T_F32A = ord("f")
_T_F64A = ord("d")
_T_BOOLA = ord("b")
_T_BYTEA = ord("c")

#: Property tags whose payload is an array (as opposed to a scalar).
_ARRAY_TAGS = frozenset({_T_BOOLA, _T_BYTEA, _T_I32A, _T_I64A, _T_F32A, _T_F64A})

#: Inclusive-exclusive ranges for the signed integer FBX types.
_I16_RANGE = (-(2**15), 2**15)
_I32_RANGE = (-(2**31), 2**31)
_I64_RANGE = (-(2**63), 2**63)

#: ``struct`` format per scalar tag (strings are length-prefixed, not here).
_SCALAR_FORMATS = {
    _T_BOOL: "<?",
    _T_CHAR: "<c",
    _T_I8: "<b",
    _T_I16: "<h",
    _T_I32: "<i",
    _T_I64: "<q",
    _T_F32: "<f",
    _T_F64: "<d",
}

#: ``struct`` format per numeric array tag.
_ARRAY_FORMATS = {
    _T_I32A: "i",
    _T_I64A: "q",
    _T_F32A: "f",
    _T_F64A: "d",
}

#: Array payloads longer than this many bytes are zlib-deflated (encoding ``1``).
_ARRAY_COMPRESS_THRESHOLD = 128


@dataclass(frozen=True, slots=True)
class Prop:
    """A single typed FBX property."""

    tag: int
    value: Any


def string(text: str) -> Prop:
    """An FBX string (``S``) property."""
    return Prop(_T_STR, text.encode("utf-8"))


def raw(data: bytes) -> Prop:
    """An FBX raw-bytes (``R``) property."""
    return Prop(_T_RAW, bytes(data))


def boolean(value: bool) -> Prop:
    """An FBX bool (``B``) property."""
    return Prop(_T_BOOL, bool(value))


def char(value: bytes) -> Prop:
    """An FBX char (``C``) property (exactly one byte)."""
    if len(value) != 1:
        raise ValueError("an FBX char property holds exactly one byte")
    return Prop(_T_CHAR, bytes(value))


def _checked_int(value: Any, bounds: tuple[int, int], type_name: str) -> int:
    """Return ``value`` as an ``int``, or raise if it does not fit ``type_name``."""
    number = int(value)
    low, high = bounds
    if not low <= number < high:
        raise ValueError(f"{number} does not fit in an FBX {type_name} property")
    return number


def int16(value: int) -> Prop:
    """An FBX 16-bit int (``Y``) property."""
    return Prop(_T_I16, _checked_int(value, _I16_RANGE, "16-bit int"))


def int32(value: int) -> Prop:
    """An FBX 32-bit int (``I``) property."""
    return Prop(_T_I32, _checked_int(value, _I32_RANGE, "32-bit int"))


def int64(value: int) -> Prop:
    """An FBX 64-bit int (``L``) property."""
    return Prop(_T_I64, _checked_int(value, _I64_RANGE, "64-bit int"))


def float32(value: float) -> Prop:
    """An FBX 32-bit float (``F``) property."""
    return Prop(_T_F32, float(value))


def float64(value: float) -> Prop:
    """An FBX 64-bit float (``D``) property."""
    return Prop(_T_F64, float(value))


def int32_array(values: Any) -> Prop:
    """An FBX 32-bit int array (``i``) property."""
    return Prop(_T_I32A, tuple(_checked_int(v, _I32_RANGE, "32-bit int") for v in values))


def int64_array(values: Any) -> Prop:
    """An FBX 64-bit int array (``l``) property."""
    return Prop(_T_I64A, tuple(_checked_int(v, _I64_RANGE, "64-bit int") for v in values))


def float32_array(values: Any) -> Prop:
    """An FBX 32-bit float array (``f``) property."""
    return Prop(_T_F32A, tuple(float(v) for v in values))


def float64_array(values: Any) -> Prop:
    """An FBX 64-bit float array (``d``) property."""
    return Prop(_T_F64A, tuple(float(v) for v in values))


def coerce(value: Any) -> Prop:
    """Auto-tag a plain Python value (``str``/``bytes``/``bool``/``int``/``float``)."""
    if isinstance(value, Prop):
        return value
    if isinstance(value, bool):
        return boolean(value)
    if isinstance(value, int):
        if _I32_RANGE[0] <= value < _I32_RANGE[1]:
            return int32(value)
        return int64(value)
    if isinstance(value, float):
        return float64(value)
    if isinstance(value, str):
        return string(value)
    if isinstance(value, (bytes, bytearray)):
        return raw(value)
    raise TypeError(f"cannot coerce {type(value).__name__!r} into an FBX property")


@dataclass(slots=True)
class FBXNode:
    """A named FBX node: a list of typed properties plus child nodes."""

    name: str
    props: list[Prop] = field(default_factory=list)
    children: list[FBXNode] = field(default_factory=list)

    @property
    def name_bytes(self) -> bytes:
        return self.name.encode("utf-8")

    def add(self, *values: Any) -> FBXNode:
        """Append properties (auto-coerced) and return ``self``."""
        self.props.extend(coerce(value) for value in values)
        return self

    def child(self, name: str, *values: Any) -> FBXNode:
        """Create, attach, and return a child node."""
        node = FBXNode(name)
        node.props.extend(coerce(value) for value in values)
        self.children.append(node)
        return node

    def find(self, name: str) -> FBXNode | None:
        """Return the first direct child named ``name``, or ``None``."""
        for node in self.children:
            if node.name == name:
                return node
        return None

    def find_all(self, name: str) -> list[FBXNode]:
        """Return every direct child named ``name``."""
        return [node for node in self.children if node.name == name]


def _encode_prop(prop: Prop) -> bytes:
    tag = prop.tag
    value = prop.value
    if tag in (_T_STR, _T_RAW):
        payload = bytes(value)
        return bytes((tag,)) + struct.pack("<I", len(payload)) + payload
    if tag == _T_CHAR:
        return bytes((tag,)) + bytes(value)
    if tag in _SCALAR_FORMATS:
        return bytes((tag,)) + struct.pack(_SCALAR_FORMATS[tag], value)
    if tag in _ARRAY_FORMATS:
        data = struct.pack("<" + _ARRAY_FORMATS[tag] * len(value), *value)
        return bytes((tag,)) + _encode_array(len(value), data)
    if tag in (_T_BOOLA, _T_BYTEA):
        data = bytes(1 if v else 0 for v in value) if tag == _T_BOOLA else bytes(value)
        return bytes((tag,)) + _encode_array(len(value), data)
    raise ValueError(f"unsupported FBX property tag {tag!r}")


def _encode_array(count: int, data: bytes) -> bytes:
    if len(data) > _ARRAY_COMPRESS_THRESHOLD:
        compressed = zlib.compress(data, 1)
        return struct.pack("<3I", count, 1, len(compressed)) + compressed
    return struct.pack("<3I", count, 0, len(data)) + data


def _write_node(out: bytearray, node: FBXNode, is_last: bool) -> None:
    name = node.name_bytes
    start = len(out)
    out += _META.pack(0, 0, 0)  # placeholder: end_offset, num_props, props_length
    out += bytes((len(name),))
    out += name

    props_start = len(out)
    for prop in node.props:
        out += _encode_prop(prop)
    props_length = len(out) - props_start

    if node.children:
        last_index = len(node.children) - 1
        for index, child in enumerate(node.children):
            _write_node(out, child, index == last_index)
        out += _SENTINEL
    elif (not node.props and not is_last) or node.name in _ALWAYS_BLOCK:
        out += _SENTINEL

    _META.pack_into(out, start, len(out), len(node.props), props_length)


def serialize(
    nodes: list[FBXNode],
    *,
    version: int = FBX_VERSION,
) -> bytes:
    """Serialize top-level ``nodes`` into a complete binary FBX document."""
    if version >= 7500:
        raise ValueError("only FBX versions below 7500 (32-bit records) are supported")

    out = bytearray()
    out += HEADER_MAGIC
    out += struct.pack("<I", version)

    last_index = len(nodes) - 1
    for index, node in enumerate(nodes):
        _write_node(out, node, index == last_index)
    out += _SENTINEL

    out += _FOOTER_ID
    out += b"\x00" * 4
    offset = len(out)
    pad = ((offset + 15) & ~15) - offset
    if pad == 0:
        pad = 16
    out += b"\x00" * pad
    out += struct.pack("<I", version)
    out += b"\x00" * 120
    out += _FOOTER_TAIL
    return bytes(out)


# --------------------------------------------------------------------------- #
# Decoding (used by tests and diagnostics; keeps the encoder honest.)
# --------------------------------------------------------------------------- #


def _read_scalar(tag: int, data: bytes, offset: int) -> tuple[Any, int]:
    if tag in (_T_STR, _T_RAW):
        (length,) = struct.unpack_from("<I", data, offset)
        offset += 4
        value: Any = data[offset : offset + length]
        if tag == _T_STR:
            value = value.decode("utf-8")
        return value, offset + length
    fmt, size = _SCALAR_FORMATS[tag], struct.calcsize(_SCALAR_FORMATS[tag])
    value = struct.unpack_from(fmt, data, offset)[0]
    return value, offset + size


def _read_array(tag: int, data: bytes, offset: int) -> tuple[tuple[Any, ...], int]:
    count, encoding, length = struct.unpack_from("<3I", data, offset)
    offset += 12
    payload = data[offset : offset + length]
    offset += length
    if encoding == 1:
        payload = zlib.decompress(payload)
    if tag == _T_BOOLA:
        values = tuple(bool(v) for v in payload)
    elif tag == _T_BYTEA:
        values = tuple(payload)
    else:
        fmt = "<" + _ARRAY_FORMATS[tag] * count
        values = struct.unpack(fmt, payload)
    return values, offset


def _read_node(data: bytes, offset: int) -> tuple[FBXNode | None, int]:
    end_offset, num_props, _props_length = _META.unpack_from(data, offset)
    if end_offset == 0:
        return None, offset + 13
    (name_length,) = struct.unpack_from("<B", data, offset + 12)
    offset += 13
    name = data[offset : offset + name_length].decode("utf-8")
    offset += name_length

    node = FBXNode(name)
    for _ in range(num_props):
        tag = data[offset]
        offset += 1
        if tag in _ARRAY_TAGS:
            value, offset = _read_array(tag, data, offset)
        else:
            value, offset = _read_scalar(tag, data, offset)
        node.props.append(Prop(tag, value))

    while offset < end_offset - 13:
        child, offset = _read_node(data, offset)
        if child is None:
            break
        node.children.append(child)
    if offset < end_offset:
        offset = end_offset
    return node, offset


def parse(data: bytes) -> list[FBXNode]:
    """Parse a complete binary FBX document into its top-level nodes."""
    if not data.startswith(HEADER_MAGIC):
        raise ValueError("not a binary FBX file (bad header magic)")
    (version,) = struct.unpack_from("<I", data, len(HEADER_MAGIC))
    if version >= 7500:
        raise ValueError(f"unsupported FBX version {version} (only < 7500)")
    offset = len(HEADER_MAGIC) + 4

    nodes: list[FBXNode] = []
    while True:
        node, offset = _read_node(data, offset)
        if node is None:
            break
        nodes.append(node)
    return nodes
