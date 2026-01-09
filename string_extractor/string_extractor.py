# string extractor
import struct
import csv
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any, BinaryIO
from config import logger, ROOT_DIR

# === Config Area ===
MAGIC_ID = b'\x00\xa0'
HEADER_SIZE = 8
OFFSET_ENTRY_SIZE = 2
OFFSET_END_PADDING_SIZE = 2
TYPE_ENTRY_SIZE = 4
STRING_BLOCK_PREFIX_SIZE = 4
STRING_BLOCK_PREFIX = b'\x40\x00\x00\00'
STRING_BLOCK_TERMINATOR_SIZE = 1
STRING_BLOCK_TERMINATOR = b'\x00'
#
STRING_ENCODING = 'utf-8'

INPUT_DIRECTORY = ROOT_DIR / 'asserts_100_strings'


class ResourceStringExtractor:
    """
    STRUCTURE: [Header(8B)] [Offsets(N*2B)] [Offset End(2B)] [Types(N*4B)] [Data]
    """

    def __init__(self, filepath: Path):
        self.filepath: Path = filepath
        self.output_filepath: Path = filepath.with_name(f"{filepath.stem}_Strings.csv")
        self.resource_count: int = 0
        self.offset_table: List[int] = []
        self.extracted_strings: List[Dict[str, Any]] = []

        # Header and table calculated attributes
        self.offset_table_start: int = HEADER_SIZE
        self.toc_end: int = 0
        self.type_table_start: int = 0
        self.data_start_offset: int = 0

    def _read_header(self, f: BinaryIO):
        """valid header section"""
        f.seek(0)
        header_data = f.read(HEADER_SIZE)
        if len(header_data) < HEADER_SIZE:
            raise ValueError(f"File size is too small (less than {HEADER_SIZE} bytes).")

        if header_data[0:2] != MAGIC_ID:
            raise ValueError(f"Invalid file signature: Expected {MAGIC_ID.hex()}, got {header_data[0:2].hex()}")

        # 0x02 - 0x03: Resource Count N
        count_declared = struct.unpack('<H', header_data[2:4])[0]
        self.resource_count = count_declared  # no need to -1 actually, it should be N entry declared
        if self.resource_count <= 0:
            raise ValueError(f"Invalid resource count: {self.resource_count}")

        # 0x06 - 0x07: First String End Offset (Offset_1)
        offset_one = struct.unpack('<H', header_data[6:8])[0]
        self.offset_table.append(offset_one)

    def _read_offset_table(self, f: BinaryIO):
        """Read and construct a complete list of string end offsets."""

        # Calculate the size of the offset table body (N entries).
        offset_table_size = self.resource_count * OFFSET_ENTRY_SIZE

        # Read the next N offsets entry starting from 0x08
        f.seek(self.offset_table_start)
        offset_data = f.read(offset_table_size)

        if len(offset_data) < offset_table_size:
            raise ValueError("Offset table data truncated.")

        # Read the subsequent N offsets to form a total list of N+1 offsets.
        num_entries = offset_table_size // OFFSET_ENTRY_SIZE

        for i in range(num_entries):
            offset_val = struct.unpack('<H', offset_data[i * 2: (i + 1) * 2])[0]
            self.offset_table.append(offset_val)

        # valid Offset End Padding (00 00)
        f.seek(self.offset_table_start + offset_table_size)
        padding = f.read(OFFSET_END_PADDING_SIZE)
        if padding != b'\x00\x00':
            logger.warning(
                f"Offset End padding mismatch: Expected 0000, got {padding.hex()}. Structure might be corrupted.")

    def _calculate_pointers(self):
        """Calculate the starting position of the Type Table and Data Area."""

        offset_table_size = self.resource_count * OFFSET_ENTRY_SIZE

        #  Offset End
        self.toc_end = self.offset_table_start + offset_table_size

        # entry start: Offset End + 2  (00 00 Padding)
        self.type_table_start = self.toc_end + OFFSET_END_PADDING_SIZE

        # Data Area Start
        # Type Table Size = N * 4
        self.data_start_offset = self.type_table_start + (self.resource_count * TYPE_ENTRY_SIZE)

    def _extract_strings(self, f: BinaryIO):
        """Use the calculated offset table to extract the string."""

        # The starting position of the first string
        current_offset = self.data_start_offset

        # 0 to N-1
        for i in range(self.resource_count):

            # offset_next It is the end position of the current string (including the 0x00 terminator).
            offset_next = self.offset_table[i + 1]

            declared_length = offset_next - current_offset

            # Skip entries that are too short to contain the prefix.
            if declared_length < STRING_BLOCK_PREFIX_SIZE:
                current_offset = offset_next
                continue

            f.seek(current_offset)
            data = f.read(declared_length)

            # check Declared Length vs Extracted Length
            extracted_length = len(data)
            if extracted_length != declared_length:
                logger.warning(
                    f"ID {i}: Length mismatch. Declared length ({declared_length}) != Extracted length ({extracted_length}). Proceeding with extracted length."
                )

            # Remove the 4-byte prefix (Type ID) from the data block.
            string_data_with_null = data[STRING_BLOCK_PREFIX_SIZE:]

            # Remove the trailing NULL terminator (0x00).
            if string_data_with_null and string_data_with_null[-1] == 0x00:
                string_body = string_data_with_null[:-1]
            else:
                string_body = string_data_with_null

                if declared_length > STRING_BLOCK_PREFIX_SIZE:
                    logger.warning(
                        f"ID {i}: String data (Offset {hex(current_offset + STRING_BLOCK_PREFIX_SIZE)}) does not end with NULL terminator.")

            try:
                string_text = string_body.decode(STRING_ENCODING, errors='replace')
            except Exception:
                # When decoding fails, record the original hex value.
                string_text = f"[DECODE_ERR] {string_body.hex()}"

            self.extracted_strings.append({
                'id': i,  # ID start with 0
                'offset': hex(current_offset),
                'length': declared_length - STRING_BLOCK_PREFIX_SIZE,
                'String': string_text.replace('\n', '\\n'),
            })

            # Move to the beginning of the next string.
            current_offset = offset_next

    def _write_to_csv(self):
        """Write the extracted list of strings to a CSV file."""
        if not self.extracted_strings:
            logger.info(f"No strings extracted from {self.filepath.name}.")
            return

        logger.info(f"Writing {len(self.extracted_strings)} strings to {self.output_filepath.name}")

        fieldnames = ['id', 'offset', 'length', 'String']
        try:
            with open(self.output_filepath, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(
                    csvfile,
                    fieldnames=fieldnames,
                    quoting=csv.QUOTE_MINIMAL,
                    escapechar='\\'
                )
                writer.writeheader()
                writer.writerows(self.extracted_strings)
        except Exception as e:
            logger.error(f"Failed to write CSV file: {e}")

    def run(self):
        """run the code"""
        logger.info(f"--- Analyzing: {self.filepath.name} ---")
        try:
            with open(self.filepath, 'rb') as f:
                self._read_header(f)
                self._read_offset_table(f)
                self._calculate_pointers()
                self._extract_strings(f)

            #  check Declared entry count vs. Extracted entry count
            extracted_count = len(self.extracted_strings)

            if extracted_count == self.resource_count:
                logger.info(
                    f"Entry count validation passed: Declared ({self.resource_count}) == Extracted ({extracted_count}).")
            else:
                logger.warning(
                    f"Entry count mismatch: Declared count ({self.resource_count}) != Extracted count ({extracted_count})."
                )

            self._write_to_csv()
            logger.info(
                f"Successfully processed {self.filepath.name}. Resources found: {self.resource_count} (Extracted: {extracted_count})")

        except FileNotFoundError:
            logger.error(f"File not found: {self.filepath}")
        except ValueError as e:
            logger.error(f"Format error in {self.filepath.name}: {e}")
            raise  # Throw an exception when encountering a formatting error.
        except Exception as e:
            logger.exception(f"An unexpected error occurred during processing {self.filepath.name}: {e}")
            raise  # Throw an error when it cannot be handled


def extract_strings_from_directory(root_dir: Path):
    """
    extract strings from all .bin files.
    """
    if not root_dir.is_dir():
        logger.error(f"Input path is not a directory: {root_dir}")
        return

    logger.info(f"\n{'=' * 40}")
    logger.info(f"Start scanning directory: {root_dir.resolve()}")

    found_files = list(root_dir.rglob('*.bin'))
    if not found_files:
        logger.info("No .bin files found.")
        return

    logger.info(f"Found {len(found_files)} .bin files to process.")
    logger.info(f"{'=' * 40}")

    for filepath in found_files:
        try:
            if filepath.stat().st_size >= HEADER_SIZE:
                extractor = ResourceStringExtractor(filepath)
                extractor.run()
            else:
                logger.warning(f"Skipping small file: {filepath.name}")
        except Exception as e:
            # Catch any exceptions thrown in run and ensure the main loop continues.
            logger.error(f"Skipping {filepath.name} due to unrecoverable error: {e}")


def main():
    extract_strings_from_directory(INPUT_DIRECTORY)


if __name__ == '__main__':
    main()