"""Read the app's persistent map and region metadata without exposing raw geometry."""

import re
from dataclasses import dataclass
from enum import StrEnum

from .cleaning import CleaningProfile
from .errors import ProtocolError

_IDENTIFIER = re.compile(r"[A-Za-z0-9_.-]{1,128}")


class RegionKind(StrEnum):
    ROOM = "rid"
    ZONE = "zid"


@dataclass(frozen=True, repr=False)
class CleaningRegion:
    region_id: str
    kind: RegionKind
    name: str | None

    def segment_id(self, map_id: str) -> str:
        return f"{map_id}:{self.kind.value}:{self.region_id}"


@dataclass(frozen=True, repr=False)
class PersistentMap:
    map_id: str
    version_id: str
    name: str | None
    regions: tuple[CleaningRegion, ...]


@dataclass(frozen=True, repr=False)
class AreaTarget:
    map_id: str
    version_id: str
    regions: tuple[CleaningRegion, ...]
    profiles: tuple[CleaningProfile, ...] = ()


def map_identifier(value: object) -> bool:
    return (
        isinstance(value, str)
        and value not in {".", ".."}
        and _IDENTIFIER.fullmatch(value) is not None
    )


def _name(value: object) -> str | None:
    if isinstance(value, str) and value.strip() and value.isprintable() and len(value) <= 100:
        return value
    return None


def parse_maps(response: object, robot_id: str) -> tuple[PersistentMap, ...]:
    """Accept only current, visible maps associated with the requested robot."""
    if not isinstance(response, list):
        raise ProtocolError("Expected the Roomba Home map list")
    maps = {}
    for item in response:
        if (
            not isinstance(item, dict)
            or item.get("robot_id") != robot_id
            or item.get("state") != "active"
            or item.get("visible") is not True
        ):
            continue
        identifier, version = item.get("p2map_id"), item.get("active_p2mapv_id")
        if not map_identifier(identifier) or not map_identifier(version):
            raise ProtocolError("Active map is missing a valid identifier or version")
        raw_regions = item.get("rooms_metadata")
        if not isinstance(raw_regions, list):
            raise ProtocolError("Active map is missing region metadata")
        regions = {}
        for raw in raw_regions:
            if not isinstance(raw, dict):
                continue
            region_id, metadata = raw.get("room_id"), raw.get("room_metadata")
            if not map_identifier(region_id) or not isinstance(metadata, dict):
                continue
            try:
                kind = RegionKind(metadata.get("region_type"))
            except ValueError:
                continue
            key = (kind, region_id)
            if key in regions:
                raise ProtocolError("An active map contains duplicate region identifiers")
            regions[key] = CleaningRegion(region_id, kind, _name(metadata.get("name")))
        if identifier in maps:
            raise ProtocolError("The map list contains duplicate active map identifiers")
        maps[identifier] = PersistentMap(
            identifier, version, _name(item.get("name")), tuple(regions.values())
        )
    return tuple(maps.values())


def resolve_segments(maps: tuple[PersistentMap, ...], segment_ids: list[str]) -> AreaTarget:
    """Resolve local HA segments only against a freshly read, associated map."""
    if (
        not isinstance(segment_ids, list)
        or not 1 <= len(segment_ids) <= 32
        or not all(isinstance(value, str) for value in segment_ids)
        or len(segment_ids) != len(set(segment_ids))
    ):
        raise ValueError("Select one or more distinct cleaning areas")
    for item in maps:
        segments = {region.segment_id(item.map_id): region for region in item.regions}
        if all(value in segments for value in segment_ids):
            return AreaTarget(item.map_id, item.version_id, tuple(segments[v] for v in segment_ids))
    raise ValueError("Selected areas are not all on one current map")
