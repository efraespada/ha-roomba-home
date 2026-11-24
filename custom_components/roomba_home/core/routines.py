"""Project the account's saved cleaning routines onto one associated robot."""

import re
from dataclasses import dataclass
from uuid import uuid4

from .cleaning import CleaningMode, CleaningProfile
from .cleaning_protocol import regional_cleaning_parameters, reported_cleaning_mode
from .errors import ProtocolError
from .maps import AreaTarget, command_region_id, map_identifier

FAVORITES_PATH = "/v1/user/favorites"
APP_EDITION = {"app_edition": "1"}
ROUTINE_ID = re.compile(r"[0-9a-fA-F]{32}")
ROUTINE_ITEM_PATH = re.compile(rf"{FAVORITES_PATH}/{ROUTINE_ID.pattern}")


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
        recognized = [
            (identifier, item)
            for item in regions
            if (identifier := command_region_id(map_id, item)) is not None
        ]
        settings = None
        if (
            1 <= len(recognized) == len(regions) <= 32
            and len({identifier for identifier, _ in recognized}) == len(regions)
            and self.command.get("select_all") is False
            and self.command.get("ordered") == 1
            and self.command.keys()
            == {
                "robot_id",
                "command",
                "ordered",
                "select_all",
                "p2map_id",
                "user_p2mapv_id",
                "regions",
            }
        ):
            profiles = [routine_region_profile(item) for _, item in recognized]
            if all(profile is not None for profile in profiles):
                settings = [
                    {"id": identifier, **profile}
                    for (identifier, _), profile in zip(recognized, profiles, strict=True)
                ]
        return {
            "id": self.identity,
            "name": self.name,
            "regions": [identifier for identifier, _ in recognized],
            "region_settings": settings,
            "editable": not self.payload.get("default"),
        }


def routine_region_profile(region: dict) -> dict | None:
    """Project settings that can be written back without dropping provider data."""
    if region.keys() != {"region_id", "type", "params"}:
        return None
    params = region["params"]
    if not isinstance(params, dict):
        return None
    code = params.get("operatingMode")
    mode = CleaningMode.VACUUM_MOP if code == 32 else reported_cleaning_mode(code)
    wetness = params.get("padWetness")
    scrub = params.get("swScrub")
    try:
        profile = CleaningProfile(
            mode=mode,
            suction_level=params.get("suctionLevel"),
            wetness_level=wetness.get("padPlate") if isinstance(wetness, dict) else None,
            two_pass=params.get("twoPass"),
            smart_scrub=bool(scrub) if type(scrub) is int and scrub in (0, 1) else None,
            carpet_boost=params.get("carpetBoost"),
        )
    except ValueError:
        return None
    if regional_cleaning_parameters(profile) != params or any(
        (level or 0) > 99 for level in (profile.suction_level, profile.wetness_level)
    ):
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


def routine_command(robot_id: str, target: AreaTarget) -> dict:
    if not isinstance(target, AreaTarget) or not target.regions or not target.profiles:
        raise ValueError("Select areas with cleaning profiles on one current map.")
    return {
        "robot_id": robot_id,
        "command": "start",
        "ordered": 1,
        "select_all": False,
        "p2map_id": target.map_id,
        "user_p2mapv_id": target.version_id,
        "regions": [
            {
                "region_id": area.region_id,
                "type": area.kind.value,
                "params": regional_cleaning_parameters(profile),
            }
            for area, profile in zip(target.regions, target.profiles, strict=True)
        ],
    }


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


def routine_matches(routine: CleaningRoutine, name: str, command: dict) -> bool:
    return routine.name == name and all(
        routine.command.get(key) == value for key, value in command.items()
    )
