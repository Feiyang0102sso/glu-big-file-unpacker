"""Convert game BIN models to OBJ and JSON."""

import json
import shutil
import struct
from pathlib import Path

from big_tool.big_archive.big_section import resource_index_of
from big_tool.logger import logger
from big_tool.models.mesh_binding import (
    build_bindings,
    group_textures_by_mesh,
    index_resource_files,
    pack_short_name,
)


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

# Section folder that holds the meshes, created by `unpack --by-section`.
# An unused Section is named "<n>_MODEL_empty" and this pattern skips it.
MODEL_SECTION_PATTERN = "*_MODEL"
# Output folder, tagged with the pack it came from so the folders stay
# distinguishable once they are moved out of the unpack tree. The textures a
# pack's meshes use are copied inside it, which keeps a converted folder
# self-contained: it can be moved anywhere and the MTL paths still resolve.
CONVERTED_DIR_PREFIX = "_converted_models"
TEXTURE_DIR_NAME = "textures"
MANIFEST_PATTERN = "*_resources.csv"
MODEL_EXTENSION = ".bin"
MATERIAL_EXTENSION = ".mtl"

# A mesh whose UVs are nothing but the four corners was never unwrapped: every
# face would show the whole texture atlas. Those are placeholder boxes, so they
# get no material even when a template binds one to them.
UV_CORNERS = frozenset({(0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)})

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


def save_mtl(filename: Path, materials: list[tuple[str, str]]) -> None:
    """Save a material library: one entry per texture bound to the mesh.

    Only the diffuse map is written. The game carries no other material data,
    so anything else would be invented.
    """
    with Path(filename).open("w", encoding="utf-8") as output:
        output.write("# Batch Exported Glu Materials\n")
        for name, texture_path in materials:
            output.write(f"newmtl {name}\n")
            output.write(f"map_Kd {texture_path}\n\n")


def save_obj(
    filename: Path,
    vertices: list[tuple[float, float, float]],
    uvs: list[tuple[float, float]],
    indices: list[int],
    materials: list[tuple[str, str]] | None = None,
) -> None:
    """Save an OBJ mesh, with a material library when its textures are known."""
    with Path(filename).open("w", encoding="utf-8") as output:
        output.write("# Batch Exported Glu Mesh\n")
        if materials:
            # A mesh with several textures keeps them all in one library and
            # starts on the first; the rest stay selectable in the importer.
            library_name = Path(filename).with_suffix(MATERIAL_EXTENSION).name
            output.write(f"mtllib {library_name}\n")
            output.write(f"usemtl {materials[0][0]}\n")
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


def is_unwrapped(uvs: list[tuple[float, float]]) -> bool:
    """Return whether a mesh carries real UVs rather than corner defaults."""
    return not set(uvs) <= UV_CORNERS


class MeshFormatError(ValueError):
    """Raised when a file is not a readable Glu mesh."""


def _read_exact(file, size: int) -> bytes:
    data = file.read(size)
    if len(data) != size:
        raise MeshFormatError("model file is truncated")
    return data


def convert_single_bin(
    input_file: Path,
    output_prefix: Path,
    materials: list[tuple[str, str]] | None = None,
) -> tuple[Path, Path]:
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

        if materials and not is_unwrapped(uvs):
            logger.warning(
                f"{input_file.name}: UVs are corner defaults, writing no material"
            )
            materials = None

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
    save_obj(obj_path, frames[0]["vertices"], uvs, indices, materials)
    if materials:
        save_mtl(output_prefix.with_suffix(MATERIAL_EXTENSION), materials)
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


def converted_dir_name(pack_dir: Path | None) -> str:
    """Return the output folder name for a pack."""
    if pack_dir is None:
        return CONVERTED_DIR_PREFIX
    return f"{CONVERTED_DIR_PREFIX}_{pack_short_name(pack_dir)}"


def resolve_output_dir(model_dir: Path, output_root: Path | None) -> Path:
    """Return where one MODEL folder's conversions go."""
    pack_dir = find_pack_dir(model_dir)
    base = output_root if output_root is not None else (pack_dir or model_dir)
    return base / converted_dir_name(pack_dir)


def build_materials(pack_dir: Path | None, target_dir: Path) -> dict[int, list[tuple[str, str]]]:
    """Return each mesh's materials, keyed by the mesh's table2 index.

    A material is a name and the path of its texture relative to the folder the
    OBJ is written into, which is what an MTL library needs.
    """
    if pack_dir is None:
        return {}

    bindings = build_bindings(pack_dir)
    if not bindings:
        return {}

    resource_files = index_resource_files(pack_dir)
    texture_dir = target_dir / TEXTURE_DIR_NAME
    copied_names: set[str] = set()

    materials_by_mesh: dict[int, list[tuple[str, str]]] = {}
    for mesh_index, texture_indexes in group_textures_by_mesh(bindings).items():
        materials: list[tuple[str, str]] = []
        for texture_index in texture_indexes:
            texture_path = resource_files.get(texture_index)
            if texture_path is None:
                continue

            # Shared textures are common, so copy each one only once.
            if texture_path.name not in copied_names:
                texture_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(texture_path, texture_dir / texture_path.name)
                copied_names.add(texture_path.name)
            materials.append((texture_path.stem, f"{TEXTURE_DIR_NAME}/{texture_path.name}"))
        if materials:
            materials_by_mesh[mesh_index] = materials

    logger.debug(
        f"{pack_dir.name}: materials for {len(materials_by_mesh)} meshes, "
        f"{len(copied_names)} textures copied"
    )
    return materials_by_mesh


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
        materials_by_mesh = build_materials(find_pack_dir(model_dir), target_dir)

        model_files = sorted(model_dir.glob(f"*{MODEL_EXTENSION}"))
        for model_file in model_files:
            # A non-mesh file in the folder must not stop the batch.
            try:
                materials = materials_by_mesh.get(resource_index_of(model_file))
                convert_single_bin(model_file, target_dir / model_file.stem, materials)
                converted_count += 1
            except (OSError, MeshFormatError, struct.error) as error:
                logger.warning(f"Skipping file {model_file.name}: {error}")
        logger.debug(f"{model_dir.name}: {len(model_files)} models -> {target_dir}")
    return converted_count
