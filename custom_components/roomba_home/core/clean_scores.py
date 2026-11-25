"""Project Roomba's cleaning scores for an exact active map revision."""

from .errors import ProtocolError
from .maps import PersistentMap, RegionKind
from .routines import routine_region_profile
from .telemetry import convert, number

TRAFFIC_CLASSES = ("low", "normal", "high")


def _timestamp(value):
    stamp = convert("timestamp", value)
    return stamp.isoformat() if stamp is not None else None


def _recorded_start(value):
    return _timestamp(value.get("startTime")) if isinstance(value, dict) else None


def read_clean_scores(document: object, floor: PersistentMap) -> dict:
    if not isinstance(document, dict) or not isinstance(rows := document.get("clean_scores"), list):
        raise ProtocolError("Expected Roomba's cleaning scores.")
    matches = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("p2map_id") == floor.map_id
        and row.get("active_p2mapv_id") == floor.version_id
    ]
    if len(matches) > 1:
        raise ProtocolError("Roomba returned multiple cleaning scores for the same revision.")
    result = {
        "map": {"id": floor.map_id, "version": floor.version_id, "name": floor.name},
        "ranges": (),
        "last_processed_mission_started_at": None,
        "rooms": [],
    }
    if not matches or matches[0].get("error") is not None:
        return result
    row = matches[0]
    if not isinstance(regions := row.get("regions"), list):
        raise ProtocolError("Expected room cleaning scores.")
    ranges = document.get("clean_score_ranges")
    if isinstance(ranges, list):
        result["ranges"] = tuple(value for value in ranges if number(value) is not None)
    result["last_processed_mission_started_at"] = _recorded_start(row.get("mission_last_processed"))
    rooms = {region.region_id: region for region in floor.regions if region.kind is RegionKind.ROOM}
    seen = set()
    for item in regions:
        if not isinstance(item, dict) or not isinstance(identifier := item.get("region_id"), str):
            continue
        if (room := rooms.get(identifier)) is None:
            continue
        if identifier in seen:
            raise ProtocolError("Roomba returned duplicate cleaning scores for one room.")
        seen.add(identifier)
        traffic = item.get("high_traffic_enum")
        result["rooms"].append(
            {
                "id": room.segment_id(floor.map_id),
                "name": room.name,
                "score": number(item.get("clean_score")),
                "traffic": traffic if traffic in TRAFFIC_CLASSES else None,
                "score_updated_at": _timestamp(item.get("updated_ts")),
                "last_cleaned_mission_started_at": _recorded_start(
                    item.get("mission_last_cleaned")
                ),
                "last_unfinished_mission_started_at": _recorded_start(
                    item.get("mission_last_unfinished")
                ),
                "preferences": routine_region_profile(
                    {
                        "region_id": identifier,
                        "type": "rid",
                        "params": item.get("smart_clean_prefs"),
                    }
                ),
            }
        )
    return result
