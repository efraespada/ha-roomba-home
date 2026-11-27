"""Exercise private, atomic Home Assistant storage for local map backups."""

import asyncio
from hashlib import sha256
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.map_history import async_remove_map_history, map_history

ROBOT = "fixture-first"
OWNER = sha256(ROBOT.encode()).hexdigest()


def record(number, *, pinned=False):
    return {
        "id": str(number),
        "pinned": pinned,
        "captured_at": "2026-11-25T21:00:00+00:00",
        "floor": {"map_id": "map-a", "version": str(number), "name": "Ático", "orientation": 0},
        "archive": "fixture-only",
    }


async def test_history_deduplicates_retains_and_isolates_snapshots(hass):
    first = map_history(hass, "entry-first")
    summary, duplicate = await asyncio.gather(
        first.async_capture(ROBOT, record(1)), first.async_capture(ROBOT, record(1))
    )
    assert summary == duplicate and "archive" not in summary
    await first.async_modify(ROBOT, "1", "pin")
    await first.async_configure(ROBOT, 1, True)
    await first.async_capture(ROBOT, record(2))
    await first.async_capture(ROBOT, record(3))
    result = await first.async_list(ROBOT)
    assert result["automatic"] is True and result["retention"] == 1
    assert [row["id"] for row in result["snapshots"]] == ["3", "1"]
    assert (await first.async_read(ROBOT, "1"))["pinned"] is True
    for history, robot in ((first, "fixture-second"), (map_history(hass, "other-entry"), ROBOT)):
        with pytest.raises(ProtocolError, match="no matching"):
            await history.async_read(robot, "1")

    await first.async_modify(ROBOT, "1", "unpin")
    assert [row["id"] for row in (await first.async_list(ROBOT))["snapshots"]] == ["3"]
    await first.async_modify(ROBOT, "3", "delete")
    assert (await first.async_list(ROBOT))["snapshots"] == []
    await async_remove_map_history(hass, "entry-first")
    with pytest.raises(ProtocolError, match="removed"):
        await first.async_list(ROBOT)
    assert (await map_history(hass, "entry-first").async_list(ROBOT))["automatic"] is False


async def test_corrupted_duplicate_is_repaired_and_pin_is_preserved(hass):
    history = map_history(hass, "entry-repair")
    await history.async_capture(ROBOT, record(1, pinned=True) | {"archive": "damaged"})
    await history.async_capture(ROBOT, record(1))
    assert await history.async_read(ROBOT, "1") == record(1, pinned=True)


async def test_floor_revisions_are_matched_in_requested_scope_order(hass):
    history = map_history(hass, "entry-revisions")
    first, second = record(1), record(2)
    group = {"automatic": False, "retention": 5, "snapshots": [second, {}, None, first]}
    with patch.object(history._store, "async_load", AsyncMock(return_value={OWNER: group})):
        matches = await history.async_matching_revisions(ROBOT, (("map-a", "1"), ("map-a", "2")))
    assert matches == ((("map-a", "1"), first), (("map-a", "2"), second))


@pytest.mark.parametrize(
    "bad_data",
    [
        [],
        None,
        {"snapshots": None},
        {"snapshots": [], "automatic": 1},
        {"snapshots": [], "automatic": True, "retention": "large"},
    ],
)
async def test_damaged_history_is_not_overwritten(hass, bad_data):
    history = map_history(hass, "entry-error")
    mocked_save = AsyncMock()
    with (
        patch.object(history._store, "async_load", AsyncMock(return_value={OWNER: bad_data})),
        patch.object(history._store, "async_save", mocked_save),
        pytest.raises(ProtocolError, match="damaged"),
    ):
        await history.async_capture(ROBOT, record(1))
    mocked_save.assert_not_awaited()


async def test_full_pinned_history_and_failed_disk_write_keeps_old_data(hass, monkeypatch):
    monkeypatch.setattr("custom_components.roomba_home.core.map_snapshots.MAX_SNAPSHOTS", 1)
    history = map_history(hass, "entry-full")
    await history.async_capture(ROBOT, record(1, pinned=True))
    with pytest.raises(ProtocolError, match="history is full"):
        await history.async_capture(ROBOT, record(2))
    with (
        patch.object(history._store, "async_save", AsyncMock()),
        pytest.raises(ProtocolError, match="could not save"),
    ):
        await history.async_modify(ROBOT, "1", "delete")
    with (
        patch.object(type(hass), "is_stopping", new_callable=PropertyMock, return_value=True),
        pytest.raises(ProtocolError, match="stopping"),
    ):
        await history.async_modify(ROBOT, "1", "delete")
    assert await history.async_read(ROBOT, "1") == record(1, pinned=True)


async def test_disconnect_during_disk_write_keeps_following_capture_consistent(hass):
    history = map_history(hass, "entry-interrupted")
    started, finish = asyncio.Event(), asyncio.Event()
    original = history._store.async_save

    async def held_write(data):
        started.set()
        await finish.wait()
        await original(data)

    with patch.object(history._store, "async_save", side_effect=held_write):
        write = asyncio.create_task(history.async_capture(ROBOT, record(1)))
        await started.wait()
        write.cancel()
        following = asyncio.create_task(history.async_capture(ROBOT, record(2)))
        await asyncio.sleep(0)
        assert not write.done() and not following.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await write
        assert (await following)["id"] == "2"
    assert [row["id"] for row in (await history.async_list(ROBOT))["snapshots"]] == ["2", "1"]
