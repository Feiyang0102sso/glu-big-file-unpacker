"""The SpriteGlu archive: how a PROP template turns into pixels.

Source: ``CSpriteGlu::Init`` / ``LoadArcheType`` / ``LoadTexturePack`` /
``LoadTexturePackData``, plus ``CSpriteIterator::SetLayer`` / ``SetSprite`` and
``CSpritePlayer::Draw`` in ``gunbros_3.6.0_IOS.c``. Notes in ``tools/map.md``.

The engine looks these resources up by name (``SPRITEGLU__BINARY_GLOBAL`` and
friends) through the pack's name directory, which is not decoded yet. They do
not need it: the block is self-describing, so ``locate_archive`` finds it by
structure instead.
"""

from dataclasses import dataclass

from big_tool.maps.stream import Stream, StreamError


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

# The block's layout, which is what locate_archive matches:
#   BINARY_GLOBAL
#   BINARY_ARCHETYPE_000 .. _00N     (archetypeCount entries)
#   BASE_TEXTURE_MAP_000 .. _00N     (archetypeCount entries)
#   TEXTURE_MAP_GLOBAL
#
# The four parts are consecutive among the pack's binary resources, but not
# always in table2 index: 1.0.0 stores the atlas pages between the archetypes
# and the texture maps, while 2.4.0 and 3.6.0 put them right before the block.
# The engine does not care either way, because CSpriteGlu::Init looks every
# part up by name.

# CProp::Bind builds three CSpritePlayers and draws them in this order.
SPRITE_LAYERS = ("background", "main", "foreground")

# 255 in an animation slot means that sprite player is not created.
NO_ANIMATION = 255

# CSpriteGlu::FlipTransform packs three independent bits, and they must be
# tested as bits: pack2 alone uses 0, 1, 2 and 3, so matching whole values
# drops most of the flips.
#
# Which bit is which axis was pinned against in-game screenshots, not read off
# the code. CSpritePlayer::Draw folds the bits into a renderer transform code
# whose enum is not MIDP's despite looking like it, and drawSurface remaps that
# code again on the transposed path. Reading it as MIDP gives the axes the
# wrong way round, which mirrors a lamp off its bracket instead of onto it.
TRANSFORM_FLIP_Y = 0x01
TRANSFORM_FLIP_X = 0x02
TRANSFORM_TRANSPOSE = 0x04

# Each sprite also carries a blend flag. CSpritePlayer::Draw switches on its
# sign: a negative value takes the glow path (PushColor and a second blend
# mode). Those sprites are fully opaque glows painted on black, so alpha
# compositing them paints a black box instead of a light.
BLEND_ADDITIVE = 0x80


# ------------------------------------------------------------------
# Data
# ------------------------------------------------------------------

@dataclass(frozen=True)
class SpritePart:
    """One entry of a frame or sub-frame: a child id and its offset."""

    child_id: int
    x: int
    y: int


@dataclass(frozen=True)
class Animation:
    """An animation: a list of (frame id, duration) steps."""

    flag: int
    steps: list[tuple[int, int]]


@dataclass(frozen=True)
class ArcheType:
    """One SPRITEGLU__BINARY_ARCHETYPE resource.

    ``sub_frames`` and ``frames`` have identical layouts but different meaning,
    and mixing them up silently swaps every sprite on the map:
    an animation's frame id indexes ``frames``, whose parts index
    ``sub_frames``, whose parts index the global sprite table.
    """

    sub_frames: list[list[SpritePart]]
    frames: list[list[SpritePart]]
    animations: list[Animation]


@dataclass(frozen=True)
class TextureRect:
    """A sprite's rectangle on one atlas page."""

    page: int
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class TextureMap:
    """One BASE_TEXTURE_MAP resource: an archetype's rectangles.

    ``remap`` is not optional decoration. A sprite's slot goes through it to
    reach a rectangle, and because the table is shuffled, skipping it swaps
    every sprite for a different one instead of failing.
    """

    page_count: int
    rects: list[TextureRect]
    remap: list[int]


@dataclass(frozen=True)
class SpriteGluRef:
    """The ``CGameSpriteGluRef`` at the head of a PROP template.

    One prop is three sprites, not one. ``CProp::Bind`` creates a separate
    ``CSpritePlayer`` per slot and ``CProp`` draws them in three passes. Reading
    only the main slot loses every ground decal in the pack.
    """

    pack_hash: int
    archetype: int
    character: int
    main: int
    foreground: int
    background: int

    def animation(self, layer: str) -> int:
        """Return one layer's animation id, or ``NO_ANIMATION``."""
        return getattr(self, layer)


def parse_prop_ref(data: bytes) -> SpriteGluRef:
    """Read the sprite reference at the start of a PROP template.

    Only the head is parsed: collision, script and move set follow, and none of
    them affect how the prop is drawn on a static map.
    """
    stream = Stream(data)
    pack_hash = stream.u32()
    archetype = stream.u8()
    character = stream.u8()
    main = stream.u8()
    foreground = stream.u8()
    background = stream.u8()
    return SpriteGluRef(pack_hash, archetype, character, main, foreground, background)


@dataclass(frozen=True)
class SpriteGluArchive:
    """Everything needed to draw a pack's sprites."""

    global_index: int
    last_index: int
    sprite_slots: list[int]
    sprites: list[tuple[int, int, int]]
    archetypes: list[ArcheType]
    texture_maps: list[TextureMap]
    page_counts: list[int]

    @property
    def total_pages(self) -> int:
        """Return how many atlas pages the whole archive uses."""
        return sum(self.page_counts)

    def page_base(self, archetype_index: int) -> int:
        """Return an archetype's first page, counted from the archive's first.

        ``CSpriteGlu::LoadTexturePack`` adds up the page counts of every
        earlier archetype to reach ``BASE_TEXTURE_PAGE_0``.
        """
        return sum(self.page_counts[:archetype_index])

    def resolve_rect(
        self, archetype_index: int, sprite_id: int
    ) -> tuple[TextureRect, int, int] | None:
        """Return a sprite's rectangle, flip transform and blend flag.

        Three lookups, all of them load-bearing: the sprite table gives a slot,
        the slot goes through the global slot table and then the archetype's
        remap, and only that result is a rectangle index.
        """
        if sprite_id >= len(self.sprites):
            # Past the sprite table are the solid-colour rectangles, which
            # carry no texture. No pack in the samples uses them.
            return None
        slot, transform, blend = self.sprites[sprite_id]
        if slot >= len(self.sprite_slots):
            return None
        slot = self.sprite_slots[slot]
        texture_map = self.texture_maps[archetype_index]
        if slot >= len(texture_map.remap):
            return None
        rect_index = texture_map.remap[slot]
        if rect_index >= len(texture_map.rects):
            # The remap's last slot is a spare that points nowhere.
            return None
        return texture_map.rects[rect_index], transform, blend


# ------------------------------------------------------------------
# Resource parsers
# ------------------------------------------------------------------

def parse_global(data: bytes) -> tuple[list[int], list[tuple[int, int, int]], int]:
    """Parse SPRITEGLU__BINARY_GLOBAL (``CSpriteGlu::Init``).

    Returns the slot table, the sprite table as (slot, transform, blend)
    triples, and how many archetypes the pack has.
    """
    stream = Stream(data)

    for _ in range(stream.u8()):
        stream.raw(stream.u16())

    stream.u16()  # Read and discarded by the engine.

    slots = []
    for _ in range(stream.u16()):
        slots.append(stream.u16())
        stream.u8()

    sprites = []
    for _ in range(stream.u16()):
        slot = stream.u16()
        transform = stream.u8()
        blend = stream.u8()
        sprites.append((slot, transform, blend))

    # Solid-colour sprites, addressed past the end of the sprite table.
    for _ in range(stream.u16()):
        stream.u32()
        stream.u16()
        stream.u16()
        stream.u8()

    # Sprite maps: per-sprite substitution lists. Empty in the samples.
    for _ in range(stream.u8()):
        for _ in range(stream.u16()):
            stream.u16()
            stream.u16()
            stream.u8()
            stream.u16()
            stream.u16()

    archetype_count = stream.u8()
    if not stream.at_end():
        raise StreamError("global block has trailing data")
    return slots, sprites, archetype_count


def parse_archetype(data: bytes, sprite_count: int) -> ArcheType:
    """Parse SPRITEGLU__BINARY_ARCHETYPE (``CSpriteGlu::LoadArcheType``)."""
    stream = Stream(data)

    def read_part_table() -> list[list[SpritePart]]:
        table = []
        for _ in range(stream.u16()):
            parts = []
            for _ in range(stream.u8()):
                child_id = stream.u16()
                x = stream.i16()
                y = stream.i16()
                parts.append(SpritePart(child_id, x, y))
            table.append(parts)
        return table

    sub_frames = read_part_table()
    frames = read_part_table()

    animations = []
    for _ in range(stream.u16()):
        flag = stream.u8()
        steps = []
        for _ in range(stream.u8()):
            frame_id = stream.u16()
            duration = stream.u16()
            steps.append((frame_id, duration))
        animations.append(Animation(flag, steps))

    # Modules: a used-sprite bitmask plus a flag, only needed for streaming.
    mask_size = (sprite_count + 7) // 8
    for _ in range(stream.u8()):
        stream.skip(mask_size)
        stream.u8()

    if not stream.at_end():
        raise StreamError("archetype block has trailing data")
    return ArcheType(sub_frames, frames, animations)


def parse_texture_map(data: bytes) -> TextureMap:
    """Parse BASE_TEXTURE_MAP (``CSpriteGlu::LoadTexturePack``)."""
    stream = Stream(data)

    page_count = stream.u8()
    stream.skip(page_count)  # Per-page load flags.

    rects = []
    for _ in range(stream.u16()):
        page = stream.u8()
        x = stream.u16()
        y = stream.u16()
        width = stream.u16()
        height = stream.u16()
        rects.append(TextureRect(page, x, y, width, height))

    remap = []
    for _ in range(stream.u16()):
        remap.append(stream.u16())

    if not stream.at_end():
        raise StreamError("texture map has trailing data")
    return TextureMap(page_count, rects, remap)


def parse_page_counts(data: bytes, archetype_count: int) -> list[int]:
    """Parse TEXTURE_MAP_GLOBAL (``CSpriteGlu::LoadTexturePackData``)."""
    stream = Stream(data)
    stream.u16()
    counts = []
    for _ in range(archetype_count):
        counts.append(stream.u8())
    if not stream.at_end():
        raise StreamError("page count block has trailing data")
    return counts


# ------------------------------------------------------------------
# Locating the archive inside a pack
# ------------------------------------------------------------------

def locate_archive(resources: dict[int, bytes]) -> SpriteGluArchive | None:
    """Find and load a pack's SpriteGlu archive, keyed by table2 index.

    Every candidate is checked by parsing: the global block declares how many
    archetypes follow, and the block only validates if that many archetype and
    texture-map resources parse exactly and the trailing page-count block
    agrees. Nothing else in a pack matches that shape by accident.
    """
    binary_indexes = sorted(resources)
    for position in range(len(binary_indexes)):
        archive = _try_load_archive(resources, binary_indexes, position)
        if archive is not None:
            return archive
    return None


def _try_load_archive(
    resources: dict[int, bytes], binary_indexes: list[int], position: int
) -> SpriteGluArchive | None:
    """Load the archive that would start at one position of ``binary_indexes``.

    The four parts follow each other among the pack's binary resources, which
    is not the same as following each other in table2 index: 1.0.0 stores the
    atlas pages between the archetypes and the texture maps, leaving a gap
    there. ``binary_indexes`` lists only the binary resources, so the pages
    drop out of the walk and both layouts stay adjacent.
    """
    try:
        slots, sprites, archetype_count = parse_global(resources[binary_indexes[position]])
    except (StreamError, IndexError):
        return None
    if archetype_count < 1 or not sprites:
        return None

    archetype_start = position + 1
    texture_map_start = archetype_start + archetype_count
    page_count_position = texture_map_start + archetype_count
    if page_count_position >= len(binary_indexes):
        return None

    try:
        archetypes = []
        for offset in range(archetype_count):
            data = resources[binary_indexes[archetype_start + offset]]
            archetypes.append(parse_archetype(data, len(sprites)))
        texture_maps = []
        for offset in range(archetype_count):
            data = resources[binary_indexes[texture_map_start + offset]]
            texture_maps.append(parse_texture_map(data))
        page_counts = parse_page_counts(
            resources[binary_indexes[page_count_position]], archetype_count
        )
    except (StreamError, KeyError, IndexError):
        return None

    return SpriteGluArchive(
        binary_indexes[position],
        binary_indexes[page_count_position],
        slots,
        sprites,
        archetypes,
        texture_maps,
        page_counts,
    )
