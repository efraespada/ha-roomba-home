"""Project the observed per-room duration estimates for supported profiles."""

from .cleaning import CleaningCapabilities, CleaningMode
from .errors import ProtocolError
from .maps import AreaTarget, RegionKind

# The estimate model uses mode 32 for simultaneous cleaning.
ESTIMATE_MODES = {
    2: CleaningMode.VACUUM,
    4: CleaningMode.MOP,
    32: CleaningMode.VACUUM_MOP,
    512: CleaningMode.VACUUM_THEN_MOP,
}
PROFILE_KEYS = {"operatingMode", "suctionLevel", "swScrub", "twoPass"}
ESTIMATE_FIELDS = ("suction_level", "smart_scrub", "two_pass")


def _estimate(entry, capabilities: CleaningCapabilities) -> dict | None:
    if not isinstance(entry, dict) or entry.get("unit") != "seconds":
        return None
    seconds, params = entry.get("value"), entry.get("params")
    if type(seconds) is not int or seconds < 0 or not isinstance(params, dict):
        return None
    if params.keys() - PROFILE_KEYS:
        return None
    mode_code = params.get("operatingMode")
    mode = ESTIMATE_MODES.get(mode_code) if type(mode_code) is int else None
    if mode is None or mode not in (capabilities.modes or ()):
        return None
    two_pass = params.get("twoPass")
    if type(two_pass) is not bool or (two_pass and capabilities.two_pass is not True):
        return None
    result = {"mode": mode.value, "duration_seconds": seconds, "two_pass": two_pass}
    if mode.vacuums:
        suction = params.get("suctionLevel")
        if type(suction) is not int or not 1 <= suction <= (capabilities.suction_levels or 0):
            return None
        result["suction_level"] = suction
    elif "suctionLevel" in params:
        return None
    if mode.mops:
        scrub = params.get("swScrub")
        if type(scrub) is not int or scrub not in (0, 1):
            return None
        if scrub and capabilities.smart_scrub is not True:
            return None
        result["smart_scrub"] = bool(scrub)
    elif "swScrub" in params:
        return None
    return result


def parse_time_estimates(
    document: object, robot_id: str, target: AreaTarget, capabilities: CleaningCapabilities
) -> dict:
    """Bind estimates to known rooms and only return typed, supported options."""
    if (
        not isinstance(document, dict)
        or document.get("api_version") != "v1"
        or document.get("robot_id") != robot_id
        or not isinstance(document.get("smart_maps"), list)
    ):
        raise ProtocolError("Invalid Roomba Home time estimates response")
    matches = [
        item
        for item in document["smart_maps"]
        if isinstance(item, dict) and item.get("smart_map_id") == target.map_id
    ]
    if len(matches) > 1 or (matches and not isinstance(matches[0].get("areas"), list)):
        raise ProtocolError("Invalid Roomba Home time estimates map")
    areas = matches[0]["areas"] if matches else []
    by_region = {}
    for area in areas:
        if (
            isinstance(area, dict)
            and area.get("area_type") == "region"
            and isinstance(room := area.get("area_id"), str)
            and isinstance(rows := area.get("estimates"), list)
        ):
            key = (RegionKind.ROOM, room)
            if key in by_region:
                raise ProtocolError("Duplicated room in Roomba Home time estimates")
            by_region[key] = rows
    return {
        "regions": [
            {
                "id": region.segment_id(target.map_id),
                "estimates": [
                    estimate
                    for entry in by_region.get((region.kind, region.region_id), ())
                    if (estimate := _estimate(entry, capabilities)) is not None
                ],
            }
            for region in target.regions
        ]
    }


def routine_time_estimate(target: AreaTarget, matrix: dict, defaults: dict) -> dict:
    """Combine unambiguous provider values for an ordered draft; keep gaps explicit."""
    rows_by_area = {area["id"]: area["estimates"] for area in matrix["regions"]}
    areas = []
    for region, profile in zip(target.regions, target.profiles, strict=True):
        identifier = region.segment_id(target.map_id)
        requested = {}
        for field in ESTIMATE_FIELDS:
            value = getattr(profile, field)
            requested[field] = defaults.get(field) if value is None else value
        matching_seconds = {
            row["duration_seconds"]
            for row in rows_by_area.get(identifier, ())
            if row["mode"] == profile.mode
            and all(
                row[field] == requested[field]
                for field in ESTIMATE_FIELDS
                if field in row and requested[field] is not None
            )
        }
        seconds = next(iter(matching_seconds)) if len(matching_seconds) == 1 else None
        areas.append(
            {"id": identifier, "duration_seconds": seconds, "ambiguous": len(matching_seconds) > 1}
        )
    available = [area["duration_seconds"] for area in areas if area["duration_seconds"] is not None]
    complete = len(available) == len(areas)
    return {
        "map_id": target.map_id,
        "version": target.version_id,
        "duration_seconds": sum(available) if complete else None,
        "partial_duration_seconds": sum(available) if available and not complete else None,
        "areas": areas,
    }
