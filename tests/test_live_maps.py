"""Synthetic native position batches and associated map archives."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.roomba_home.core.cleaning import CleaningMode
from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.live_maps import (
    MissionPath,
    mission_timeline,
    position_batch,
    resolve_live_floor,
)
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
POINT_COMMAND = {
    "command": "point_clean",
    "p2map_id": MAP.map_id,
    "user_p2mapv_id": MAP.version_id,
    "geom": {"center": [5.0, 2.0]},
    "params": {"operatingMode": 4},
}


def test_live_point_retains_exact_target_and_reported_mode():
    raw = {"timelineRequestId": 12, "nMssn": 8, "event": [], "cmd": POINT_COMMAND}
    point = mission_timeline(raw, 12, 8, NOW).point
    assert point.mode is CleaningMode.MOP
    assert (point.target.map_id, point.target.version_id) == (MAP.map_id, MAP.version_id)
    assert point.target.center == (5.0, 2.0)


def test_live_floor_can_use_a_whole_floor_request_without_a_directed_plan():
    raw = {
        "timelineRequestId": 12,
        "nMssn": 8,
        "event": [],
        "cmd": POINT_COMMAND | {"command": "start", "select_all": True},
    }
    other = PersistentMap("map-b", "version.b", "Upper floor", ())
    scope = MAP.map_id, MAP.version_id
    report = mission_timeline(raw, 12, 8, NOW)
    assert report.plan is None
    assert report.requested_floor == scope
    assert resolve_live_floor((other, MAP), report, None) is MAP
    assert resolve_live_floor((other, MAP), None, None) is None
    assert resolve_live_floor((other,), None, None) is other
    assert resolve_live_floor((other,), report, None) is None


def test_confirmed_relocation_identifies_the_floor_even_with_an_internal_revision():
    other = PersistentMap("map-b", "version.b", "Upper floor", ())
    confirmed = {
        "p2mapId": MAP.map_id,
        "p2mapvId": "robot-version",
        "confp2mapId": MAP.map_id,
        "confp2mapvId": "robot-version",
    }
    before = {"type": "reloc", "ts": NOW - 2, "reloc": {}}
    event = {"type": "reloc", "ts": NOW - 1, "reloc": confirmed}
    raw = {"timelineRequestId": 12, "nMssn": 8, "event": [before], "finEvents": [event]}
    report = mission_timeline(raw, 12, 8, NOW)
    assert report.localized_maps == {MAP.map_id}
    assert resolve_live_floor((other, MAP), report, None) is MAP
    scope = MAP.map_id, MAP.version_id
    assert resolve_live_floor((other, MAP), None, scope) is MAP
    newer = PersistentMap(MAP.map_id, "new-version", MAP.name, MAP.regions)
    assert resolve_live_floor((other, newer), report, scope) is None

    contradicts_request = mission_timeline(
        raw
        | {"cmd": POINT_COMMAND | {"p2map_id": other.map_id, "user_p2mapv_id": other.version_id}},
        12,
        8,
        NOW,
    )
    assert resolve_live_floor((other, MAP), contradicts_request, None) is None
    contradicts_pin = mission_timeline(
        raw
        | {
            "finEvents": [
                event
                | {"reloc": confirmed | {"p2mapId": other.map_id, "confp2mapId": other.map_id}}
            ]
        },
        12,
        8,
        NOW,
    )
    assert resolve_live_floor((other, MAP), contradicts_pin, scope) is None
    tentative = mission_timeline(
        raw | {"finEvents": [event | {"reloc": confirmed | {"p2mapId": other.map_id}}]},
        12,
        8,
        NOW,
    )
    assert resolve_live_floor((other, MAP), tentative, None) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"command": "start"},
        {"geom": []},
        {"geom": {}},
        {"geom": {"center": [5]}},
        {"geom": {"center": [True, 2]}},
        {"params": []},
        {"params": {"operatingMode": 3}},
        {"p2map_id": ".."},
    ],
)
def test_malformed_or_unrecognized_live_point_is_omitted(changes):
    raw = {
        "timelineRequestId": 12,
        "nMssn": 8,
        "event": [],
        "cmd": POINT_COMMAND | changes,
    }
    assert mission_timeline(raw, 12, 8, NOW).point is None


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


def test_position_scope_retains_small_provider_clock_skew_and_expires_at_the_deadline():
    now = datetime.fromtimestamp(NOW, UTC)
    stamp = NOW + 1
    batch = position_batch(
        FRAME | {"timestamp": stamp, "pos_update": {"cur_path": [35, 4.2, 6, 1.3, 6, stamp]}},
        NOW,
    )
    assert batch.belongs_to(now - timedelta(seconds=15), now)
    assert not batch.belongs_to(now + timedelta(seconds=2), now)
    assert not batch.belongs_to(now, now - timedelta(seconds=5))
    assert not batch.belongs_to(now, now + timedelta(seconds=20))


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


def test_floor_display_layers_ignore_degenerate_segments_and_unknown_features(
    make_point_bundle, map_display_layers
):
    def update(documents):
        map_display_layers(documents)
        (wall,) = documents["floorPlan.geojson"]["features"]
        walls = documents["floorPlan.geojson"]["features"]
        lines = wall["geometry"]["coordinates"]
        lines.extend(([[5, 5]], [[4, 4], [4, 4]]))
        walls.extend(
            (
                wall | {"properties": {"type": "door"}},
                wall | {"properties": {"type": "unknown"}},
                wall | {"geometry": {"type": "Polygon"}},
            )
        )
        (carpet,) = documents["floorTypes.geojson"]["features"]
        documents["floorTypes.geojson"]["features"].append(carpet | {"properties": {}})
        (dock,) = documents["dockPoses.geojson"]["features"]
        documents["dockPoses.geojson"]["features"].append(dock | {"geometry": {"type": "Polygon"}})
        documents["manifest.json"]["experimentalFeatures"] = [
            documents["manifest.json"]["features"].pop()
        ]

    plan = read_floor_plan(make_point_bundle(mutate=update), MAP)
    assert plan.walls == (("exterior", ((0, 0), (10, 0))), ("door", ((0, 0), (10, 0))))
    assert plan.carpets == ((((4, 0), (6, 0), (6, 2), (4, 0)),),)
    assert plan.docks == ((8, 1),)


@pytest.mark.parametrize("problem", ["missing", "duplicate", "malformed"])
def test_optional_wall_layer_failure_preserves_the_plan_and_other_layers(
    problem, make_point_bundle, map_display_layers
):
    def update(documents):
        map_display_layers(documents)
        if problem == "missing":
            del documents["floorPlan.geojson"]
        elif problem == "duplicate":
            layers = documents["manifest.json"]["features"]
            layers.append(next(layer for layer in layers if layer["type"] == "floorPlan"))
        else:
            documents["floorPlan.geojson"]["features"][0]["geometry"]["coordinates"] = [[None]]

    plan = read_floor_plan(make_point_bundle(mutate=update), MAP)
    assert plan.walls == ()
    assert plan.room_at((3, 5)) == "Office"
    assert plan.carpets and plan.docks


def test_timeline_requires_current_mission_and_matching_request():
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
            {
                "type": "zone",
                "ts": 230,
                "zone": {
                    "p2mapId": "fixture-map",
                    "p2mapvId": "fixture-revision",
                    "zid": "160",
                    "area": 5,
                    "totalArea": 8,
                    "passCount": 0,
                },
            },
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
    assert result.stage_started_at.timestamp() == 240
    assert mission_timeline(raw, 12, 8, 239).stage_started_at is None
    (reading,) = result.active_rooms
    assert (reading.area, reading.pass_count, reading.status) == (6, 1, None)
    (zone,) = result.active_zones
    assert (zone.kind, zone.area, zone.total_area, zone.pass_count) == ("zone", 5, 8, 0)
    assert result.observed_at.timestamp() == 241
    assert result.skip_observation().destination.identity == reading.identity
    assert not result.skip_observation().skipped
    for malformed in (
        [],
        {"nMssn": 8},
        raw | {"event": {}},
        raw | {"nMssn": 7},
        raw | {"timelineRequestId": 13},
    ):
        assert mission_timeline(malformed, 12, 8, 241) is None
    assert mission_timeline(raw | {"event": []}, 12, 8, 241).stage is None

    furniture = raw | {
        "cmd": {
            "command": "start",
            "p2map_id": "fixture-map",
            "user_p2mapv_id": "requested-revision",
            "regions": [{"type": "tid", "region_id": "160"}],
            "id_multipolys": [
                {
                    "id": "160",
                    "metadata": {"furniture_id": "chair"},
                    "poly": [[0, 0], [0, 1], [1, 1], [1, 0]],
                }
            ],
        }
    }
    (target,) = mission_timeline(furniture, 12, 8, 241).active_zones
    assert target.identity == ("fixture-map", "requested-revision", "chair")
    assert target.kind == "furniture"


@pytest.mark.parametrize(
    ("travel", "kind", "identifier"),
    [
        ({"dest": "room", "rid": "room-a"}, "room", "room-a"),
        ({"dest": "zone", "zid": "160"}, "furniture", "sofa"),
        ({"dest": "zone", "zid": []}, None, None),
        ({"dest": "dock", "reason": 1}, None, None),
        (None, None, None),
    ],
)
def test_skip_observes_identified_travel_destinations_and_finished_skip_events(
    travel, kind, identifier
):
    scope = {"p2mapId": "fixture-map", "p2mapvId": "device-revision"}
    raw = {
        "nMssn": 8,
        "timelineRequestId": 12,
        "cmd": {
            "command": "start",
            "p2map_id": "fixture-map",
            "user_p2mapv_id": "fixture-revision",
            "regions": [{"type": "tid", "region_id": "160"}],
            "id_multipolys": [
                {
                    "id": "160",
                    "metadata": {"furniture_id": "sofa"},
                    "poly": [[0, 0], [1, 0], [1, 1], [0, 1]],
                }
            ],
        },
        "event": [{"type": "travel", "ts": 250, "travel": scope | travel if travel else None}],
        "finEvents": [
            {"type": "room", "ts": 200, "room": scope | {"rid": "third", "status": 8}},
            {"type": "room", "ts": 210, "room": scope | {"rid": "second", "status": 7}},
            {"type": "room", "ts": 220, "room": scope | {"rid": "first", "status": 3}},
        ],
    }
    result = mission_timeline(raw, 12, 8, 251).skip_observation()
    assert result.directed
    assert {area.identity[-1] for area in result.skipped} == {"first", "second"}
    if kind is None:
        assert result.destination is None
    else:
        assert result.destination.kind == kind
        assert result.destination.identity[-1] == identifier
    assert not mission_timeline(raw | {"cmd": {"regions": []}}, 12, 8, 251).directed
