"""Synthetic native position batches and associated map archives."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.live_maps import MissionPath, position_batch
from custom_components.roomba_home.core.maps import CleaningRegion, PersistentMap, RegionKind
from custom_components.roomba_home.core.point_maps import read_floor_plan

NOW = 1_700_000_000
FRAME = {
    "timestamp": NOW,
    "update_expire_ts": NOW + 20,
    "pos_update": {"cur_path": [30, 4.2, 6.0, 1.3, 2, 3, 5, 1.2, 2, NOW]},
}
MAP = PersistentMap(
    "map-a", "version.42", "Example map", (CleaningRegion("room-a", RegionKind.ROOM, "Office"),)
)


def test_position_batches_preserve_indices_and_ignore_old_latest_frame():
    batch = position_batch(FRAME, NOW)
    latest = position_batch(
        {
            "timestamp": NOW + 1,
            "update_expire_ts": NOW + 20,
            "pos_update": {"cur_path": [34, 3, 4, 0, 2, NOW + 1]},
        },
        NOW + 1,
    )
    assert batch.positions[-1].x == 3
    assert batch.positions[-1].modes == 2
    path = MissionPath(("map-a", "version.42"), datetime.fromtimestamp(NOW - 30, UTC), latest, ())
    path = path.append(latest).append(batch).append(batch)
    assert path.latest == latest
    assert [index for index, _ in path.points] == [30, 31, 34]


@pytest.mark.parametrize(
    "update",
    [
        lambda value: {"map_update": {"livemap_url_raw": "https://example.test/"}},
        lambda value: value | {"update_expire_ts": NOW},
        lambda value: value | {"timestamp": NOW + 6},
        lambda value: value | {"timestamp": 0},
        lambda value: value | {"update_expire_ts": None},
        lambda value: value | {"pos_update": {"cur_path": []}},
        lambda value: value | {"pos_update": {"cur_path": [1, 1, 2, 0, 1, 2, NOW]}},
        lambda value: value | {"pos_update": {"cur_path": [False, 1, 2, 0, 1, NOW]}},
        lambda value: value | {"pos_update": {"cur_path": [1, 1, 2, 0, 1, NOW + 2]}},
        lambda value: value | {"pos_update": {"cur_path": [1, float("inf"), 2, 0, 1, NOW]}},
        lambda value: value | {"pos_update": {"cur_path": [1, 1, 2, "0", 1, NOW]}},
        lambda value: value | {"pos_update": {"cur_path": [1, 1, 2, float("nan"), 1, NOW]}},
        lambda value: value | {"pos_update": {"cur_path": [1, 1, 2, 0, False, NOW]}},
    ],
)
def test_invalid_or_expired_position_updates_are_ignored(update):
    assert position_batch(update(FRAME), NOW) is None


def test_room_requires_a_unique_containing_polygon(make_point_bundle):
    floor = read_floor_plan(make_point_bundle(), MAP)
    assert floor.room_at((3, 5)) == "Office"
    assert floor.room_at((1.5, 7.5)) is None  # Hole.
    assert floor.room_at((0, 5)) is None  # Boundary.
    assert floor.room_at((30, 5)) is None

    def duplicate_room(documents):
        features = documents["rooms.geojson"]["features"]
        features.append({**deepcopy(features[0]), "id": "room-b"})

    second = read_floor_plan(make_point_bundle(mutate=duplicate_room), MAP)
    assert second.room_at((3, 5)) is None


@pytest.mark.parametrize("mutation", ["duplicate", "empty", "missing"])
def test_invalid_floor_plan_geometry_is_not_rendered(mutation, make_point_bundle):
    def update(documents):
        features = documents["rooms.geojson"]["features"]
        if mutation == "duplicate":
            features.append(deepcopy(features[0]))
        elif mutation == "empty":
            features.clear()
        else:
            documents["manifest.json"]["features"].pop(0)

    with pytest.raises(ProtocolError):
        read_floor_plan(make_point_bundle(mutate=update), MAP)


def test_timeline_requires_current_mission_and_matching_request():
    from custom_components.roomba_home.core.live_maps import mission_timeline

    raw = {
        "mission_id": "private-session",
        "nMssn": 8,
        "timelineRequestId": 12,
        "event": [
            {"type": "pause", "ts": 203},
            {
                "type": "room",
                "ts": 240,
                "room": {
                    "p2mapId": "fixture-map",
                    "p2mapvId": "fixture-revision",
                    "rid": "fixture-room",
                    "area": 6,
                    "passCount": 1,
                },
            },
            {"type": "future-code", "ts": 250},
            {"type": "pause", "ts": None},
            {"type": [], "ts": 260},
        ],
        "finEvents": [
            {
                "type": "room",
                "ts": 202,
                "room": {
                    "p2mapId": "fixture-map",
                    "p2mapvId": "fixture-revision",
                    "rid": "fixture-room",
                    "status": 0,
                },
            }
        ],
        "futureEvents": [{"type": "fin", "ts": 1000}],
    }
    result = mission_timeline(raw, 12, 8, 241)
    assert result.stage == "room" and result.rooms[0].status == 0
    (reading,) = result.active_rooms
    assert (reading.area, reading.pass_count, reading.status) == (6, 1, None)
    assert result.observed_at.timestamp() == 241
    for malformed in (
        [],
        {"nMssn": 8},
        raw | {"event": {}},
        raw | {"nMssn": 7},
        raw | {"timelineRequestId": 13},
    ):
        assert mission_timeline(malformed, 12, 8, 241) is None
    assert mission_timeline(raw | {"event": []}, 12, 8, 241).stage is None
