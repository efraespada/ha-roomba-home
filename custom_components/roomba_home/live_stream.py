"""Manage account-scoped live map subscriptions for active missions."""

import asyncio
import logging
import threading
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from .core.client import RoombaClient
from .core.mqtt import MqttProfile, live_map_topic
from .core.mqtt_live import MqttLiveReader

_LOGGER = logging.getLogger(__name__)
RETRY_SECONDS = 30


@dataclass(frozen=True, repr=False)
class MapWatch:
    robot_id: str
    started: datetime
    map_version: tuple[str, str]


def live_map_client(client: RoombaClient) -> RoombaClient:
    """Use a stable, separately authorized native MQTT identity for map reads."""
    source = client.profile
    app_id = uuid5(NAMESPACE_URL, f"roomba-home/live/{source.app_id}")
    device_id = uuid5(NAMESPACE_URL, f"roomba-home/live/{source.app_info['device_id']}")
    profile = replace(
        source,
        app_id=f"ANDROID-PRIME-{app_id}",
        app_info={
            **source.app_info,
            "device_id": f"ANDROID-DEVICE-{device_id}",
            "device_name": "Home Assistant live maps",
        },
    )
    return RoombaClient(client.http, client.login_details, profile, client.country)


class LiveMapStream:
    def __init__(self, client, create_task, executor, receive):
        self.client = client
        self._create_task = create_task
        self._executor = executor
        self._receive = receive
        self._watches = {}
        self._changed = asyncio.Event()
        self._stop = None
        self._task = None

    def update(self, watches: dict[str, MapWatch]) -> None:
        if self._watches == watches:
            return
        self._watches = dict(watches)
        self._changed.set()
        if self._stop is not None:
            self._stop.set()
        if watches and (self._task is None or self._task.done()):
            self._task = self._create_task(self._run())

    def _deliver(self, watch, sample):
        if self._watches.get(watch.robot_id) == watch:
            self._receive(watch, sample)

    async def _run(self):
        while self._watches:
            watches = self._watches
            self._changed.clear()
            try:
                await self._observe(watches)
            except Exception as error:
                _LOGGER.debug("Live position subscription failed: %s", type(error).__name__)
            if self._watches == watches:
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._changed.wait(), RETRY_SECONDS)

    async def _observe(self, watches):
        topics = {}
        async with asyncio.timeout(15):
            session = await self.client.ensure_session()
            for robot_id in watches.keys() & session.raw["robots"].keys():
                topic = live_map_topic(session, robot_id)
                if topic and await self.client.live_map_topic(robot_id) == topic:
                    topics[topic] = robot_id
        if watches != self._watches or not topics:
            return

        loop = asyncio.get_running_loop()
        stop = self._stop = threading.Event()
        workers = []

        def deliver(robot_id, sample):
            loop.call_soon_threadsafe(self._deliver, watches[robot_id], sample)

        try:
            for index, _ in enumerate(session.raw["connection_tokens"]):
                profile = MqttProfile.from_session(session, index)
                group = {
                    topic: robot for topic, robot in topics.items() if robot in profile.devices
                }
                if group:
                    reader = MqttLiveReader(profile)
                    workers.append(self._executor(reader.listen, group, stop, deliver))
            if workers:
                done, _ = await asyncio.wait(workers, return_when=asyncio.FIRST_COMPLETED)
                for future in done:
                    future.result()
        finally:
            stop.set()
            if workers:
                await asyncio.gather(*workers, return_exceptions=True)
            self._stop = None

    async def async_close(self):
        self.update({})
        if self._task is not None:
            await self._task
