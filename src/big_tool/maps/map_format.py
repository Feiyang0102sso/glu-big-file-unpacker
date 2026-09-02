"""TILELAYER (CMap) and TILESET (TileSet) resource formats.

Source: ``CMap::Init``, ``CLayerTile::Init``, ``TileSet::Init`` in
``gunbros_3.6.0_IOS.c``. Notes live in ``tools/map.md``.
"""

from dataclasses import dataclass, field

from big_tool.maps.stream import Stream


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

# CMap::Init layer type ids, one class each.
LAYER_TILE = 0
LAYER_COLLISION = 1
LAYER_OBJECT = 2
LAYER_MOVIE = 3
LAYER_CAMERA = 4
LAYER_PATH_LINK = 5
LAYER_PATH_MESH = 6

LAYER_NAMES = {
    LAYER_TILE: "Tile",
    LAYER_COLLISION: "Collision",
    LAYER_OBJECT: "Object",
    LAYER_MOVIE: "Movie",
    LAYER_CAMERA: "Camera",
    LAYER_PATH_LINK: "PathLink",
    LAYER_PATH_MESH: "PathMesh",
}

# CLayerTile cell values.
EMPTY_TILE = 255
FLIP_X = 0x01
FLIP_Y = 0x02

# GameObjectTypeStrings ids used by the object layer.
OBJECT_TYPE_PLAYER = 15
OBJECT_TYPE_PROP = 19

# CLayerObject::InitializeObjects picks the per-object extra data by object
# type: (kind, stride). Only kinds 0, 1 and 6 read anything from the stream.
OBJECT_EXTRA_RULES = {
    3: (5, 0),
    5: (1, 4),
    11: (3, 0),
    12: (4, 0),
    14: (6, 1),
    OBJECT_TYPE_PLAYER: (0, 12),
    OBJECT_TYPE_PROP: (2, 0),
}
OBJECT_EXTRA_DEFAULT = (8, 0)
EXTRA_KIND_U16 = 0
EXTRA_KIND_U8_I16 = 1
EXTRA_KIND_U8 = 6

# CLayerCamera::Init reads two rectangles as eight int16 values.
CAMERA_VALUE_COUNT = 8


# ------------------------------------------------------------------
# Data
# ------------------------------------------------------------------

@dataclass(frozen=True)
class Tile:
    """One rectangle of a tileset atlas page."""

    image_index: int
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class TileSet:
    """A TILESET resource: which atlases to load and how to cut them up."""

    images: list[tuple[int, int]]
    tiles: list[Tile]

    @property
    def tile_width(self) -> int:
        """Return the draw width every tile uses.

        ``CLayerTile::GetWidth`` multiplies the layer width by ``tiles[0].w``,
        so the first tile sets the grid step for the whole set.
        """
        return self.tiles[0].width

    @property
    def tile_height(self) -> int:
        """Return the draw height every tile uses."""
        return self.tiles[0].height


@dataclass(frozen=True)
class TileLayer:
    """A CLayerTile: a grid of (tile id, flip flags) cells."""

    width: int
    height: int
    cells: list[tuple[int, int]]

    def cell(self, column: int, row: int) -> tuple[int, int]:
        """Return a cell, wrapping like ``CLayerTile::DrawBackground`` does.

        The engine takes both indexes modulo the layer size, so a layer smaller
        than the map keeps repeating instead of leaving a hole.
        """
        return self.cells[(row % self.height) * self.width + (column % self.width)]


@dataclass(frozen=True)
class ObjectInstance:
    """One placed object: which template, and where on the map."""

    pack_hash: int
    local_index: int
    x: int
    y: int
    flags: int


@dataclass(frozen=True)
class ObjectGroup:
    """The instances of one object type inside an object layer."""

    object_type: int
    instances: list[ObjectInstance]


@dataclass
class MapLayer:
    """One CMap layer. ``data`` is None for the layer types left unparsed."""

    layer_type: int
    data: object = None


@dataclass
class GameMap:
    """A TILELAYER resource."""

    tileset_pack_hash: int
    tileset_index: int
    layers: list[MapLayer] = field(default_factory=list)

    @property
    def tile_layers(self) -> list[TileLayer]:
        """Return the tile layers, bottom one first."""
        found = []
        for layer in self.layers:
            if layer.layer_type == LAYER_TILE:
                found.append(layer.data)
        return found

    @property
    def object_groups(self) -> list[ObjectGroup]:
        """Return every object group across all object layers."""
        found = []
        for layer in self.layers:
            if layer.layer_type != LAYER_OBJECT:
                continue
            found.extend(layer.data)
        return found

    def grid_size(self) -> tuple[int, int]:
        """Return the map size in tiles: the largest of all tile layers.

        Layers are allowed to differ in size; the smaller ones wrap under the
        larger, so the map is as big as its biggest layer.
        """
        columns = 0
        rows = 0
        for layer in self.tile_layers:
            columns = max(columns, layer.width)
            rows = max(rows, layer.height)
        return columns, rows


# ------------------------------------------------------------------
# TILESET
# ------------------------------------------------------------------

def parse_tileset(data: bytes) -> TileSet:
    """Parse a TILESET resource (``TileSet::Init``)."""
    stream = Stream(data)

    images = []
    for _ in range(stream.u8()):
        # CGameAssetRef: pack hash plus the asset's index inside that pack.
        pack_hash = stream.u32()
        asset_index = stream.i32()
        images.append((pack_hash, asset_index))

    tiles = []
    for _ in range(stream.u8()):
        image_index = stream.u8()
        x = stream.u16()
        y = stream.u16()
        width = stream.u16()
        height = stream.u16()
        tiles.append(Tile(image_index, x, y, width, height))

    return TileSet(images, tiles)


# ------------------------------------------------------------------
# TILELAYER
# ------------------------------------------------------------------

def _read_requirements(stream: Stream) -> None:
    """Skip the RequirementList: the objects the map wants preloaded.

    It carries no geometry, only which templates to have in memory, so the
    contents are read and dropped.
    """
    for _ in range(stream.u8()):
        stream.u8()
        for _ in range(stream.u8()):
            stream.u32()
            stream.u8()


def _read_tile_layer(stream: Stream) -> TileLayer:
    """Read a CLayerTile."""
    stream.u8()  # Read and discarded by the engine too; always 1 in the samples.
    width = stream.u16()
    height = stream.u16()
    cells = []
    for _ in range(width * height):
        tile_id = stream.u8()
        flags = stream.u8()
        cells.append((tile_id, flags))
    return TileLayer(width, height, cells)


def _read_collision_layer(stream: Stream) -> None:
    """Skip a CLayerCollision (``CCollisionData::Load``)."""
    for _ in range(stream.u16()):
        stream.i32()
        stream.i32()
    for _ in range(stream.u16()):
        stream.u8()
        stream.u16()
        stream.u16()


def _read_object_layer(stream: Stream) -> list[ObjectGroup]:
    """Read a CLayerObject (``CLayerObject::InitializeObjects``)."""
    stream.u16()  # Total instance count, only used to size the engine's array.
    groups = []
    for _ in range(stream.u8()):
        object_type = stream.u8()
        count = stream.u16()
        stream.u16()  # Allocation count for the type's extra-data buffer.
        extra_kind, _stride = OBJECT_EXTRA_RULES.get(object_type, OBJECT_EXTRA_DEFAULT)

        instances = []
        # The engine always walks the body at least once, even for count 0.
        for _ in range(max(count, 1)):
            pack_hash = stream.u32()
            local_index = stream.u8()
            has_extra = stream.u8()
            x = stream.i16()
            y = stream.i16()
            flags = stream.u8()
            if has_extra:
                _read_object_extra(stream, extra_kind)
            instances.append(ObjectInstance(pack_hash, local_index, x, y, flags))
        groups.append(ObjectGroup(object_type, instances))
    return groups


def _read_object_extra(stream: Stream, extra_kind: int) -> None:
    """Skip an instance's extra data, whose size depends on the object type."""
    if extra_kind == EXTRA_KIND_U16:
        stream.u16()
    elif extra_kind == EXTRA_KIND_U8_I16:
        stream.u8()
        stream.i16()
    elif extra_kind == EXTRA_KIND_U8:
        stream.u8()
    # Every other kind reads nothing.


def _read_movie_layer(stream: Stream) -> None:
    """Skip a CLayerMovie: a CGameAssetRef and a screen position."""
    stream.u32()
    stream.i32()
    stream.i16()
    stream.i16()


def _read_camera_layer(stream: Stream) -> None:
    """Skip a CLayerCamera: two rectangles."""
    for _ in range(CAMERA_VALUE_COUNT):
        stream.i16()


LAYER_READERS = {
    LAYER_TILE: _read_tile_layer,
    LAYER_COLLISION: _read_collision_layer,
    LAYER_OBJECT: _read_object_layer,
    LAYER_MOVIE: _read_movie_layer,
    LAYER_CAMERA: _read_camera_layer,
}


def parse_map(data: bytes) -> GameMap:
    """Parse a TILELAYER resource (``CMap::Init``).

    Parsing stops at the first path layer: those carry nothing drawable and
    their formats are not decoded, so anything after them is unreachable.
    """
    stream = Stream(data)

    # The map's own GameObjectRef is its tileset: CMap::Bind resolves it as
    # object type 0x18 (TILESET). The trailing byte is only present when the
    # pack hash is non-zero.
    tileset_pack_hash = stream.u32()
    tileset_index = 0
    if tileset_pack_hash:
        tileset_index = stream.u8()

    _read_requirements(stream)

    game_map = GameMap(tileset_pack_hash, tileset_index)
    for _ in range(stream.u8()):
        layer_type = stream.u8()
        reader = LAYER_READERS.get(layer_type)
        if reader is None:
            game_map.layers.append(MapLayer(layer_type))
            break
        game_map.layers.append(MapLayer(layer_type, reader(stream)))
    return game_map
