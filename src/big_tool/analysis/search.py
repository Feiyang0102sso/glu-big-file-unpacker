"""Binary file search tools."""

import mmap
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SearchOptions:
    """Options for a binary search."""

    target_value: str
    big_endian: bool = True
    file_extension: str | None = "*"
    mode: str = "exact"
    start_offset: int | None = None
    size_min: int | None = None
    size_max: int | None = None


@dataclass(frozen=True)
class SearchResult:
    """Search results for one file."""

    path: Path
    offsets: tuple[int, ...]
    score: int


def parse_value_to_bytes(value: str, big_endian: bool = False) -> bytes:
    """Convert a decimal or hexadecimal value to search bytes."""
    clean_value = str(value).strip()
    if clean_value.lower().startswith("0x"):
        clean_hex = clean_value[2:].replace(" ", "").replace(",", "").replace("_", "")
        if not clean_hex:
            raise ValueError(f"Invalid hexadecimal value: {value}")
        if len(clean_hex) % 2:
            clean_hex = f"0{clean_hex}"
        try:
            target_bytes = bytes.fromhex(clean_hex)
        except ValueError as error:
            raise ValueError(f"Invalid hexadecimal value: {value}") from error
    else:
        decimal_value = int(clean_value)
        if decimal_value < 0:
            raise ValueError("Target value cannot be negative")
        byte_length = max(2, (decimal_value.bit_length() + 7) // 8)
        if byte_length > 4:
            byte_length = 8
        elif byte_length > 2:
            byte_length = 4
        target_bytes = decimal_value.to_bytes(byte_length, byteorder="big")

    if not big_endian:
        target_bytes = target_bytes[::-1]
    return target_bytes


def search_in_file(filepath: Path, target_bytes: bytes) -> list[int]:
    """Return all offsets of a byte sequence in a file."""
    if filepath.stat().st_size == 0:
        return []

    offsets: list[int] = []
    with filepath.open("rb") as file:
        with mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as mapped_file:
            offset = mapped_file.find(target_bytes)
            while offset != -1:
                offsets.append(offset)
                offset = mapped_file.find(target_bytes, offset + 1)
    return offsets


def search_path(root: Path, options: SearchOptions) -> list[SearchResult]:
    """Search a directory recursively or search one file."""
    root = Path(root).resolve()
    if root.is_file():
        files = [root]
    elif root.is_dir():
        files = []
        for path in root.rglob("*"):
            if path.is_file():
                files.append(path)
    else:
        raise FileNotFoundError(root)

    target_bytes = parse_value_to_bytes(options.target_value, options.big_endian)
    results: list[SearchResult] = []
    for filepath in sorted(files):
        if not _matches_extension(filepath, options.file_extension):
            continue

        file_size = filepath.stat().st_size
        offsets = search_in_file(filepath, target_bytes)
        if not offsets:
            continue

        exact_match, score = _check_filters(file_size, offsets, options)
        if options.mode == "exact" and not exact_match:
            continue
        if options.mode not in {"exact", "fuzzy"}:
            raise ValueError(f"Unsupported search mode: {options.mode}")

        results.append(SearchResult(filepath, tuple(offsets), score))

    if options.mode == "fuzzy":
        results.sort(key=_result_score, reverse=True)
    return results


def _matches_extension(filepath: Path, extension: str | None) -> bool:
    if extension in {None, "*"}:
        return True
    if extension == "":
        return filepath.suffix == ""
    return filepath.name.lower().endswith(extension.lower())


def _check_filters(file_size: int, offsets: list[int], options: SearchOptions) -> tuple[bool, int]:
    exact_match = True
    score = 0

    if options.start_offset is not None:
        matched = options.start_offset in offsets
        exact_match = exact_match and matched
        score += int(matched)
    if options.size_min is not None:
        matched = file_size >= options.size_min
        exact_match = exact_match and matched
        score += int(matched)
    if options.size_max is not None:
        matched = file_size <= options.size_max
        exact_match = exact_match and matched
        score += int(matched)

    return exact_match, score


def _result_score(result: SearchResult) -> int:
    """Return the fuzzy search score."""
    return result.score
