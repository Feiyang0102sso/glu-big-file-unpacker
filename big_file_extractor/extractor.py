import zlib
import struct
import csv
from collections import defaultdict
from pathlib import Path
from typing import Dict

from logger import logger
from big_archive import BigArchive
from utils_file_type import FileTypeUtils


class ResourceExtractor:
    # Mapping of resource hashes to types
    TYPE_MAP = {
        0x69e4c505: "string pack",
        0x69e5d35c: "meta data",
        0xb7178678: "png",
        0xf4e02223: ".bin",
        0xf686aadc: "manifest",
        0xfd8a7754: "wav"
    }

    def __init__(self, archive: BigArchive, output_basedir: Path):
        self.archive = archive
        self.output_dir = output_basedir / archive.filepath.stem
        self.stats = defaultdict(lambda: {"count": 0, "size": 0})
        self.csv_data = []  # store csv

    def extract_all(self):
        if not self.archive.parse():
            logger.error("Cannot extract: Archive parsed failed.")
            return

        logger.info(f"\n{'=' * 40}")
        logger.info(f"Start extracting files: {self.archive.filepath.name}")
        logger.info(f"{'=' * 40}")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.csv_data = []  # Reset CSV data on each extraction

        total_files = len(self.archive.toc)
        for i, entry in enumerate(self.archive.toc):
            self._extract_single_entry(i, entry)

        self._print_summary()
        self.export_to_csv()  # Automatically export CSV after extraction

    def _extract_single_entry(self, index: int, entry: Dict):
        res_hash = entry['hash']
        offset, block_size = self.archive.get_entry_data_info(index)

        # --- initialize csv data ---
        csv_is_compressed_bool = False
        csv_compressed_size = 0
        csv_original_size = 0
        csv_type = "unknown"  # default

        try:
            self.archive.file_handle.seek(offset)
            std_header = self.archive.file_handle.read(4)
            if len(std_header) < 4: return

            compression_flag = std_header[2]
            is_compressed = (compression_flag & 0x80) != 0
            csv_is_compressed_bool = is_compressed  # whether data compressed

            final_data = b''
            log_extra_info = ""

            if is_compressed:
                extra_header = self.archive.file_handle.read(8)
                original_size, compressed_size = struct.unpack('<II', extra_header)

                # 记录压缩和原始大小
                csv_original_size = original_size
                csv_compressed_size = compressed_size

                if original_size == 0:
                    # --- all file regarded as .bin ---
                    final_data = extra_header
                    extension = ".bin"
                    log_extra_info = "(Placeholder/Reference)"
                    csv_type = "ref"  # 0kb can be seen as ref
                else:
                    compressed_data = self.archive.file_handle.read(compressed_size)
                    try:
                        final_data = zlib.decompress(compressed_data)
                        extension = FileTypeUtils.guess_extension(final_data, res_hash)
                        csv_type = extension.lstrip('.')  # 初始类型为扩展名
                        log_extra_info = f"(Compressed: {compressed_size} -> {original_size})"
                    except zlib.error as e:
                        logger.error(f"  [ERROR] Decompression failed at {hex(offset)}: {e}")
                        extension = ".corrupt"
                        csv_type = "corrupt"
                        final_data = compressed_data
            else:
                data_len = max(0, block_size - 4)
                final_data = self.archive.file_handle.read(data_len)

                # Uncompressed file, original size = file size, compressed size is 0.
                csv_original_size = len(final_data)
                csv_compressed_size = 0  # set to 0

                extension = FileTypeUtils.guess_extension(final_data, res_hash)
                csv_type = extension.lstrip('.')  # 初始类型为扩展名
                log_extra_info = f"(Uncompressed: {len(final_data)} bytes)"

            # --- Check hash table for overlay type ---
            if res_hash in ResourceExtractor.TYPE_MAP:
                csv_type = ResourceExtractor.TYPE_MAP[res_hash]

            # --- Store CSV row data ---
            row = {
                "id": index,
                "section": "",  # leave blank
                "sub_group": hex(res_hash),
                "type": csv_type,
                "Offset": hex(offset),
                "compressed?": "T" if csv_is_compressed_bool else "F",
                "compressed size": csv_compressed_size,
                "original size": csv_original_size
            }
            self.csv_data.append(row)

            # --- write to disk ---
            group_dir = self.output_dir / hex(res_hash)
            group_dir.mkdir(parents=True, exist_ok=True)

            archive_prefix = self.archive.filepath.stem
            resource_index = f"{index:04d}"
            output_filename = f"{archive_prefix}_{resource_index}_{hex(offset)}{extension}"

            output_path = group_dir / output_filename
            with open(output_path, 'wb') as f:
                f.write(final_data)

            logger.debug(f"Extracted: {hex(res_hash)}/{output_filename} {log_extra_info}")

            self.stats[extension]["count"] += 1
            self.stats[extension]["size"] += len(final_data)

        except Exception as e:
            logger.error(f"Failed to process entry at {hex(offset)}: {e}")
            # if writing to csv failed
            row = {
                "id": index,
                "section": "",
                "sub_group": hex(res_hash),
                "type": "ERROR",
                "Offset": hex(offset),
                "compressed?": "N/A",
                "compressed size": 0,
                "original size": 0
            }
            self.csv_data.append(row)

    def _print_summary(self):
        total_bytes = sum(v["size"] for v in self.stats.values())
        total_count = sum(v["count"] for v in self.stats.values())
        logger.info("-" * 40)
        logger.info(f"Extract Summary: {self.archive.filepath.name}")
        logger.info(f"Total file: {total_count}, Total size: {total_bytes / 1024 / 1024:.2f} MB")
        for ext, data in sorted(self.stats.items(), key=lambda x: -x[1]["count"]):
            logger.info(f"  {ext:<8} | num: {data['count']:<5} | size: {data['size'] / 1024:>8.2f} KB")
        logger.info("-" * 40 + "\n")

    def export_to_csv(self):
        """
        export data into a csv file
        """
        if not self.csv_data:
            logger.info("No resource data to export to CSV.")
            return

        # CSV filenames begin with .bigdocumentname + .csv
        csv_filename = self.archive.filepath.stem + "_resources.csv"
        csv_path = self.output_dir / csv_filename

        # CSV cols
        headers = [
            "id", "section", "sub_group", "type", "Offset",
            "compressed?", "compressed size", "original size"
        ]

        logger.info(f"Exporting resource manifest to {csv_path}...")
        try:
            with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(self.csv_data)
            logger.info(f"Successfully exported {len(self.csv_data)} rows to {csv_path}")
        except Exception as e:
            logger.error(f"Failed to write CSV manifest: {e}")