"""Save one restriction while preserving the full Roomba policy layer."""

from dataclasses import dataclass, replace
from itertools import pairwise
from math import hypot

from .errors import ProtocolError
from .map_edits import edited_floor_plan, overlaps_visible_room, rectangle_on_floor
from .maps import PersistentMap
from .point_maps import (
    Coordinate,
    FloorPlan,
    MapRestriction,
    Polygon,
    RestrictionKind,
    Ring,
    _coordinate,
    _inside,
    line_crossings,
)

EDITABLE_RESTRICTIONS = (RestrictionKind.KEEP_OUT, RestrictionKind.NO_MOP, RestrictionKind.WALL)
_WIRE_CODES = {
    RestrictionKind.KEEP_OUT: 1,
    RestrictionKind.NO_MOP: 6,
    RestrictionKind.WALL: 2,
}


@dataclass(frozen=True, repr=False)
class RestrictionEdit:
    restrictions: tuple[MapRestriction, ...]

    def changes(self, current: FloorPlan) -> list[dict]:
        existing = {item.identifier: item for item in current.policy_shapes}
        return [
            {
                "id": item.identifier,
                "kind": item.kind.value,
                "missing": previous is None,
            }
            for item in self.restrictions
            if not _same_restriction(item, previous := existing.get(item.identifier))
        ]

    def request_body(self) -> dict:
        entries = []
        for restriction in self.restrictions:
            points = restriction.points
            if restriction.kind is RestrictionKind.WALL:
                # Roomba reads the first and last vertices as the line endpoints.
                start, end = points
                points = (start, start, end, end)
            entries.append(
                [
                    restriction.identifier,
                    _WIRE_CODES[restriction.kind],
                    *(coordinate for point in points for coordinate in point),
                ]
            )
        return {
            "edit_cmd": {
                "command": "set_virtual_wall",
                "params": {"virwall": [len(entries), *entries]},
            },
            "response_type": "binary",
        }


def prepare_restriction_edit(
    plan: FloorPlan, operation: str, identifier: str | None, kind: str | None, bounds: list | None
) -> RestrictionEdit:
    if plan.policy_shapes is None:
        raise ValueError("The restriction editor cannot preserve every restriction on this floor.")
    restrictions = {item.identifier: item for item in plan.policy_shapes}
    selected = restrictions.get(identifier)
    if operation == "create":
        if identifier is not None or kind not in EDITABLE_RESTRICTIONS or bounds is None:
            raise ValueError("Choose a restriction type and place it on the map.")
        identifier = next(
            str(i) for i in range(100, 101 + len(restrictions)) if str(i) not in restrictions
        )
        shape = RestrictionKind(kind)
        restrictions[identifier] = MapRestriction(
            identifier, shape, _restriction_points(shape, bounds, plan)
        )
    elif selected is None or kind is not None:
        raise ValueError("Select an editable restriction on this floor.")
    elif operation == "update" and bounds is not None:
        restrictions[identifier] = replace(
            selected, points=_restriction_points(selected.kind, bounds, plan)
        )
    elif operation == "delete" and bounds is None:
        del restrictions[identifier]
    else:
        raise ValueError(
            "Draw the new outline or endpoints to move or resize the selected restriction."
        )
    return _restriction_edit(restrictions)


def _restriction_points(kind: RestrictionKind, bounds: list, plan: FloorPlan) -> Ring:
    if kind is not RestrictionKind.WALL:
        return rectangle_on_floor(bounds, plan)
    if len(bounds) != 4 or not all(map(_coordinate, bounds)):
        raise ValueError("Choose two finite wall endpoints.")
    start, end = tuple(bounds[:2]), tuple(bounds[2:])
    if start == end:
        raise ValueError("Place two distinct endpoints for the virtual wall.")
    if not any(
        _wall_crosses_room(start, end, polygon)
        for room in plan.rooms
        if room.visible
        for polygon in room.polygons
    ):
        raise ValueError("Place part of the virtual wall inside a visible room.")
    return start, end


def _wall_crosses_room(start: Coordinate, end: Coordinate, polygon: Polygon) -> bool:
    # Test the open intervals between boundary crossings and both endpoints.
    crossings = {0, 1} | {
        cut for ring in polygon for cut in line_crossings(start, end, ring) if 0 < cut < 1
    }
    for left, right in pairwise(sorted(crossings)):
        mid = (left + right) / 2
        if _inside(
            (start[0] + (end[0] - start[0]) * mid, start[1] + (end[1] - start[1]) * mid), polygon
        ):
            return True
    return False


def prepare_restriction_restore(saved: FloorPlan, current: FloorPlan) -> RestrictionEdit:
    """Reapply saved restrictions by ID while retaining other current restrictions."""
    if saved.policy_shapes is None or current.policy_shapes is None:
        raise ValueError("Restriction recovery requires fully supported policy layers.")
    if not saved.border_digest or saved.border_digest != current.border_digest:
        raise ValueError("The floor boundary has changed since this backup.")
    restrictions = {item.identifier: item for item in current.policy_shapes}
    for item in saved.policy_shapes:
        previous = restrictions.get(item.identifier)
        if _same_restriction(item, previous):
            continue
        if previous is not None and previous.kind is not item.kind:
            raise ValueError("A saved restriction identifier is in use by a different type.")
        if not overlaps_visible_room(item.points, current):
            raise ValueError("A saved restriction no longer overlaps a visible room on this floor.")
        restrictions[item.identifier] = item
    return _restriction_edit(restrictions)


def _restriction_edit(restrictions: dict[str, MapRestriction]) -> RestrictionEdit:
    return RestrictionEdit(
        tuple(item for kind in _WIRE_CODES for item in restrictions.values() if item.kind is kind)
    )


def _same_restriction(expected: MapRestriction, actual: MapRestriction | None) -> bool:
    return (
        actual is not None
        and actual.kind is expected.kind
        and _same_outline(expected.points, actual.points)
    )


def _same_outline(expected: Ring, actual: Ring) -> bool:
    if len(expected) != len(actual):
        return False
    return any(
        all(
            hypot(x - a, y - b) <= 0.0001
            for (x, y), (a, b) in zip(expected, points[start:] + points[:start], strict=True)
        )
        for points in (actual, actual[::-1])
        for start in range(len(points))
    )


def confirm_restriction_edit(
    archive: bytes, floor: PersistentMap, before: FloorPlan, edit: RestrictionEdit
) -> str:
    version, after = edited_floor_plan(archive, floor)
    expected_floor = replace(
        before,
        keep_out=after.keep_out,
        virtual_walls=after.virtual_walls,
        no_mop=after.no_mop,
        policy_shapes=after.policy_shapes,
    )
    if after != expected_floor or after.policy_shapes is None:
        raise ProtocolError("Roomba returned unexpected changes outside the restrictions.")
    actual = {item.identifier: item for item in after.policy_shapes}
    if actual.keys() != {item.identifier for item in edit.restrictions} or any(
        not _same_restriction(item, actual[item.identifier]) for item in edit.restrictions
    ):
        raise ProtocolError("Roomba did not return the expected restriction types and outlines.")
    return version
