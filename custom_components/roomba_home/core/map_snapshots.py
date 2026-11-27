"""Build, verify, and retain local backups of associated Roomba floor plans."""

import base64
import json
import re
from datetime import datetime
from hashlib import sha256

from .errors import ProtocolError
from .maps import CleaningRegion, PersistentMap, RegionKind, map_identifier
from .point_maps import MAX_MAP_BYTES, FloorPlan, read_floor_plan

SNAPSHOT_ID = re.compile(r"[0-9a-f]{64}")
DEFAULT_RETENTION = 5
MAX_SNAPSHOTS = 20
MAX_ENCODED_SIZE = 4 * ((MAX_MAP_BYTES + 2) // 3)
MAX_HISTORY_SIZE = 2 * MAX_ENCODED_SIZE


def _floor_document(floor: PersistentMap) -> dict:
    return {
        "map_id": floor.map_id,
        "version": floor.version_id,
        "name": floor.name,
        "orientation": floor.orientation,
        "regions": [
            [region.kind.value, region.region_id, region.name]
            for region in sorted(floor.regions, key=lambda region: (region.kind, region.region_id))
        ],
    }


def _identity(floor: dict, archive: bytes, programs: dict | None = None) -> str:
    metadata = floor if programs is None else {"floor": floor, "programs": programs}
    encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
    return sha256(sha256(archive).digest() + encoded).hexdigest()


def capture_snapshot(floor: PersistentMap, archive: bytes, now: datetime) -> tuple[dict, FloorPlan]:
    if not isinstance(archive, bytes) or not 0 < len(archive) <= MAX_MAP_BYTES:
        raise ProtocolError("The floor archive is outside the supported size.")
    plan = read_floor_plan(archive, floor)
    metadata = _floor_document(floor)
    record = {
        "id": _identity(metadata, archive),
        "captured_at": now.isoformat(),
        "pinned": False,
        "floor": metadata,
        "archive": base64.b64encode(archive).decode("ascii"),
    }
    return record, plan


def with_backup_programs(record: dict, archive: bytes, programs: dict) -> dict:
    return {
        **record,
        "programs": programs,
        "id": _identity(record["floor"], archive, programs),
    }


def snapshot_summary(snapshot: dict) -> dict:
    floor = snapshot["floor"]
    overview = {
        "id": snapshot["id"],
        "captured_at": snapshot["captured_at"],
        "pinned": snapshot["pinned"],
        "map_id": floor["map_id"],
        "version": floor["version"],
        "name": floor["name"],
        "orientation": floor["orientation"],
    }
    if (programs := snapshot.get("programs")) is not None:
        overview["program_count"] = len(programs["items"])
        overview["programs_unchecked"] = programs["unchecked"]
    return overview


def read_snapshot(snapshot: dict):
    """Recheck the saved bytes and floor revision before viewing or exporting."""
    floor, archive = read_snapshot_archive(snapshot)
    return floor, read_floor_plan(archive, floor)


def read_snapshot_archive(snapshot: dict) -> tuple[PersistentMap, bytes]:
    """Recover the verified metadata and archive bytes for a saved revision."""
    try:
        metadata = snapshot["floor"]
        encoded = snapshot["archive"]
        if not isinstance(encoded, str) or len(encoded) > MAX_ENCODED_SIZE:
            raise ValueError
        archive = base64.b64decode(encoded, validate=True)
        if snapshot["id"] != _identity(metadata, archive, snapshot.get("programs")):
            raise ValueError
        if not all(map_identifier(metadata[key]) for key in ("map_id", "version")):
            raise ValueError
        floor = PersistentMap(
            metadata["map_id"],
            metadata["version"],
            metadata["name"],
            tuple(
                CleaningRegion(identifier, RegionKind(kind), name)
                for kind, identifier, name in metadata["regions"]
            ),
            metadata["orientation"],
        )
    except KeyError, TypeError, ValueError, RecursionError:
        raise ProtocolError("The local floor backup is damaged.") from None
    return floor, archive


def retained_snapshots(snapshots: list[dict], retention: int) -> list[dict]:
    """Keep pinned records and the newest unpinned records within storage limits."""
    keep = [snapshot for snapshot in snapshots if snapshot["pinned"]]
    available = min(retention, MAX_SNAPSHOTS - len(keep))
    size = sum(len(snapshot["archive"]) for snapshot in keep)
    for snapshot in snapshots:
        if snapshot["pinned"]:
            continue
        if available <= 0 or size + len(snapshot["archive"]) > MAX_HISTORY_SIZE:
            break
        keep.append(snapshot)
        available -= 1
        size += len(snapshot["archive"])
    retained = {snapshot["id"] for snapshot in keep}
    return [snapshot for snapshot in snapshots if snapshot["id"] in retained]
