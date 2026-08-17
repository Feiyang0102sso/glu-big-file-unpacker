"""BIG resource extraction service."""

import csv
import shutil
import struct
import zlib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from big_tool.big_archive.big_format import ArchiveEntry, BigArchive
from big_tool.big_archive.file_types import TYPE_MAP, guess_extension
from big_tool.logger import logger


@dataclass(frozen=True)
class ExtractionResult:
    """Result of one BIG archive extraction."""

    archive: Path
    output_dir: Path
    extracted_count: int
    failed_count: int


def clear_directory(directory: Path) -> None:
    """Clear and recreate an output directory."""
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)


class ArchiveExtractor:
    """Write all resources from one BIG file to an output directory."""

    def __init__(self, archive: BigArchive, output_dir: Path):
        self.archive = archive
        self.output_dir = Path(output_dir).resolve()
        self.stats: defaultdict[str, dict[str, int]] = defaultdict(_new_stats)
        self.csv_data: list[dict[str, object]] = []

    def extract_all(self) -> ExtractionResult:
        """Extract all resources and write a CSV manifest."""
        self.archive.parse()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        failed_count = 0
        for entry in self.archive.entries:
            try:
                self._extract_entry(entry)
            except Exception as error:
                failed_count += 1
                logger.error(f"Failed to process entry {entry.index}: {error}")
                self._append_error_row(entry, str(error))

        self._write_manifest()
        extracted_count = len(self.csv_data) - failed_count
        logger.info(
            f"Extracted {extracted_count} resources from {self.archive.filepath.name}"
        )
        return ExtractionResult(
            self.archive.filepath,
            self.output_dir,
            extracted_count,
            failed_count,
        )

    def _extract_entry(self, entry: ArchiveEntry) -> None:
        block = self.archive.read_entry(entry)
        if len(block) < 4:
            raise ValueError("resource header is truncated")

        resource_hash = entry.group_hash
        header = block[:4]
        is_compressed = bool(header[2] & 0x80)
        compressed_size = 0

        if is_compressed:
            if len(block) < 12:
                raise ValueError("compressed resource header is truncated")
            original_size, compressed_size = struct.unpack("<II", block[4:12])
            if original_size == 0:
                final_data = block[4:12]
                extension = ".bin"
                resource_type = "ref"
            else:
                compressed_data = block[12:12 + compressed_size]
                final_data = zlib.decompress(compressed_data)
                if len(final_data) != original_size:
                    logger.warning(
                        f"Resource {entry.index} size mismatch: "
                        f"declared {original_size}, actual {len(final_data)}"
                    )
                extension = guess_extension(final_data, resource_hash)
                resource_type = extension.lstrip(".")
        else:
            final_data = block[4:]
            original_size = len(final_data)
            extension = guess_extension(final_data, resource_hash)
            resource_type = extension.lstrip(".")

        mapped_type = TYPE_MAP.get(resource_hash)
        if mapped_type is not None:
            resource_type = mapped_type

        group_dir = self.output_dir / hex(resource_hash)
        group_dir.mkdir(parents=True, exist_ok=True)
        filename = (
            f"{self.archive.filepath.stem}_{entry.index:04d}_"
            f"{hex(entry.offset)}{extension}"
        )
        output_path = group_dir / filename
        output_path.write_bytes(final_data)

        self.csv_data.append(
            {
                "id": entry.index,
                "section": "",
                "sub_group": hex(resource_hash),
                "type": resource_type,
                "Offset": hex(entry.offset),
                "compressed?": "T" if is_compressed else "F",
                "compressed size": compressed_size,
                "original size": original_size,
            }
        )
        self.stats[extension]["count"] += 1
        self.stats[extension]["size"] += len(final_data)

    def _append_error_row(self, entry: ArchiveEntry, message: str) -> None:
        self.csv_data.append(
            {
                "id": entry.index,
                "section": "",
                "sub_group": hex(entry.group_hash),
                "type": "ERROR",
                "Offset": hex(entry.offset),
                "compressed?": "N/A",
                "compressed size": 0,
                "original size": 0,
                "error": message,
            }
        )

    def _write_manifest(self) -> None:
        if not self.csv_data:
            return

        manifest_path = self.output_dir / f"{self.archive.filepath.stem}_resources.csv"
        headers = [
            "id",
            "section",
            "sub_group",
            "type",
            "Offset",
            "compressed?",
            "compressed size",
            "original size",
            "error",
        ]
        with manifest_path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=headers)
            writer.writeheader()
            writer.writerows(self.csv_data)


def _natural_sort_key(path: Path) -> list[object]:
    """Build a natural sort key from a file name."""
    parts: list[object] = []
    current = ""
    for char in path.name:
        if char.isdigit():
            if current and not current[-1].isdigit():
                parts.append(current.lower())
                current = ""
            current += char
        else:
            if current and current[-1].isdigit():
                parts.append(int(current))
                current = ""
            current += char
    if current:
        if current.isdigit():
            parts.append(int(current))
        else:
            parts.append(current.lower())
    return parts


def find_archives(input_dir: Path, recursive: bool = True) -> list[Path]:
    """Find BIG files in an input directory."""
    input_dir = Path(input_dir).resolve()
    if not input_dir.is_dir():
        raise NotADirectoryError(input_dir)

    pattern = "**/*.big" if recursive else "*.big"
    archives = list(input_dir.glob(pattern))
    archives.sort(key=_natural_sort_key)
    return archives


def unpack_directory(
    input_dir: Path,
    output_dir: Path | None = None,
    recursive: bool = True,
    clean: bool = True,
    assume_yes: bool = False,
    confirm: Callable[[list[Path]], bool] | None = None,
) -> list[ExtractionResult]:
    """Extract all BIG files in an asset package directory."""
    input_dir = Path(input_dir).resolve()
    if output_dir is None:
        output_dir = input_dir.with_name(f"{input_dir.name}_out")
    output_dir = Path(output_dir).resolve()
    if output_dir == input_dir:
        raise ValueError("Output directory must be different from input directory")

    archives = find_archives(input_dir, recursive=recursive)
    if not archives:
        logger.warning(f"No .big files found in {input_dir}")
        return []

    target_dirs: list[Path] = []
    for archive_path in archives:
        target_dirs.append(output_dir / archive_path.stem)

    existing_targets: list[Path] = []
    for target_dir in target_dirs:
        if target_dir.exists():
            existing_targets.append(target_dir)

    if clean and existing_targets and not assume_yes:
        if confirm is None or not confirm(existing_targets):
            logger.info("Cleanup cancelled by user.")
            return []

    results: list[ExtractionResult] = []
    for archive_path, target_dir in zip(archives, target_dirs):
        if clean:
            clear_directory(target_dir)
        else:
            target_dir.mkdir(parents=True, exist_ok=True)

        try:
            with BigArchive(archive_path) as archive:
                extractor = ArchiveExtractor(archive, target_dir)
                results.append(extractor.extract_all())
        except Exception as error:
            logger.error(f"Failed to unpack {archive_path.name}: {error}")

    return results


def _new_stats() -> dict[str, int]:
    """Create a resource statistics object."""
    return {"count": 0, "size": 0}
