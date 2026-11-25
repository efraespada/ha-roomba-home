"""A local snapshot keeps the verified native floor archive and its settings."""

import base64
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.roomba_home.core import map_snapshots
from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.map_snapshots import (
    capture_snapshot,
    read_snapshot,
    with_backup_programs,
)
from custom_components.roomba_home.core.maps import CleaningRegion, PersistentMap, RegionKind

FLOOR = PersistentMap(
    "map-a",
    "version.42",
    "Ático",
    (
        CleaningRegion("room-a", RegionKind.ROOM, "Oficina"),
        CleaningRegion("zone-a", RegionKind.ZONE, "Alfombra"),
    ),
    0.5,
)
CAPTURED = datetime(2026, 11, 25, 21, tzinfo=UTC)


def test_backup_preserves_floor_settings_and_archive_bytes(make_point_bundle):
    raw = make_point_bundle()
    first, _ = capture_snapshot(FLOOR, raw, CAPTURED)
    reorder = replace(FLOOR, regions=tuple(reversed(FLOOR.regions)))
    second, _ = capture_snapshot(reorder, raw, CAPTURED + timedelta(seconds=5))
    assert first["id"] == second["id"] and first["captured_at"] != second["captured_at"]
    renamed, _ = capture_snapshot(replace(FLOOR, name="Renamed"), raw, CAPTURED)
    assert renamed["id"] != first["id"]
    rebuilt, plan = read_snapshot(first)
    assert rebuilt == FLOOR and plan.rooms[0].name == "Oficina"
    assert plan.keep_out and base64.b64decode(first["archive"]) == raw


@pytest.mark.parametrize("archive", [None, b"", b"corrupt", b"x" * 100])
def test_capture_rejects_unverified_bytes(make_point_bundle, monkeypatch, archive):
    monkeypatch.setattr(map_snapshots, "MAX_MAP_BYTES", 20)
    with pytest.raises(ProtocolError):
        capture_snapshot(FLOOR, archive, CAPTURED)


@pytest.mark.parametrize("corruption", ["data", "size", "digest", "missing", "scope"])
def test_preview_rejects_a_damaged_or_mismatched_backup(make_point_bundle, monkeypatch, corruption):
    raw = make_point_bundle()
    record, _ = capture_snapshot(FLOOR, raw, CAPTURED)
    if corruption == "data":
        record["archive"] = "%%%"
    elif corruption == "size":
        monkeypatch.setattr(map_snapshots, "MAX_ENCODED_SIZE", 3)
    elif corruption == "digest":
        record["floor"]["name"] = "Changed"
    elif corruption == "missing":
        del record["floor"]
    else:
        record["floor"]["map_id"] = ".."
        record["id"] = map_snapshots._identity(record["floor"], raw)
    with pytest.raises(ProtocolError, match="damaged"):
        read_snapshot(record)


def test_history_counts_and_byte_budget_keep_recent_and_pinned_entries(monkeypatch):
    monkeypatch.setattr(map_snapshots, "MAX_HISTORY_SIZE", 50)
    pinned = {"id": "pin", "pinned": True, "archive": "x" * 15}
    newer = {"id": "second", "pinned": False, "archive": "x" * 20}
    older = {"id": "first", "pinned": False, "archive": "x" * 20}
    records = [newer, older, pinned]
    assert map_snapshots.retained_snapshots(records, 5) == [newer, pinned]
    assert map_snapshots.retained_snapshots(records, 1) == [newer, pinned]


def test_program_contents_participate_in_the_backup_digest(make_point_bundle):
    raw = make_point_bundle()
    original, _ = capture_snapshot(FLOOR, raw, CAPTURED)
    backup = with_backup_programs(original, raw, {"items": [], "unchecked": ["schedule"]})
    assert original["id"] != backup["id"] and read_snapshot(backup)[0] == FLOOR
    backup["programs"]["unchecked"].clear()
    with pytest.raises(ProtocolError, match="damaged"):
        read_snapshot(backup)
    assert read_snapshot(original)[0] == FLOOR
