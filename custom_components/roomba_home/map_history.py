"""Persist per-robot map backups using Home Assistant's private storage."""

import asyncio
from hashlib import sha256

from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .core.errors import ProtocolError
from .core.map_snapshots import DEFAULT_RETENTION, retained_snapshots, snapshot_summary

_STORES = f"{DOMAIN}.map_history"


def map_history(hass, entry_id):
    histories = hass.data.setdefault(_STORES, {})
    if entry_id not in histories:
        histories[entry_id] = MapHistory(hass, entry_id)
    return histories[entry_id]


async def async_remove_map_history(hass, entry_id):
    await map_history(hass, entry_id).async_remove()
    del hass.data[_STORES][entry_id]


class MapHistory:
    def __init__(self, hass, entry_id):
        self.hass = hass
        self._store = Store(
            hass,
            1,
            f"{_STORES}.{entry_id}",
            private=True,
            atomic_writes=True,
            serialize_in_event_loop=False,
        )
        self._lock = asyncio.Lock()
        self._removed = False

    async def _load(self, robot_id):
        if self._removed:
            raise ProtocolError("The local map history was removed.")
        saved = await self._store.async_load()
        data = {} if saved is None else saved
        owner = sha256(robot_id.encode()).hexdigest()
        try:
            group = data.get(
                owner, {"automatic": False, "retention": DEFAULT_RETENTION, "snapshots": []}
            )
            if (
                not isinstance(group["snapshots"], list)
                or type(group["automatic"]) is not bool
                or type(group["retention"]) is not int
            ):
                raise ValueError
        except AttributeError, KeyError, TypeError, ValueError:
            raise ProtocolError("The local map history is damaged.") from None
        return data, owner, group

    async def _save(self, data):
        if self.hass.is_stopping:
            raise ProtocolError("Home Assistant is stopping. The map backup was not saved.")
        write = asyncio.create_task(self._store.async_save(data))
        try:
            await asyncio.shield(write)
        except asyncio.CancelledError:
            # Keep the history lock until the in-flight disk write has finished.
            await asyncio.shield(write)
            raise
        # Store logs some disk write failures without raising them.
        if await self._store.async_load() != data:
            raise ProtocolError("Home Assistant could not save the local map history.")

    async def async_list(self, robot_id):
        async with self._lock:
            _, _, group = await self._load(robot_id)
            return {
                "automatic": group["automatic"],
                "retention": group["retention"],
                "snapshots": [snapshot_summary(row) for row in group["snapshots"]],
            }

    async def async_automatic(self, robot_id):
        async with self._lock:
            _, _, group = await self._load(robot_id)
            return group["automatic"] is True

    async def async_configure(self, robot_id, retention, automatic):
        async with self._lock:
            data, owner, group = await self._load(robot_id)
            group = {
                "retention": retention,
                "automatic": automatic,
                "snapshots": retained_snapshots(group["snapshots"], retention),
            }
            await self._save({**data, owner: group})

    async def async_capture(self, robot_id, snapshot):
        async with self._lock:
            data, owner, group = await self._load(robot_id)
            history = group["snapshots"]
            duplicate = next((row for row in history if row["id"] == snapshot["id"]), None)
            if duplicate is not None:
                if all(
                    duplicate.get(key) == snapshot.get(key)
                    for key in ("archive", "floor", "programs")
                ):
                    return snapshot_summary(duplicate)
                snapshot = {**snapshot, "pinned": duplicate["pinned"]}
                history = [row for row in history if row is not duplicate]
            retained = retained_snapshots([snapshot, *history], group["retention"])
            if snapshot not in retained:
                raise ProtocolError("The local map history is full. Unpin or delete a backup.")
            await self._save({**data, owner: {**group, "snapshots": retained}})
            return snapshot_summary(snapshot)

    @staticmethod
    def _find(group, identity):
        for row in group["snapshots"]:
            if row["id"] == identity:
                return row
        raise ProtocolError("This robot has no matching local map backup.")

    async def async_read(self, robot_id, identity):
        async with self._lock:
            _, _, group = await self._load(robot_id)
            return self._find(group, identity)

    async def async_modify(self, robot_id, identity, operation):
        async with self._lock:
            data, owner, group = await self._load(robot_id)
            row = self._find(group, identity)
            snapshots = [entry for entry in group["snapshots"] if entry is not row]
            if operation != "delete":
                snapshots = [
                    entry if entry is not row else {**row, "pinned": operation == "pin"}
                    for entry in group["snapshots"]
                ]
            retained = retained_snapshots(snapshots, group["retention"])
            await self._save({**data, owner: {**group, "snapshots": retained}})

    async def async_remove(self):
        async with self._lock:
            self._removed = True
            await self._store.async_remove()
