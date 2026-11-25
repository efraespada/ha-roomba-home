"""Common validation for an archive returned by a persistent map edit."""

from dataclasses import replace
from itertools import pairwise

from .errors import ProtocolError
from .maps import PersistentMap, map_identifier
from .point_maps import (
    FloorPlan,
    Polygon,
    Ring,
    _coordinate,
    _documents,
    _floor_plan_documents,
    _inside,
    line_crossings,
)


def edited_floor_plan(archive: bytes, floor: PersistentMap) -> tuple[str, FloorPlan]:
    documents = _documents(archive)
    metadata = documents["metadata"]
    version = metadata.get("version")
    if (
        metadata.get("id") != floor.map_id
        or not map_identifier(version)
        or version == floor.version_id
    ):
        raise ProtocolError("Roomba did not return a new revision of this floor.")
    return version, _floor_plan_documents(documents, replace(floor, version_id=version))


def touches_outline(outline: Ring, footprint: Polygon) -> bool:
    return any(_inside(point, footprint, include_boundary=True) for point in outline) or any(
        0 <= crossing <= 1
        for start, end in pairwise(footprint[0])
        for crossing in line_crossings(start, end, outline)
    )


def _overlaps_room(footprint: Polygon, polygon: Polygon) -> bool:
    return any(_inside(point, polygon) for point in footprint[0][:-1]) or any(
        touches_outline(ring, footprint) for ring in polygon
    )


def overlaps_visible_room(corners: Ring, plan: FloorPlan) -> bool:
    footprint = ((*corners, corners[0]),)
    return any(
        _overlaps_room(footprint, polygon)
        for room in plan.rooms
        if room.visible
        for polygon in room.polygons
    )


def rectangle_on_floor(bounds: list, plan: FloorPlan) -> Ring:
    if len(bounds) != 4 or not all(_coordinate(value) for value in bounds):
        raise ValueError("Choose two finite corners for the zone.")
    left, right = sorted((bounds[0], bounds[2]))
    bottom, top = sorted((bounds[1], bounds[3]))
    if left == right or bottom == top:
        raise ValueError("The zone must have a positive width and height.")
    corners = ((right, bottom), (right, top), (left, top), (left, bottom))
    if not overlaps_visible_room(corners, plan):
        raise ValueError("Place part of the zone on a visible room.")
    return corners
