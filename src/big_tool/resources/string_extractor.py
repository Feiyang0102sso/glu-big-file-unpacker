"""String pack (group hash 0x69E4C505) parser and CSV exporter."""

import csv
import struct
from dataclasses import dataclass
from pathlib import Path

from big_tool.logger import logger


# ------------------------------------------------------------------
# Header
# ------------------------------------------------------------------

# Layout: magic(2) + entryCount(2) + entryId(2) + first entry offset(2 or 4)
MAGIC_POSITION = 0
ENTRY_COUNT_POSITION = 2
FIRST_OFFSET_POSITION = 6
MIN_HEADER_SIZE = 10

# Magic bit flags.
# 0x8000 set   -> byte 4..6 is the id of the whole pack, entries only store offsets.
# 0x8000 clear -> every entry stores its own uint16 id followed by its offset.
# Either way byte 4..6 is a uint16 id, which is why byte 6 always starts an offset.
FLAG_SEQUENTIAL_ID = 0x8000
FLAG_32BIT_OFFSET = 0x4000
KNOWN_MAGICS = {0x2000, 0xA000, 0xE000}

# ------------------------------------------------------------------
# Resource type table
# ------------------------------------------------------------------

# One uint32 per entry, stored right before the string data.
TYPE_ENTRY_SIZE = 4
RESOURCE_TYPE_UTF8 = 0xF686AADC

# ------------------------------------------------------------------
# String block
# ------------------------------------------------------------------

# uint32 prefix (always 4 in every known sample) + UTF-8 text + 0x00.
BLOCK_PREFIX_SIZE = 4
BLOCK_TERMINATOR = b"\x00"
STRING_ENCODING = "utf-8"

CSV_HEADERS = ["id", "offset", "length", "String"]
CSV_SUFFIX = "_Strings.csv"


@dataclass(frozen=True)
class StringResource:
    """A string resource and its file location."""

    resource_id: int
    offset: int
    length: int
    text: str


class ResourceStringExtractor:
    """
    Read every string out of a string pack.

    File layout:
        [header] [offset table] [type table] [string blocks]

    The offset table is redundant: string blocks are stored back to back, so
    parsing jumps straight to the first entry offset and walks forward until
    the end of the file. Verified against every known sample - the derived
    offsets match the declared table exactly.
    """

    def __init__(self, filepath: Path):
        self.filepath = Path(filepath).resolve()
        self.magic = 0
        self.entry_count = 0
        self.data_start = 0
        self.strings: list[StringResource] = []

    def extract(self) -> list[StringResource]:
        """Parse the file and return all string resources."""
        data = self.filepath.read_bytes()
        self._read_header(data)
        self._read_strings(data)
        self._check_resource_types(data)
        return self.strings

    def write_csv(self) -> Path:
        """Write the strings to a CSV file next to the string pack."""
        if not self.strings:
            self.extract()

        output_filepath = self.filepath.with_name(f"{self.filepath.stem}{CSV_SUFFIX}")
        with output_filepath.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_HEADERS)
            writer.writeheader()
            for resource in self.strings:
                writer.writerow(
                    {
                        "id": resource.resource_id,
                        "offset": hex(resource.offset),
                        "length": resource.length,
                        "String": resource.text,
                    }
                )

        logger.info(f"Wrote {len(self.strings)} strings to {output_filepath}")
        return output_filepath

    def _read_header(self, data: bytes) -> None:
        """Read the magic, the entry count and where the string data starts."""
        if len(data) < MIN_HEADER_SIZE:
            raise ValueError("File is too small to be a string pack")

        self.magic = struct.unpack_from("<H", data, MAGIC_POSITION)[0]
        if self.magic not in KNOWN_MAGICS:
            logger.warning(
                f"{self.filepath.name}: unknown string pack magic {hex(self.magic)}, "
                f"parsing it as a {'32' if self.magic & FLAG_32BIT_OFFSET else '16'}-bit offset table"
            )

        self.entry_count = struct.unpack_from("<H", data, ENTRY_COUNT_POSITION)[0]

        # The first entry offset is where the string data begins.
        if self.magic & FLAG_32BIT_OFFSET:
            self.data_start = struct.unpack_from("<I", data, FIRST_OFFSET_POSITION)[0]
        else:
            self.data_start = struct.unpack_from("<H", data, FIRST_OFFSET_POSITION)[0]

        if self.data_start > len(data):
            raise ValueError(
                f"First entry offset {hex(self.data_start)} is outside the file"
            )

    def _check_resource_types(self, data: bytes) -> None:
        """Warn once if the pack does not hold UTF-8 string resources."""
        table_start = self.data_start - self.entry_count * TYPE_ENTRY_SIZE
        if table_start < FIRST_OFFSET_POSITION:
            logger.warning(
                f"{self.filepath.name}: no room for a resource type table before {hex(self.data_start)}"
            )
            return

        for index in range(self.entry_count):
            resource_type = struct.unpack_from("<I", data, table_start + index * TYPE_ENTRY_SIZE)[0]
            if resource_type != RESOURCE_TYPE_UTF8:
                logger.warning(
                    f"{self.filepath.name}: entry {index} has resource type {hex(resource_type)}, "
                    f"not UTF-8 ({hex(RESOURCE_TYPE_UTF8)})"
                )
                return

    def _read_strings(self, data: bytes) -> None:
        """Walk the string blocks from the first entry offset to the end of the file."""
        self.strings = []
        position = self.data_start

        # A block needs a prefix plus at least the terminator byte.
        while position + BLOCK_PREFIX_SIZE < len(data):
            text_start = position + BLOCK_PREFIX_SIZE
            terminator_position = data.find(BLOCK_TERMINATOR, text_start)
            if terminator_position < 0:
                raise ValueError(f"String block at {hex(position)} has no terminator")

            body = data[text_start:terminator_position]
            # Escape newlines so a multi line string stays on one CSV row.
            text = body.decode(STRING_ENCODING, errors="replace").replace("\n", "\\n")
            self.strings.append(
                StringResource(len(self.strings), position, len(body), text)
            )
            position = terminator_position + 1

        if len(self.strings) != self.entry_count:
            raise ValueError(
                f"Entry count mismatch: header declares {self.entry_count}, "
                f"parsed {len(self.strings)}"
            )
