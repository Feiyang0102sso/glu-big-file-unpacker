"""Mesh to texture bindings recovered from object templates.

A mesh file carries geometry, UVs and animation but no texture reference: the
pairing lives in the object templates that use the mesh. Both sides are stored
as a Section-local index and resolved by the engine as
``Section base + local index``, so this module turns those indexes back into
the table2 indexes of the unpacked files.

Two encodings exist, and a template type may use either or both:

* ``CGameAssetRef`` - an 8 byte ``PackHash + signed local index`` pair at a
  fixed file offset. ARMOR, BULLET and GUN read theirs before the variable
  length ``CScript``, so the offsets are constant.
* ``CMoveSetMesh`` - a one byte mesh index and a one byte texture index inside
  an animation block. ENEMY, GUN and PLAYER carry one, but it sits *after*
  ``CScript``, so it has to be located by scanning. It never names the same mesh
  as the fixed refs: a gun's refs point at that gun's own model, while its
  MeshConfig points at the arms every gun shares. Only ``CEnemy`` asks
  ``CMoveSetMesh::Load`` to load the image, because a shared part is already
  loaded by whoever owns it, but the texture byte still names the right texture.

The player has no texture of its own: the armour system swaps one onto the
player mesh. An ARMOR template with no mesh of its own carries exactly that,
one per brother when its first byte is 1.
"""

import struct
from dataclasses import dataclass
from pathlib import Path

from big_tool.analysis.hashing import cstring_to_key
from big_tool.big_archive.big_section import (
    MANIFEST_SUFFIX,
    PHYSICAL_ID_COLUMN,
    SECTION_COLUMN,
    read_manifest,
    resource_index_of,
)
from big_tool.logger import logger


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

MODEL_SECTION_SUFFIX = "_MODEL"
PNG_SECTION_SUFFIX = "_PNG"
EMPTY_SECTION_SUFFIX = "_empty"

# Pack names are hashed without the resolution suffix: the archive
# "pack1_xga.big" identifies itself as "pack1".
PACK_NAME_SUFFIX = "_xga"

# Unpacked resources live in one folder per resource group, named after the
# group hash. Converted output sits beside those folders and reuses the same
# file names, so only these are walked when indexing resources.
GROUP_DIR_PREFIX = "0x"

# A CGameAssetRef holds a signed local index; -1 means the slot is unused and
# the object falls back to a 2D sprite.
UNUSED_LOCAL_INDEX = -1

# Sections whose templates bind through fixed CGameAssetRef offsets, listed as
# (mesh ref offset, texture ref offset). ARMOR has two independent slots.
FIXED_REF_SLOTS = {
    "_ARMOR": [(1, 9), (18, 26)],
    "_BULLET": [(7, 15)],
    "_GUN": [(1, 9)],
}

# Sections whose templates carry a CMoveSetMesh block.
MOVE_SET_MESH_SECTIONS = ("_ENEMY", "_GUN", "_PLAYER")

ARMOR_SECTION_SUFFIX = "_ARMOR"
PLAYER_SECTION_SUFFIX = "_PLAYER"

# Every texture ref of an ARMOR template. A template with no mesh uses these to
# skin the player instead.
ARMOR_TEXTURE_OFFSETS = (9, 26, 35, 43)

# Bounds used while scanning for a CMoveSetMesh. They only have to be loose
# enough to keep every real block and tight enough to kill random byte runs.
MAX_MESH_COUNT = 16
MAX_MOVE_COUNT = 64
MAX_FRAME_NUMBER = 4096
MAX_MOVE_SPEED = 0x00400000  # 16.16 fixed point, so 64.0
MOVE_RECORD_SIZE = 15
MOVE_EVENT_SIZE = 3


@dataclass(frozen=True)
class MeshBinding:
    """One mesh and texture pairing, as table2 indexes of unpacked files."""

    template_index: int
    section: str
    mesh_index: int
    texture_index: int


@dataclass(frozen=True)
class SectionRange:
    """A Section's table2 range, both ends included."""

    first_index: int
    last_index: int

    @property
    def length(self) -> int:
        """Return how many resources the Section covers."""
        return self.last_index - self.first_index + 1


# ------------------------------------------------------------------
# Manifest
# ------------------------------------------------------------------

def read_section_ranges(rows: list[dict[str, str]]) -> dict[str, SectionRange]:
    """Return the table2 range of every named Section in a manifest."""
    ranges: dict[str, SectionRange] = {}
    for row in rows:
        name = row[SECTION_COLUMN]
        if not name:
            continue
        index = int(row[PHYSICAL_ID_COLUMN])
        known = ranges.get(name)
        if known is None:
            ranges[name] = SectionRange(index, index)
        else:
            ranges[name] = SectionRange(min(known.first_index, index),
                                        max(known.last_index, index))
    return ranges


def find_section_range(ranges: dict[str, SectionRange], suffix: str) -> SectionRange | None:
    """Return the Section whose name ends with a suffix, ignoring empty ones."""
    for name, section_range in ranges.items():
        if name.endswith(suffix):
            return section_range
    return None


def pack_short_name(pack_dir: Path) -> str:
    """Return a pack's name without the resolution suffix."""
    pack_name = pack_dir.name
    if pack_name.endswith(PACK_NAME_SUFFIX):
        pack_name = pack_name[: -len(PACK_NAME_SUFFIX)]
    return pack_name


def pack_hash_of(pack_dir: Path) -> int:
    """Return the PackHash a pack's own templates use to refer to themselves."""
    return cstring_to_key(pack_short_name(pack_dir))


# ------------------------------------------------------------------
# CMoveSetMesh
# ------------------------------------------------------------------

def parse_move_set_mesh(
    data: bytes,
    start: int,
    pack_hash: int,
    mesh_count_limit: int,
    texture_count_limit: int,
) -> tuple[list[tuple[int, int]], int] | None:
    """Try to read a CMoveSetMesh at an offset.

    Returns the (mesh index, texture index) pairs and the offset just past the
    block, or None when the bytes do not form a valid block.
    """
    if start + 6 > len(data):
        return None
    if struct.unpack_from("<I", data, start)[0] != pack_hash:
        return None

    position = start + 4
    mesh_count = data[position]
    position += 1
    if mesh_count == 0 or mesh_count > MAX_MESH_COUNT:
        return None
    if position + 2 * mesh_count >= len(data):
        return None

    pairs: list[tuple[int, int]] = []
    for _ in range(mesh_count):
        mesh_index = data[position]
        texture_index = data[position + 1]
        position += 2
        if mesh_index >= mesh_count_limit or texture_index >= texture_count_limit:
            return None
        pairs.append((mesh_index, texture_index))

    move_count = data[position]
    position += 1
    if move_count > MAX_MOVE_COUNT:
        return None

    # Each move: u8, u16 first frame, u16 last frame, u8, int32 speed in 16.16
    # fixed point, uint32, u8 event count, then that many (u16, u8) events.
    for _ in range(move_count):
        if position + MOVE_RECORD_SIZE > len(data):
            return None
        first_frame, last_frame = struct.unpack_from("<HH", data, position + 1)
        speed = struct.unpack_from("<i", data, position + 6)[0]
        if last_frame < first_frame or last_frame > MAX_FRAME_NUMBER:
            return None
        if speed <= 0 or speed > MAX_MOVE_SPEED:
            return None
        event_count = data[position + 14]
        position += MOVE_RECORD_SIZE + MOVE_EVENT_SIZE * event_count
        if position > len(data):
            return None
    return pairs, position


def skip_game_object_ref(data: bytes, position: int) -> int | None:
    """Skip a GameObjectRef: a PackHash plus one byte when it is not null."""
    if position + 4 > len(data):
        return None
    if struct.unpack_from("<I", data, position)[0] == 0:
        return position + 4
    return position + 5


def skip_enemy_tail(data: bytes, position: int) -> int | None:
    """Skip what CEnemy::Template reads after its CMoveSetMesh."""
    position = skip_game_object_ref(data, position)
    if position is None:
        return None

    position += 10  # two uint16, two uint8, two uint16
    if position + 2 > len(data):
        return None

    # CCollisionData: a point array then a box array, each behind a uint16 count.
    position += 2 + 8 * struct.unpack_from("<H", data, position)[0]
    if position + 2 > len(data):
        return None
    return position + 2 + 5 * struct.unpack_from("<H", data, position)[0]


def skip_gun_tail(data: bytes, position: int) -> int | None:
    """CGun::Template ends with its CMoveSetMesh, so nothing follows."""
    return position


def skip_player_tail(data: bytes, position: int) -> int | None:
    """Skip what CBrother::Template reads after its CMoveSetMesh."""
    position = skip_game_object_ref(data, position)
    if position is None:
        return None
    position += 2  # uint16

    for _ in range(2):
        position = skip_game_object_ref(data, position)
        if position is None:
            return None

    position += 7  # CGameSpriteGluRef: a PackHash plus three uint8
    if position > len(data):
        return None
    return position


TAIL_SKIPPERS = {
    "_ENEMY": skip_enemy_tail,
    "_GUN": skip_gun_tail,
    "_PLAYER": skip_player_tail,
}


def find_move_set_mesh(
    data: bytes,
    section: str,
    pack_hash: int,
    mesh_count_limit: int,
    texture_count_limit: int,
) -> list[tuple[int, int]]:
    """Locate the single CMoveSetMesh in a template.

    The block sits after a variable length script, so every offset is tried.
    The rest of the template is then skipped and must land exactly on the end
    of the file, which leaves only one candidate in practice.
    """
    skip_tail = None
    for suffix, skipper in TAIL_SKIPPERS.items():
        if section.endswith(suffix):
            skip_tail = skipper
    if skip_tail is None:
        return []

    accepted: list[list[tuple[int, int]]] = []
    for offset in range(len(data)):
        parsed = parse_move_set_mesh(
            data, offset, pack_hash, mesh_count_limit, texture_count_limit
        )
        if parsed is None:
            continue
        pairs, end = parsed
        if skip_tail(data, end) == len(data):
            accepted.append(pairs)

    if len(accepted) == 1:
        return accepted[0]
    return []


# ------------------------------------------------------------------
# CGameAssetRef
# ------------------------------------------------------------------

def read_asset_ref(data: bytes, offset: int, pack_hash: int, count_limit: int) -> int | None:
    """Read a local index from a CGameAssetRef at a fixed offset."""
    if offset + 8 > len(data):
        return None

    ref_pack_hash, local_index = struct.unpack_from("<Ii", data, offset)
    if ref_pack_hash != pack_hash:
        return None
    if local_index == UNUSED_LOCAL_INDEX or not 0 <= local_index < count_limit:
        return None
    return local_index


def read_fixed_slots(
    data: bytes,
    section: str,
    pack_hash: int,
    mesh_count_limit: int,
    texture_count_limit: int,
) -> list[tuple[int, int]]:
    """Read the fixed CGameAssetRef slots of a template."""
    slots = []
    for suffix, offsets in FIXED_REF_SLOTS.items():
        if section.endswith(suffix):
            slots = offsets

    pairs: list[tuple[int, int]] = []
    for mesh_offset, texture_offset in slots:
        mesh_index = read_asset_ref(data, mesh_offset, pack_hash, mesh_count_limit)
        texture_index = read_asset_ref(data, texture_offset, pack_hash, texture_count_limit)
        if mesh_index is not None and texture_index is not None:
            pairs.append((mesh_index, texture_index))
    return pairs


def read_armor_skins(data: bytes, pack_hash: int, texture_count_limit: int) -> list[int]:
    """Read the textures of an ARMOR template that owns no mesh.

    Those textures are worn by the player mesh rather than by a mesh of the
    armour itself. When the template's first byte is 1 the slots hold one
    variant per brother, which is why a body can have several.
    """
    textures: list[int] = []
    for offset in ARMOR_TEXTURE_OFFSETS:
        texture_index = read_asset_ref(data, offset, pack_hash, texture_count_limit)
        if texture_index is not None and texture_index not in textures:
            textures.append(texture_index)
    return textures


# ------------------------------------------------------------------
# Driver
# ------------------------------------------------------------------

def build_bindings(pack_dir: Path) -> list[MeshBinding]:
    """Recover every mesh and texture pairing of one unpacked pack."""
    pack_dir = Path(pack_dir).resolve()
    manifest_files = list(pack_dir.glob(f"*{MANIFEST_SUFFIX}"))
    if not manifest_files:
        return []

    _headers, rows = read_manifest(manifest_files[0])
    ranges = read_section_ranges(rows)
    model_range = find_section_range(ranges, MODEL_SECTION_SUFFIX)
    png_range = find_section_range(ranges, PNG_SECTION_SUFFIX)
    if model_range is None or png_range is None:
        return []

    pack_hash = pack_hash_of(pack_dir)
    template_paths = index_resource_files(pack_dir)

    bindings: list[MeshBinding] = []
    player_meshes: list[int] = []
    skins: list[tuple[int, str, int]] = []
    for row in rows:
        section = row[SECTION_COLUMN]
        if not section or section.endswith(EMPTY_SECTION_SUFFIX):
            continue

        template_index = int(row[PHYSICAL_ID_COLUMN])
        template_path = template_paths.get(template_index)
        if template_path is None:
            continue

        is_fixed_ref = any(section.endswith(suffix) for suffix in FIXED_REF_SLOTS)
        if not is_fixed_ref and not section.endswith(MOVE_SET_MESH_SECTIONS):
            continue

        data = template_path.read_bytes()
        pairs = read_fixed_slots(
            data, section, pack_hash, model_range.length, png_range.length
        )
        move_set_pairs = find_move_set_mesh(
            data, section, pack_hash, model_range.length, png_range.length
        )

        pairs += move_set_pairs
        if section.endswith(PLAYER_SECTION_SUFFIX):
            for mesh_local, _texture_local in move_set_pairs:
                player_meshes.append(model_range.first_index + mesh_local)

        if section.endswith(ARMOR_SECTION_SUFFIX) and not pairs:
            for texture_local in read_armor_skins(data, pack_hash, png_range.length):
                skins.append(
                    (template_index, section, png_range.first_index + texture_local)
                )

        for mesh_local, texture_local in pairs:
            bindings.append(
                MeshBinding(
                    template_index,
                    section,
                    model_range.first_index + mesh_local,
                    png_range.first_index + texture_local,
                )
            )

    # Which player mesh a skin lands on is decided by the render code, which is
    # not read here, so every skin is offered on every player mesh. That can
    # over-offer, but it never drops a texture the player can actually wear.
    for template_index, section, texture_index in skins:
        for mesh_index in player_meshes:
            bindings.append(MeshBinding(template_index, section, mesh_index, texture_index))

    logger.debug(
        f"{pack_dir.name}: {len(bindings)} mesh bindings, "
        f"{len(skins)} armour skins on {len(player_meshes)} player meshes"
    )
    return bindings


def index_resource_files(pack_dir: Path) -> dict[int, Path]:
    """Map every unpacked resource's table2 index to its file.

    Only the resource group folders are walked. A converted OBJ and a copied
    texture keep the name of the resource they came from, so walking the whole
    pack would let them shadow the real resources on a second run.
    """
    files: dict[int, Path] = {}
    for group_dir in sorted(pack_dir.iterdir()):
        if not group_dir.is_dir() or not group_dir.name.startswith(GROUP_DIR_PREFIX):
            continue
        for path in group_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                files[resource_index_of(path)] = path
            except ValueError:
                # Derived files such as the string CSVs carry no resource index.
                continue
    return files


def group_textures_by_mesh(bindings: list[MeshBinding]) -> dict[int, list[int]]:
    """Return each mesh's texture indexes, in first-seen order and deduplicated.

    A mesh can carry several textures when different templates reuse it as a
    recoloured variant, so the value is a list rather than a single index.
    """
    textures: dict[int, list[int]] = {}
    for binding in bindings:
        known = textures.setdefault(binding.mesh_index, [])
        if binding.texture_index not in known:
            known.append(binding.texture_index)
    return textures
