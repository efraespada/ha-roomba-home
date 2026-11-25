"""Synthetic Roomba raw map objects and correlation with the live route."""

import zlib
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.live_maps import MissionPath, Position, PositionBatch
from custom_components.roomba_home.core.live_route import (
    backfill_route,
    decode_raw_route,
    decode_raw_snapshot,
    raw_route_reference,
    reconcile_live_snapshot,
)

NOW = 1_700_000_000
ROBOT = "fixture-robot"


def test_raw_route_reference_keeps_signature_private(make_raw_route_document):
    document = make_raw_route_document(NOW)
    reference = raw_route_reference(document, ROBOT, NOW)
    assert reference.timestamp == NOW
    assert reference.url == document["map_update"]["livemap_url_raw"]
    assert "X-Amz" not in repr(reference)


@pytest.mark.parametrize(
    "change",
    [
        lambda document: [],
        lambda document: document | {"map_update": []},
        lambda document: document | {"timestamp": False},
        lambda document: document | {"timestamp": NOW - 61},
        lambda document: document | {"timestamp": NOW + 6},
        lambda document: document | {"map_update": {"livemap_url_raw": 7}},
    ],
)
def test_requires_current_broker_message(make_raw_route_document, change):
    assert raw_route_reference(change(make_raw_route_document(NOW)), ROBOT, NOW) is None


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("https://", "http://"),
        ("s3.amazonaws.com/", "s3.amazonaws.com:443/"),
        ("s3.amazonaws.com/", "s3.amazonaws.com.attacker.invalid/"),
        ("s3.amazonaws.com/", "s3.amazonaws.com@localhost/"),
        ("s3.amazonaws.com/", "[s3.amazonaws.com/"),
        ("pmaptransferbucket", "otherbucket"),
        ("/v007/", "/v008/"),
        ("/fixture-scope/", "/../"),
        ("/fixture-scope/", "/"),
        ("/fixture-robot/", "/another-robot/"),
        ("rawmap?", "different?"),
        ("X-Amz-Algorithm=", "&unexpected=1&X-Amz-Algorithm="),
        ("X-Amz-Algorithm=", "badquery&"),
        ("AWS4-HMAC-SHA256", "different"),
        ("3600", "100"),
        ("X-Amz-SignedHeaders=host", "X-Amz-SignedHeaders=host#ignored"),
        ("X-Amz-Date", "Date"),
        ("20231114", "20231113"),
        ("X-Amz-SignedHeaders=host", "X-Amz-SignedHeaders=authorization"),
        ("a" * 64, "g" * 64),
        ("fixture%2Fread-only", "fixture\nread-only"),
    ],
)
def test_object_url_must_match_robot_and_signed_scope(make_raw_route_document, old, new):
    document = make_raw_route_document(NOW)
    update = document["map_update"]
    original = update["livemap_url_raw"]
    assert old in original
    update["livemap_url_raw"] = original.replace(old, new, 1)
    assert raw_route_reference(document, ROBOT, NOW) is None


def test_one_based_route_skips_optional_fields_and_retains_recent_points(
    make_raw_route_bundle, monkeypatch
):
    monkeypatch.setattr("custom_components.roomba_home.core.live_route.MAX_PATH_POINTS", 2)
    archive = make_raw_route_bundle(
        [(0, 3, 0), (1, 3, 5), (2, 3, 178)],
        prefix=b"\x08\x01\x11" + b"\x00" * 8,
        suffix=b"\x08\x04",
    )
    assert [
        (index, point.x, point.y, point.modes) for index, point in decode_raw_route(archive)
    ] == [
        (2, 1, 3, 5),
        (3, 2, 3, 178),
    ]


def test_nested_unknown_fields_allow_an_empty_live_route():
    assert decode_raw_route(zlib.compress(b"\x32\x04\x08\x00\x18\x01")) == ()


@pytest.mark.parametrize(
    "payload",
    [
        b"bad compressed data",
        zlib.compress(b"")[:-1],
        zlib.compress(b"") + b"trailing data",
        zlib.compress(b"\x80"),
        zlib.compress(b"\x80" * 11),
        zlib.compress(b"\x80" * 9 + b"\x02"),
        zlib.compress(b"\x03"),
        zlib.compress(b"\x00"),
        zlib.compress(b"\x08\x01"),
        zlib.compress(b"\x32\x05\x08\x01"),
        zlib.compress(b"\x32\x04\x08\x01\x12\x00"),
        zlib.compress(b"\x32\x04\x08\x00\x08\x00"),
        zlib.compress(b"\x32\x02\x08\x01\x32\x02\x08\x01"),
    ],
)
def test_malformed_objects_are_rejected(payload):
    with pytest.raises(ProtocolError):
        decode_raw_route(payload)


@pytest.mark.parametrize(
    ("point", "count", "match"),
    [
        ((0, 1, 0), 0, "point count"),
        ((0, 1, 0), 2, "point count"),
        ((float("nan"), 1, 0), 1, "route point"),
        ((1, 2, 2**54), 1, "route point"),
    ],
)
def test_unusable_route_fields_are_rejected(make_raw_route_bundle, point, count, match):
    with pytest.raises(ProtocolError, match=match):
        decode_raw_route(make_raw_route_bundle([point], count=count))


def test_oversized_zlib_stream_is_bounded(monkeypatch):
    monkeypatch.setattr("custom_components.roomba_home.core.live_route.MAX_MAP_BYTES", 20)
    with pytest.raises(ProtocolError, match="oversized"):
        decode_raw_route(zlib.compress(b"0" * 21))


def test_reconcile_temporary_obstacles_from_the_declared_route_prefix(make_raw_route_bundle):
    recent = [(1, 1, 5), (2, 1, 5), (3, 1, 4), (4, 1, 4)]
    trail = recent + [(5, 1, 4), (6, 1, 4)]
    snapshot = decode_raw_snapshot(
        make_raw_route_bundle(
            trail,
            count=4,
            obstacles=[(2, 3), (1, 4), (2, 3)],
        )
    )
    assert [index for index, _ in snapshot.route] == [1, 2, 3, 4]
    assert snapshot.obstacles == ((1, 4), (2, 3))
    batch = PositionBatch(
        1, NOW, NOW + 20, tuple(Position(x + 10, y - 2, 1, mode) for x, y, mode in recent)
    )
    path = MissionPath(("floor", "revision"), datetime.fromtimestamp(NOW, UTC), batch, ()).append(
        batch
    )
    assert not path.needs_backfill()
    assert reconcile_live_snapshot(path, snapshot) == (path, (), ((11, 2), (12, 1)))
    assert reconcile_live_snapshot(path, replace(snapshot, obstacles=())) == (path, (), ())
    assert reconcile_live_snapshot(path, replace(snapshot, obstacles=None)) == (path, (), None)
    assert reconcile_live_snapshot(replace(path, points=()), snapshot)[2] is None


@pytest.mark.parametrize(
    ("obstacles", "extra"),
    [
        ([(0, 2), (1, 2), (2, 2)], b""),
        ([(float("nan"), 0)], b""),
        ([], b"\x7a\x01\x80"),
        ([], b"\x78\x01"),
    ],
)
def test_bad_obstacle_layer_keeps_the_route(make_raw_route_bundle, monkeypatch, obstacles, extra):
    monkeypatch.setattr("custom_components.roomba_home.core.live_route.MAX_OBSTACLES", 1)
    snapshot = decode_raw_snapshot(
        make_raw_route_bundle(
            [(0, 2, 5)],
            obstacles=obstacles,
            suffix=extra,
        )
    )
    assert snapshot.obstacles is None
    assert snapshot.route[0][1].modes == 5


@pytest.mark.parametrize("stationary", [False, True])
def test_partial_alignment_can_place_obstacles_without_restoring_a_revised_route(
    make_raw_route_bundle, stationary
):
    points = [(1, 1, 5)] * 5 if stationary else [(x, 1, 5) for x in range(1, 6)]
    snapshot = decode_raw_snapshot(
        make_raw_route_bundle(
            [(0, 0, 5), *points, (7, 1, 4)],
            obstacles=[(3, 3)],
        )
    )
    batch = PositionBatch(
        2,
        NOW,
        NOW + 20,
        (*[Position(x + 10, y - 2, 1, mode) for x, y, mode in points], Position(17, -1, 1, 5)),
    )
    path = MissionPath(("floor", "revision"), datetime.fromtimestamp(NOW, UTC), batch, ()).append(
        batch
    )
    assert path.needs_backfill()
    expected = None if stationary else ((13, 1),)
    assert reconcile_live_snapshot(path, snapshot) == (path, (), expected)


@pytest.mark.parametrize(
    "case", ["aligned", "missing anchors", "mode changed", "stationary", "drift"]
)
def test_only_current_route_anchors_restore_a_prefix(make_raw_route_bundle, case):
    local = [(2, 1, 0), (3, 1, 0), (4, 2, 5), (5, 2, 5), (6, 2, 5), (7, 2, 0), (8, 1, 0)]
    raw = list(local)
    if case == "mode changed":
        raw[2] = (4, 2, 0)
    if case == "stationary":
        local[2:6] = raw[2:6] = [(4, 1, 5)] * 4
    if case == "drift":
        raw[2] = (4.08, 2, 5)
    route = decode_raw_route(make_raw_route_bundle(raw))
    positions = tuple(Position(x + 10, y - 2, 1, modes) for x, y, modes in local[2:6])
    if case == "missing anchors":
        positions = positions[:3]
    batch = PositionBatch(3, NOW, NOW + 20, positions)
    path = MissionPath(("floor", "revision"), datetime.fromtimestamp(NOW, UTC), batch, ())
    assert not path.needs_backfill()
    path = path.append(batch)
    assert path.needs_backfill()
    result, supplement = backfill_route(path, route)
    if case == "aligned":
        assert result.latest is batch
        assert result.map_version == path.map_version
        assert not result.needs_backfill()
        assert (result.points[0][1].x, result.points[0][1].y) == (12, -1)
        assert result.points[2:] == path.points
        assert supplement == result.points[:2]
    else:
        assert result is path
        assert supplement == ()


def test_mission_route_backfill_respects_zero_based_batches_and_visible_limit(
    make_raw_route_bundle, monkeypatch
):
    monkeypatch.setattr("custom_components.roomba_home.core.live_maps.MAX_PATH_POINTS", 4)
    batch = PositionBatch(0, NOW, NOW + 20, (Position(3, 0, 0, 0),))
    start = datetime.fromtimestamp(NOW, UTC)
    path = MissionPath(("floor", "revision"), start, batch, ()).append(batch)
    assert not path.needs_backfill()
    path = replace(path, points=tuple((index, batch.positions[0]) for index in range(9997, 10001)))
    assert not path.needs_backfill()
    assert replace(path, points=path.points[:-2] + path.points[-1:]).needs_backfill()
