"""Verify account and mission boundaries for the live subscription."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.roomba_home.core.client import RoombaClient
from custom_components.roomba_home.core.models import AppProfile, LoginDetails
from custom_components.roomba_home.live_stream import LiveMapStream, MapWatch, live_map_client

TOPIC = "irbt/things/example/livemap/update"
WATCH = MapWatch("example", datetime(2026, 11, 25, tzinfo=UTC), ("floor", "version"))


def test_live_map_client_uses_a_stable_independent_native_profile():
    client = RoombaClient(Mock(), LoginDetails("a@example.test", "example"), AppProfile.native())
    receiver = live_map_client(client)
    assert receiver.http is client.http and receiver.login_details is client.login_details
    assert receiver.profile.app_id != client.profile.app_id
    assert receiver.profile.app_info["device_id"] != client.profile.app_info["device_id"]
    assert receiver.profile.app_id == live_map_client(client).profile.app_id
    assert (
        receiver.profile.app_info["device_id"]
        == live_map_client(client).profile.app_info["device_id"]
    )


def create_stream():
    client = SimpleNamespace(
        ensure_session=AsyncMock(
            return_value=SimpleNamespace(
                raw={
                    "robots": {"example": {}, "without-topic": {}},
                    "connection_tokens": [{}, {}],
                }
            )
        ),
        live_map_topic=AsyncMock(return_value=TOPIC),
    )
    ready = asyncio.Event()
    seen = []

    def receive(watch, sample):
        seen.append((watch, sample))
        ready.set()

    loop = asyncio.get_running_loop()
    stream = LiveMapStream(
        client,
        asyncio.create_task,
        lambda job, *args: loop.run_in_executor(None, job, *args),
        receive,
    )
    return stream, ready, seen


async def test_subscription_delivers_only_the_current_watched_mission():
    stream, ready, seen = create_stream()
    other = MapWatch("without-topic", WATCH.started, WATCH.map_version)
    future = MapWatch(WATCH.robot_id, WATCH.started + timedelta(hours=1), WATCH.map_version)

    def listen(topics, stop, deliver):
        assert topics == {TOPIC: WATCH.robot_id}
        deliver(WATCH.robot_id, "sample")
        assert stop.wait(2)

    with (
        patch(
            "custom_components.roomba_home.live_stream.live_map_topic",
            side_effect=(lambda _session, robot: TOPIC if robot == WATCH.robot_id else None),
        ),
        patch(
            "custom_components.roomba_home.live_stream.MqttProfile.from_session",
            side_effect=[SimpleNamespace(devices={}), SimpleNamespace(devices={WATCH.robot_id})],
        ),
        patch("custom_components.roomba_home.live_stream.MqttLiveReader") as reader,
    ):
        reader.return_value.listen.side_effect = listen
        stream.update({WATCH.robot_id: WATCH, other.robot_id: other})
        stream.update({WATCH.robot_id: WATCH, other.robot_id: other})
        await asyncio.wait_for(ready.wait(), 2)
        stream._deliver(future, "stale")
        assert seen == [(WATCH, "sample")]
        await stream.async_close()
    reader.return_value.listen.assert_called_once()
    stream.client.live_map_topic.assert_awaited_once_with(WATCH.robot_id)


@pytest.mark.parametrize("failure", ["wrong topic", "no group", "authorization error"])
async def test_retries_without_an_accepted_subscription_and_stops_on_close(failure):
    stream, _, seen = create_stream()
    if failure == "wrong topic":
        stream.client.live_map_topic.return_value = "other-topic"
    if failure == "authorization error":
        stream.client.ensure_session.side_effect = OSError
    with (
        patch("custom_components.roomba_home.live_stream.RETRY_SECONDS", 0.01),
        patch("custom_components.roomba_home.live_stream.live_map_topic", return_value=TOPIC),
        patch(
            "custom_components.roomba_home.live_stream.MqttProfile.from_session",
            return_value=SimpleNamespace(devices={}),
        ),
        patch("custom_components.roomba_home.live_stream.MqttLiveReader") as reader,
    ):
        stream.update({WATCH.robot_id: WATCH})
        async with asyncio.timeout(2):
            while stream.client.ensure_session.await_count < 2:
                await asyncio.sleep(0.01)
        await stream.async_close()
    assert seen == [] and not reader.called
