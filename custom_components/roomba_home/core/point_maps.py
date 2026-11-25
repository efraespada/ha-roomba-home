"""Resolve a private point using the current, associated persistent map."""

import gzip
import io
import json
import tarfile
import zlib
from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256
from itertools import pairwise
from math import isclose

from .errors import ProtocolError
from .maps import (
    SAVED_ZONE_IDS,
    AreaTarget,
    CleaningRegion,
    PersistentMap,
    RegionKind,
    _name,
    map_identifier,
)

MAX_MAP_BYTES = 8 * 1024 * 1024
_MAP_LAYERS = frozenset({"rooms", "borders", "policyZones", "cleanZones", "furniture"})
_DISPLAY_LAYERS = ("floorPlan", "floorTypes", "dockPoses")

type Coordinate = tuple[float, float]
type Ring = tuple[Coordinate, ...]
type Polygon = tuple[Ring, ...]


@dataclass(frozen=True, repr=False)
class FloorRoom:
    name: str | None
    polygons: tuple[Polygon, ...]
    region_id: str | None = None
    visible: bool = False
    adjacent: frozenset[str] = frozenset()
    room_type: str | None = None


class RestrictionKind(StrEnum):
    KEEP_OUT = "keep_out"
    NO_MOP = "no_mop"
    WALL = "wall"


@dataclass(frozen=True, repr=False)
class MapRestriction:
    identifier: str
    kind: RestrictionKind
    points: Ring


@dataclass(frozen=True, repr=False)
class MapFurniture:
    identifier: str
    kind: str
    source: str
    orientation: float
    points: Ring
    cleaning_area: tuple[Polygon, ...] = ()


@dataclass(frozen=True, repr=False)
class FloorPlan:
    rooms: tuple[FloorRoom, ...]
    zones: tuple[FloorRoom, ...] = ()
    keep_out: tuple[Polygon, ...] = ()
    virtual_walls: tuple[Ring, ...] = ()
    unlinked_zone_count: int = 0
    no_mop: tuple[Polygon, ...] = ()
    source_format: str | None = None
    zone_outlines: tuple[FloorRoom, ...] = ()
    border_digest: str | None = None
    policy_shapes: tuple[MapRestriction, ...] | None = None
    furniture: tuple[MapFurniture, ...] | None = None
    walls: tuple[tuple[str, Ring], ...] = ()
    carpets: tuple[Polygon, ...] = ()
    docks: tuple[Coordinate, ...] = ()

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


def _documents(data: bytes, extra_layers: tuple[str, ...] = ()) -> dict:
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
            documents = {name: _document(archive, members, path) for name, path in paths.items()}
            for name in (*_DISPLAY_LAYERS, *extra_layers):
                try:
                    paths = _layer_paths(manifest.get("experimentalFeatures", []), {name})
                    paths |= _layer_paths(manifest["features"], {name})
                    if name in paths:
                        documents[name] = _document(archive, members, paths[name])
                except ProtocolError, ValueError, RecursionError, KeyError, TypeError:
                    # The edit and command paths do not depend on display layers.
                    continue
            return documents
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


def _layer_paths(layers, supported=_MAP_LAYERS):
    paths = {}
    for layer in layers:
        name = layer["type"]
        if name in supported:
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


def rectangle_outline(polygons: tuple[Polygon, ...]) -> Ring:
    if len(polygons) == 1 and len(polygons[0]) == 1:
        ring = polygons[0][0]
        if len(ring) == 5 and len(set(ring[:-1])) == 4:
            return ring[:-1]
    return ()


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


def line_crossings(start: Coordinate, end: Coordinate, ring: Ring) -> list[float]:
    """Return intersections along the line through the endpoints."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    crossings = []
    for a, b in pairwise(ring):
        ex, ey = b[0] - a[0], b[1] - a[1]
        ox, oy = a[0] - start[0], a[1] - start[1]
        denominator = dx * ey - dy * ex
        if not denominator:
            continue
        along = (ox * ey - oy * ex) / denominator
        across = (ox * dy - oy * dx) / denominator
        if 0 <= across <= 1 and not any(
            isclose(along, item, rel_tol=0, abs_tol=1e-9) for item in crossings
        ):
            crossings.append(along)
    return sorted(crossings)


def _map_documents(data, map_id, version_id, extra_layers=()):
    documents = _documents(data, extra_layers)
    metadata = documents["metadata"]
    if (metadata.get("id"), metadata.get("version")) != (map_id, version_id):
        raise ProtocolError("Persistent map geometry did not match its active version.")
    return documents


def read_floor_plan(data: bytes, floor: PersistentMap) -> FloorPlan:
    """Load rooms and labels from the exact same associated, active map version."""
    documents = _map_documents(data, floor.map_id, floor.version_id)
    return _floor_plan_documents(documents, floor)


def _floor_plan_documents(documents: dict, floor: PersistentMap) -> FloorPlan:
    if "rooms" not in documents:
        raise ProtocolError("Persistent map lacks its room layer.")
    source = documents["metadata"].get("sourceFormat")
    names = {room.region_id: room.name for room in floor.regions if room.kind is RegionKind.ROOM}
    rooms = {}
    for feature in _features(documents["rooms"]):
        identifier = feature.get("id")
        if not map_identifier(identifier) or identifier in rooms:
            raise ProtocolError("Expected unique room geometry.")
        properties = feature.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        visibility = properties.get("visibility")
        adjacent = properties.get("adjacentRoomIDs")
        category = properties.get("type")
        room_type = category.get("value") if isinstance(category, dict) else None
        archive_name = properties.get("name")
        name = names.get(identifier)
        if (
            source == "picea"
            and isinstance(archive_name, str)
            and 0 < len(archive_name) <= 100
            and archive_name.isprintable()
            and archive_name.strip()
        ):
            name = archive_name
        rooms[identifier] = FloorRoom(
            name,
            _polygons(feature),
            identifier,
            isinstance(visibility, dict) and visibility.get("type") == "visible",
            frozenset(room for room in adjacent if map_identifier(room))
            if isinstance(adjacent, list)
            else frozenset(),
            room_type if isinstance(room_type, str) else None,
        )
    if not rooms:
        raise ProtocolError("Persistent map contains no room geometry.")
    document = documents.get("cleanZones", {"type": "FeatureCollection", "features": []})
    zone_names = {
        zone.region_id: zone.name for zone in floor.regions if zone.kind is RegionKind.ZONE
    }
    zone_features = _features(document)
    zones = tuple(
        FloorRoom(zone_names[identifier], _polygons(feature), identifier)
        for feature in zone_features
        if isinstance(identifier := feature.get("id"), str) and identifier in zone_names
    )
    unlinked_zones = {
        identifier
        for feature in zone_features
        if map_identifier(identifier := feature.get("id")) and identifier not in zone_names
    }
    outlines = _read_zone_outlines(zone_features) if source == "picea" else ()
    restrictions, walls, no_mop = policy_geometry(documents, include_no_mop=True)
    return FloorPlan(
        tuple(rooms.values()),
        zones,
        restrictions,
        walls,
        len(unlinked_zones),
        no_mop,
        source if isinstance(source, str) else None,
        outlines,
        sha256(json.dumps(documents.get("borders"), sort_keys=True).encode()).hexdigest(),
        _read_policy_shapes(documents.get("policyZones")) if source == "picea" else None,
        _read_furniture(documents.get("furniture")) if source == "picea" else None,
        walls=_display_features(documents, "floorPlan", _wall_segments),
        carpets=_display_features(documents, "floorTypes", _carpet_polygons),
        docks=_display_features(documents, "dockPoses", _dock_points),
    )


def _display_features(documents, layer, read):
    if layer not in documents:
        return ()
    try:
        return tuple(item for feature in _features(documents[layer]) for item in read(feature))
    except ProtocolError, KeyError, TypeError, AttributeError:
        return ()


def _wall_segments(feature):
    kind = feature.get("properties", {}).get("type")
    geometry = feature["geometry"]
    if kind not in ("exterior", "interior", "door") or geometry["type"] != "MultiLineString":
        return ()
    return tuple(
        (kind, line)
        for raw in geometry["coordinates"]
        if len(line := _coordinates(raw)) >= 2 and len(set(line)) > 1
    )


def _carpet_polygons(feature):
    return _polygons(feature) if feature.get("properties", {}).get("type") == "carpet" else ()


def _dock_points(feature):
    geometry = feature["geometry"]
    return _coordinates([geometry["coordinates"]]) if geometry["type"] == "Point" else ()


def _read_furniture(document: dict | None) -> tuple[MapFurniture, ...] | None:
    if document is None:
        return ()
    items = {}
    try:
        for feature in _features(document):
            identifier, properties = feature["id"], feature["properties"]
            if (
                not map_identifier(identifier)
                or identifier == "0"
                or identifier in items
                or not isinstance(properties, dict)
                or properties.keys() - {"type", "source", "orientation", "cleaningArea"}
            ):
                return None
            kind, source, heading = (
                properties["type"],
                properties["source"],
                properties["orientation"],
            )
            if _name(kind) is None or source not in ("robot", "user") or not _coordinate(heading):
                return None
            points = rectangle_outline(_polygons(feature))
            if not points:
                return None
            area = properties.get("cleaningArea")
            cleaning_area = _polygons({"geometry": area}) if area is not None else ()
            items[identifier] = MapFurniture(
                identifier, kind, source, heading, points, cleaning_area
            )
    except KeyError, ProtocolError:
        return None
    return tuple(items.values())


def _read_zone_outlines(features: list[dict]) -> tuple[FloorRoom, ...]:
    outlines = {}
    for feature in features:
        identifier = feature.get("id")
        if not map_identifier(identifier) or identifier in outlines:
            raise ProtocolError("Expected unique cleaning zone geometry.")
        properties = feature.get("properties")
        name = _name(properties.get("name")) if isinstance(properties, dict) else None
        outlines[identifier] = FloorRoom(name, _polygons(feature), identifier)
    return tuple(outlines.values())


def _read_policy_shapes(document: dict | None) -> tuple[MapRestriction, ...] | None:
    """The write replaces the whole layer. Only edit maps we can round-trip."""
    if document is None:
        return ()
    restrictions = {}
    for feature in _features(document):
        identifier = feature.get("id")
        properties = feature.get("properties", {})
        geometry = feature.get("geometry")
        if (
            not map_identifier(identifier)
            or identifier in restrictions
            or properties.keys() != {"type"}
            or not isinstance(geometry, dict)
        ):
            return None
        match properties["type"], geometry.get("type"):
            case "KeepOutZone", "LineString":
                points = _coordinates(geometry["coordinates"])
                kind = RestrictionKind.WALL
                if len(points) != 2 or points[0] == points[1]:
                    return None
            case "KeepOutZone" | "NoMopZone", "Polygon":
                try:
                    points = rectangle_outline(_polygons(feature))
                except ProtocolError:
                    return None
                kind = (
                    RestrictionKind.KEEP_OUT
                    if properties["type"] == "KeepOutZone"
                    else RestrictionKind.NO_MOP
                )
                if not points:
                    return None
            case _:
                return None
        restrictions[identifier] = MapRestriction(identifier, kind, points)
    return tuple(restrictions.values())


def with_archive_destinations(floor: PersistentMap, plan: FloorPlan) -> PersistentMap:
    """Resolve verified Picea destinations against the current revision."""
    if plan.source_format != "picea":
        return floor
    floor = _with_archive_rooms(floor, plan)
    outlines = {zone.region_id: zone for zone in plan.zone_outlines}
    zones = {region.region_id for region in floor.regions if region.kind is RegionKind.ZONE}
    regions = []
    for region in floor.regions:
        if region.kind is not RegionKind.ZONE:
            regions.append(region)
        elif (outline := outlines.get(region.region_id)) is not None:
            regions.append(replace(region, name=outline.name or region.name))
        elif region.region_id not in SAVED_ZONE_IDS:
            regions.append(region)
    regions.extend(
        CleaningRegion(zone.region_id, RegionKind.ZONE, zone.name)
        for zone in plan.zone_outlines
        if zone.region_id in SAVED_ZONE_IDS
        and zone.region_id not in zones
        and zone.name
        and rectangle_outline(zone.polygons)
    )
    destinations = tuple(regions)
    return floor if destinations == floor.regions else replace(floor, regions=destinations)


def _with_archive_rooms(floor: PersistentMap, plan: FloorPlan) -> PersistentMap:
    rooms = {room.region_id: room for room in plan.rooms if room.region_id and room.visible}
    if not rooms:
        return floor
    regions = []
    for region in floor.regions:
        if region.kind is RegionKind.ZONE:
            regions.append(region)
        elif (room := rooms.pop(region.region_id, None)) is not None:
            regions.append(replace(region, name=room.name))
    regions.extend(
        CleaningRegion(identifier, RegionKind.ROOM, room.name) for identifier, room in rooms.items()
    )
    return replace(floor, regions=tuple(regions))


def policy_geometry(
    documents, *, include_no_mop=False, require_no_mop_outline=False
) -> tuple[tuple[Polygon, ...], tuple[Ring, ...], tuple[Polygon, ...]]:
    if "policyZones" not in documents:
        return (), (), ()
    restrictions = []
    walls = []
    no_mop = []
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
        elif include_no_mop and properties["type"] == "NoMopZone":
            try:
                no_mop.extend(_polygons(item))
            except ProtocolError:
                # Some maps describe a no-mop zone without supplying its outline.
                if require_no_mop_outline:
                    raise
    return tuple(restrictions), tuple(walls), tuple(no_mop)


def resolve_room_point(
    data: bytes, area: AreaTarget, x: float, y: float, *, mops: bool = False
) -> PointTarget:
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
        keep_out, walls, no_mop = policy_geometry(
            documents, include_no_mop=mops, require_no_mop_outline=mops
        )
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
        or any(_inside(point, polygon, include_boundary=True) for polygon in keep_out)
    ):
        raise ValueError("Selected point is outside the room or inside a keep-out zone.")
    if any(_inside(point, polygon, include_boundary=True) for polygon in no_mop):
        raise ValueError("Selected point is inside a no-mop zone.")
    return PointTarget(area.map_id, area.version_id, point)
