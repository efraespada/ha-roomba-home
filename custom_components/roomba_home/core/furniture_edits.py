"""Validate and reconcile a complete, source-preserving Roomba furniture write."""

from dataclasses import dataclass, replace
from math import cos, degrees, dist, radians, remainder, sin, tau
from time import time

from .errors import ProtocolError
from .map_edits import edited_floor_plan, overlaps_visible_room
from .maps import PersistentMap
from .point_maps import FloorPlan, MapFurniture, Ring, _coordinate

# Native object keys from the map layer and codes used by the Android editor.
FURNITURE_TYPES = {
    "bed": (1513, "Bed"),
    "chair/living": (1528, "Chair"),
    "sofa": (1525, "Sofa"),
    "sofa/left_L_shaped": (1526, "Left sectional sofa"),
    "sofa/right_L_shaped": (1527, "Right sectional sofa"),
    "table/dining": (1511, "Dining table"),
    "table/coffee": (1518, "Coffee table"),
    "table/sidetable": (1519, "Side table"),
    "cabinet": (1515, "Cabinet"),
    "cabinet/tv": (1520, "TV cabinet"),
    "refrigerator/regular": (1516, "Refrigerator"),
    "toilet": (1514, "Toilet"),
    "washing_machine_or_dryer": (1524, "Washer or dryer"),
    "pet_furniture/litter_box": (1055, "Litter box"),
    "pet_furniture/pet_bowl": (1052, "Pet bowl"),
    "pet_furniture/pet_bed": (1053, "Pet bed"),
    "pet_furniture/pet_feeder": (1056, "Pet feeder"),
    "pet_furniture/cat_tower": (1059, "Cat tower"),
}
_TOLERANCE = 0.0001


def can_edit_furniture(plan: FloorPlan) -> bool:
    return plan.furniture is not None and all(
        item.kind in FURNITURE_TYPES for item in plan.furniture
    )


def furniture_pose(item: MapFurniture) -> tuple[float, float, float, float, float]:
    first, second, third, _ = item.points
    return (
        sum(x for x, _ in item.points) / 4,
        sum(y for _, y in item.points) / 4,
        dist(first, second),
        dist(second, third),
        degrees(remainder(item.orientation, tau)),
    )


@dataclass(frozen=True, repr=False)
class FurnitureEdit:
    retained: tuple[MapFurniture, ...]
    changed: MapFurniture | None
    removed: MapFurniture | None

    def request_body(self) -> dict:
        items = (*self.retained, self.changed) if self.changed is not None else self.retained
        entries = [
            [
                item.identifier,
                FURNITURE_TYPES[item.kind][0],
                int(item.source == "user"),
                *(value for point in item.points for value in point),
            ]
            for item in items
        ]
        if self.removed is not None:
            entries.append(
                [
                    "0",
                    FURNITURE_TYPES[self.removed.kind][0],
                    1,
                    *(value for point in self.removed.points for value in point),
                ]
            )
        return {
            "edit_cmd": {
                "command": "adjust_furniture",
                "params": {"timestamp": int(time()), "furniture_list": entries, "package": [1, 1]},
            },
            "response_type": "binary",
        }


def _footprint(pose: list, plan: FloorPlan) -> Ring:
    if len(pose) != 5 or not all(_coordinate(value) for value in pose):
        raise ValueError("Enter a finite position, size, and rotation.")
    x, y, width, depth, angle = pose
    if width <= 0 or depth <= 0 or abs(angle) > 360:
        raise ValueError("Use a positive size and a rotation between -360 and 360 degrees.")
    heading = radians(angle)
    c, s = cos(heading), sin(heading)
    w, d = width / 2, depth / 2
    points = tuple(
        (x + u * c - v * s, y + u * s + v * c) for u, v in ((-w, -d), (w, -d), (w, d), (-w, d))
    )
    if (
        len(set(points)) != 4
        or not all(_coordinate(value) for point in points for value in point)
        or not overlaps_visible_room(points, plan)
    ):
        raise ValueError("Place the furniture on a visible room.")
    return points


def prepare_furniture_edit(
    plan: FloorPlan, operation: str, identifier: str | None, kind: str | None, pose: list | None
) -> FurnitureEdit:
    if not can_edit_furniture(plan):
        raise ValueError("The furniture editor cannot preserve every object on this floor.")
    existing = {item.identifier: item for item in plan.furniture}
    selected = existing.get(identifier)
    if operation == "create":
        if identifier is not None or kind not in FURNITURE_TYPES or pose is None:
            raise ValueError("Choose a furniture type, size, and position.")
        identifier = next(str(i) for i in range(1, len(existing) + 2) if str(i) not in existing)
    elif selected is None or kind is not None:
        raise ValueError("Select an editable object on this floor.")
    elif operation == "delete" and pose is None:
        del existing[identifier]
        return FurnitureEdit(tuple(existing.values()), None, selected)
    elif operation == "update" and pose is not None:
        kind = selected.kind
        del existing[identifier]
    else:
        raise ValueError("Choose a position and size for the selected furniture.")
    points = _footprint(pose, plan)
    changed = MapFurniture(identifier, kind, "user", radians(pose[-1]), points)
    return FurnitureEdit(tuple(existing.values()), changed, None)


def confirm_furniture_edit(
    archive: bytes, floor: PersistentMap, before: FloorPlan, edit: FurnitureEdit
) -> str:
    version, after = edited_floor_plan(archive, floor)
    if replace(after, furniture=before.furniture) != before or after.furniture is None:
        raise ProtocolError("Roomba returned unexpected changes outside the furniture layer.")
    observed = {item.identifier: item for item in after.furniture}
    if (changed := edit.changed) is not None:
        actual = observed.pop(changed.identifier, None)
        if (
            actual is None
            or (actual.source, actual.kind) != (changed.source, changed.kind)
            or abs(remainder(actual.orientation - changed.orientation, tau)) > _TOLERANCE
            or any(
                dist(a, b) > _TOLERANCE for a, b in zip(changed.points, actual.points, strict=True)
            )
        ):
            raise ProtocolError("Roomba did not return the expected furniture type and placement.")
    # Roomba derives cleaning areas from the objects around them after every save.
    retained = {item.identifier: replace(item, cleaning_area=()) for item in edit.retained}
    if {
        identifier: replace(item, cleaning_area=()) for identifier, item in observed.items()
    } != retained:
        raise ProtocolError("Roomba did not preserve the rest of the furniture layer.")
    return version
