"""Resolve a private point using the current, associated persistent map."""

import gzip
import io
import json
import tarfile
import zlib
from dataclasses import dataclass
from itertools import pairwise

from .errors import ProtocolError
from .maps import AreaTarget, PersistentMap, RegionKind, map_identifier

MAX_MAP_BYTES = 8 * 1024 * 1024
_MAP_LAYERS = frozenset({"rooms", "borders", "policyZones", "cleanZones"})

type Coordinate = tuple[float, float]
type Ring = tuple[Coordinate, ...]
type Polygon = tuple[Ring, ...]


@dataclass(frozen=True, repr=False)
class FloorRoom:
    name: str | None
    polygons: tuple[Polygon, ...]
    region_id: str | None = None


@dataclass(frozen=True, repr=False)
class FloorPlan:
    rooms: tuple[FloorRoom, ...]
    zones: tuple[FloorRoom, ...] = ()
    keep_out: tuple[Polygon, ...] = ()
    virtual_walls: tuple[Ring, ...] = ()

    def room_at(self, point: Coordinate) -> str | None:
        matches = [
            room for room in self.rooms if any(_inside(point, polygon) for polygon in room.polygons)
        ]
        return matches[0].name if len(matches) == 1 else None


def _coordinate(value: object) -> bool:
    # Keep planar calculations finite even for corrupted provider coordinates.
    return type(value) in (int, float) and -1e9 <= value <= 1e9


@dataclass(frozen=True, repr=False)
class PointTarget:
    map_id: str
    version_id: str
    center: Coordinate

    def __post_init__(self):
        if (
            not map_identifier(self.map_id)
            or not map_identifier(self.version_id)
            or not isinstance(self.center, tuple)
            or len(self.center) != 2
            or not all(_coordinate(value) for value in self.center)
        ):
            raise ValueError("Expected an active map version and two planar coordinates.")


def room_fraction(value: object) -> float:
    if type(value) not in (int, float) or not 0 < value < 1:
        raise ValueError("Expected a fraction strictly between 0 and 1.")
    return float(value)


def _documents(data: bytes) -> dict:
    """Read known GeoJSON layers from a bounded in-memory archive."""
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
            raw = compressed.read(MAX_MAP_BYTES + 1)
        if len(raw) > MAX_MAP_BYTES:
            raise ProtocolError("Persistent map exceeds the decompression limit.")
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            members = archive.getmembers()
            manifest = _document(archive, members, "manifest.json")
            # The SDK picks the regular policy layer before the experimental one.
            fallback = _layer_paths(manifest.get("experimentalFeatures", []))
            paths = fallback | _layer_paths(manifest["features"])
            paths["metadata"] = manifest["metadata"]
            return {name: _document(archive, members, path) for name, path in paths.items()}
    except (
        OSError,
        EOFError,
        tarfile.TarError,
        zlib.error,
        ValueError,
        RecursionError,
        KeyError,
        TypeError,
    ):
        raise ProtocolError("Could not read the persistent map bundle.") from None


def _layer_paths(layers):
    paths = {}
    for layer in layers:
        name = layer["type"]
        if name in _MAP_LAYERS:
            if name in paths:
                raise ProtocolError("Persistent map has duplicate layers.")
            paths[name] = layer["filepath"]
    return paths


def _document(archive, members, name):
    matches = [member for member in members if member.name == name]
    if len(matches) != 1 or not matches[0].isfile() or matches[0].size > MAX_MAP_BYTES:
        raise ProtocolError("Expected a single regular persistent map document.")
    with archive.extractfile(matches[0]) as item:
        document = json.load(item)
    if not isinstance(document, dict):
        raise ProtocolError("Expected a persistent map document.")
    return document


def _ring(values: list) -> Ring:
    if not isinstance(values, list) or len(values) < 4 or values[0] != values[-1]:
        raise ProtocolError("Expected a closed persistent map ring.")
    return _coordinates(values)


def _coordinates(values: list) -> Ring:
    if not all(
        isinstance(pair, list) and len(pair) == 2 and all(_coordinate(v) for v in pair)
        for pair in values
    ):
        raise ProtocolError("Expected finite planar coordinates.")
    return tuple((x, y) for x, y in values)


def _polygons(feature: dict) -> tuple[Polygon, ...]:
    try:
        geometry = feature["geometry"]
        match geometry["type"]:
            case "Polygon":
                coordinates = [geometry["coordinates"]]
            case "MultiPolygon":
                coordinates = geometry["coordinates"]
            case _:
                raise ProtocolError("Expected a polygonal persistent map layer.")
        polygons = tuple(tuple(_ring(ring) for ring in polygon) for polygon in coordinates)
    except KeyError, TypeError:
        raise ProtocolError("Expected persistent map polygons.") from None
    if not polygons or not all(polygons):
        raise ProtocolError("Expected nonempty persistent map polygons.")
    return polygons


def _features(document: dict) -> list[dict]:
    match document.get("type"):
        case "Feature":
            return [document]
        case "FeatureCollection":
            features = document.get("features")
            if isinstance(features, list) and all(isinstance(item, dict) for item in features):
                return features
    raise ProtocolError("Expected persistent map features.")


def _ring_position(point: Coordinate, ring: Ring) -> int:
    """Return 0 outside, 1 inside, and -1 on a boundary."""
    x, y = point
    inside = False
    for (ax, ay), (bx, by) in pairwise(ring):
        if (
            (x - ax) * (by - ay) == (y - ay) * (bx - ax)
            and min(ax, bx) <= x <= max(ax, bx)
            and min(ay, by) <= y <= max(ay, by)
        ):
            return -1
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return int(inside)


def _inside(point: Coordinate, polygon: Polygon, *, include_boundary: bool = False) -> bool:
    outer, *holes = polygon
    position = _ring_position(point, outer)
    accepted_outer = (1, -1) if include_boundary else (1,)
    accepted_hole = (0, -1) if include_boundary else (0,)
    return position in accepted_outer and all(
        _ring_position(point, hole) in accepted_hole for hole in holes
    )


def _map_documents(data, map_id, version_id):
    documents = _documents(data)
    metadata = documents["metadata"]
    if (metadata.get("id"), metadata.get("version")) != (map_id, version_id):
        raise ProtocolError("Persistent map geometry did not match its active version.")
    return documents


def read_floor_plan(data: bytes, floor: PersistentMap) -> FloorPlan:
    """Load rooms and labels from the exact same associated, active map version."""
    documents = _map_documents(data, floor.map_id, floor.version_id)
    if "rooms" not in documents:
        raise ProtocolError("Persistent map lacks its room layer.")
    names = {room.region_id: room.name for room in floor.regions if room.kind is RegionKind.ROOM}
    rooms = {}
    for feature in _features(documents["rooms"]):
        identifier = feature.get("id")
        if not map_identifier(identifier) or identifier in rooms:
            raise ProtocolError("Expected unique room geometry.")
        rooms[identifier] = FloorRoom(names.get(identifier), _polygons(feature), identifier)
    if not rooms:
        raise ProtocolError("Persistent map contains no room geometry.")
    document = documents.get("cleanZones", {"type": "FeatureCollection", "features": []})
    zone_names = {
        zone.region_id: zone.name for zone in floor.regions if zone.kind is RegionKind.ZONE
    }
    zones = tuple(
        FloorRoom(zone_names[identifier], _polygons(feature), identifier)
        for feature in _features(document)
        if isinstance(identifier := feature.get("id"), str) and identifier in zone_names
    )
    restrictions, walls = keep_out_geometry(documents)
    return FloorPlan(tuple(rooms.values()), zones, restrictions, walls)


def keep_out_geometry(documents) -> tuple[tuple[Polygon, ...], tuple[Ring, ...]]:
    if "policyZones" not in documents:
        return (), ()
    restrictions = []
    walls = []
    for item in _features(documents["policyZones"]):
        properties = item.get("properties")
        if not isinstance(properties, dict) or not isinstance(properties.get("type"), str):
            raise ProtocolError("Could not identify a persistent map policy zone.")
        if properties["type"] == "KeepOutZone":
            geometry = item.get("geometry")
            if isinstance(geometry, dict) and geometry.get("type") == "LineString":
                coordinates = geometry.get("coordinates")
                if not isinstance(coordinates, list) or len(coordinates) < 2:
                    raise ProtocolError("Expected a persistent map virtual wall.")
                walls.append(_coordinates(coordinates))
            else:
                restrictions.extend(_polygons(item))
    return tuple(restrictions), tuple(walls)


def resolve_room_point(data: bytes, area: AreaTarget, x: float, y: float) -> PointTarget:
    """Convert room fractions to coordinates and reject points outside its walkable outline."""
    x, y = room_fraction(x), room_fraction(y)
    if len(area.regions) != 1 or area.regions[0].kind is not RegionKind.ROOM:
        raise ValueError("Select one mapped room.")
    documents = _map_documents(data, area.map_id, area.version_id)
    try:
        room_id = area.regions[0].region_id
        rooms = [item for item in _features(documents["rooms"]) if item.get("id") == room_id]
        if len(rooms) != 1:
            raise ProtocolError("Expected exactly one geometry for the selected room.")
        floor = _polygons(rooms[0])
        borders = [
            polygon for item in _features(documents["borders"]) for polygon in _polygons(item)
        ]
        restrictions, walls = keep_out_geometry(documents)
        # A virtual wall can divide a room without defining its accessible side.
        if walls:
            raise ProtocolError("Point cleaning cannot verify access across virtual walls.")
    except KeyError:
        raise ProtocolError("Persistent map lacks its room or border layer.") from None
    xs, ys = zip(*(pair for outer, *_ in floor for pair in outer), strict=True)
    point = (min(xs) + (max(xs) - min(xs)) * x, min(ys) + (max(ys) - min(ys)) * y)
    if (
        not any(_inside(point, polygon) for polygon in floor)
        or not any(_inside(point, polygon) for polygon in borders)
        or any(_inside(point, polygon, include_boundary=True) for polygon in restrictions)
    ):
        raise ValueError("Selected point is outside the room or inside a keep-out zone.")
    return PointTarget(area.map_id, area.version_id, point)
