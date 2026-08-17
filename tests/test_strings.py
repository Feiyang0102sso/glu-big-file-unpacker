import struct
from pathlib import Path

from big_tool.resources.string_extractor import ResourceStringExtractor


def test_extract_string_resource(tmp_path: Path):
    first = b"@\x00\x00\x00hello\x00"
    second = b"@\x00\x00\x00world\x00"
    resource_count = 2
    data_start = 8 + resource_count * 2 + 2 + resource_count * 4
    offsets = [data_start + len(first), data_start + len(first) + len(second)]
    header = b"\x00\xa0" + struct.pack("<H", resource_count) + b"\x00\x00" + struct.pack("<H", offsets[0])
    offset_table = struct.pack("<HH", *offsets)
    types = b"\x00" * (resource_count * 4)
    resource_file = tmp_path / "strings.bin"
    resource_file.write_bytes(header + offset_table + b"\x00\x00" + types + first + second)

    resources = ResourceStringExtractor(resource_file).extract()

    texts = []
    for resource in resources:
        texts.append(resource.text)

    assert texts == ["hello", "world"]
