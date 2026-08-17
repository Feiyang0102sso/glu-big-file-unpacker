"""String resource extractor."""

import csv
import struct
from dataclasses import dataclass
from pathlib import Path

from big_tool.logger import logger


@dataclass(frozen=True)
class StringResource:
    """A string resource and its file location."""

    resource_id: int
    offset: int
    length: int
    text: str


class ResourceStringExtractor:
    """
    File layout:
    [Header(8B)] [Offsets(N*2B)] [Offset End(2B)] [Types(N*4B)] [Data]
    """

    MAGIC_ID = b"\x00\xa0"
    HEADER_SIZE = 8
    OFFSET_ENTRY_SIZE = 2
    OFFSET_END_PADDING_SIZE = 2
    TYPE_ENTRY_SIZE = 4
    STRING_BLOCK_PREFIX_SIZE = 4
    STRING_ENCODING = "utf-8"

    def __init__(self, filepath: Path):
        self.filepath = Path(filepath).resolve()
        self.resource_count = 0
        self.offset_table: list[int] = []
        self.extracted_strings: list[StringResource] = []
        self.data_start_offset = 0

    def extract(self) -> list[StringResource]:
        """Extract all string resources."""
        data = self.filepath.read_bytes()
        self._read_header(data)
        self._read_offset_table(data)
        self._calculate_pointers()
        self._extract_strings(data)
        return self.extracted_strings

    def write_csv(self, output_filepath: Path | None = None) -> Path:
        """Extract strings and write a CSV file."""
        if not self.extracted_strings:
            self.extract()

        if output_filepath is None:
            output_filepath = self.filepath.with_name(
                f"{self.filepath.stem}_Strings.csv"
            )

        output_filepath = Path(output_filepath).resolve()
        output_filepath.parent.mkdir(parents=True, exist_ok=True)
        with output_filepath.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=["id", "offset", "length", "String"])
            writer.writeheader()
            for resource in self.extracted_strings:
                writer.writerow(
                    {
                        "id": resource.resource_id,
                        "offset": hex(resource.offset),
                        "length": resource.length,
                        "String": resource.text,
                    }
                )

        logger.info(f"Writing {len(self.extracted_strings)} strings to {output_filepath}")
        return output_filepath

    def _read_header(self, data: bytes) -> None:
        if len(data) < self.HEADER_SIZE:
            raise ValueError("File size is too small for a string resource header")

        header = data[: self.HEADER_SIZE]
        if header[:2] != self.MAGIC_ID:
            raise ValueError(
                f"Invalid file signature: expected {self.MAGIC_ID.hex()}, got {header[:2].hex()}"
            )

        self.resource_count = struct.unpack("<H", header[2:4])[0]
        if self.resource_count <= 0:
            raise ValueError(f"Invalid resource count: {self.resource_count}")

        first_offset = struct.unpack("<H", header[6:8])[0]
        self.offset_table = [first_offset]

    def _read_offset_table(self, data: bytes) -> None:
        table_start = self.HEADER_SIZE
        table_size = self.resource_count * self.OFFSET_ENTRY_SIZE
        table_end = table_start + table_size
        if table_end + self.OFFSET_END_PADDING_SIZE > len(data):
            raise ValueError("Offset table data truncated")

        for position in range(table_start, table_end, self.OFFSET_ENTRY_SIZE):
            offset = struct.unpack("<H", data[position:position + 2])[0]
            self.offset_table.append(offset)

        padding_start = table_end
        padding = data[padding_start:padding_start + self.OFFSET_END_PADDING_SIZE]
        if padding != b"\x00\x00":
            logger.warning(
                f"Offset table padding mismatch: expected 0000, got {padding.hex()}"
            )

    def _calculate_pointers(self) -> None:
        table_size = self.resource_count * self.OFFSET_ENTRY_SIZE
        type_table_start = self.HEADER_SIZE + table_size + self.OFFSET_END_PADDING_SIZE
        self.data_start_offset = type_table_start + self.resource_count * self.TYPE_ENTRY_SIZE

    def _extract_strings(self, data: bytes) -> None:
        current_offset = self.data_start_offset
        self.extracted_strings = []

        for resource_id in range(self.resource_count):
            next_offset = self.offset_table[resource_id + 1]
            declared_length = next_offset - current_offset
            if declared_length < 0:
                raise ValueError(f"Invalid string offset at resource {resource_id}")

            block = data[current_offset:next_offset]
            if len(block) != declared_length:
                logger.warning(f"String resource {resource_id} is truncated")

            string_body = block[self.STRING_BLOCK_PREFIX_SIZE:]
            if string_body.endswith(b"\x00"):
                string_body = string_body[:-1]
            elif string_body:
                logger.warning(f"String resource {resource_id} has no null terminator")

            text = string_body.decode(self.STRING_ENCODING, errors="replace")
            self.extracted_strings.append(
                StringResource(
                    resource_id,
                    current_offset,
                    len(string_body),
                    text.replace("\n", "\\n"),
                )
            )
            current_offset = next_offset


def extract_strings_from_directory(root_dir: Path) -> list[Path]:
    """Extract parseable string BIN files recursively."""
    root_dir = Path(root_dir).resolve()
    if not root_dir.is_dir():
        raise NotADirectoryError(root_dir)

    output_files: list[Path] = []
    files = list(root_dir.rglob("*.bin"))
    files.sort()
    for filepath in files:
        if filepath.stat().st_size < ResourceStringExtractor.HEADER_SIZE:
            logger.warning(f"Skipping small file: {filepath.name}")
            continue

        try:
            extractor = ResourceStringExtractor(filepath)
            output_files.append(extractor.write_csv())
        except ValueError as error:
            logger.warning(f"Skipping {filepath.name}: {error}")

    return output_files
