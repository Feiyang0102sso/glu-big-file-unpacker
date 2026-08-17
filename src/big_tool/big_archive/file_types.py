"""Resource type detection."""


TYPE_MAP = {
    0x69E4C505: "string_pack",
    0x69E5D35C: "metadata",
    0xB7178678: "png",
    0xF4E02223: "bin",
    0xF686AADC: "manifest",
    0xFD8A7754: "wav",
}


def guess_extension(data: bytes, group_hash: int | None = None) -> str:
    """Guess an output extension from data and group hash."""
    if group_hash == 0xF686AADC:
        return ".txt"

    if data.startswith(b"\x89PNG"):
        return ".png"

    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return ".wav"

    return ".bin"
