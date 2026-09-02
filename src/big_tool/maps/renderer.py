"""Render a pack's maps: tile layers plus the props placed on them.

Works on an unpacked pack folder produced by ``unpack --by-section``; the
Section names are what locate the TILELAYER, TILESET, PROP and PNG resources.
"""

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from PIL import Image, ImageChops

from big_tool.big_archive.big_section import read_manifest
from big_tool.logger import logger
from big_tool.maps.map_format import (
    EMPTY_TILE,
    FLIP_X,
    FLIP_Y,
    OBJECT_TYPE_PROP,
    GameMap,
    TileLayer,
    TileSet,
    parse_map,
    parse_tileset,
)
from big_tool.maps.sprite_glu import (
    BLEND_ADDITIVE,
    NO_ANIMATION,
    SPRITE_LAYERS,
    TRANSFORM_FLIP_X,
    TRANSFORM_FLIP_Y,
    TRANSFORM_TRANSPOSE,
    SpriteGluArchive,
    SpriteGluRef,
    locate_archive,
    parse_prop_ref,
)
from big_tool.models.mesh_binding import (
    find_section_range,
    index_resource_files,
    read_section_ranges,
)


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

# Section folders created by `unpack --by-section`. An unused Section is named
# "<n>_NAME_empty", and find_section_range already skips those.
TILELAYER_SECTION = "_TILELAYER"
TILESET_SECTION = "_TILESET"
PROP_SECTION = "_PROP"
PNG_SECTION = "_PNG"

MANIFEST_PATTERN = "*_resources.csv"
RENDER_DIR_PREFIX = "_rendered_maps"
TRANSPARENT = (0, 0, 0, 0)
OPAQUE_BLACK = (0, 0, 0, 255)

# A loop of one full tile of scroll. CLayerTile::SetSpeed scales the script's
# speed by 0.05 tiles per second, so one tile really takes 20 to 40 seconds.
# That is unwatchable, so the loop is compressed rather than played at speed.
ANIMATION_FRAME_COUNT = 60

# Which way the layers drift. The real axis and speed come from the level
# script's setTileLayerSpeed, and the script resources are not decoded, so this
# is a choice, not a reading: down the screen, one tile per loop.
SCROLL_STEP_X = 0
SCROLL_STEP_Y = 1

# Speed multiplier per scrolling layer, lowest layer first. pack12 stacks a
# translucent water layer over an opaque one, which only reads as water if the
# two drift apart, so the upper layers run faster. The real ratios are in the
# undecoded scripts; these are a guess, kept whole so that one tile of travel
# still closes the loop seamlessly.
SCROLL_RATES = (1, 2, 3)

# MP4: the full-resolution output. Frames are piped to ffmpeg raw as they are
# drawn, because holding 60 frames of a 2816x2048 map would cost gigabytes.
FFMPEG_COMMAND = "ffmpeg"
MP4_FPS = 30
MP4_CRF = "16"
MP4_PRESET = "slow"

# GIF: the small preview, unchanged from when it only ever showed lava.
# Every third frame of the 60 gives back the original 20.
GIF_FRAME_STRIDE = 3
GIF_FRAME_MS = 100
GIF_SCALE = 0.25


@dataclass(frozen=True)
class PropPart:
    """One drawable piece of a prop, positioned relative to the prop's origin."""

    image: Image.Image
    x: int
    y: int
    additive: bool


@dataclass
class PackAssets:
    """Everything one pack needs to draw its maps."""

    tileset: TileSet
    tile_sprites: list[Image.Image]
    props: list[SpriteGluRef]
    archive: SpriteGluArchive | None
    pages: list[Image.Image]


@dataclass
class MapRenderCache:
    """What stays the same across the frames of one map's animation.

    Only the scrolling layers move, so every other tile layer is drawn once.
    Prop parts are cropped and flipped out of the atlas pages, which is the
    expensive half of drawing a prop, and that result never changes either.
    """

    tile_layers: dict[int, Image.Image] = field(default_factory=dict)
    prop_parts: dict[tuple[int, str], list[PropPart]] = field(default_factory=dict)


# ------------------------------------------------------------------
# Pack layout
# ------------------------------------------------------------------

def find_pack_dirs(directory: Path) -> list[Path]:
    """Return every unpacked pack folder under a directory."""
    directory = Path(directory)
    if list(directory.glob(MANIFEST_PATTERN)):
        return [directory]

    pack_dirs = []
    for path in sorted(directory.iterdir()):
        if path.is_dir() and list(path.glob(MANIFEST_PATTERN)):
            pack_dirs.append(path)
    return pack_dirs


def _read_ranges(pack_dir: Path) -> dict:
    manifest_paths = sorted(pack_dir.glob(MANIFEST_PATTERN))
    if not manifest_paths:
        return {}
    _headers, rows = read_manifest(manifest_paths[0])
    return read_section_ranges(rows)


def _section_files(
    ranges: dict, resource_files: dict[int, Path], suffix: str
) -> list[Path]:
    """Return a Section's resources in table2 order."""
    section_range = find_section_range(ranges, suffix)
    if section_range is None:
        return []
    files = []
    for index in range(section_range.first_index, section_range.last_index + 1):
        path = resource_files.get(index)
        if path is not None:
            files.append(path)
    return files


# ------------------------------------------------------------------
# Assets
# ------------------------------------------------------------------

def _cut_tile_sprites(tileset: TileSet, atlases: list[Image.Image]) -> list[Image.Image]:
    sprites = []
    for tile in tileset.tiles:
        atlas = atlases[tile.image_index]
        box = (tile.x, tile.y, tile.x + tile.width, tile.y + tile.height)
        sprites.append(atlas.crop(box))
    return sprites


def load_pack_assets(pack_dir: Path) -> PackAssets | None:
    """Load a pack's tileset, props and sprite archive, or None if it has none."""
    ranges = _read_ranges(pack_dir)
    resource_files = index_resource_files(pack_dir)

    tileset_files = _section_files(ranges, resource_files, TILESET_SECTION)
    png_files = _section_files(ranges, resource_files, PNG_SECTION)
    if not tileset_files or not png_files:
        return None

    # A pack can hold several tilesets; the maps say which, but every sample
    # uses the last non-empty one, and the first is a 2-byte placeholder.
    tileset = None
    for path in reversed(tileset_files):
        candidate = parse_tileset(path.read_bytes())
        if candidate.tiles:
            tileset = candidate
            break
    if tileset is None:
        return None

    # A tileset's images are CGameAssetRef asset ids, which count from the
    # start of the pack's PNG Section.
    atlases = []
    for _pack_hash, asset_index in tileset.images:
        atlases.append(Image.open(png_files[asset_index]).convert("RGBA"))

    props = []
    for path in _section_files(ranges, resource_files, PROP_SECTION):
        props.append(parse_prop_ref(path.read_bytes()))

    archive, pages = _load_sprite_archive(pack_dir, resource_files, png_files)

    return PackAssets(tileset, _cut_tile_sprites(tileset, atlases), props, archive, pages)


def _load_sprite_archive(
    pack_dir: Path, resource_files: dict[int, Path], png_files: list[Path]
) -> tuple[SpriteGluArchive | None, list[Image.Image]]:
    """Find the pack's SpriteGlu archive and load its atlas pages."""
    resources = {}
    for index, path in resource_files.items():
        if path.suffix == ".bin":
            resources[index] = path.read_bytes()

    archive = locate_archive(resources)
    if archive is None:
        logger.warning(f"{pack_dir.name}: no SpriteGlu archive, props will be skipped")
        return None, []

    # BASE_TEXTURE_PAGE_0 heads a contiguous run of PNG resources, but the run
    # sits in a different place per build: 2.4.0 and 3.6.0 put it right before
    # the archive, 1.0.0 puts it inside, between the archetypes and the texture
    # maps. Named lookup would give the pages directly, so the run is located
    # and checked rather than assumed.
    png_indexes = []
    for index, path in sorted(resource_files.items()):
        if path.suffix == ".png":
            png_indexes.append(index)

    page_indexes = []
    for index in png_indexes:
        if archive.global_index < index < archive.last_index:
            page_indexes.append(index)

    if not page_indexes:
        # Nothing inside the block, so the run is the one it starts after.
        for index in png_indexes:
            if index < archive.global_index:
                page_indexes.append(index)
        page_indexes = page_indexes[-archive.total_pages:]

    pages_are_contiguous = False
    if page_indexes:
        span = page_indexes[-1] - page_indexes[0] + 1
        pages_are_contiguous = span == len(page_indexes)

    if len(page_indexes) != archive.total_pages or not pages_are_contiguous:
        logger.warning(
            f"{pack_dir.name}: expected {archive.total_pages} contiguous sprite "
            f"pages but found {len(page_indexes)}, props may be wrong"
        )

    pages = []
    for index in page_indexes:
        pages.append(Image.open(resource_files[index]).convert("RGBA"))
    return archive, pages


# ------------------------------------------------------------------
# Drawing
# ------------------------------------------------------------------

def draw_tile_layer(
    layer: TileLayer,
    sprites: list[Image.Image],
    tile_width: int,
    tile_height: int,
    columns: int,
    rows: int,
    shift_x: int = 0,
    shift_y: int = 0,
) -> Image.Image:
    """Draw one tile layer over the whole map, wrapping as the engine does.

    ``shift_x`` / ``shift_y`` scroll the layer in pixels; an extra ring of tiles
    is laid down so the wrap has no seam.
    """
    canvas = Image.new("RGBA", (columns * tile_width, rows * tile_height), TRANSPARENT)
    margin = 0
    if shift_x or shift_y:
        margin = 1

    for row in range(-margin, rows + margin):
        for column in range(-margin, columns + margin):
            tile_id, flags = layer.cell(column, row)
            if tile_id == EMPTY_TILE:
                continue
            sprite = sprites[tile_id]
            if flags & FLIP_X:
                sprite = sprite.transpose(Image.FLIP_LEFT_RIGHT)
            if flags & FLIP_Y:
                sprite = sprite.transpose(Image.FLIP_TOP_BOTTOM)
            canvas.alpha_composite(
                sprite, (column * tile_width + shift_x, row * tile_height + shift_y)
            )
    return canvas


def prop_parts(prop: SpriteGluRef, layer: str, assets: PackAssets) -> list[PropPart]:
    """Return one sprite layer of a prop as images with offsets.

    Follows ``CSpriteIterator::SetLayer`` and ``SetSprite``: an animation names
    a frame, the frame's parts name sub-frames, and the sub-frames' parts name
    sprites. The two offsets add up. Parts are walked backwards, so index 0 is
    drawn last and ends up on top.
    """
    archive = assets.archive
    if archive is None:
        return []
    animation_id = prop.animation(layer)
    if animation_id == NO_ANIMATION:
        return []

    if prop.archetype >= len(archive.archetypes):
        return []
    archetype = archive.archetypes[prop.archetype]
    if animation_id >= len(archetype.animations):
        return []
    animation = archetype.animations[animation_id]
    if not animation.steps:
        return []
    frame_id = animation.steps[0][0]
    if frame_id >= len(archetype.frames):
        return []

    parts = []
    for frame_part in reversed(archetype.frames[frame_id]):
        sub_frame = archetype.sub_frames[frame_part.child_id]
        for sub_part in reversed(sub_frame):
            resolved = archive.resolve_rect(prop.archetype, sub_part.child_id)
            if resolved is None:
                continue
            rect, transform, blend = resolved
            page = assets.pages[archive.page_base(prop.archetype) + rect.page]
            image = page.crop((rect.x, rect.y, rect.x + rect.width, rect.y + rect.height))
            # Test the bits, do not match whole values: pack2 alone uses
            # 0, 1, 2 and 3, so a value check silently drops half the flips.
            # The sprite keeps its box; drawSurface translates to the part's
            # position and lets the renderer flip inside it.
            if transform & TRANSFORM_TRANSPOSE:
                image = image.transpose(Image.TRANSPOSE)
            if transform & TRANSFORM_FLIP_X:
                image = image.transpose(Image.FLIP_LEFT_RIGHT)
            if transform & TRANSFORM_FLIP_Y:
                image = image.transpose(Image.FLIP_TOP_BOTTOM)
            parts.append(PropPart(
                image,
                frame_part.x + sub_part.x,
                frame_part.y + sub_part.y,
                bool(blend & BLEND_ADDITIVE),
            ))
    return parts


def paste_part(canvas: Image.Image, part: PropPart, x: int, y: int) -> None:
    """Draw one part onto the canvas with the blend its sprite asks for."""
    if not part.additive:
        canvas.alpha_composite(part.image, (x, y))
        return
    # A glow sprite is opaque black around the light, so it has to be added,
    # not composited. Clipped to the canvas, since props may hang off the edge.
    box = (x, y, x + part.image.width, y + part.image.height)
    if box[0] >= canvas.width or box[1] >= canvas.height or box[2] <= 0 or box[3] <= 0:
        return
    region = canvas.crop(box)
    canvas.paste(ImageChops.add(region, part.image), box)


def render_map(
    game_map: GameMap,
    assets: PackAssets,
    with_props: bool = True,
    shifts: dict[int, tuple[int, int]] | None = None,
    cache: MapRenderCache | None = None,
) -> Image.Image:
    """Compose one map into a single image.

    ``shifts`` scrolls individual tile layers by a pixel offset, keyed by the
    layer's index among the tile layers. ``cache``, when given, keeps the
    unshifted layers and the prop parts across calls so an animation does not
    redraw them every frame.
    """
    if shifts is None:
        shifts = {}
    tile_width = assets.tileset.tile_width
    tile_height = assets.tileset.tile_height
    columns, rows = game_map.grid_size()
    canvas = Image.new("RGBA", (columns * tile_width, rows * tile_height), OPAQUE_BLACK)

    for index, layer in enumerate(game_map.tile_layers):
        shift_x, shift_y = shifts.get(index, (0, 0))
        cached = None
        if cache is not None and not shift_x and not shift_y:
            cached = cache.tile_layers.get(index)
        if cached is None:
            cached = draw_tile_layer(
                layer, assets.tile_sprites, tile_width, tile_height,
                columns, rows, shift_x, shift_y,
            )
            if cache is not None and not shift_x and not shift_y:
                cache.tile_layers[index] = cached
        canvas.alpha_composite(cached)

    if with_props:
        _draw_props(canvas, game_map, assets, cache)
    return canvas


def _draw_props(
    canvas: Image.Image,
    game_map: GameMap,
    assets: PackAssets,
    cache: MapRenderCache | None = None,
) -> int:
    """Draw every prop instance, and return how many parts were drawn.

    Props are redrawn every frame rather than kept as an overlay: a glow sprite
    is added to what is already on the canvas, so it needs the scrolled layers
    underneath it to be there already.
    """
    instances = []
    for group in game_map.object_groups:
        if group.object_type != OBJECT_TYPE_PROP:
            continue
        instances.extend(group.instances)
    # CProp::GetZOrder sorts on y, so the lower a prop sits the later it draws.
    instances.sort(key=lambda instance: instance.y)

    drawn = 0
    for layer in SPRITE_LAYERS:
        for instance in instances:
            if instance.local_index >= len(assets.props):
                continue
            prop = assets.props[instance.local_index]
            parts = None
            if cache is not None:
                parts = cache.prop_parts.get((instance.local_index, layer))
            if parts is None:
                parts = prop_parts(prop, layer, assets)
                if cache is not None:
                    cache.prop_parts[(instance.local_index, layer)] = parts
            for part in parts:
                paste_part(canvas, part, instance.x + part.x, instance.y + part.y)
                drawn += 1
    return drawn


def find_scrolling_layers(game_map: GameMap) -> list[int]:
    """Return the tile layers that drift, lowest first.

    A scrolling layer is one seamless texture tiled across the whole layer, so
    it uses exactly one tile id. That is what separates a lava sheet, a
    starfield or a water surface from a ground layer, which always mixes
    several tiles. The level scripts address these by the same index, counting
    tile layers only (the ``setTileLayerSpeed`` case at
    ``gunbros_3.6.0_IOS.c:117851`` skips every layer that is not a tile layer).
    """
    found = []
    for index, layer in enumerate(game_map.tile_layers):
        used = set()
        for tile_id, _flags in layer.cells:
            used.add(tile_id)
        used.discard(EMPTY_TILE)
        if len(used) == 1:
            found.append(index)
    return found


# ------------------------------------------------------------------
# Batch
# ------------------------------------------------------------------

def render_pack(pack_dir: Path, output_dir: Path, with_props: bool = True,
                animated_background: bool = False) -> int:
    """Render every map in one pack and return how many were written."""
    assets = load_pack_assets(pack_dir)
    if assets is None:
        logger.info(f"{pack_dir.name}: no tileset, skipped")
        return 0

    ranges = _read_ranges(pack_dir)
    resource_files = index_resource_files(pack_dir)
    map_files = _section_files(ranges, resource_files, TILELAYER_SECTION)
    if not map_files:
        logger.info(f"{pack_dir.name}: no TILELAYER Section, skipped")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for path in map_files:
        game_map = parse_map(path.read_bytes())
        if not game_map.tile_layers:
            continue
        name = path.stem
        # The still and the animation share a cache: the still fills it with
        # every unshifted layer and every prop part, which is most of the work.
        cache = MapRenderCache()
        image = render_map(game_map, assets, with_props, cache=cache)
        image.convert("RGB").save(output_dir / f"{name}.png")
        columns, rows = game_map.grid_size()
        logger.info(f"{name}: {columns}x{rows} tiles -> {image.size[0]}x{image.size[1]}px")
        written += 1

        if animated_background:
            _write_animation(game_map, assets, with_props, output_dir, name, cache)
    return written


def _layer_shifts(
    layers: list[int], step: int, tile_width: int, tile_height: int
) -> dict[int, tuple[int, int]]:
    """Return each scrolling layer's pixel offset at one step of the loop."""
    shifts = {}
    for order, layer_index in enumerate(layers):
        # Past the end of SCROLL_RATES every further layer keeps the last rate;
        # no sample stacks more than two scrolling layers.
        rate = SCROLL_RATES[min(order, len(SCROLL_RATES) - 1)]
        travel = rate * step / ANIMATION_FRAME_COUNT
        shift_x = round(tile_width * SCROLL_STEP_X * travel) % tile_width
        shift_y = round(tile_height * SCROLL_STEP_Y * travel) % tile_height
        shifts[layer_index] = (shift_x, shift_y)
    return shifts


def _write_animation(
    game_map: GameMap,
    assets: PackAssets,
    with_props: bool,
    output_dir: Path,
    name: str,
    cache: MapRenderCache,
) -> None:
    """Write a seamless loop of a map's scrolling layers as MP4 and GIF.

    One loop is one tile of travel, so the last frame joins back onto the
    first. Frames are handed to ffmpeg as they are drawn and only the small
    GIF copies are kept, because the full-resolution frames of a large map add
    up to gigabytes.
    """
    layers = find_scrolling_layers(game_map)
    if not layers:
        return

    tile_width = assets.tileset.tile_width
    tile_height = assets.tileset.tile_height
    columns, rows = game_map.grid_size()
    size = (columns * tile_width, rows * tile_height)
    encoder = _start_mp4(output_dir / f"{name}_bak.mp4", size)

    gif_frames = []
    for step in range(ANIMATION_FRAME_COUNT):
        shifts = _layer_shifts(layers, step, tile_width, tile_height)
        frame = render_map(game_map, assets, with_props, shifts, cache).convert("RGB")
        if encoder is not None:
            encoder[0].stdin.write(frame.tobytes())
        if step % GIF_FRAME_STRIDE == 0:
            gif_frames.append(frame.resize(
                (round(frame.width * GIF_SCALE), round(frame.height * GIF_SCALE)),
                Image.LANCZOS,
            ))

    gif_path = output_dir / f"{name}_bak.gif"
    gif_frames[0].save(
        gif_path, save_all=True, append_images=gif_frames[1:],
        duration=GIF_FRAME_MS, loop=0, optimize=True,
    )
    _finish_mp4(encoder, name)
    logger.info(
        f"{name}: animated layers {layers}, "
        f"{ANIMATION_FRAME_COUNT} frames -> mp4, {len(gif_frames)} -> gif"
    )


def _start_mp4(
    output_path: Path, size: tuple[int, int]
) -> tuple[subprocess.Popen, IO[bytes]] | None:
    """Open an ffmpeg process fed a stream of raw RGB frames, or None if it is missing.

    Frames go over the pipe uncompressed. PNG-ing them first costs more than
    the whole x264 encode does -- 20 seconds of zlib against 0.2 seconds of
    encoding on a 1536x2048 map -- and the pipe does not care about the bytes.

    ffmpeg's diagnostics go to a temporary file rather than a pipe. A pipe
    nobody drains fills up after a few dozen frames, at which point ffmpeg
    stops reading stdin and both sides wait on each other forever.
    """
    command = [
        FFMPEG_COMMAND, "-y", "-loglevel", "error", "-nostats",
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{size[0]}x{size[1]}",
        "-framerate", str(MP4_FPS), "-i", "-",
        "-c:v", "libx264", "-preset", MP4_PRESET, "-crf", MP4_CRF,
        # yuv420p is what every player can decode; the maps are whole tiles
        # across, so the even-size requirement is always met.
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(output_path),
    ]
    log = tempfile.TemporaryFile()
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=log, stderr=log,
        )
    except FileNotFoundError:
        log.close()
        logger.warning("ffmpeg not found, writing the GIF only")
        return None
    return process, log


def _finish_mp4(encoder: tuple[subprocess.Popen, IO[bytes]] | None, name: str) -> None:
    """Close the frame stream and report whether ffmpeg wrote the file."""
    if encoder is None:
        return
    process, log = encoder
    process.stdin.close()
    process.wait()
    if process.returncode != 0:
        log.seek(0)
        tail = log.read().decode("utf-8", "replace").strip().splitlines()[-3:]
        logger.warning(f"{name}: ffmpeg failed: {' | '.join(tail)}")
    log.close()


def render_directory(directory: Path, output_dir: Path | None = None,
                     with_props: bool = True, animated_background: bool = False) -> int:
    """Render every pack under a directory and return the map count.

    Without ``output_dir`` each pack keeps its own ``_rendered_maps`` folder.
    """
    directory = Path(directory).resolve()
    output_root = None
    if output_dir is not None:
        output_root = Path(output_dir).resolve()

    pack_dirs = find_pack_dirs(directory)
    logger.info(f"Found {len(pack_dirs)} packs under {directory.name}")

    total = 0
    for pack_dir in pack_dirs:
        target_name = f"{RENDER_DIR_PREFIX}_{pack_dir.name}"
        if output_root is None:
            target_dir = pack_dir / RENDER_DIR_PREFIX
        else:
            target_dir = output_root / target_name
        total += render_pack(pack_dir, target_dir, with_props, animated_background)
    return total
