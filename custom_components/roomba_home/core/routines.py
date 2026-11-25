"""Project the account's saved cleaning routines onto one associated robot."""

import re
from dataclasses import dataclass
from uuid import uuid4

from .cleaning_protocol import (
    cleaning_parameters,
    parse_regional_profile,
    regional_cleaning_parameters,
)
from .errors import ProtocolError
from .furniture_targets import furniture_command_fields, furniture_links
from .maps import AreaTarget, FurnitureRegion, RegionKind, command_region_id, map_identifier
from .telemetry import number

FAVORITES_PATH = "/v1/user/favorites"
APP_EDITION = {"app_edition": "1"}
ROUTINE_ID = re.compile(r"[0-9a-fA-F]{32}")
ROUTINE_ITEM_PATH = re.compile(rf"{FAVORITES_PATH}/{ROUTINE_ID.pattern}")
_ROUTINE_COMMAND_FIELDS = {
    "robot_id",
    "command",
    "p2map_id",
    "user_p2mapv_id",
    "regions",
}
_ESTIMATE_CONFIDENCE = {
    "GOOD_CONFIDENCE": "good",
    "PARTIAL_CONFIDENCE": "partial",
    "POOR_CONFIDENCE": "poor",
}


def routine_name(value: str) -> str:
    if not isinstance(value, str) or not value.isprintable() or not 1 <= len(value.strip()) <= 120:
        raise ValueError("Use a printable routine name up to 120 characters.")
    return value.strip()


@dataclass(frozen=True, repr=False)
class CleaningRoutine:
    identity: str
    name: str
    payload: dict

    @property
    def command(self) -> dict:
        return self.payload["commanddefs"][0]

    def action_response(self) -> dict:
        map_id = self.command.get("p2map_id")
        regions = self.command.get("regions")
        if not isinstance(regions, list) or not map_identifier(map_id):
            regions = []
        links = furniture_links(self.command.get("id_multipolys"))
        recognized = [
            (identifier, item)
            for item in regions
            if (identifier := _routine_region_id(map_id, item, links)) is not None
        ]
        settings = None
        if (
            1 <= len(recognized) == len(regions) <= 32
            and len({identifier for identifier, _ in recognized}) == len(regions)
            and _round_trip_command(self.command, regions, links)
        ):
            common = self.command.get("params", {}) if "ordered" not in self.command else {}
            profiles = [routine_region_profile(item, common) for _, item in recognized]
            if all(profile is not None for profile in profiles):
                settings = [
                    {"id": identifier, **profile}
                    for (identifier, _), profile in zip(recognized, profiles, strict=True)
                ]
        result = {
            "id": self.identity,
            "name": self.name,
            "regions": [identifier for identifier, _ in recognized],
            "region_settings": settings,
            "editable": not self.payload.get("default"),
        }
        if (
            settings is not None
            and "ordered" not in self.command
            and self.command.get("params") is not None
        ):
            result["ordered"] = False
        if (estimate := _routine_estimate(self.payload.get("time_estimates"))) is not None:
            result["estimate"] = estimate
        return result


def _routine_estimate(estimates):
    if not isinstance(estimates, list) or len(estimates) != 1:
        return None
    entry = estimates[0]
    if (
        not isinstance(entry, dict)
        or entry.get("unit") != "minute"
        or (minutes := number(entry.get("estimate"))) is None
    ):
        return None
    confidence = entry.get("confidence")
    return {
        "duration_minutes": minutes,
        "confidence": _ESTIMATE_CONFIDENCE.get(confidence) if isinstance(confidence, str) else None,
    }


def _routine_region_id(map_id, region, links):
    if isinstance(region, dict) and region.get("type") == "tid":
        identity = region.get("region_id")
        if map_identifier(identity) and identity in links:
            return f"{map_id}:{RegionKind.FURNITURE}:{links[identity]}"
        return None
    return command_region_id(map_id, region)


def _round_trip_command(command, regions, links):
    fields = command.keys()
    ordered_fields = _ROUTINE_COMMAND_FIELDS | {"ordered"}
    timed_fields = _ROUTINE_COMMAND_FIELDS | {"initiator", "time"}
    if "user_p2mapv_id" in command and not map_identifier(command["user_p2mapv_id"]):
        return False
    if fields == timed_fields:
        return len(regions) == 1 and _timed_app_command(command)
    if fields == timed_fields | {"params"}:
        common = command["params"]
        return _timed_app_command(command) and (
            common == {} or _routine_profile(common) is not None
        )
    if type(command.get("ordered")) is not int or command["ordered"] != 1:
        return False
    if fields == (ordered_fields - {"user_p2mapv_id"}) | {"initiator", "time"}:
        return _timed_app_command(command)
    if fields == ordered_fields | {"select_all"}:
        return command["select_all"] is False
    if fields == ordered_fields | {"select_all", "params"}:
        return command["select_all"] is False and _ordered_routine_params(command["params"])
    return (
        fields == ordered_fields | {"initiator", "time", "id_multipolys"}
        and _timed_app_command(command)
        and bool(links)
        and links.keys() == {item["region_id"] for item in regions if item["type"] == "tid"}
    )


def _timed_app_command(command):
    return command["initiator"] == "rmtApp" and type(command["time"]) is int and command["time"] > 0


def _ordered_routine_params(params):
    if params == {"profile": "normal"}:
        return True
    return (
        isinstance(params, dict)
        and params.keys() <= {"profile", "routine_type", "routine_modified", "replay_of"}
        and params.get("profile", "normal") == "normal"
        and params.get("routine_type") == "REPLAY"
        and params.get("routine_modified", True) is True
        and map_identifier(params.get("replay_of"))
    )


def _routine_profile(params):
    if (
        isinstance(params, dict)
        and params.get("operatingMode") == 2
        and type(params.get("swScrub")) is int
        and params["swScrub"] == 0
    ):
        # Some native vacuum routines include the disabled mop switch.
        params = {key: value for key, value in params.items() if key != "swScrub"}
    return parse_regional_profile(params)


def routine_region_profile(
    region: dict, common: dict | None = None, *, inactive_mop=False
) -> dict | None:
    """Project settings that can be written back without dropping provider data."""
    if region.keys() != {"region_id", "type", "params"}:
        return None
    if not isinstance(params := region["params"], dict):
        return None
    settings = (common or {}) | params
    profile = (
        parse_regional_profile(settings, inactive_mop=True)
        if inactive_mop
        else _routine_profile(settings)
    )
    if profile is None:
        return None
    return {
        "mode": profile.mode.value,
        "suction_level": profile.suction_level,
        "wetness_level": profile.wetness_level,
        "two_pass": profile.two_pass,
        "smart_scrub": profile.smart_scrub,
        "carpet_boost": profile.carpet_boost,
    }


def cleaning_routines(document: object, robot_id: str) -> dict[str, CleaningRoutine]:
    if not isinstance(document, list):
        raise ProtocolError("Expected a saved routine list.")
    result = {}
    for item in document:
        if not isinstance(item, dict) or item.get("deleted") or item.get("hidden"):
            continue
        identifier = item.get("favorite_id")
        commands = item.get("commanddefs")
        if (
            not isinstance(identifier, str)
            or ROUTINE_ID.fullmatch(identifier) is None
            or not isinstance(commands, list)
            or len(commands) != 1
            or not isinstance(command := commands[0], dict)
            or command.get("robot_id") != robot_id
            or command.get("command") != "start"
        ):
            continue
        try:
            name = routine_name(item.get("name"))
        except ValueError:
            continue
        if identifier in result:
            raise ProtocolError("Roomba returned a duplicate routine identifier.")
        result[identifier] = CleaningRoutine(identifier, name, item)
    return result


def routine_command(robot_id: str, target: AreaTarget, timestamp: int = 0) -> dict:
    if not isinstance(target, AreaTarget) or not target.regions or not target.profiles:
        raise ValueError("Select areas with cleaning profiles on one current map.")
    command = {
        "robot_id": robot_id,
        "command": "start",
        "p2map_id": target.map_id,
        "user_p2mapv_id": target.version_id,
    }
    if any(isinstance(region, FurnitureRegion) for region in target.regions):
        if type(timestamp) is not int or timestamp <= 0:
            raise ValueError("A furniture routine requires a positive timestamp.")
        return {
            **command,
            "time": timestamp,
            "initiator": "rmtApp",
            **furniture_command_fields(target, saved_routine=True),
        }
    encode = regional_cleaning_parameters if target.ordered else cleaning_parameters
    command["regions"] = [
        {"region_id": area.region_id, "type": area.kind.value, "params": encode(profile)}
        for area, profile in zip(target.regions, target.profiles, strict=True)
    ]
    if target.ordered:
        return {**command, "ordered": 1, "select_all": False}
    if type(timestamp) is not int or timestamp <= 0:
        raise ValueError("An unordered routine requires a positive timestamp.")
    return {**command, "time": timestamp, "initiator": "rmtApp", "params": {}}


def new_routine(name: str, command: dict, timestamp: int) -> dict:
    return {
        "favorite_id": uuid4().hex,
        "name": routine_name(name),
        "icon": "🤖",
        "color": "#DAF6A1",
        "creation_timestamp": timestamp,
        "last_modified": timestamp,
        "last_user_modified": timestamp,
        "commanddefs": [command],
    }


def routine_matches(
    routine: CleaningRoutine, name: str, command: dict, *, regenerated: bool = False
) -> bool:
    ignore_time = regenerated and "time" in command
    if regenerated and ("ordered" in routine.command) != ("ordered" in command):
        return False
    return routine.name == name and all(
        (ignore_time and key == "time") or routine.command.get(key) == value
        for key, value in command.items()
    )
