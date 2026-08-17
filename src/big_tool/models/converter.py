"""Convert game BIN models to OBJ and JSON."""

import json
import struct
from pathlib import Path

from big_tool.logger import logger


def save_obj(filename: Path, vertices: list[list[float]], uvs: list[tuple[float, float]], indices: list[int]) -> None:
    """Save an OBJ mesh."""
    with Path(filename).open("w", encoding="utf-8") as output:
        output.write("# Batch Exported Glu Mesh\n")
        for vertex in vertices:
            output.write(f"v {vertex[0]:.6f} {vertex[1]:.6f} {vertex[2]:.6f}\n")
        for uv in uvs:
            output.write(f"vt {uv[0]:.6f} {uv[1]:.6f}\n")

        flip = False
        for index in range(len(indices) - 2):
            first = indices[index] + 1
            second = indices[index + 1] + 1
            third = indices[index + 2] + 1
            if first == second or second == third or first == third:
                flip = not flip
                continue
            if flip:
                output.write(f"f {first}/{first} {third}/{third} {second}/{second}\n")
            else:
                output.write(f"f {first}/{first} {second}/{second} {third}/{third}\n")
            flip = not flip


def _read_exact(file, size: int) -> bytes:
    data = file.read(size)
    if len(data) != size:
        raise ValueError("model file is truncated")
    return data


def convert_single_bin(input_file: Path, output_prefix: Path) -> tuple[Path, Path]:
    """Convert one model BIN file."""
    input_file = Path(input_file).resolve()
    output_prefix = Path(output_prefix).resolve()
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    with input_file.open("rb") as file:
        _version = struct.unpack("B", _read_exact(file, 1))[0]
        index_count = struct.unpack("<I", _read_exact(file, 4))[0]
        bone_count = struct.unpack("B", _read_exact(file, 1))[0]
        frame_count = struct.unpack("<H", _read_exact(file, 2))[0]
        vertex_count = struct.unpack("<H", _read_exact(file, 2))[0]

        for _ in range(bone_count):
            name_length = struct.unpack("B", _read_exact(file, 1))[0]
            _read_exact(file, name_length)

        indices: list[int] = []
        for _ in range(index_count):
            indices.append(struct.unpack("<H", _read_exact(file, 2))[0])

        uvs: list[tuple[float, float]] = []
        for _ in range(vertex_count):
            u, v = struct.unpack("<ff", _read_exact(file, 8))
            uvs.append((u, 1.0 - v))

        if frame_count == 0:
            raise ValueError("model has no animation frame")

        animation_start = file.tell()
        frame_stride = 4 + bone_count * 28 + vertex_count * 12
        frames: list[dict[str, object]] = []
        for frame_index in range(frame_count):
            file.seek(animation_start + frame_index * frame_stride)
            time_ms = struct.unpack("<I", _read_exact(file, 4))[0]
            file.seek(bone_count * 28, 1)
            vertices: list[list[float]] = []
            for _ in range(vertex_count):
                x, y, z = struct.unpack("<fff", _read_exact(file, 12))
                vertices.append([x, z, -y])
            frames.append({"time": time_ms, "vertices": vertices})

    animation_data = {
        "metadata": {"vertex_count": vertex_count, "frame_count": frame_count},
        "frames": frames,
    }
    obj_path = output_prefix.with_suffix(".obj")
    json_path = output_prefix.with_suffix(".json")
    save_obj(obj_path, frames[0]["vertices"], uvs, indices)
    json_path.write_text(json.dumps(animation_data), encoding="utf-8")
    return obj_path, json_path


def convert_directory(directory: Path, output_dir: Path | None = None) -> int:
    """Convert BIN models in a directory and return the count."""
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise NotADirectoryError(directory)
    if output_dir is None:
        output_dir = directory / "converted_models"
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    converted_count = 0
    bin_files = list(directory.glob("*.bin"))
    bin_files.sort()
    for bin_file in bin_files:
        try:
            convert_single_bin(bin_file, output_dir / bin_file.stem)
            converted_count += 1
        except (OSError, ValueError, struct.error) as error:
            logger.warning(f"Skipping file {bin_file.name}: {error}")
    return converted_count
