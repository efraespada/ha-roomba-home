"""Keep optional mission position captures in private Home Assistant storage."""

import asyncio
from hashlib import sha256
from time import time

from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .core.errors import ProtocolError
from .core.mission_routes import MAX_LOCAL_ROUTES, ROUTE_CHECKPOINT_SECONDS, merge_samples

_STORES = f"{DOMAIN}.mission_routes"


def mission_route_store(hass, entry_id):
    stores = hass.data.setdefault(_STORES, {})
    if entry_id not in stores:
        stores[entry_id] = MissionRouteStore(hass, entry_id)
    return stores[entry_id]


async def async_remove_mission_routes(hass, entry_id):
    await mission_route_store(hass, entry_id).async_remove()
    del hass.data[_STORES][entry_id]


class MissionRouteStore:
    def __init__(self, hass, entry_id):
        self._store = Store(
            hass,
            1,
            f"{_STORES}.{entry_id}",
            private=True,
            atomic_writes=True,
            serialize_in_event_loop=False,
        )
        self._lock = asyncio.Lock()
        self._data = None
        self._removed = False

    async def _group(self, robot_id):
        if self._removed:
            raise ProtocolError("The local mission routes were removed.")
        if self._data is None:
            saved = await self._store.async_load()
            if saved is not None and not isinstance(saved, dict):
                raise ProtocolError("The local mission routes are damaged.")
            self._data = {} if saved is None else saved
        owner = sha256(robot_id.encode()).hexdigest()
        group = self._data.get(owner, {"enabled_since": None, "routes": []})
        if not isinstance(group, dict) or not isinstance(group.get("routes"), list):
            raise ProtocolError("The local mission routes are damaged.")
        return owner, group

    async def _save(self, owner, group):
        data = {**self._data, owner: group}
        self._data = None
        write = asyncio.create_task(self._store.async_save(data))
        try:
            await asyncio.shield(write)
        except asyncio.CancelledError:
            await asyncio.shield(write)
            raise
        if await self._store.async_load() != data:
            raise ProtocolError("Home Assistant could not save the local mission routes.")
        self._data = data

    async def async_settings(self, robot_id, *, enabled=None, clear=False, now=None):
        async with self._lock:
            owner, group = await self._group(robot_id)
            since = group.get("enabled_since")
            recording = since is not None
            if enabled is None:
                enabled = recording
            if clear or enabled != recording:
                group = {
                    "enabled_since": (time() if now is None else now) if enabled else None,
                    "routes": [] if clear else group["routes"],
                }
                await self._save(owner, group)
            return {"enabled": enabled, "count": len(group["routes"])}

    async def async_checkpoint(self, robot_id, key, observed, samples, *, final=False):
        async with self._lock:
            owner, group = await self._group(robot_id)
            since = group.get("enabled_since")
            if since is None or key.started.timestamp() < since:
                return
            identity = key.storage_key()
            routes = group["routes"]
            previous = next((row for row in routes if row["key"] == identity), None)
            if (
                previous is not None
                and not final
                and observed < previous["updated"] + ROUTE_CHECKPOINT_SECONDS
            ):
                return
            points = merge_samples(previous["points"] if previous else (), samples)
            if not points or (previous is not None and points == previous["points"]):
                return
            record = {"key": identity, "updated": observed, "points": points}
            routes = sorted(
                [record, *(row for row in routes if row is not previous)],
                key=lambda row: row["updated"],
                reverse=True,
            )[:MAX_LOCAL_ROUTES]
            await self._save(owner, {**group, "routes": routes})

    async def async_lookup(self, robot_id, started, number, requested, archived):
        async with self._lock:
            _, group = await self._group(robot_id)
            candidates = [
                row
                for row in group["routes"]
                if row["key"][:2] == [started.isoformat(), number]
                and (requested is None or tuple(row["key"][2:]) == requested)
                and (archived is None or row["key"][2] == archived[0])
            ]
            return candidates[0] if len(candidates) == 1 else None

    async def async_remove(self):
        async with self._lock:
            self._removed = True
            await self._store.async_remove()
