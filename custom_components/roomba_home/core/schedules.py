"""Project cloud schedules and serialize weekly cleaning with validated targets."""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo

from .cleaning_protocol import regional_cleaning_parameters
from .errors import ProtocolError
from .maps import AreaTarget
from .telemetry import integer

IDENTIFIER = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}")
SCHEDULE_ID = re.compile(rf"{IDENTIFIER.pattern}:{IDENTIFIER.pattern}")
SCHEDULE_ITEM_PATH = re.compile(
    rf"/v1/households/{IDENTIFIER.pattern}/settings/schedule/{IDENTIFIER.pattern}"
)
WALL_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9](?::00)?")


def _identifier(value: object) -> bool:
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None


@dataclass(frozen=True, repr=False)
class WeeklySchedule:
    group_id: str
    item_id: str
    options: dict
    start: dict

    @property
    def id(self) -> str:
        return f"{self.group_id}:{self.item_id}"

    def action_response(self) -> dict:
        name = self.options.get("name")
        return {
            "id": self.id,
            "name": name
            if isinstance(name, str) and name.isprintable() and len(name) <= 120
            else None,
            "enabled": self.options["enabled"],
            **self.start,
        }


def weekly_start(weekdays: list[int], local_time: str) -> dict:
    if (
        not isinstance(weekdays, list)
        or not weekdays
        or not all(type(day) is int and 1 <= day <= 7 for day in weekdays)
        or len(weekdays) != len(set(weekdays))
        or not isinstance(local_time, str)
        or WALL_TIME.fullmatch(local_time) is None
    ):
        raise ValueError("Select distinct ISO weekdays and a local time to the minute.")
    hour, minute = local_time.split(":")[:2]
    return {"day": sorted(weekdays), "hour": int(hour), "min": int(minute)}


def new_weekly_schedule(robot_id: str, name: str, start: dict, target: AreaTarget) -> dict:
    if not isinstance(name, str) or not name.isprintable() or not 1 <= len(name.strip()) <= 120:
        raise ValueError("Use a non-empty schedule name up to 120 characters")
    if (
        not isinstance(target, AreaTarget)
        or not target.regions
        or len(target.profiles) != len(target.regions)
    ):
        raise ValueError("Each scheduled region must have a cleaning profile")
    return {
        "robot_id": robot_id,
        "name": name.strip(),
        "enabled": False,
        "frequency": "WEEKLY",
        "start": start,
        "commands": [
            {
                "command": {
                    "robot_id": robot_id,
                    "command": "start",
                    "ordered": 1,
                    "p2map_id": target.map_id,
                    "user_p2mapv_id": target.version_id,
                    "params": {"routine_modified": True},
                    "regions": [
                        {
                            "region_id": region.region_id,
                            "type": region.kind.value,
                            "params": regional_cleaning_parameters(profile),
                        }
                        for region, profile in zip(target.regions, target.profiles, strict=True)
                    ],
                }
            }
        ],
    }


def associated_households(document: object, robots: frozenset[str]) -> dict[str, frozenset[str]]:
    if not isinstance(document, list):
        raise ProtocolError("Expected the associated households list")
    result = {}
    for row in document:
        if not isinstance(row, dict):
            continue
        identifier = row.get("household_id")
        members = row.get("household_robots")
        if not _identifier(identifier):
            continue
        if not isinstance(members, list):
            continue
        selected = frozenset(
            entry["robot_id"]
            for entry in members
            if isinstance(entry, dict)
            and isinstance(entry.get("robot_id"), str)
            and entry["robot_id"] in robots
        )
        if selected:
            result[identifier] = result.get(identifier, frozenset()) | selected
    return result


def _weekly_start(options: dict) -> dict | None:
    start = options.get("start")
    if options.get("frequency") != "WEEKLY" or not isinstance(start, dict):
        return None
    hour, minute, days = (
        integer(start.get("hour"), 23),
        integer(start.get("min"), 59),
        start.get("day"),
    )
    if hour is None or minute is None or not isinstance(days, list) or not days:
        return None
    if not all(type(day) is int and 1 <= day <= 7 for day in days):
        return None
    return {"weekdays": tuple(sorted(set(days))), "time": f"{hour:02d}:{minute:02d}"}


def _raw_groups(document: object) -> list:
    if not isinstance(document, dict) or not isinstance(document.get("household_schedules"), list):
        raise ProtocolError("Expected the household schedules list")
    return document["household_schedules"]


def _schedule_groups(document: object):
    for group in _raw_groups(document):
        if isinstance(group, dict) and isinstance(group.get("schedules"), list):
            yield group.get("household_schedule_id"), group["schedules"]


def schedule_removed(document: object, group_id: str) -> bool:
    """Confirm absence without treating a malformed group as a successful removal."""
    for group in _raw_groups(document):
        if not isinstance(group, dict) or not _identifier(group.get("household_schedule_id")):
            return False
        if group["household_schedule_id"] == group_id:
            items = group.get("schedules")
            if not isinstance(items, list) or not all(
                isinstance(item, dict)
                and isinstance(options := item.get("options"), dict)
                and options.get("deleted") is True
                for item in items
            ):
                return False
    return True


def _starts_selected_robot(options: dict, robot_id: str) -> bool:
    commands = options.get("commands")
    if not isinstance(commands, list) or len(commands) != 1 or not isinstance(commands[0], dict):
        return False
    command = commands[0].get("command")
    return (
        isinstance(command, dict)
        and command.get("command") == "start"
        and command.get("robot_id") == robot_id
        and not options.get("end_commands")
    )


def editable_schedules(document: object, robot_id: str) -> dict[str, WeeklySchedule]:
    """Only a verified single-entry group may be updated as a whole."""
    schedules = {}
    groups = set()
    for group_id, entries in _schedule_groups(document):
        if not _identifier(group_id):
            continue
        if group_id in groups:
            raise ProtocolError("The same schedule group occurred more than once")
        groups.add(group_id)
        if len(entries) != 1 or not isinstance(entry := entries[0], dict):
            continue
        item_id, options = entry.get("schedule_id"), entry.get("options")
        if (
            not _identifier(item_id)
            or not isinstance(options, dict)
            or options.get("robot_id") != robot_id
            or options.get("deleted") is True
            or type(options.get("enabled")) is not bool
            or not _starts_selected_robot(options, robot_id)
            or (start := _weekly_start(options)) is None
        ):
            continue
        schedule = WeeklySchedule(group_id, item_id, options, start)
        schedules[schedule.id] = schedule
    return schedules


def schedule_metrics(document: object, robots: frozenset[str]) -> dict[str, dict]:
    rows = {robot: {} for robot in robots}
    for _, entries in _schedule_groups(document):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            options = entry.get("options")
            if not isinstance(options, dict) or options.get("deleted") is True:
                continue
            robot, identifier = options.get("robot_id"), entry.get("schedule_id")
            if not isinstance(robot, str) or robot not in rows:
                continue
            if _identifier(identifier):
                rows[robot][identifier] = options
    result = {}
    for robot, schedules in rows.items():
        enabled = [item.get("enabled") for item in schedules.values()]
        result[robot] = {
            "cloud_schedule_count": len(schedules),
            "cloud_enabled_schedule_count": (
                sum(enabled) if all(type(value) is bool for value in enabled) else None
            ),
            "cloud_schedule_times": tuple(
                {**weekly, "enabled": item["enabled"]}
                for item in schedules.values()
                if type(item.get("enabled")) is bool and (weekly := _weekly_start(item))
            ),
        }
    return result


def _utc_folds(wall_clock: datetime) -> tuple[datetime, datetime]:
    return wall_clock.astimezone(UTC), wall_clock.replace(fold=1).astimezone(UTC)


def _next_occurrence(
    weekday: int, start: time, today: date, zone: tzinfo, now: datetime
) -> tuple[datetime, bool]:
    day = today + timedelta(days=(weekday - today.isoweekday()) % 7)
    local_start = datetime.combine(day, start, zone)
    first, second = _utc_folds(local_start)
    if max(first, second) <= now:
        first, second = _utc_folds(local_start + timedelta(weeks=1))
    # An offset change can make this time ambiguous or nonexistent. Treat the
    # earlier possible instant as a bound without assuming a provider policy.
    return min(first, second), first != second


def next_weekly_start(telemetry: dict, zone: tzinfo, now: datetime) -> datetime | None:
    """Return the earliest unambiguous start from a complete set of enabled schedules."""
    enabled = [item for item in telemetry["cloud_schedule_times"] if item["enabled"]]
    if not enabled or len(enabled) != telemetry.get("cloud_enabled_schedule_count"):
        return None
    today = now.astimezone(zone).date()
    occurrence, uncertain = min(
        _next_occurrence(day, time.fromisoformat(item["time"]), today, zone, now)
        for item in enabled
        for day in item["weekdays"]
    )
    return None if uncertain else occurrence
