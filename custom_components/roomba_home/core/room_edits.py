"""Validate room edits against the active floor plan and verify the map response."""

from dataclasses import dataclass, replace
from itertools import pairwise

from .errors import ProtocolError
from .map_edits import edited_floor_plan
from .maps import PersistentMap, map_identifier
from .point_maps import Coordinate, FloorPlan, FloorRoom, _coordinate, _inside, line_crossings

MAX_ROOM_NAME_LENGTH = 31
ROOM_TYPES = {
    "other": "Other",
    "balcony": "Balcony",
    "bathroom": "Bathroom",
    "bedroom": "Bedroom",
    "diningRoom": "Dining room",
    "hallway": "Hallway",
    "kitchen": "Kitchen",
    "livingRoom": "Living room",
}


@dataclass(frozen=True, repr=False)
class RoomEdit:
    room_ids: tuple[str, ...]
    divider: tuple[Coordinate, Coordinate] | None = None
    name: str | None = None
    room_type: str = "other"

    def request_body(self) -> dict:
        if self.name is not None:
            command = "set_room_metadata"
            params = {
                "room_id": self.room_ids[0],
                "room_metadata": {"name": self.name, "type": self.room_type},
            }
        elif self.divider is None:
            command = "arrange_room"
            params = {"room_ids": list(self.room_ids)}
        else:
            command = "split_room"
            first, last = self.divider
            params = {"room_id": self.room_ids[0], "split_points": [*first, *last]}
        return {"edit_cmd": {"command": command, "params": params}, "response_type": "binary"}


def prepare_room_edit(
    plan: FloorPlan,
    operation: str,
    room_ids: list[str],
    points: list | None,
    name: str | None = None,
    room_type: str | None = None,
) -> RoomEdit:
    if plan.source_format != "picea":
        raise ValueError("Room editing is unavailable for this map format.")
    rooms = {room.region_id: room for room in plan.rooms if room.visible}
    if not all(map_identifier(identifier) and identifier in rooms for identifier in room_ids):
        raise ValueError("Select visible rooms on the current map.")
    if operation == "rename":
        if len(room_ids) != 1 or points is not None:
            raise ValueError("Select one room to rename.")
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > MAX_ROOM_NAME_LENGTH
            or not name.isprintable()
        ):
            raise ValueError(f"Enter a room name of up to {MAX_ROOM_NAME_LENGTH} characters.")
        category = "other" if room_type is None else room_type
        if not isinstance(category, str) or category not in ROOM_TYPES:
            raise ValueError("Select a supported room type.")
        return RoomEdit(tuple(room_ids), name=name, room_type=category)
    if name is not None or room_type is not None:
        raise ValueError("Room names and types can only be changed in a rename.")
    if operation == "merge":
        if (
            points is not None
            or len(room_ids) != 2
            or room_ids[0] == room_ids[1]
            or room_ids[1] not in rooms[room_ids[0]].adjacent
            or room_ids[0] not in rooms[room_ids[1]].adjacent
        ):
            raise ValueError("Select two adjacent rooms to merge.")
        return RoomEdit(tuple(room_ids))
    if operation != "split" or len(room_ids) != 1:
        raise ValueError("Select one room to divide.")
    if not isinstance(points, list) or len(points) != 4 or not all(map(_coordinate, points)):
        raise ValueError("Choose two finite divider endpoints.")
    start, end = tuple(points[:2]), tuple(points[2:])
    polygons = rooms[room_ids[0]].polygons
    if len(polygons) != 1 or start == end:
        raise ValueError("Choose a divider through one connected room.")
    polygon = polygons[0]
    outer, *holes = polygon
    crossings = line_crossings(start, end, outer)
    if (
        len(crossings) != 2
        or min(crossings[1], 1) <= max(crossings[0], 0)
        or any(line_crossings(start, end, hole) for hole in holes)
    ):
        raise ValueError("Draw a line that crosses two room boundaries without crossing a hole.")
    center = sum(crossings) / 2
    middle = (start[0] + (end[0] - start[0]) * center, start[1] + (end[1] - start[1]) * center)
    if not _inside(middle, polygon):
        raise ValueError("Draw the divider through the interior of the room.")
    return RoomEdit(tuple(room_ids), (start, end))


def _footprint(room: FloorRoom) -> frozenset:
    def edges(ring):
        return frozenset(frozenset(edge) for edge in pairwise(ring))

    return frozenset(
        (edges(outer), frozenset(edges(hole) for hole in holes)) for outer, *holes in room.polygons
    )


def review_room_details(saved: FloorPlan, current: FloorPlan) -> list[tuple[dict, RoomEdit | None]]:
    """Only restore labels and types for rooms with the same identity and footprint."""
    if saved.source_format != "picea" or current.source_format != "picea":
        raise ValueError("Room detail recovery is unavailable for this map format.")
    if not saved.border_digest or saved.border_digest != current.border_digest:
        raise ValueError("The floor boundary has changed since this backup.")
    active = {room.region_id: room for room in current.rooms if room.visible}
    changes = []
    for original in saved.rooms:
        if not original.visible:
            continue
        previous = active.get(original.region_id)
        row = {
            "id": original.region_id,
            "name": {"from": previous.name if previous else None, "to": original.name},
            "room_type": {
                "from": previous.room_type if previous else None,
                "to": original.room_type,
            },
        }
        if previous is None:
            changes.append((row | {"status": "missing_room"}, None))
        elif _footprint(previous) != _footprint(original):
            changes.append((row | {"status": "changed_boundary"}, None))
        elif (previous.name, previous.room_type) != (original.name, original.room_type):
            try:
                if original.room_type is None:
                    raise ValueError
                edit = prepare_room_edit(
                    current, "rename", [original.region_id], None, original.name, original.room_type
                )
            except ValueError:
                changes.append((row | {"status": "unsupported_details"}, None))
            else:
                changes.append((row | {"status": "ready"}, edit))
    return changes


def edited_revision(archive: bytes, floor: PersistentMap, before: FloorPlan, edit: RoomEdit) -> str:
    version, after = edited_floor_plan(archive, floor)
    if edit.name is not None:
        (target,) = edit.room_ids
        expected = {
            room.region_id: (
                replace(room, name=edit.name, room_type=edit.room_type)
                if room.region_id == target
                else room
            )
            for room in before.rooms
        }
        actual = {room.region_id: room for room in after.rooms}
        if actual != expected or replace(after, rooms=before.rooms) != before:
            raise ProtocolError("Roomba did not confirm the requested room name and type.")
        return version
    unaffected = {
        room.region_id: room.polygons
        for room in before.rooms
        if room.region_id not in edit.room_ids
    }
    remaining = {room.region_id: room.polygons for room in after.rooms}
    expected = 2 if edit.divider is not None else 1
    if len(remaining.keys() - unaffected.keys()) != expected or any(
        remaining.get(identifier) != polygons for identifier, polygons in unaffected.items()
    ):
        raise ProtocolError("Roomba did not return the expected room changes.")
    return version
