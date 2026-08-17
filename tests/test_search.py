from pathlib import Path

from big_tool.analysis.search import SearchOptions, parse_value_to_bytes, search_path


def test_parse_value_to_bytes_preserves_explicit_hex_length():
    assert parse_value_to_bytes("0x8275260001", big_endian=True) == bytes.fromhex("8275260001")


def test_search_path_returns_all_offsets(tmp_path: Path):
    target = tmp_path / "sample.bin"
    target.write_bytes(b"x\x01\x02\x01\x02")

    results = search_path(
        tmp_path,
        SearchOptions(target_value="0x0102", big_endian=True, file_extension=".bin"),
    )

    assert len(results) == 1
    assert results[0].offsets == (1, 3)
