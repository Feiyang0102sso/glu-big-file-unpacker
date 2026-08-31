"""Parser for FGIB/BIG archives."""

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from big_tool.logger import logger


class BigArchiveError(ValueError):
    """Raised when a BIG archive has an invalid structure."""


@dataclass(frozen=True)
class LogicalIdRange:
    """One table1 entry: a run of logical IDs mapped to a run of table2 indices."""

    base_resource_id: int
    length: int
    table2_start_index: int


@dataclass(frozen=True)
class ArchiveEntry:
    """One resource entry in the BIG table of contents."""

    index: int
    group_hash: int
    offset: int
    size: int


class BigArchive:
    """Read BIG headers, tables, and resource data."""

    HEADER_FORMAT = "<4sHHIIIIII"
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
    ENTRY_FORMAT = "<II"
    ENTRY_SIZE = struct.calcsize(ENTRY_FORMAT)
    RANGE_FORMAT = "<IHH"
    RANGE_SIZE = struct.calcsize(RANGE_FORMAT)
    FOOTER_SIZE = 8

    def __init__(self, filepath: Path):
        self.filepath = Path(filepath).resolve()
        self.file_handle: BinaryIO | None = None
        self.metadata: dict[str, int | bytes] = {}
        self.entries: list[ArchiveEntry] = []
        self.id_ranges: list[LogicalIdRange] = []
        self._is_parsed = False

    @property
    def toc(self) -> list[ArchiveEntry]:
        """Return the table of contents."""
        return self.entries

    def __enter__(self) -> "BigArchive":
        self.file_handle = self.filepath.open("rb")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.file_handle is not None:
            self.file_handle.close()
            self.file_handle = None

    def parse(self) -> "BigArchive":
        """Parse the archive and return this object."""
        if self._is_parsed:
            return self

        if not self.filepath.is_file():
            raise FileNotFoundError(self.filepath)

        if self.file_handle is None:
            raise RuntimeError("BigArchive must be used as a context manager")

        logger.info(f"Parsing archive structure: {self.filepath.name}...")
        self._load_header_and_footer()
        self._load_id_ranges()
        self._load_main_toc()
        self._is_parsed = True
        return self

    def _load_header_and_footer(self) -> None:
        file_size = self.filepath.stat().st_size
        if file_size < self.HEADER_SIZE:
            raise BigArchiveError("File is too small to contain a valid BIG header")

        self.file_handle.seek(0)
        data = self.file_handle.read(self.HEADER_SIZE)
        unpacked = struct.unpack(self.HEADER_FORMAT, data)
        magic, version, flags, table1_offset, table1_count, toc_offset, toc_count, data_offset, data_size = unpacked

        if magic != b"FGIB":
            logger.warning(f"Invalid magic number: {magic!r}. Expected b'FGIB'.")

        footer_offset = toc_offset + toc_count * self.ENTRY_SIZE
        footer_end = footer_offset + self.FOOTER_SIZE
        if footer_end > file_size:
            raise BigArchiveError("File is too small to contain the BIG TOC footer")

        if footer_end != data_offset:
            logger.warning(
                f"Footer end ({hex(footer_end)}) does not match data start ({hex(data_offset)})"
            )

        self.file_handle.seek(footer_offset)
        footer_data = self.file_handle.read(self.FOOTER_SIZE)
        declared_file_size = struct.unpack("<I", footer_data[4:])[0]
        if declared_file_size != file_size:
            logger.warning(
                f"Declared file size {declared_file_size} differs from actual size {file_size}"
            )

        self.metadata = {
            "magic": magic,
            "version": version,
            "flags": flags,
            "table1_offset": table1_offset,
            "table1_count": table1_count,
            "toc_offset": toc_offset,
            "toc_count": toc_count,
            "data_offset": data_offset,
            "data_size": data_size,
            "total_file_size": declared_file_size,
        }

    def _load_id_ranges(self) -> None:
        """Read table1, the sparse logical ID to table2 index mapping."""
        table1_offset = int(self.metadata["table1_offset"])
        table1_count = int(self.metadata["table1_count"])
        file_size = self.filepath.stat().st_size
        table1_end = table1_offset + table1_count * self.RANGE_SIZE
        if table1_offset < self.HEADER_SIZE or table1_end > file_size:
            raise BigArchiveError("BIG table1 is outside the file")

        self.file_handle.seek(table1_offset)
        self.id_ranges = []
        for _ in range(table1_count):
            range_data = self.file_handle.read(self.RANGE_SIZE)
            if len(range_data) != self.RANGE_SIZE:
                raise BigArchiveError("BIG table1 is truncated")
            base_id, length, start_index = struct.unpack(self.RANGE_FORMAT, range_data)
            self.id_ranges.append(LogicalIdRange(base_id, length, start_index))

    def logical_id_of(self, table2_index: int) -> int | None:
        """Return the logical resource ID of a table2 entry, or None if unmapped."""
        for id_range in self.id_ranges:
            distance = table2_index - id_range.table2_start_index
            if 0 <= distance < id_range.length:
                return id_range.base_resource_id + distance
        return None

    def table2_index_of(self, logical_id: int) -> int | None:
        """Return the table2 index of a logical resource ID, or None if unmapped.

        Logical IDs that fall in a table1 hole belong to string pack entries and
        are resolved by the string pack itself, not by this table.
        """
        for id_range in self.id_ranges:
            distance = logical_id - id_range.base_resource_id
            if 0 <= distance < id_range.length:
                return id_range.table2_start_index + distance
        return None

    def _load_main_toc(self) -> None:
        toc_offset = int(self.metadata["toc_offset"])
        toc_count = int(self.metadata["toc_count"])
        file_size = self.filepath.stat().st_size
        toc_end = toc_offset + toc_count * self.ENTRY_SIZE
        if toc_offset < self.HEADER_SIZE or toc_end > file_size:
            raise BigArchiveError("BIG main TOC is outside the file")

        self.file_handle.seek(toc_offset)
        raw_entries: list[tuple[int, int]] = []
        for _ in range(toc_count):
            entry_data = self.file_handle.read(self.ENTRY_SIZE)
            if len(entry_data) != self.ENTRY_SIZE:
                raise BigArchiveError("BIG main TOC is truncated")
            raw_entries.append(struct.unpack(self.ENTRY_FORMAT, entry_data))

        raw_entries.sort(key=_resource_offset)
        self.entries = []
        for index, item in enumerate(raw_entries):
            group_hash, offset = item
            next_offset = file_size
            if index + 1 < len(raw_entries):
                next_offset = raw_entries[index + 1][1]

            if offset < 0 or offset > next_offset or next_offset > file_size:
                raise BigArchiveError(f"Invalid resource offset at entry {index}")

            self.entries.append(ArchiveEntry(index, group_hash, offset, next_offset - offset))

    def get_entry_data_info(self, index: int) -> tuple[int, int]:
        """Return a resource offset and its physical size."""
        if not self._is_parsed:
            self.parse()

        entry = self.entries[index]
        return entry.offset, entry.size

    def read_entry(self, entry: ArchiveEntry) -> bytes:
        """Read the complete data block for one resource."""
        if self.file_handle is None:
            raise RuntimeError("BigArchive must be used as a context manager")

        self.file_handle.seek(entry.offset)
        data = self.file_handle.read(entry.size)
        if len(data) != entry.size:
            raise BigArchiveError(f"Resource {entry.index} is truncated")
        return data


def _resource_offset(item: tuple[int, int]) -> int:
    """Return the resource offset from a table entry."""
    return item[1]
