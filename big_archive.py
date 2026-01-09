import struct
import os
from pathlib import Path
from typing import Tuple
from config import logger


class BigArchive:
    """
    represent a .big archive file
    Responsible for parsing the underlying data structure:
    Header, Table1, Table2 (Main TOC) and TOC_Footer
    Data Section
    """

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.file_handle = None
        self.metadata = {}
        self.toc = []
        self._is_parsed = False

    def __enter__(self):
        try:
            self.file_handle = open(self.filepath, 'rb')
        except Exception as e:
            logger.error(f"Failed to open archive {self.filepath}: {e}")
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.file_handle:
            self.file_handle.close()

    def parse(self) -> bool:
        """parse the archive file"""
        if self._is_parsed:
            return True

        logger.info(f"Parsing archive structure: {self.filepath.name}...")
        if not self._load_header_and_footer():
            return False
        if not self._load_main_toc():
            return False

        self._is_parsed = True
        # logger.info(f"Parsed successfully: {len(self.toc)} entries in Main TOC (Table2).")
        # logging the header infos
        logger.debug(
            f"  [Header Info] Version: {self.metadata.get('version')}, Flags: {hex(self.metadata.get('flags', 0))}")
        logger.debug(
            f"  [Table1] Offset: {hex(self.metadata.get('table1_offset', 0))}, Entries: {self.metadata.get('table1_count')}")
        logger.debug(f"  [TOC] Offset: {hex(self.metadata['toc_offset'])}, Entries: {self.metadata['toc_count']}")
        logger.debug(
            f"  [Data Section] Start Offset: {hex(self.metadata.get('data_offset', 0))}, Declared Size: {self.metadata.get('data_size')} bytes")
        return True

    def _load_header_and_footer(self) -> bool:
        """
        Read the 32-byte file header and
        the 8-byte footer located at the end of TOC.
        """
        try:
            self.file_handle.seek(0)
            # header: 32 bytes (0x20)
            # < = Little Endian
            # 4s = Magic ('FGIB')
            # H  = Version (2 bytes)
            # H  = Flags and Padding (1 + 1 bytes)
            # I  = Table1 Offset (4 bytes)
            # I  = Table1 Count (4 bytes)
            # I  = Table2 Offset (Main TOC) (4 bytes)
            # I  = Table2 Count (4 bytes)
            # I  = Data Block Offset (4 bytes)
            # I  = Data Block Size (4 bytes)
            header_fmt = '<4sHHIIIIII'
            header_size = struct.calcsize(header_fmt)  # Should be 32

            if os.path.getsize(self.filepath) < header_size:
                logger.error("File is too small to contain a valid BIG header.")
                return False

            data = self.file_handle.read(header_size)
            (magic, version, flags,
             t1_off, t1_cnt,
             t2_off, t2_cnt,
             data_off, data_size) = struct.unpack(header_fmt, data)

            if magic != b'FGIB':
                logger.warning(f"Invalid magic number: {magic}. Expected b'FGIB'. Continuing anyway...")

            self.metadata = {
                'magic': magic,
                'version': version,
                'flags': flags,
                'table1_offset': t1_off,
                'table1_count': t1_cnt,
                # table2 = TOC
                'toc_offset': t2_off,
                'toc_count': t2_cnt,
                'data_offset': data_off,
                'data_size': data_size
            }

            # --- load Footer ---
            # The footer is located after Table 2 and immediately before the data area.
            # offset = Table2 Offset + (Table2 Entries * 8 bytes per entry)
            footer_offset = t2_off + (t2_cnt * 8)

            # Simple verification
            # If footer_offset + 8 == data_offset, then the structure is very standard.
            if footer_offset + 8 != data_off:
                logger.warning(
                    f"Notice: Footer end ({hex(footer_offset + 8)}) does not match Data start ({hex(data_off)}). There might be gaps.")

            if os.path.getsize(self.filepath) < footer_offset + 8:
                logger.error("File is too small to contain TOC footer.")
                return False

            self.file_handle.seek(footer_offset)
            footer_data = self.file_handle.read(8)
            # The last 4 bytes in the footer is the total file size.
            self.metadata['total_file_size'] = struct.unpack('<I', footer_data[4:])[0]
            # compare the total size
            declared_size = self.metadata['total_file_size']
            actual_size = os.path.getsize(self.filepath)
            # logger.debug(f"  [Footer]  Declared total file size: {declared_size} bytes")
            # logger.debug(f"  [Footer]  Actual   total file size: {actual_size} bytes")
            if declared_size != actual_size:
                logger.warning(f"  [Footer] Size mismatch detected! Declared={declared_size}, Actual={actual_size}")

            # may add more log info about table 1 latter

            return True
        except Exception as e:
            logger.error(f"Error loading header/footer from '{self.filepath.name}': {e}")
            return False

    def _load_main_toc(self) -> bool:
        """read the main TOC (Table2)"""
        try:
            self.toc = []
            self.file_handle.seek(self.metadata['toc_offset'])
            for _ in range(self.metadata['toc_count']):
                entry_data = self.file_handle.read(8)
                if len(entry_data) < 8: break
                # Each item is 8 bytes: 4 bytes Group_Hash, 4 bytes Offset
                name_hash, resource_offset = struct.unpack('<II', entry_data)
                self.toc.append({'hash': name_hash, 'offset': resource_offset})

            # Each entry is 8 bytes: 4 bytes Group_Hash, 4 bytes Offset
            self.toc.sort(key=lambda x: x['offset'])
            return True
        except Exception as e:
            logger.error(f"Error loading TOC from '{self.filepath.name}': {e}")
            return False

    def get_entry_data_info(self, index: int) -> Tuple[int, int]:
        """
        Calculates the data block size for a specified index entry.
        return (offset, block_size)
        """
        entry = self.toc[index]
        offset = entry['offset']

        if index + 1 < len(self.toc):
            next_offset = self.toc[index + 1]['offset']
            block_size = next_offset - offset
        else:
            # Prioritize using the total_file_size from the metadata (from the footer),
            # as this is usually the most accurate physical endpoint.
            end_of_data = self.metadata.get('total_file_size')

            # If the footer is not found, os.path.getsize can be used as a backup.
            if not end_of_data:
                end_of_data = os.path.getsize(self.filepath)

            block_size = end_of_data - offset

        return offset, max(0, block_size)