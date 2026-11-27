"""Exercise the private route store without an active Roomba connection."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.live_maps import RoutePoint
from custom_components.roomba_home.core.mission_routes import RouteCaptureKey, captured_geometry
from custom_components.roomba_home.mission_route_store import (
    MissionRouteStore,
    async_remove_mission_routes,
    mission_route_store,
)

ROBOT = "fixture-route-owner"
STARTED = datetime(2026, 11, 27, 10, tzinfo=UTC)
NOW = STARTED.timestamp()
FLOOR = ("map-floor", "reviewed-version")
CAPTURE = RouteCaptureKey(STARTED, 22, FLOOR)
EARLY = {1: RoutePoint(1, 1, 0), 2: RoutePoint(1.2, 1, 5)}
LATE = {3: RoutePoint(1.4, 1, 5), 7: RoutePoint(4, 4, 4), 8: RoutePoint(4, 4.2, 6)}


async def test_route_checkpoints_merge_and_reload_without_inventing_missing_positions(hass):
    history = mission_route_store(hass, "entry-route")
    assert await history.async_settings(ROBOT) == {"enabled": False, "count": 0}
    await history.async_checkpoint(ROBOT, CAPTURE, NOW, EARLY)
    assert await history.async_settings(ROBOT, enabled=True, now=NOW - 1) == {
        "enabled": True,
        "count": 0,
    }
    await history.async_checkpoint(
        ROBOT, replace(CAPTURE, started=STARTED - timedelta(seconds=2)), NOW, EARLY
    )
    await history.async_checkpoint(ROBOT, CAPTURE, NOW, {})
    assert await history.async_lookup(ROBOT, STARTED, 22, FLOOR, None) is None
    await history.async_checkpoint(ROBOT, CAPTURE, NOW + 10, EARLY)
    await history.async_checkpoint(ROBOT, CAPTURE, NOW + 20, LATE)
    assert len((await history.async_lookup(ROBOT, STARTED, 22, FLOOR, None))["points"]) == 2
    await history.async_checkpoint(ROBOT, CAPTURE, NOW + 21, LATE, final=True)
    await history.async_checkpoint(ROBOT, CAPTURE, NOW + 120, LATE)

    reloaded = MissionRouteStore(hass, "entry-route")
    record = await reloaded.async_lookup(ROBOT, STARTED, 22, FLOOR, (FLOOR[0], "archive-version"))
    assert record["updated"] == NOW + 21
    assert [point[0] for point in record["points"]] == [1, 2, 3, 7, 8]
    geometry = captured_geometry(record["points"])
    assert geometry["trajectories"] == [
        {"index": 1, "modes": ("traveling",), "points": [(1, 1)]},
        {"index": 2, "modes": ("vacuuming",), "points": [(1, 1), (1.2, 1), (1.4, 1)]},
        {"index": 7, "modes": ("mopping",), "points": [(4, 4)]},
        {"index": 8, "modes": ("vacuuming", "mopping"), "points": [(4, 4), (4, 4.2)]},
    ]
    assert {mask for _, runs in geometry["estimated_coverage"]["rows"] for _, _, mask in runs} == {
        1,
        2,
        3,
    }
    for owner, start, number, requested, archive in [
        ("different-robot", STARTED, 22, FLOOR, None),
        (ROBOT, STARTED + timedelta(seconds=1), 22, FLOOR, None),
        (ROBOT, STARTED, 23, FLOOR, None),
        (ROBOT, STARTED, 22, (FLOOR[0], "wrong"), None),
        (ROBOT, STARTED, 22, None, ("other-floor", "archive")),
    ]:
        assert await reloaded.async_lookup(owner, start, number, requested, archive) is None
    assert (
        await MissionRouteStore(hass, "other-entry").async_lookup(ROBOT, STARTED, 22, FLOOR, None)
        is None
    )


async def test_retention_clear_and_ambiguous_floor_are_scoped(hass, monkeypatch):
    monkeypatch.setattr("custom_components.roomba_home.mission_route_store.MAX_LOCAL_ROUTES", 2)
    monkeypatch.setattr("custom_components.roomba_home.core.mission_routes.MAX_SAMPLES", 2)
    history = mission_route_store(hass, "entry-retention")
    await history.async_settings(ROBOT, enabled=True, now=NOW)
    await history.async_checkpoint(ROBOT, CAPTURE, NOW + 1, EARLY | LATE)
    await history.async_checkpoint(
        ROBOT, replace(CAPTURE, floor=(FLOOR[0], "other-version")), NOW + 2, EARLY
    )
    assert await history.async_lookup(ROBOT, STARTED, 22, None, None) is None
    record = await history.async_lookup(ROBOT, STARTED, 22, FLOOR, None)
    assert [point[0] for point in record["points"]] == [7, 8]
    await history.async_checkpoint(ROBOT, replace(CAPTURE, number=23), NOW + 3, EARLY)
    assert await history.async_lookup(ROBOT, STARTED, 22, FLOOR, None) is None
    assert await history.async_settings(ROBOT, enabled=False, now=NOW + 4) == {
        "enabled": False,
        "count": 2,
    }
    await history.async_settings(ROBOT, enabled=True, now=NOW + 5)
    assert await history.async_settings(ROBOT, clear=True, now=NOW + 6) == {
        "enabled": True,
        "count": 0,
    }
    await history.async_checkpoint(ROBOT, CAPTURE, NOW + 7, EARLY, final=True)
    assert await history.async_settings(ROBOT) == {"enabled": True, "count": 0}
    await async_remove_mission_routes(hass, "entry-retention")
    with pytest.raises(ProtocolError, match="removed"):
        await history.async_settings(ROBOT)
    assert await mission_route_store(hass, "entry-retention").async_settings(ROBOT) == {
        "enabled": False,
        "count": 0,
    }


@pytest.mark.parametrize(
    "data",
    [
        [],
        {sha256(ROBOT.encode()).hexdigest(): None},
        {sha256(ROBOT.encode()).hexdigest(): {"routes": 2}},
    ],
)
async def test_damaged_route_storage_is_not_overwritten(hass, data):
    history = mission_route_store(hass, "entry-damaged")
    with (
        patch.object(history._store, "async_load", AsyncMock(return_value=data)),
        patch.object(history._store, "async_save", AsyncMock()) as save,
        pytest.raises(ProtocolError, match="damaged"),
    ):
        await history.async_settings(ROBOT, enabled=True)
    save.assert_not_awaited()


async def test_route_write_failure_and_cancellation_keep_the_next_read_consistent(hass):
    history = mission_route_store(hass, "entry-disk")
    with (
        patch.object(history._store, "async_save", AsyncMock()),
        pytest.raises(ProtocolError, match="could not save"),
    ):
        await history.async_settings(ROBOT, enabled=True, now=NOW)

    started, finish = asyncio.Event(), asyncio.Event()
    save = history._store.async_save

    async def held(data):
        started.set()
        await finish.wait()
        await save(data)

    with patch.object(history._store, "async_save", side_effect=held):
        write = asyncio.create_task(history.async_settings(ROBOT, enabled=True, now=NOW))
        await started.wait()
        write.cancel()
        reading = asyncio.create_task(history.async_settings(ROBOT))
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await write
        assert await reading == {"enabled": True, "count": 0}
