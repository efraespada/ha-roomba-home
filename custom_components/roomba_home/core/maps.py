"""Read the app's persistent map and region metadata without exposing raw geometry."""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from math import tau

from .area_preferences import AreaDefaults, read_area_defaults
from .cleaning import CleaningProfile
from .errors import ProtocolError
from .telemetry import convert

_IDENTIFIER = re.compile(r"[A-Za-z0-9_.-]{1,128}")
SAVED_ZONE_IDS = tuple(str(identifier) for identifier in range(100, 140))


class RegionKind(StrEnum):
    ROOM = "rid"
    ZONE = "zid"
    FURNITURE = "furniture"


@dataclass(frozen=True, repr=False)
class CleaningRegion:
    region_id: str
    kind: RegionKind
    name: str | None
    remembered: AreaDefaults | None = field(default=None, compare=False, kw_only=True)

    def segment_id(self, map_id: str) -> str:
        return f"{map_id}:{self.kind.value}:{self.region_id}"


@dataclass(frozen=True, repr=False)
class FurnitureRegion(CleaningRegion):
    outline: tuple[tuple[float, float], ...]


@dataclass(frozen=True, repr=False)
class PersistentMap:
    map_id: str
    version_id: str
    name: str | None
    regions: tuple[CleaningRegion, ...]
    orientation: float | None = None
    created_at: datetime | None = field(default=None, compare=False, kw_only=True)
    revision_updated_at: datetime | None = field(default=None, compare=False, kw_only=True)

    @property
    def geometry_key(self) -> tuple[str, str, tuple[CleaningRegion, ...]]:
        return self.map_id, self.version_id, self.regions

    @property
    def inventory_id(self) -> str:
        return _region_digest(self.regions)

    @property
    def selection_id(self) -> str:
        return _region_digest(
            sorted(self.regions, key=lambda region: (region.kind, region.region_id))
        )

    @property
    def settings_id(self) -> str:
        return sha256(json.dumps((self.name, self.orientation)).encode()).hexdigest()


@dataclass(frozen=True, repr=False)
class AreaTarget:
    map_id: str
    version_id: str
    regions: tuple[CleaningRegion, ...]
    profiles: tuple[CleaningProfile, ...] = ()
    ordered: bool = True


def _region_digest(regions: Iterable[CleaningRegion]) -> str:
    content = [(region.region_id, region.kind, region.name) for region in regions]
    return sha256(json.dumps(content).encode()).hexdigest()


def map_identifier(value: object) -> bool:
    return (
        isinstance(value, str)
        and value not in {".", ".."}
        and _IDENTIFIER.fullmatch(value) is not None
    )


def command_region_id(map_id: str, region: object) -> str | None:
    if (
        isinstance(region, dict)
        and region.get("type") in ("rid", "zid")
        and map_identifier(region.get("region_id"))
    ):
        return f"{map_id}:{region['type']}:{region['region_id']}"
    return None


def _name(value: object) -> str | None:
    if isinstance(value, str) and value.strip() and value.isprintable() and len(value) <= 100:
        return value
    return None


def _read_orientation(value: object) -> float | None:
    if type(value) in (int, float) and -tau <= value <= tau:
        return float(value)
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
        # A newly mapped floor is visible before Roomba publishes its room inventory.
        raw_regions = item.get("rooms_metadata", [])
        if not isinstance(raw_regions, list):
            raise ProtocolError("Active map has invalid region metadata")
        regions = {}
        for raw in raw_regions:
            if not isinstance(raw, dict):
                continue
            region_id, metadata = raw.get("room_id"), raw.get("room_metadata")
            if not map_identifier(region_id) or not isinstance(metadata, dict):
                continue
            if metadata.get("region_type") not in (RegionKind.ROOM, RegionKind.ZONE):
                continue
            kind = RegionKind(metadata["region_type"])
            key = (kind, region_id)
            if key in regions:
                raise ProtocolError("An active map contains duplicate region identifiers")
            regions[key] = CleaningRegion(
                region_id,
                kind,
                _name(metadata.get("name")),
                remembered=read_area_defaults(metadata),
            )
        if identifier in maps:
            raise ProtocolError("The map list contains duplicate active map identifiers")
        maps[identifier] = PersistentMap(
            identifier,
            version,
            _name(item.get("name")),
            tuple(regions.values()),
            _read_orientation(item.get("user_orientation_rad")),
            created_at=convert("timestamp", item.get("create_time")),
            revision_updated_at=convert("timestamp", item.get("last_p2mapv_ts")),
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
