from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

GGUF_MAGIC = b"GGUF"
MAX_METADATA_ENTRIES = 100_000
MAX_STRING_BYTES = 16 * 1024 * 1024
MAX_ARRAY_ITEMS = 1_000_000
MAX_MATERIALIZED_ARRAY_ITEMS = 256
MAX_NESTING = 4
DISCARD_CHUNK_BYTES = 64 * 1024

VALUE_UINT8 = 0
VALUE_INT8 = 1
VALUE_UINT16 = 2
VALUE_INT16 = 3
VALUE_UINT32 = 4
VALUE_INT32 = 5
VALUE_FLOAT32 = 6
VALUE_BOOL = 7
VALUE_STRING = 8
VALUE_ARRAY = 9
VALUE_UINT64 = 10
VALUE_INT64 = 11
VALUE_FLOAT64 = 12

SCALARS: dict[int, tuple[str, int]] = {
    VALUE_UINT8: ("<B", 1),
    VALUE_INT8: ("<b", 1),
    VALUE_UINT16: ("<H", 2),
    VALUE_INT16: ("<h", 2),
    VALUE_UINT32: ("<I", 4),
    VALUE_INT32: ("<i", 4),
    VALUE_FLOAT32: ("<f", 4),
    VALUE_BOOL: ("<?", 1),
    VALUE_UINT64: ("<Q", 8),
    VALUE_INT64: ("<q", 8),
    VALUE_FLOAT64: ("<d", 8),
}


class GGUFError(ValueError):
    pass


@dataclass(frozen=True)
class GGUFMetadata:
    version: int
    tensor_count: int
    metadata_count: int
    values: dict[str, Any]


def _read_exact(handle: BinaryIO, size: int) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise GGUFError("unexpected end of GGUF metadata")
    return data


def _discard(handle: BinaryIO, size: int) -> None:
    remaining = int(size)
    while remaining > 0:
        chunk = handle.read(min(remaining, DISCARD_CHUNK_BYTES))
        if not chunk:
            raise GGUFError("unexpected end of GGUF metadata")
        remaining -= len(chunk)


def _u32(handle: BinaryIO) -> int:
    return struct.unpack("<I", _read_exact(handle, 4))[0]


def _u64(handle: BinaryIO) -> int:
    return struct.unpack("<Q", _read_exact(handle, 8))[0]


def _string(handle: BinaryIO) -> str:
    length = _u64(handle)
    if length > MAX_STRING_BYTES:
        raise GGUFError(f"GGUF string length exceeds safety limit: {length}")
    raw = _read_exact(handle, int(length))
    return raw.decode("utf-8", errors="replace")


def _skip_string(handle: BinaryIO) -> None:
    length = _u64(handle)
    if length > MAX_STRING_BYTES:
        raise GGUFError(f"GGUF string length exceeds safety limit: {length}")
    _discard(handle, int(length))


def _skip_value(handle: BinaryIO, value_type: int, depth: int = 0) -> None:
    if depth > MAX_NESTING:
        raise GGUFError("GGUF metadata nesting exceeds safety limit")
    if value_type in SCALARS:
        _discard(handle, SCALARS[value_type][1])
        return
    if value_type == VALUE_STRING:
        _skip_string(handle)
        return
    if value_type == VALUE_ARRAY:
        item_type = _u32(handle)
        count = _u64(handle)
        if count > MAX_ARRAY_ITEMS:
            raise GGUFError(f"GGUF array length exceeds safety limit: {count}")
        if item_type in SCALARS:
            _discard(handle, SCALARS[item_type][1] * int(count))
            return
        for _ in range(int(count)):
            _skip_value(handle, item_type, depth + 1)
        return
    raise GGUFError(f"unsupported GGUF metadata value type: {value_type}")


def _value(handle: BinaryIO, value_type: int, depth: int = 0) -> Any:
    if depth > MAX_NESTING:
        raise GGUFError("GGUF metadata nesting exceeds safety limit")
    if value_type in SCALARS:
        fmt, size = SCALARS[value_type]
        return struct.unpack(fmt, _read_exact(handle, size))[0]
    if value_type == VALUE_STRING:
        return _string(handle)
    if value_type == VALUE_ARRAY:
        item_type = _u32(handle)
        count = _u64(handle)
        if count > MAX_ARRAY_ITEMS:
            raise GGUFError(f"GGUF array length exceeds safety limit: {count}")
        if count > MAX_MATERIALIZED_ARRAY_ITEMS:
            for _ in range(int(count)):
                _skip_value(handle, item_type, depth + 1)
            return {"array_items": int(count), "materialized": False}
        return [_value(handle, item_type, depth + 1) for _ in range(int(count))]
    raise GGUFError(f"unsupported GGUF metadata value type: {value_type}")


def inspect_gguf(path: Path) -> GGUFMetadata:
    with path.open("rb") as handle:
        if _read_exact(handle, 4) != GGUF_MAGIC:
            raise GGUFError("file does not start with GGUF magic")
        version = _u32(handle)
        if version not in {2, 3}:
            raise GGUFError(f"unsupported GGUF version: {version}")
        tensor_count = _u64(handle)
        metadata_count = _u64(handle)
        if metadata_count > MAX_METADATA_ENTRIES:
            raise GGUFError(f"GGUF metadata count exceeds safety limit: {metadata_count}")

        values: dict[str, Any] = {}
        for _ in range(int(metadata_count)):
            key = _string(handle)
            value_type = _u32(handle)
            values[key] = _value(handle, value_type)

    return GGUFMetadata(
        version=version,
        tensor_count=int(tensor_count),
        metadata_count=int(metadata_count),
        values=values,
    )


def _first_int(values: dict[str, Any], keys: list[str]) -> int | None:
    for key in keys:
        value = values.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return int(value)
    return None


def summarize_gguf(metadata: GGUFMetadata) -> dict[str, Any]:
    values = metadata.values
    architecture = values.get("general.architecture")
    if not isinstance(architecture, str):
        architecture = None

    context_keys: list[str] = []
    if architecture:
        context_keys.append(f"{architecture}.context_length")
    context_keys.extend(
        key for key in values
        if key.endswith(".context_length") and key not in context_keys
    )

    display_name = values.get("general.name")
    if not isinstance(display_name, str):
        display_name = None

    size_label = values.get("general.size_label")
    if not isinstance(size_label, str):
        size_label = None

    quantization = values.get("general.file_type")
    if isinstance(quantization, bool) or not isinstance(quantization, int):
        quantization = None

    quantization_version = values.get("general.quantization_version")
    if isinstance(quantization_version, bool) or not isinstance(quantization_version, int):
        quantization_version = None

    return {
        "gguf_version": metadata.version,
        "tensor_count": metadata.tensor_count,
        "metadata_count": metadata.metadata_count,
        "architecture": architecture,
        "display_name": display_name,
        "context_length": _first_int(values, context_keys),
        "parameter_count": _first_int(values, ["general.parameter_count", "general.parameters"]),
        "size_label": size_label,
        "file_type": quantization,
        "quantization_version": quantization_version,
        "metadata": values,
    }
