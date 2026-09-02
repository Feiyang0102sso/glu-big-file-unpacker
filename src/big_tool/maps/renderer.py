"""Render a pack's maps: tile layers plus the props placed on them.

Works on an unpacked pack folder produced by ``unpack --by-section``; the
Section names are what locate the TILELAYER, TILESET, PROP and PNG resources.
"""

from dataclasses import dataclass
from pathlib import Path

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
LAVA_FRAME_COUNT = 20
LAVA_FRAME_MS = 100
LAVA_SCALE = 0.25


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

    # BASE_TEXTURE_PAGE_0 is the first of a contiguous run of PNG resources
    # that ends right before the archive. Named lookup would give this
    # directly, so the run is checked rather than assumed.
    page_indexes = []
    for index, path in sorted(resource_files.items()):
        if path.suffix == ".png":
            page_indexes.append(index)
    page_indexes = page_indexes[-archive.total_pages:]

    expected_last = archive.global_index - 1
    if len(page_indexes) != archive.total_pages or page_indexes[-1] != expected_last:
        logger.warning(
            f"{pack_dir.name}: sprite pages do not sit right before the archive, "
            f"props may be wrong"
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
    lava_layer: int | None = None,
    lava_shift: tuple[int, int] = (0, 0),
) -> Image.Image:
    """Compose one map into a single image."""
    tile_width = assets.tileset.tile_width
    tile_height = assets.tileset.tile_height
    columns, rows = game_map.grid_size()
    canvas = Image.new("RGBA", (columns * tile_width, rows * tile_height), OPAQUE_BLACK)

    for index, layer in enumerate(game_map.tile_layers):
        shift_x = 0
        shift_y = 0
        if index == lava_layer:
            shift_x, shift_y = lava_shift
        canvas.alpha_composite(
            draw_tile_layer(
                layer, assets.tile_sprites, tile_width, tile_height,
                columns, rows, shift_x, shift_y,
            )
        )

    if with_props:
        _draw_props(canvas, game_map, assets)
    return canvas


def _draw_props(canvas: Image.Image, game_map: GameMap, assets: PackAssets) -> int:
    """Draw every prop instance, and return how many parts were drawn."""
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
            for part in prop_parts(prop, layer, assets):
                paste_part(canvas, part, instance.x + part.x, instance.y + part.y)
                drawn += 1
    return drawn


def find_lava_layer(game_map: GameMap, assets: PackAssets) -> int | None:
    """Return the tile layer that scrolls, or None.

    The scrolling layer is the one paved entirely with tiles from the flow
    atlas, which is the last image the tileset loads. It is the layer the level
    scripts address as index 0 in ``setTileLayerSpeed``.
    """
    flow_image = len(assets.tileset.images) - 1
    if flow_image < 1:
        return None
    flow_tiles = set()
    for index, tile in enumerate(assets.tileset.tiles):
        if tile.image_index == flow_image:
            flow_tiles.add(index)

    for index, layer in enumerate(game_map.tile_layers):
        used = set()
        for tile_id, _flags in layer.cells:
            used.add(tile_id)
        used.discard(EMPTY_TILE)
        if used and used <= flow_tiles:
            return index
    return None


# ------------------------------------------------------------------
# Batch
# ------------------------------------------------------------------

def render_pack(pack_dir: Path, output_dir: Path, with_props: bool = True,
                lava_gif: bool = False) -> int:
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
        image = render_map(game_map, assets, with_props)
        image.convert("RGB").save(output_dir / f"{name}.png")
        columns, rows = game_map.grid_size()
        logger.info(f"{name}: {columns}x{rows} tiles -> {image.size[0]}x{image.size[1]}px")
        written += 1

        if lava_gif:
            _write_lava_gif(game_map, assets, with_props, output_dir / f"{name}_lava.gif")
    return written


def _write_lava_gif(
    game_map: GameMap, assets: PackAssets, with_props: bool, output_path: Path
) -> None:
    """Write a seamless loop of the scrolling lava layer, if the map has one."""
    lava_layer = find_lava_layer(game_map, assets)
    if lava_layer is None:
        return

    tile_height = assets.tileset.tile_height
    frames = []
    for step in range(LAVA_FRAME_COUNT):
        shift = (0, round(tile_height * step / LAVA_FRAME_COUNT))
        frame = render_map(game_map, assets, with_props, lava_layer, shift).convert("RGB")
        frame = frame.resize(
            (int(frame.width * LAVA_SCALE), int(frame.height * LAVA_SCALE)), Image.LANCZOS
        )
        frames.append(frame)

    frames[0].save(
        output_path, save_all=True, append_images=frames[1:],
        duration=LAVA_FRAME_MS, loop=0, optimize=True,
    )
    logger.info(f"{output_path.name}: {LAVA_FRAME_COUNT} frames")


def render_directory(directory: Path, output_dir: Path | None = None,
                     with_props: bool = True, lava_gif: bool = False) -> int:
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
        total += render_pack(pack_dir, target_dir, with_props, lava_gif)
    return total
