"""Prepare and reconcile settings that leave the native map revision intact."""

from dataclasses import dataclass
from math import atan2, cos, pi, remainder, sin, tau

from .maps import PersistentMap

MAX_FLOOR_NAME_LENGTH = 16
MAX_INITIAL_FLOOR_NAME_LENGTH = 20


def floor_name_limit(floor: PersistentMap) -> int:
    return MAX_INITIAL_FLOOR_NAME_LENGTH if floor.name is None else MAX_FLOOR_NAME_LENGTH


@dataclass(frozen=True, repr=False)
class FloorSettingsEdit:
    name: str | None = None
    orientation: float | None = None

    def request_body(self) -> dict:
        body = {}
        if self.name is not None:
            body["name"] = self.name
        if self.orientation is not None:
            body["user_orientation_rad"] = self.orientation
        return body

    def matches(self, before: PersistentMap, current: PersistentMap) -> bool:
        expected_name = before.name if self.name is None else self.name
        expected_angle = before.orientation if self.orientation is None else self.orientation
        return (
            current.geometry_key == before.geometry_key
            and current.name == expected_name
            and same_orientation(current.orientation, expected_angle)
        )


def same_orientation(first: float | None, second: float | None) -> bool:
    if first is None or second is None:
        return first is second
    return abs(remainder(first - second, tau)) <= 1e-6


def prepare_floor_settings(
    floor: PersistentMap, operation: str, name: str | None, quarter_turns: int | None
) -> FloorSettingsEdit:
    if operation == "rename":
        limit = floor_name_limit(floor)
        if (
            quarter_turns is not None
            or not isinstance(name, str)
            or not name.strip()
            or len(name) > limit
            or not name.isprintable()
        ):
            raise ValueError(f"Enter a floor name of up to {limit} characters.")
        return FloorSettingsEdit(name=name)
    if (
        operation != "rotate"
        or name is not None
        or type(quarter_turns) is not int
        or not 1 <= quarter_turns <= 3
    ):
        raise ValueError("Choose one, two, or three clockwise quarter-turns.")
    angle = (floor.orientation or 0.0) - quarter_turns * pi / 2
    return FloorSettingsEdit(orientation=atan2(sin(angle), cos(angle)))


def prepare_floor_settings_restore(
    current: PersistentMap, saved: PersistentMap
) -> FloorSettingsEdit:
    """Recover the selected floor's backed-up metadata independently of its geometry."""
    if current.map_id != saved.map_id:
        raise ValueError("Select the active floor for this backup.")
    name = saved.name if saved.name != current.name else None
    if name is not None and (
        not isinstance(name, str)
        or not name.strip()
        or not name.isprintable()
        or len(name) > MAX_INITIAL_FLOOR_NAME_LENGTH
    ):
        raise ValueError("The saved floor name is outside the supported name range.")
    angle = saved.orientation
    if angle is not None and (type(angle) not in (float, int) or not -tau <= angle <= tau):
        raise ValueError("The backup has an invalid floor orientation.")
    return FloorSettingsEdit(
        name=name,
        orientation=None if same_orientation(current.orientation, angle) else angle,
    )
