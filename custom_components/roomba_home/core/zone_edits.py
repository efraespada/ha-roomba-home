"""Prepare cleaning zone saves and check the returned active-map geometry."""

from dataclasses import dataclass, replace
from math import isclose

from .errors import ProtocolError
from .map_edits import edited_floor_plan, overlaps_visible_room, rectangle_on_floor, touches_outline
from .maps import SAVED_ZONE_IDS, PersistentMap, RegionKind
from .point_maps import FloorPlan, FloorRoom, Ring, _inside, rectangle_outline


@dataclass(frozen=True, repr=False)
class CleaningZoneEdit:
    zone_id: str
    name: str | None = None
    corners: Ring = ()

    def request_body(self) -> dict:
        if self.name is None:
            command = "del_permanent_area"
            params = {"area_ids": [self.zone_id]}
        else:
            return _save_zones((self,))
        return {"edit_cmd": {"command": command, "params": params}, "response_type": "binary"}


def _save_zones(edits: tuple[CleaningZoneEdit, ...]) -> dict:
    return {
        "edit_cmd": {
            "command": "set_permanent_area",
            "params": {
                "area_points": [
                    [zone.zone_id, zone.name, [value for point in zone.corners for value in point]]
                    for zone in edits
                ]
            },
        },
        "response_type": "binary",
    }


@dataclass(frozen=True, repr=False)
class CleaningZoneRestore:
    zones: tuple[CleaningZoneEdit, ...]

    def request_body(self) -> dict:
        return _save_zones(self.zones)

    def changes(self, current: FloorPlan) -> list[dict]:
        existing = {zone.region_id: zone for zone in current.zone_outlines}
        return [
            {
                "id": zone.zone_id,
                "name": zone.name,
                "current_name": existing[zone.zone_id].name if zone.zone_id in existing else None,
                "missing": zone.zone_id not in existing,
                "outline_changed": zone.zone_id not in existing
                or not _same_corners(zone_corners(existing[zone.zone_id]), zone.corners),
            }
            for zone in self.zones
        ]


def zone_corners(zone: FloorRoom) -> Ring:
    return rectangle_outline(zone.polygons)


def _rectangle(bounds: list, plan: FloorPlan) -> Ring:
    corners = rectangle_on_floor(bounds, plan)
    _require_clear_zone(corners, plan)
    return corners


def _require_clear_zone(corners: Ring, plan: FloorPlan) -> None:
    footprint = ((*corners, corners[0]),)
    if any(touches_outline(wall, footprint) for wall in plan.virtual_walls) or any(
        any(_inside(point, exclusion, include_boundary=True) for point in corners)
        or any(touches_outline(ring, footprint) for ring in exclusion)
        for exclusion in plan.keep_out
    ):
        raise ValueError("Keep the zone clear of restricted areas and virtual walls.")


def prepare_zone_edit(
    floor: PersistentMap,
    plan: FloorPlan,
    operation: str,
    zone_id: str | None,
    name: str | None,
    bounds: list | None,
) -> CleaningZoneEdit:
    if plan.source_format != "picea":
        raise ValueError("Cleaning zone editing is unavailable for this map format.")
    zones = {zone.region_id: zone for zone in plan.zone_outlines}
    if operation == "create":
        if zone_id is not None or bounds is None:
            raise ValueError("Draw a rectangle for the new cleaning zone.")
        occupied = set(zones) | {
            region.region_id for region in floor.regions if region.kind is RegionKind.ZONE
        }
        zone_id = next(
            (identifier for identifier in SAVED_ZONE_IDS if identifier not in occupied), None
        )
        if zone_id is None:
            raise ValueError("Roomba has no available cleaning zone IDs on this floor.")
    elif zone_id not in zones or operation not in {"update", "delete"}:
        raise ValueError("Select a saved cleaning zone on the current map.")
    if operation == "delete":
        if name is not None or bounds is not None:
            raise ValueError("Remove the zone without changing its name or shape.")
        return CleaningZoneEdit(zone_id)
    if name is None or not name.strip() or len(name.strip()) > 16 or not name.isprintable():
        raise ValueError("Enter a cleaning zone name of up to 16 characters.")
    corners = _rectangle(bounds, plan) if bounds is not None else zone_corners(zones[zone_id])
    if not corners:
        raise ValueError("Draw a rectangular outline for this cleaning zone.")
    return CleaningZoneEdit(zone_id, name.strip(), corners)


def _same_corners(actual: Ring, expected: Ring) -> bool:
    return bool(actual and len(actual) == len(expected)) and all(
        any(
            isclose(x, a, rel_tol=0, abs_tol=0.0001) and isclose(y, b, rel_tol=0, abs_tol=0.0001)
            for a, b in actual
        )
        for x, y in expected
    )


def prepare_zone_restore(saved: FloorPlan, current: FloorPlan) -> CleaningZoneRestore:
    """Use the archived identifiers and vertices in their verified map frame."""
    if saved.source_format != "picea" or current.source_format != "picea":
        raise ValueError("Cleaning zone recovery is unavailable for this map format.")
    if not saved.border_digest or saved.border_digest != current.border_digest:
        raise ValueError("The floor boundary has changed since this backup.")
    existing = {zone.region_id: zone for zone in current.zone_outlines}
    edits = []
    for zone in saved.zone_outlines:
        previous = existing.get(zone.region_id)
        corners = zone_corners(zone)
        if previous is not None and matching_saved_zone(zone, previous):
            continue
        if (
            zone.region_id not in SAVED_ZONE_IDS
            or not corners
            or zone.name is None
            or not zone.name.strip()
            or len(zone.name) > 16
            or not zone.name.isprintable()
        ):
            raise ValueError("A saved zone does not have a supported identifier, name, or outline.")
        if not overlaps_visible_room(corners, current):
            raise ValueError("A saved zone no longer overlaps a visible room on this floor.")
        _require_clear_zone(corners, current)
        edits.append(CleaningZoneEdit(zone.region_id, zone.name, corners))
    return CleaningZoneRestore(tuple(edits))


def matching_saved_zone(saved: FloorRoom, current: FloorRoom) -> bool:
    return saved.name == current.name and (
        saved.polygons == current.polygons
        or _same_corners(zone_corners(saved), zone_corners(current))
    )


def confirm_zone_restore(
    archive: bytes, floor: PersistentMap, before: FloorPlan, edit: CleaningZoneRestore
) -> str:
    version, after = edited_floor_plan(archive, floor)
    without_zones = replace(
        after,
        zones=before.zones,
        zone_outlines=before.zone_outlines,
        unlinked_zone_count=before.unlinked_zone_count,
    )
    actual = {zone.region_id: zone for zone in after.zone_outlines}
    previous = {zone.region_id: zone for zone in before.zone_outlines}
    for change in edit.zones:
        restored = actual.pop(change.zone_id, None)
        previous.pop(change.zone_id, None)
        if (
            restored is None
            or restored.name != change.name
            or not _same_corners(zone_corners(restored), change.corners)
        ):
            raise ProtocolError("Roomba did not return the recorded cleaning zone geometry.")
    if without_zones != before or actual != previous:
        raise ProtocolError("Roomba returned unexpected map changes during zone recovery.")
    return version


def confirm_zone_edit(
    archive: bytes, floor: PersistentMap, before: FloorPlan, edit: CleaningZoneEdit
) -> str:
    version, after = edited_floor_plan(archive, floor)
    previous = {zone.region_id: zone for zone in before.zone_outlines}
    zones = {zone.region_id: zone for zone in after.zone_outlines}
    changed = zones.pop(edit.zone_id, None)
    previous.pop(edit.zone_id, None)
    if (
        after.source_format != before.source_format
        or after.rooms != before.rooms
        or after.keep_out != before.keep_out
        or after.no_mop != before.no_mop
        or after.virtual_walls != before.virtual_walls
        or after.border_digest != before.border_digest
        or zones != previous
    ):
        raise ProtocolError("Roomba returned unexpected changes outside the selected zone.")
    if edit.name is None:
        if changed is not None:
            raise ProtocolError("Roomba still shows the deleted zone.")
    elif (
        changed is None
        or changed.name != edit.name
        or not _same_corners(zone_corners(changed), edit.corners)
    ):
        raise ProtocolError("Roomba did not return the saved zone name and outline.")
    return version
