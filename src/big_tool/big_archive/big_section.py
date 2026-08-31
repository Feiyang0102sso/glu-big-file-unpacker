"""Section table for BIG packs.

A Section is one entry of the non-aggregate prefix of ``___GAME_TOC_KEYSET``.
Each prefix entry is the base resource handle of a contiguous range of logical
IDs, and the engine addresses an object as ``base_handle + local_index``
(``CGameObjectPack::GetIndex``). This module rebuilds that partition from an
already unpacked directory and writes it into the resource manifest.
"""

import csv
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from big_tool.logger import logger


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

# Resource group that holds every keyset. A pack's ___GAME_TOC_KEYSET is the
# lowest numbered resource in it (verified on all 36 sample packs).
KEYSET_GROUP_HASH = 0x69E5D35C
KEYSET_DIR_NAME = hex(KEYSET_GROUP_HASH)

# Handle layout: bit 29 marks an aggregate (string) handle and the low 15 bits
# are the logical resource ID. The type byte in bits 24-31 is not used here.
AGGREGATE_HANDLE_FLAG = 0x20000000
LOGICAL_ID_MASK = 0x7FFF

# The number in an unpacked file name is that resource's table2 index. This must
# stay in sync with the name built in ArchiveExtractor._extract_entry.
RESOURCE_INDEX_PATTERN = re.compile(r"_(\d+)_0x[0-9a-fA-F]+$")

MANIFEST_SUFFIX = "_resources.csv"
MANIFEST_ENCODING = "utf-8-sig"
SECTION_COLUMN = "section"
LOGICAL_ID_COLUMN = "logical_id"
PHYSICAL_ID_COLUMN = "physical_id"

# Object type names, from GameObjectTypeStrings in the decompiled engine. Types
# are only ever appended, so an older build uses a prefix of this list: 1.0.0
# has 26 types, 2.4.0 has 27, 3.6.0 has 28.
GAME_OBJECT_TYPE_NAMES = [
    "ACHIEVEMENT",
    "ACHIEVEMENTLIST",
    "ARMOR",
    "BULLET",
    "DAILYBONUS",
    "ENEMY",
    "GUN",
    "LEVEL",
    "LEVELPROGRESSION",
    "MISSION",
    "MISSIONOBJECTIVE",
    "PARTICLEEFFECT",
    "PICKUP",
    "PLANET",
    "PLATFORM",
    "PLAYER",
    "PLAYERPROGRESSION",
    "POWERUP",
    "PRIZE",
    "PROP",
    "REFINEMENT",
    "SOUNDEFFECT",
    "STORE",
    "TILELAYER",
    "TILESET",
    "TUTORIAL",
    "CHALLENGE",
    "MP_MATCH",
]

# The five trailing sections are not object types. They are numbered like the
# rest, so their numbers shift with the engine's type count: 29-33 in 3.6.0,
# 28-32 in 2.4.0, 27-31 in 1.0.0.
TAIL_SECTION_NAMES = ["PNG", "WAV", "MODEL", "LEVEL_REFS", "COUNTS"]

# A Section holding nothing but one empty placeholder gets this suffix, so an
# unused object type is visible without opening the folder.
EMPTY_SECTION_SUFFIX = "_empty"
EMPTY_RESOURCE_TYPE = "ref"


class SectionTableError(ValueError):
    """Raised when a pack's Section table cannot be rebuilt."""


@dataclass(frozen=True)
class Section:
    """One Section: a run of table2 entries, both ends included."""

    number: int
    name: str
    first_index: int
    last_index: int

    @property
    def length(self) -> int:
        """Return how many resources the Section covers."""
        return self.last_index - self.first_index + 1


# ------------------------------------------------------------------
# Keyset
# ------------------------------------------------------------------

def read_keyset_prefix(keyset_data: bytes) -> list[int]:
    """Return the non-aggregate prefix of a keyset resource.

    A keyset is ``uint16 count`` followed by ``count`` 32-bit handles.
    ___GAME_TOC_KEYSET is the only keyset that starts with non-aggregate
    handles and then switches to aggregate ones, so that shape doubles as the
    check that the right resource was picked.
    """
    if len(keyset_data) < 2:
        raise SectionTableError("keyset is too small to hold a handle count")

    handle_count = struct.unpack_from("<H", keyset_data, 0)[0]
    expected_size = 2 + handle_count * 4
    if len(keyset_data) != expected_size:
        raise SectionTableError(
            f"keyset size mismatch: expected {expected_size} bytes for "
            f"{handle_count} handles, got {len(keyset_data)}"
        )

    handles = struct.unpack_from(f"<{handle_count}I", keyset_data, 2)
    prefix: list[int] = []
    for handle in handles:
        if handle & AGGREGATE_HANDLE_FLAG:
            break
        prefix.append(handle)

    if not prefix:
        raise SectionTableError("keyset has no non-aggregate prefix")
    if len(prefix) == handle_count:
        raise SectionTableError("keyset has no aggregate tail")
    return prefix


def resource_index_of(resource_path: Path) -> int:
    """Return the table2 index encoded in an unpacked file name."""
    match = RESOURCE_INDEX_PATTERN.search(resource_path.stem)
    if match is None:
        raise SectionTableError(f"cannot read a resource index from {resource_path.name}")
    return int(match.group(1))


def find_keyset_file(pack_dir: Path) -> Path:
    """Return the ___GAME_TOC_KEYSET file of an unpacked pack directory."""
    keyset_dir = pack_dir / KEYSET_DIR_NAME
    if not keyset_dir.is_dir():
        raise SectionTableError(f"no keyset group directory in {pack_dir.name}")

    keyset_files = [entry for entry in keyset_dir.iterdir() if entry.is_file()]
    if not keyset_files:
        raise SectionTableError(f"keyset group directory of {pack_dir.name} is empty")

    keyset_files.sort(key=resource_index_of)
    return keyset_files[0]


# ------------------------------------------------------------------
# Section table
# ------------------------------------------------------------------

def build_section_names(section_count: int) -> list[str]:
    """Return the Section names for a keyset prefix of the given length."""
    type_count = section_count - len(TAIL_SECTION_NAMES)
    if type_count < 1:
        raise SectionTableError(f"a prefix of {section_count} entries is too short")

    if type_count > len(GAME_OBJECT_TYPE_NAMES):
        logger.warning(
            f"Section table has {type_count} object types but only "
            f"{len(GAME_OBJECT_TYPE_NAMES)} names are known; the rest are numbered"
        )

    type_names: list[str] = []
    for type_id in range(type_count):
        if type_id < len(GAME_OBJECT_TYPE_NAMES):
            type_names.append(GAME_OBJECT_TYPE_NAMES[type_id])
        else:
            # A newer engine build than the decompiled one. Number it rather
            # than guess a name; the range itself is still correct.
            type_names.append(f"TYPE{type_id}")

    names: list[str] = []
    for position, name in enumerate(type_names + TAIL_SECTION_NAMES):
        names.append(f"{position + 1:02d}_{name}")
    return names


def build_section_table(
    prefix: list[int],
    logical_id_to_index: dict[int, int],
    empty_indexes: set[int] | None = None,
) -> list[Section]:
    """Turn keyset base handles into table2 ranges.

    A Section runs from its own base ID up to the next Section's base ID. The
    last one always covers a single resource: the Section system stops at the
    end of its table1 range, so the arithmetic cannot continue past it.

    ``empty_indexes`` holds the table2 indexes of empty placeholder resources.
    A Section whose only resource is one of them is an unused object type and
    gets the ``_empty`` suffix.
    """
    if empty_indexes is None:
        empty_indexes = set()
    names = build_section_names(len(prefix))
    sections: list[Section] = []
    for position, handle in enumerate(prefix):
        first_id = handle & LOGICAL_ID_MASK
        if position + 1 < len(prefix):
            next_id = prefix[position + 1] & LOGICAL_ID_MASK
        else:
            next_id = first_id + 1

        first_index = logical_id_to_index.get(first_id)
        last_index = logical_id_to_index.get(next_id - 1)
        if first_index is None or last_index is None:
            raise SectionTableError(
                f"Section {position + 1} covers logical IDs "
                f"0x{first_id:04x}-0x{next_id - 1:04x} which table1 does not map"
            )
        name = names[position]
        if first_index == last_index and first_index in empty_indexes:
            name += EMPTY_SECTION_SUFFIX
        sections.append(Section(position + 1, name, first_index, last_index))
    return sections


def build_index_labels(sections: list[Section]) -> dict[int, str]:
    """Map every covered table2 index to its Section name."""
    labels: dict[int, str] = {}
    for section in sections:
        for index in range(section.first_index, section.last_index + 1):
            labels[index] = section.name
    return labels


# ------------------------------------------------------------------
# Manifest
# ------------------------------------------------------------------

def read_manifest(manifest_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Return the header and the rows of a resource manifest."""
    text = manifest_path.read_text(encoding=MANIFEST_ENCODING)
    reader = csv.DictReader(text.splitlines())
    rows = list(reader)
    if reader.fieldnames is None:
        raise SectionTableError(f"{manifest_path.name} has no header row")
    return list(reader.fieldnames), rows


def write_manifest(manifest_path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    """Write a resource manifest back in place."""
    with manifest_path.open("w", newline="", encoding=MANIFEST_ENCODING) as manifest_file:
        writer = csv.DictWriter(manifest_file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def build_logical_id_map(rows: list[dict[str, str]], manifest_name: str) -> dict[int, int]:
    """Build the logical ID to table2 index map from manifest rows."""
    id_map: dict[int, int] = {}
    for row in rows:
        logical_text = row.get(LOGICAL_ID_COLUMN, "")
        if not logical_text:
            continue
        id_map[int(logical_text, 16)] = int(row[PHYSICAL_ID_COLUMN])

    if not id_map:
        raise SectionTableError(
            f"{manifest_name} has no {LOGICAL_ID_COLUMN} values; "
            "unpack the archive again with a current version of big-tool"
        )
    return id_map


def move_resources_into_sections(pack_dir: Path, labels: dict[int, str]) -> int:
    """Move every section-covered resource into a folder named after its Section.

    Resources outside the Section system stay at the top of their group folder,
    which is what marks them as unreachable by base-plus-index addressing.
    Files are moved, not copied, so running this twice is a no-op.
    """
    moved_count = 0
    for group_dir in pack_dir.iterdir():
        if not group_dir.is_dir():
            continue

        for resource_path in group_dir.iterdir():
            if not resource_path.is_file():
                continue

            # Derived files such as the string CSVs carry no resource index.
            match = RESOURCE_INDEX_PATTERN.search(resource_path.stem)
            if match is None:
                continue

            section_name = labels.get(int(match.group(1)))
            if section_name is None:
                continue

            section_dir = group_dir / section_name
            section_dir.mkdir(exist_ok=True)
            resource_path.rename(section_dir / resource_path.name)
            moved_count += 1
    return moved_count


def label_pack(pack_dir: Path) -> list[Section]:
    """Rebuild one pack's Section table and write it into its manifest."""
    manifest_files = list(pack_dir.glob(f"*{MANIFEST_SUFFIX}"))
    if not manifest_files:
        raise SectionTableError(f"no resource manifest in {pack_dir.name}")

    manifest_path = manifest_files[0]
    headers, rows = read_manifest(manifest_path)
    empty_indexes = {
        int(row[PHYSICAL_ID_COLUMN])
        for row in rows
        if row["type"] == EMPTY_RESOURCE_TYPE
    }

    prefix = read_keyset_prefix(find_keyset_file(pack_dir).read_bytes())
    sections = build_section_table(
        prefix,
        build_logical_id_map(rows, manifest_path.name),
        empty_indexes,
    )

    labels = build_index_labels(sections)
    for row in rows:
        row[SECTION_COLUMN] = labels.get(int(row[PHYSICAL_ID_COLUMN]), "")
    write_manifest(manifest_path, headers, rows)

    moved_count = move_resources_into_sections(pack_dir, labels)
    logger.debug(
        f"{pack_dir.name}: {len(sections)} sections covering "
        f"table2[{sections[0].first_index}..{sections[-1].last_index}], "
        f"{moved_count} files moved"
    )
    return sections


def label_output_directory(output_dir: Path) -> int:
    """Label every unpacked pack under an output directory. Return the count."""
    output_dir = Path(output_dir).resolve()
    labelled_count = 0
    for pack_dir in sorted(output_dir.iterdir()):
        if not pack_dir.is_dir():
            continue

        # One unreadable pack must not stop the rest: its manifest simply keeps
        # an empty section column.
        try:
            label_pack(pack_dir)
            labelled_count += 1
        except SectionTableError as error:
            logger.warning(f"No sections for {pack_dir.name}: {error}")

    logger.info(f"Labelled sections for {labelled_count} packs")
    return labelled_count
