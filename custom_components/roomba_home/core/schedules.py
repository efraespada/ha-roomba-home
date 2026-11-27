"""Project cloud schedules and serialize cleaning with validated targets."""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo

from .cleaning_protocol import regional_cleaning_parameters
from .errors import ProtocolError
from .furniture_targets import furniture_command_fields, furniture_links, region_target_id
from .maps import AreaTarget, FurnitureRegion, map_identifier
from .routines import routine_region_profile
from .telemetry import convert, integer

IDENTIFIER = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}")
SCHEDULE_ID = re.compile(rf"{IDENTIFIER.pattern}:{IDENTIFIER.pattern}")
SCHEDULE_ITEM_PATH = re.compile(
    rf"/v1/households/{IDENTIFIER.pattern}/settings/schedule/{IDENTIFIER.pattern}"
)
WALL_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9](?::00)?")
SCHEDULE_FREQUENCIES = ("weekly", "once")
REGIONAL_COMMAND_FIELDS = {
    "robot_id",
    "command",
    "ordered",
    "p2map_id",
    "user_p2mapv_id",
    "params",
    "regions",
}
TIMED_COMMAND_FIELDS = REGIONAL_COMMAND_FIELDS - {"robot_id"} | {"initiator", "time"}
FURNITURE_COMMAND_FIELDS = TIMED_COMMAND_FIELDS | {"id_multipolys"}


def _identifier(value: object) -> bool:
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None


@dataclass(frozen=True, repr=False)
class CleaningSchedule:
    group_id: str
    item_id: str
    options: dict
    start: dict

    @property
    def id(self) -> str:
        return f"{self.group_id}:{self.item_id}"

    @property
    def command(self) -> dict:
        return self.options["commands"][0]["command"]

    def action_response(self) -> dict:
        name = self.options.get("name")
        command = self.command
        map_id = command.get("p2map_id")
        regions = command.get("regions")
        links = furniture_links(command.get("id_multipolys"))
        targets = None
        if (
            command.get("select_all") is not True
            and map_identifier(map_id)
            and isinstance(regions, list)
            and regions
        ):
            identifiers = [region_target_id(map_id, region, links) for region in regions]
            if all(identifier is not None for identifier in identifiers):
                targets = identifiers
        response = {
            "id": self.id,
            "name": name
            if isinstance(name, str) and name.isprintable() and len(name) <= 120
            else None,
            "enabled": self.options["enabled"],
            "regions": targets,
            **self.start,
        }
        if targets and (settings := self.region_settings(targets, links)) is not None:
            response["region_settings"] = settings
        return response

    def region_settings(self, targets: list[str], links: dict[str, str]) -> list[dict] | None:
        command = self.command
        if (
            self.options["commands"][0].keys() != {"command"}
            or type(command.get("ordered")) is not int
            or command["ordered"] != 1
            or command.get("select_all", False) is not False
            or not map_identifier(command.get("user_p2mapv_id"))
            or len(targets) > 32
            or len(set(targets)) != len(targets)
        ):
            return None
        fields = command.keys()
        furniture = fields == FURNITURE_COMMAND_FIELDS
        timed = furniture or fields == TIMED_COMMAND_FIELDS
        if timed:
            if (
                not furniture
                and self.options["frequency"] != "ONCE"
                or command["params"] != {}
                or not _native_command_time(command)
            ):
                return None
            if furniture and (
                not links
                or links.keys()
                != {region["region_id"] for region in command["regions"] if region["type"] == "tid"}
            ):
                return None
        elif (
            fields not in (REGIONAL_COMMAND_FIELDS, REGIONAL_COMMAND_FIELDS | {"select_all"})
            or command["params"] != {"routine_modified": True}
            or command["params"]["routine_modified"] is not True
        ):
            return None
        profiles = [
            routine_region_profile(region, inactive_mop=timed) for region in command["regions"]
        ]
        if any(profile is None for profile in profiles):
            return None
        return [
            {"id": identifier, **profile}
            for identifier, profile in zip(targets, profiles, strict=True)
        ]

    def matches_creation(self, options: dict) -> bool:
        if self.start != schedule_start(options) or any(
            self.options.get(field) != value
            for field, value in options.items()
            if field not in {"start", "commands"}
        ):
            return False
        wanted = options["commands"][0]["command"]
        if "id_multipolys" in wanted and _native_command_time(self.command):
            # A retry may generate a new timestamp for the same disabled schedule.
            wanted = {**wanted, "time": self.command["time"]}
        return self.options["commands"] == [{"command": wanted}]

    def replace_selection(self, target: AreaTarget, timestamp: int) -> list[dict]:
        if "region_settings" not in self.action_response():
            raise ValueError("The scheduled cleaning preferences are not supported for editing.")
        command = schedule_command(
            self.options["robot_id"], target, timestamp=self.command.get("time", timestamp)
        )
        if "select_all" in self.command:
            command["select_all"] = False
        return [{"command": command}]


def _native_command_time(command: dict) -> bool:
    stamp = command.get("time")
    return command.get("initiator") == "rmtApp" and type(stamp) is int and stamp > 0


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
    # Home Assistant uses ISO weekdays. The native editor encodes Sunday as zero.
    return {"day": sorted(day % 7 for day in weekdays), "hour": int(hour), "min": int(minute)}


def cleaning_schedule_start(weekdays: list[int], local_time: str, frequency: str) -> dict:
    start = weekly_start(weekdays, local_time)
    if frequency not in SCHEDULE_FREQUENCIES or frequency == "once" and len(start["day"]) != 1:
        raise ValueError(
            "Select a supported frequency and exactly one day for a one-time schedule."
        )
    return start


def once_weekday(local_time: str, zone: tzinfo, now: datetime) -> int:
    """Use the next occurrence of the selected local time in the robot's zone."""
    clock = time.fromisoformat(local_time)
    day = now.astimezone(zone).date()
    first, second = _utc_folds(datetime.combine(day, clock, zone))
    if max(first, second) <= now:
        day += timedelta(days=1)
        first, second = _utc_folds(datetime.combine(day, clock, zone))
    if first != second:
        raise ValueError("Choose a local time outside a clock change.")
    return day.isoweekday()


def new_cleaning_schedule(
    robot_id: str, name: str, start: dict, target: AreaTarget, *, frequency="weekly", timestamp=0
) -> dict:
    return {
        "robot_id": robot_id,
        "name": schedule_name(name),
        "enabled": False,
        "frequency": frequency.upper(),
        "start": start,
        "commands": [{"command": schedule_command(robot_id, target, timestamp=timestamp)}],
    }


def schedule_name(name: str) -> str:
    if not isinstance(name, str) or not name.isprintable() or not 1 <= len(name.strip()) <= 120:
        raise ValueError("Use a non-empty schedule name up to 120 characters")
    return name.strip()


def schedule_command(robot_id: str, target: AreaTarget, *, timestamp: int = 0) -> dict:
    if (
        not isinstance(target, AreaTarget)
        or not target.regions
        or len(target.profiles) != len(target.regions)
    ):
        raise ValueError("Each scheduled region must have a cleaning profile")
    if any(isinstance(region, FurnitureRegion) for region in target.regions):
        if type(timestamp) is not int or timestamp <= 0:
            raise ValueError("A furniture schedule requires a positive timestamp.")
        return {
            "command": "start",
            "p2map_id": target.map_id,
            "user_p2mapv_id": target.version_id,
            "params": {},
            "initiator": "rmtApp",
            "time": timestamp,
            **furniture_command_fields(target, saved_routine=True),
        }
    return {
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


def schedule_start(options: dict) -> dict | None:
    start = options.get("start")
    frequency = options.get("frequency")
    if frequency not in ("WEEKLY", "ONCE") or not isinstance(start, dict):
        return None
    hour, minute, days = (
        integer(start.get("hour"), 23),
        integer(start.get("min"), 59),
        start.get("day"),
    )
    if hour is None or minute is None or not isinstance(days, list) or not days:
        return None
    if not all(type(day) is int and 0 <= day <= 7 for day in days):
        return None
    # Releases that wrote ISO weekdays to the API used seven for Sunday.
    iso_days = tuple(sorted({day or 7 for day in days}))
    local_time = f"{hour:02d}:{minute:02d}"
    if frequency == "ONCE":
        if len(days) != 1:
            return None
        return {"frequency": "once", "weekday": iso_days[0], "time": local_time}
    return {"weekdays": iso_days, "time": local_time}


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
        and command.get("robot_id", robot_id) == robot_id
        and not options.get("end_commands")
    )


def editable_schedules(document: object, robot_id: str) -> dict[str, CleaningSchedule]:
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
            or (start := schedule_start(options)) is None
        ):
            continue
        schedule = CleaningSchedule(group_id, item_id, options, start)
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
        weekly = []
        one_time = []
        for item in schedules.values():
            if type(item.get("enabled")) is not bool or (start := schedule_start(item)) is None:
                continue
            reading = {**start, "enabled": item["enabled"]}
            if item["frequency"] == "ONCE":
                reading["created_at"] = convert("iso_timestamp", item.get("created_time"))
                one_time.append(reading)
            else:
                weekly.append(reading)
        result[robot] = {
            "cloud_schedule_count": len(schedules),
            "cloud_enabled_schedule_count": (
                sum(enabled) if all(type(value) is bool for value in enabled) else None
            ),
            "cloud_schedule_times": tuple(weekly),
        }
        if one_time:
            result[robot]["cloud_once_schedule_times"] = tuple(one_time)
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


def _once_occurrence(item, zone, now):
    created = item["created_at"]
    if created is None:
        return now, True
    local_day = created.astimezone(zone).date()
    offset = (item["weekday"] - local_day.isoweekday()) % 7
    if offset > 1:
        return now, True
    local_start = datetime.combine(
        local_day + timedelta(days=offset), time.fromisoformat(item["time"]), zone
    )
    first, second = _utc_folds(local_start)
    if max(first, second) <= created:
        return now, True
    return (min(first, second), first != second) if max(first, second) > now else None


def next_schedule_start(telemetry: dict, zone: tzinfo, now: datetime) -> datetime | None:
    """Return the earliest unambiguous start from a complete set of enabled schedules."""
    enabled = [item for item in telemetry["cloud_schedule_times"] if item["enabled"]]
    one_time = [item for item in telemetry.get("cloud_once_schedule_times", ()) if item["enabled"]]
    if len(enabled) + len(one_time) != telemetry.get("cloud_enabled_schedule_count"):
        return None
    today = now.astimezone(zone).date()
    weekly = (
        _next_occurrence(day, time.fromisoformat(item["time"]), today, zone, now)
        for item in enabled
        for day in item["weekdays"]
    )
    once = (_once_occurrence(item, zone, now) for item in one_time)
    earliest = min((*weekly, *(item for item in once if item is not None)), default=None)
    return earliest[0] if earliest and not earliest[1] else None
