"""Sequential reader for the little-endian resource formats.

The engine parses every resource through ``CInputStream``, one field at a time
with no offsets or padding. Mirroring that here keeps each parser a line-by-line
match of its ``Init`` in the decompiled source, which is the only way to tell a
correct layout from a plausible one.
"""

import struct


class StreamError(ValueError):
    """A resource ended before its declared contents did."""


class Stream:
    """Read little-endian values forward through a resource."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0

    @property
    def remaining(self) -> int:
        """Return how many bytes are left."""
        return len(self.data) - self.position

    def _take(self, size: int) -> bytes:
        if self.remaining < size:
            raise StreamError(
                f"need {size} bytes at 0x{self.position:x}, only {self.remaining} left"
            )
        chunk = self.data[self.position:self.position + size]
        self.position += size
        return chunk

    def u8(self) -> int:
        """Read an unsigned byte."""
        return self._take(1)[0]

    def u16(self) -> int:
        """Read an unsigned 16-bit value."""
        return struct.unpack("<H", self._take(2))[0]

    def i16(self) -> int:
        """Read a signed 16-bit value."""
        return struct.unpack("<h", self._take(2))[0]

    def u32(self) -> int:
        """Read an unsigned 32-bit value."""
        return struct.unpack("<I", self._take(4))[0]

    def i32(self) -> int:
        """Read a signed 32-bit value."""
        return struct.unpack("<i", self._take(4))[0]

    def raw(self, size: int) -> bytes:
        """Read a run of bytes."""
        return self._take(size)

    def skip(self, size: int) -> None:
        """Step over a run of bytes."""
        self._take(size)

    def at_end(self) -> bool:
        """Return whether the whole resource was consumed.

        A layout that consumes a resource exactly is strong evidence it is
        right, so every parser here is checked against this.
        """
        return self.remaining == 0
