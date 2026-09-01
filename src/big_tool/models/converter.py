"""Convert game BIN models to OBJ and JSON."""

import json
import struct
from pathlib import Path

from big_tool.logger import logger


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

# Section folder that holds the meshes, created by `unpack --by-section`.
# An unused Section is named "<n>_MODEL_empty" and this pattern skips it.
MODEL_SECTION_PATTERN = "*_MODEL"
CONVERTED_DIR_NAME = "_converted_models"
MANIFEST_PATTERN = "*_resources.csv"
MODEL_EXTENSION = ".bin"

# Coordinate handling. Nothing is converted: the game's own vertex and UV
# values are written straight out, so the mesh and its texture stay consistent
# with each other by construction. Converting here would force the PNG to be
# converted to match. Do the orientation fix in the importer instead.
#   FLIP_UV_V        writes 1 - v, for tools whose texture origin is bottom-left
#   SWIZZLE_TO_Y_UP  writes (x, z, -y), for tools that are Y-up
FLIP_UV_V = False
SWIZZLE_TO_Y_UP = False

# Mesh header: version, index count, bone count, frame count, vertex count.
HEADER_FORMAT = "<BIBHH"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# One animation frame is a timestamp, a bone block, then every vertex again.
FRAME_TIME_SIZE = 4
BONE_FRAME_SIZE = 28
VERTEX_SIZE = 12
UV_SIZE = 8
INDEX_SIZE = 2


def save_obj(
    filename: Path,
    vertices: list[tuple[float, float, float]],
    uvs: list[tuple[float, float]],
    indices: list[int],
) -> None:
    """Save an OBJ mesh."""
    with Path(filename).open("w", encoding="utf-8") as output:
        output.write("# Batch Exported Glu Mesh\n")
        for vertex in vertices:
            output.write(f"v {vertex[0]:.6f} {vertex[1]:.6f} {vertex[2]:.6f}\n")
        for uv in uvs:
            output.write(f"vt {uv[0]:.6f} {uv[1]:.6f}\n")

        # The index list is one long triangle strip: every three consecutive
        # indices form a face and the winding alternates. Degenerate triangles
        # are the strip's way of jumping to a new run, so they only flip the
        # winding and emit nothing.
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


class MeshFormatError(ValueError):
    """Raised when a file is not a readable Glu mesh."""


def _read_exact(file, size: int) -> bytes:
    data = file.read(size)
    if len(data) != size:
        raise MeshFormatError("model file is truncated")
    return data


def convert_single_bin(input_file: Path, output_prefix: Path) -> tuple[Path, Path]:
    """Convert one model BIN file into an OBJ mesh and an animation JSON."""
    input_file = Path(input_file).resolve()
    output_prefix = Path(output_prefix).resolve()
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    with input_file.open("rb") as file:
        header = struct.unpack(HEADER_FORMAT, _read_exact(file, HEADER_SIZE))
        _version, index_count, bone_count, frame_count, vertex_count = header
        if frame_count == 0:
            raise MeshFormatError("model has no animation frame")

        for _ in range(bone_count):
            name_length = _read_exact(file, 1)[0]
            _read_exact(file, name_length)

        indices: list[int] = []
        for _ in range(index_count):
            indices.append(struct.unpack("<H", _read_exact(file, INDEX_SIZE))[0])

        uvs: list[tuple[float, float]] = []
        for _ in range(vertex_count):
            u, v = struct.unpack("<ff", _read_exact(file, UV_SIZE))
            if FLIP_UV_V:
                v = 1.0 - v
            uvs.append((u, v))

        animation_start = file.tell()
        frame_stride = FRAME_TIME_SIZE + bone_count * BONE_FRAME_SIZE + vertex_count * VERTEX_SIZE
        frames: list[dict[str, object]] = []
        for frame_index in range(frame_count):
            file.seek(animation_start + frame_index * frame_stride)
            time_ms = struct.unpack("<I", _read_exact(file, FRAME_TIME_SIZE))[0]
            file.seek(bone_count * BONE_FRAME_SIZE, 1)
            vertices: list[tuple[float, float, float]] = []
            for _ in range(vertex_count):
                x, y, z = struct.unpack("<fff", _read_exact(file, VERTEX_SIZE))
                if SWIZZLE_TO_Y_UP:
                    vertices.append((x, z, -y))
                else:
                    vertices.append((x, y, z))
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


def find_model_dirs(root: Path) -> list[Path]:
    """Return every MODEL Section folder under a directory.

    This accepts an unpack output root, a single pack folder, or the Section
    folder itself. A directory with no MODEL Section is used as-is, so a
    hand-assembled folder of mesh files still works.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)

    model_dirs = sorted(path for path in root.rglob(MODEL_SECTION_PATTERN) if path.is_dir())
    if model_dirs:
        return model_dirs
    return [root]


def find_pack_dir(model_dir: Path) -> Path | None:
    """Return the pack folder a MODEL Section belongs to, or None.

    An unpacked Section sits at ``<pack>/<group hash>/<n>_MODEL``, and a pack
    folder is the one holding the resource manifest.
    """
    pack_dir = model_dir.parent.parent
    if pack_dir.is_dir() and any(pack_dir.glob(MANIFEST_PATTERN)):
        return pack_dir
    return None


def resolve_output_dir(model_dir: Path, output_root: Path | None) -> Path:
    """Return where one MODEL folder's conversions go."""
    pack_dir = find_pack_dir(model_dir)
    if output_root is None:
        base = pack_dir if pack_dir is not None else model_dir
        return base / CONVERTED_DIR_NAME
    if pack_dir is None:
        return output_root
    return output_root / pack_dir.name


def convert_directory(directory: Path, output_dir: Path | None = None) -> int:
    """Convert every mesh under a directory and return the count.

    Without ``output_dir`` each pack keeps its own ``_converted_models`` folder.
    With it, those per-pack folders are created under that root instead.
    """
    directory = Path(directory).resolve()
    output_root = Path(output_dir).resolve() if output_dir is not None else None

    model_dirs = find_model_dirs(directory)
    logger.info(f"Found {len(model_dirs)} model directories under {directory.name}")

    converted_count = 0
    for model_dir in model_dirs:
        target_dir = resolve_output_dir(model_dir, output_root)
        target_dir.mkdir(parents=True, exist_ok=True)

        model_files = sorted(model_dir.glob(f"*{MODEL_EXTENSION}"))
        for model_file in model_files:
            # A non-mesh file in the folder must not stop the batch.
            try:
                convert_single_bin(model_file, target_dir / model_file.stem)
                converted_count += 1
            except (OSError, MeshFormatError, struct.error) as error:
                logger.warning(f"Skipping file {model_file.name}: {error}")
        logger.debug(f"{model_dir.name}: {len(model_files)} models -> {target_dir}")
    return converted_count
