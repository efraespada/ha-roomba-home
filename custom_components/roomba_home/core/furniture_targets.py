"""Resolve saved furniture to the native temporary regions used by cleaning commands."""

from collections import Counter
from math import dist, hypot, isclose

from .cleaning import CleaningMode
from .cleaning_protocol import cleaning_parameters, regional_cleaning_parameters
from .furniture_edits import FURNITURE_TYPES
from .maps import AreaTarget, FurnitureRegion, RegionKind, map_identifier
from .point_maps import FloorPlan, Ring, _coordinate

_MARGIN = 0.4
_FIRST_TEMPORARY_ID = 160


def _expanded_outline(points: Ring) -> Ring:
    (ax, ay), (bx, by), (cx, cy), (dx, dy) = points
    width, depth = hypot(bx - ax, by - ay), hypot(dx - ax, dy - ay)
    if not width or not depth or dist((bx + dx - ax, by + dy - ay), (cx, cy)) > 0.001:
        return ()
    ux, uy = (bx - ax) / width, (by - ay) / width
    vx, vy = (dx - ax) / depth, (dy - ay) / depth
    if not isclose(ux * vx + uy * vy, 0, abs_tol=0.001):
        return ()
    return tuple(
        (x + _MARGIN * (su * ux + sv * vx), y + _MARGIN * (su * uy + sv * vy))
        for (x, y), (su, sv) in zip(points, ((-1, -1), (1, -1), (1, 1), (-1, 1)), strict=True)
    )


def furniture_regions(plan: FloorPlan) -> tuple[FurnitureRegion, ...]:
    counts = Counter()
    destinations = []
    for item in plan.furniture or ():
        if item.kind in FURNITURE_TYPES and (outline := _expanded_outline(item.points)):
            counts[item.kind] += 1
            label = FURNITURE_TYPES[item.kind][1]
            number = counts[item.kind]
            name = label if number == 1 else f"{label} {number}"
            destinations.append(
                FurnitureRegion(item.identifier, RegionKind.FURNITURE, name, outline)
            )
    return tuple(destinations)


def furniture_command_fields(target: AreaTarget, *, saved_routine: bool = False) -> dict:
    """Keep native temporary IDs independent of persistent furniture identifiers."""
    if not target.ordered:
        raise ValueError("Furniture destinations require an explicit order.")
    regions = []
    polygons = []
    for area, profile in zip(target.regions, target.profiles, strict=True):
        identity, kind = area.region_id, area.kind.value
        if isinstance(area, FurnitureRegion):
            identity, kind = str(_FIRST_TEMPORARY_ID + len(polygons)), "tid"
            polygons.append(
                {
                    "id": identity,
                    "metadata": {"furniture_id": area.region_id},
                    "poly": [list(point) for point in area.outline],
                }
            )
        params = (
            regional_cleaning_parameters(profile)
            if saved_routine and profile.mode is CleaningMode.VACUUM_THEN_MOP
            else cleaning_parameters(profile)
        )
        regions.append({"region_id": identity, "type": kind, "params": params})
    return {"ordered": 1, "regions": regions, "id_multipolys": polygons}


def furniture_links(polygons: object) -> dict[str, str]:
    """Interpret only complete, unambiguous furniture polygon links."""
    links = {}
    if not isinstance(polygons, list):
        return links
    for polygon in polygons:
        if not isinstance(polygon, dict) or polygon.keys() != {"id", "metadata", "poly"}:
            return {}
        identity, metadata, outline = polygon["id"], polygon["metadata"], polygon["poly"]
        if (
            not map_identifier(identity)
            or identity in links
            or not isinstance(metadata, dict)
            or metadata.keys() != {"furniture_id"}
            or not map_identifier(metadata["furniture_id"])
            or not isinstance(outline, list)
            or len(outline) != 4
            or not all(
                isinstance(point, list) and len(point) == 2 and all(map(_coordinate, point))
                for point in outline
            )
            or len({tuple(point) for point in outline}) != 4
        ):
            return {}
        links[identity] = metadata["furniture_id"]
    return links
