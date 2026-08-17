"""Hashing for game resource names."""


def cstring_to_key(value: str, ignore_case: bool = False) -> int:
    """Return the 32-bit hash used by the target program."""
    current_hash = len(value)

    for character in value:
        char_value = ord(character) & 0xFF
        if ignore_case and 0x41 <= char_value <= 0x5A:
            char_value += 0x20

        if char_value >= 0x80:
            char_value |= 0xFFFFFF00

        rotated = ((current_hash >> 28) | (current_hash << 4)) & 0xFFFFFFFF
        current_hash = (rotated ^ char_value) & 0xFFFFFFFF

    return current_hash
