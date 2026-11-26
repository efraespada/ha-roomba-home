"""Bounded MQTT shadow reads using the native app's WebSocket authentication.

This blocking research adapter must run outside an event loop. It deliberately
has no robot-command or settings-write operation.
"""

import json
import re
import ssl
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

import paho.mqtt.client as paho

from .errors import ProtocolError
from .live_maps import (
    MAX_PATH_POINTS,
    MissionTimeline,
    PositionBatch,
    mission_timeline,
    position_batch,
)
from .live_route import RawRouteReference, raw_route_reference
from .models import CloudSession

SHADOWS = (
    "ro-currentstate",
    "rw-settings",
    "ro-services",
    "rw-software",
    "ro-configinfo",
    "ro-stats",
    "rw-schedule",
    "rw-constatus",
    "ro-sensor",
)
POSITION_SAMPLE_SECONDS = 6


@dataclass(frozen=True, repr=False)
class MqttProfile:
    host: str
    client_id: str
    headers: dict[str, str]
    devices: dict[str, str]

    def __repr__(self):
        return "MqttProfile(<redacted>)"

    @classmethod
    def from_session(cls, session: CloudSession, index: int):
        try:
            token = session.raw["connection_tokens"][index]
            host = session.deployment["mqttAts"]
            if not isinstance(host, str) or not re.fullmatch(
                r"[a-z0-9-]+\.iot\.[a-z0-9-]+\.amazonaws\.com", host
            ):
                raise ValueError
            client_id = token["client_id"]
            headers = {
                "x-irobot-auth": token["iot_token"],
                "x-amz-customauthorizer-name": token["iot_authorizer_name"],
                "x-amz-customauthorizer-signature": token["iot_signature"],
            }
            if not all(
                isinstance(v, str) and v and not any(c in v for c in "\r\n")
                for v in [client_id, *headers.values()]
            ):
                raise ValueError
            devices = {}
            for robot_id in token["devices"]:
                if not re.fullmatch(r"[A-Za-z0-9_-]+", robot_id):
                    raise ValueError
                robot = session.raw["robots"][robot_id]
                deployment = session.discovery["deployments"][robot["svcDeplId"]]
                prefix = deployment["iotTopics"]
                if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z0-9_$-]+", prefix):
                    raise ValueError
                devices[robot_id] = prefix
            if not devices:
                raise ValueError
        except (IndexError, KeyError, TypeError, ValueError) as error:
            raise ProtocolError("Incomplete MQTT connection profile.") from error
        return cls(host, client_id, headers, devices)


@dataclass(frozen=True, repr=False)
class ShadowReply:
    robot_id: str
    shadow: str
    accepted: bool
    document: dict[str, Any]

    def __repr__(self):
        return "ShadowReply(<private state>)"


def live_map_topic(session: CloudSession, robot_id: str) -> str | None:
    """Use only the discovered live-map topic for a robot in the current session."""
    robot = session.raw["robots"][robot_id]
    deployment = session.discovery["deployments"][robot["svcDeplId"]]
    prefix = deployment.get("irbtTopics")
    if isinstance(prefix, str) and re.fullmatch(r"[A-Za-z0-9_$-]+", prefix):
        return f"{prefix}/things/{robot_id}/livemap/update"
    return None


class MqttShadowReader:
    """One explicit, bounded connection; no automatic reconnect or blind retry."""

    def __init__(self, profile: MqttProfile, *, timeout=15, client_factory=paho.Client):
        if not 0 < timeout <= 60:
            raise ValueError("MQTT timeout must be between zero and 60 seconds.")
        self.profile = profile
        self.timeout = timeout
        self.client_factory = client_factory

    def read(
        self,
        shadows=SHADOWS,
        *,
        allow_partial: bool = False,
        live_topics: dict[str, str] | None = None,
        positions: dict[str, list[PositionBatch]] | None = None,
        timeline_requests: dict[str, int] | None = None,
        timelines: dict[str, MissionTimeline] | None = None,
        raw_routes: dict[str, RawRouteReference] | None = None,
    ) -> list[ShadowReply]:
        """Keep accepted replies at the deadline when partial reads are enabled."""
        shadows = tuple(dict.fromkeys(shadows))
        if not shadows or any(s not in SHADOWS for s in shadows):
            raise ValueError("Use an observed named shadow.")
        connected, subscribed = threading.Event(), threading.Event()
        received = threading.Condition()
        failed = []
        replies = {}
        request_token = str(uuid.uuid4())
        live_topics = live_topics or {}
        requested = timeline_requests or {}
        report_topics = {
            topic.removesuffix("/livemap/update") + "/mission/timeline/report": (
                robot_id,
                requested[robot_id],
                uuid.uuid4().int & 0x7FFFFFFF,
            )
            for topic, robot_id in live_topics.items()
            if robot_id in requested
        }
        reports = {}
        references: dict[str, RawRouteReference] = {}
        batches: dict[str, dict[int, PositionBatch]] = {
            robot_id: {} for robot_id in live_topics.values()
        }
        expected = {}
        for robot_id, prefix in self.profile.devices.items():
            for shadow in shadows:
                base = f"{prefix}/things/{robot_id}/shadow/name/{shadow}/get"
                expected[base + "/accepted"] = (robot_id, shadow, True)
                expected[base + "/rejected"] = (robot_id, shadow, False)

        def on_connect(client, userdata, flags, reason, properties):
            if reason.is_failure:
                failed.append("MQTT authentication was rejected.")
            connected.set()

        def on_subscribe(client, userdata, mid, reasons, properties):
            if not reasons or any(r.is_failure for r in reasons):
                failed.append("MQTT subscription was rejected.")
            subscribed.set()

        def on_message(client, userdata, message):
            if len(message.payload) > 1024 * 1024:
                return
            if live_robot := live_topics.get(message.topic):
                if getattr(message, "retain", False):
                    return
                try:
                    document = json.loads(message.payload)
                    now = int(time.time())
                    batch = position_batch(document, now)
                except ValueError, RecursionError:
                    return
                if batch is not None:
                    with received:
                        saved = batches[live_robot]
                        saved[batch.index] = batch
                        if len(saved) > 32:
                            del saved[min(saved)]
                        received.notify_all()
                elif raw_routes is not None:
                    reference = raw_route_reference(document, live_robot, now)
                    if reference is not None:
                        with received:
                            previous = references.get(live_robot)
                            if previous is None or previous.timestamp <= reference.timestamp:
                                references[live_robot] = reference
                return
            if expected_report := report_topics.get(message.topic):
                if getattr(message, "retain", False):
                    return
                robot_id, number, request_id = expected_report
                try:
                    report = mission_timeline(
                        json.loads(message.payload), request_id, number, int(time.time())
                    )
                except ValueError, RecursionError:
                    return
                if report is not None:
                    with received:
                        reports[robot_id] = report
                        received.notify_all()
                return
            identity = expected.get(message.topic)
            if identity is None:
                return
            try:
                value = json.loads(message.payload)
                if not isinstance(value, dict) or value.get("clientToken") != request_token:
                    return
            except ValueError, RecursionError:
                return
            robot, shadow, accepted = identity
            with received:
                replies[robot, shadow] = ShadowReply(robot, shadow, accepted, value)
                received.notify_all()

        client = self.client_factory(
            paho.CallbackAPIVersion.VERSION2,
            client_id=self.profile.client_id,
            transport="websockets",
            reconnect_on_failure=False,
        )
        client.ws_set_options(path="/mqtt", headers=self.profile.headers)
        client.tls_set_context(ssl.create_default_context())
        client.on_connect = on_connect
        client.on_subscribe = on_subscribe
        client.on_message = on_message
        try:
            client.connect(self.profile.host, 443, 20)
            client.loop_start()
            if not connected.wait(self.timeout) or failed:
                raise ProtocolError(failed[0] if failed else "MQTT connection timed out.")
            topics = [(t, 0) for t in expected]
            # AWS IoT allows at most eight filters in one SUBSCRIBE packet.
            for offset in range(0, len(topics), 8):
                subscribed.clear()
                result, _ = client.subscribe(topics[offset : offset + 8])
                if result != paho.MQTT_ERR_SUCCESS:
                    raise ProtocolError("MQTT subscription could not be submitted.")
                if not subscribed.wait(self.timeout) or failed:
                    raise ProtocolError(failed[0] if failed else "MQTT subscription timed out.")
            live_filters = [(topic, 0) for topic in (*live_topics, *report_topics)]
            for offset in range(0, len(live_filters), 8):
                subscribed.clear()
                result, _ = client.subscribe(live_filters[offset : offset + 8])
                if result != paho.MQTT_ERR_SUCCESS or not subscribed.wait(1) or failed:
                    break
            body = json.dumps({"clientToken": request_token})
            for topic in expected:
                if topic.endswith("/accepted"):
                    info = client.publish(
                        topic.removesuffix("/accepted"), body, qos=0, retain=False
                    )
                    if info.rc != paho.MQTT_ERR_SUCCESS:
                        raise ProtocolError("MQTT read could not be submitted.")
            if not failed:
                for topic, (_, _, request_id) in report_topics.items():
                    client.publish(
                        topic.removesuffix("/report") + "/request",
                        json.dumps({"timelineRequestId": request_id}),
                        qos=1,
                        retain=False,
                    )
            deadline = time.monotonic() + self.timeout
            with received:
                while len(replies) < len(expected) // 2:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        if allow_partial and any(reply.accepted for reply in replies.values()):
                            break
                        raise ProtocolError("MQTT shadow responses timed out.")
                    received.wait(remaining)
                if positions is not None and batches and not failed:
                    sample_until = min(deadline, time.monotonic() + POSITION_SAMPLE_SECONDS)
                    while (remaining := sample_until - time.monotonic()) > 0:
                        received.wait(remaining)
                    for robot_id, items in batches.items():
                        recent = []
                        count = 0
                        for item in sorted(
                            items.values(), key=lambda value: value.index, reverse=True
                        ):
                            count += len(item.positions)
                            if count > MAX_PATH_POINTS:
                                break
                            recent.append(item)
                        positions[robot_id] = list(reversed(recent))
                if timelines is not None:
                    if report_topics and not failed:
                        received.wait_for(
                            lambda: len(reports) == len(report_topics),
                            timeout=deadline - time.monotonic(),
                        )
                    timelines.update(reports)
                if raw_routes is not None:
                    raw_routes.update(references)
                return list(replies.values())
        finally:
            client.disconnect()
            client.loop_stop()
