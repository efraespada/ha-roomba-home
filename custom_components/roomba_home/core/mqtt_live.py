"""Receive the native live-map stream without sharing the command connection."""

import json
import ssl
import threading
import time

import paho.mqtt.client as paho

from .errors import ProtocolError
from .live_maps import position_batch
from .live_route import raw_route_reference
from .mqtt import MqttProfile

MAX_MESSAGE_BYTES = 1024 * 1024


class MqttLiveReader:
    """Own an authenticated, read-only subscription until stopped."""

    def __init__(self, profile: MqttProfile, *, timeout=10, client_factory=paho.Client):
        self.profile = profile
        self.timeout = timeout
        self.client_factory = client_factory

    def listen(self, topics, stop: threading.Event, deliver) -> None:
        if (
            not topics
            or len(topics) > 8
            or any(
                robot not in self.profile.devices
                or not topic.endswith(f"/things/{robot}/livemap/update")
                or "+" in topic
                or "#" in topic
                for topic, robot in topics.items()
            )
        ):
            raise ValueError("Use authorized live-map topics.")
        if stop.is_set():
            return
        ready, lost = threading.Event(), threading.Event()

        def fail():
            lost.set()
            ready.set()

        def on_connect(client, userdata, flags, reason, properties):
            if reason.is_failure:
                fail()
                return
            result, _ = client.subscribe([(topic, 0) for topic in topics])
            if result != paho.MQTT_ERR_SUCCESS:
                fail()

        def on_subscribe(client, userdata, mid, reasons, properties):
            if reasons and not any(reason.is_failure for reason in reasons):
                ready.set()
            else:
                fail()

        def on_disconnect(client, userdata, flags, reason, properties):
            fail()

        def on_message(client, userdata, message):
            robot = topics.get(message.topic)
            if (
                robot is None
                or message.retain
                or stop.is_set()
                or len(message.payload) > MAX_MESSAGE_BYTES
            ):
                return
            try:
                document = json.loads(message.payload)
                now = int(time.time())
                sample = position_batch(document, now) or raw_route_reference(document, robot, now)
            except ValueError, RecursionError:
                return
            if sample is not None:
                deliver(robot, sample)

        client = self.client_factory(
            paho.CallbackAPIVersion.VERSION2,
            client_id=self.profile.client_id,
            transport="websockets",
            reconnect_on_failure=False,
        )
        client.connect_timeout = self.timeout
        client.ws_set_options(path="/mqtt", headers=self.profile.headers)
        client.tls_set_context(ssl.create_default_context())
        client.on_connect = on_connect
        client.on_subscribe = on_subscribe
        client.on_disconnect = on_disconnect
        client.on_message = on_message
        try:
            client.connect(self.profile.host, 443, 20)
            client.loop_start()
            if not ready.wait(self.timeout) or lost.is_set():
                raise ProtocolError("Live map subscription is unavailable.")
            while not stop.wait(0.25):
                if lost.is_set():
                    raise ProtocolError("Live map subscription disconnected.")
        finally:
            client.disconnect()
            client.loop_stop()
