"""MQTT boundary tests use a synthetic broker; no account or robot is contacted."""

import json
import ssl
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.roomba_home.core import mqtt
from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.live_maps import PositionBatch
from custom_components.roomba_home.core.models import CloudSession
from custom_components.roomba_home.core.mqtt import MqttProfile, MqttShadowReader
from custom_components.roomba_home.core.mqtt_live import MqttLiveReader


def cloud_session():
    return CloudSession.parse(
        {
            "credentials": {
                "AccessKeyId": "fixture-access",
                "SecretKey": "fixture-secret",
                "SessionToken": "fixture-session",
                "Expiration": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
            "robots": {"fixture-robot": {"svcDeplId": "fixture"}},
            "connection_tokens": [
                {
                    "client_id": "fixture-client",
                    "iot_token": "fixture-token",
                    "iot_authorizer_name": "fixture-authorizer",
                    "iot_signature": "fixture-signature",
                    "devices": ["fixture-robot"],
                }
            ],
        },
        {
            "current_deployment": "fixture",
            "deployments": {
                "fixture": {
                    "mqttAts": "fixture-ats.iot.us-east-1.amazonaws.com",
                    "iotTopics": "$aws",
                }
            },
        },
    )


class Broker:
    reject_connect = False
    reject_subscribe = False
    subscribe_result = 0
    publish_result = 0
    rejected_shadow = False
    deliver = True
    dropped_topics = frozenset()

    def __init__(self, *args, **kwargs):
        self.options = kwargs
        self.published = []
        self.batches = []
        self.closed = self.stopped = False

    def ws_set_options(self, **kwargs):
        self.websocket = kwargs

    def tls_set_context(self, context):
        self.tls = context

    def connect(self, host, port, keepalive):
        self.endpoint = (host, port, keepalive)

    def loop_start(self):
        self.on_connect(self, None, None, SimpleNamespace(is_failure=self.reject_connect), None)

    def subscribe(self, topics):
        self.topics = topics
        self.batches.append(topics)
        assert len(topics) <= 8
        self.on_subscribe(self, None, 1, [SimpleNamespace(is_failure=self.reject_subscribe)], None)
        return self.subscribe_result, 1

    def publish(self, topic, body, **kwargs):
        self.published.append((topic, body, kwargs))
        if self.deliver and topic not in self.dropped_topics:
            payload = json.loads(body)
            payload.update({"state": {"reported": {"batPct": 77}}, "version": 5})
            if self.rejected_shadow:
                payload["code"] = 404
            suffix = "/rejected" if self.rejected_shadow else "/accepted"
            # Unrelated messages and invalid payloads cannot satisfy this request.
            for other_topic, other_payload in [
                ("unrelated/topic", b"{}"),
                (topic + suffix, b"[]"),
                (topic + suffix, b"not-json"),
                (topic + suffix, b'{"clientToken":"other"}'),
                (topic + suffix, b" " * (1024 * 1024 + 1)),
                (topic + suffix, json.dumps(payload).encode()),
            ]:
                self.on_message(
                    self, None, SimpleNamespace(topic=other_topic, payload=other_payload)
                )
        return SimpleNamespace(rc=self.publish_result)

    def disconnect(self):
        self.closed = True

    def loop_stop(self):
        self.stopped = True


def run_reader(broker, timeout=0.01):
    profile = MqttProfile.from_session(cloud_session(), 0)
    return MqttShadowReader(profile, timeout=timeout, client_factory=lambda *a, **k: broker)


LIVE_TOPIC = "fixture-irbt/things/fixture-robot/livemap/update"


def live_reader(broker):
    return MqttLiveReader(
        MqttProfile.from_session(cloud_session(), 0),
        timeout=0.01,
        client_factory=lambda *a, **k: broker,
    )


def test_live_reader_delivers_fresh_positions_and_never_publishes():
    stop = threading.Event()
    fresh = int(time.time())
    payload = json.dumps(
        {
            "timestamp": fresh,
            "update_expire_ts": fresh + 30,
            "pos_update": {"cur_path": [23, 2.1, 1, 0, 5, fresh]},
        }
    ).encode()

    class LiveBroker(Broker):
        def loop_start(self):
            super().loop_start()
            for topic, body, retained in (
                ("unrelated", payload, False),
                (LIVE_TOPIC, payload, True),
                (LIVE_TOPIC, b" " * (1024 * 1024 + 1), False),
                (LIVE_TOPIC, b"bad JSON", False),
                (LIVE_TOPIC, b"{}", False),
                (LIVE_TOPIC, payload, False),
            ):
                self.on_message(
                    self, None, SimpleNamespace(topic=topic, payload=body, retain=retained)
                )
            stop.set()

    broker = LiveBroker()
    received = []
    live_reader(broker).listen(
        {LIVE_TOPIC: "fixture-robot"}, stop, lambda *row: received.append(row)
    )
    ((robot, position),) = received
    assert robot == "fixture-robot"
    assert isinstance(position, PositionBatch) and position.index == 23
    assert broker.batches == [[(LIVE_TOPIC, 0)]]
    assert broker.published == [] and broker.closed and broker.stopped
    live_reader(broker).listen({LIVE_TOPIC: "fixture-robot"}, stop, lambda *_: pytest.fail())


@pytest.mark.parametrize(
    "topics",
    [
        {},
        {f"test{x}/things/fixture-robot/livemap/update": "fixture-robot" for x in range(9)},
        {LIVE_TOPIC: "wrong-robot"},
        {"fixture-irbt/#": "fixture-robot"},
        {"+/things/fixture-robot/livemap/update": "fixture-robot"},
        {"#/things/fixture-robot/livemap/update": "fixture-robot"},
    ],
)
def test_live_reader_rejects_invalid_scopes(topics):
    with pytest.raises(ValueError, match="authorized"):
        live_reader(Broker()).listen(topics, threading.Event(), lambda *_: pytest.fail())


@pytest.mark.parametrize("failure", ["connect", "subscribe", "submit", "timeout", "lost"])
def test_live_reader_closes_the_connection_on_failure(failure):
    class FailingBroker(Broker):
        def loop_start(self):
            if failure == "timeout":
                return
            super().loop_start()
            if failure == "lost":
                threading.Timer(
                    0.03, self.on_disconnect, args=(self, None, None, None, None)
                ).start()

    broker = FailingBroker()
    broker.reject_connect = failure == "connect"
    broker.reject_subscribe = failure == "subscribe"
    broker.subscribe_result = 1 if failure == "submit" else 0
    match = "disconnected" if failure == "lost" else "unavailable"
    with pytest.raises(ProtocolError, match=match):
        live_reader(broker).listen(
            {LIVE_TOPIC: "fixture-robot"}, threading.Event(), lambda *_: pytest.fail()
        )
    assert broker.closed and broker.stopped


def test_live_reader_waits_for_more_packets_until_explicitly_stopped():
    broker = Broker()
    stop = threading.Event()
    timer = threading.Timer(0.32, stop.set)
    timer.start()
    try:
        live_reader(broker).listen({LIVE_TOPIC: "fixture-robot"}, stop, lambda *_: pytest.fail())
    finally:
        timer.cancel()
    assert stop.is_set() and broker.closed


def test_native_mqtt_uses_verified_tls_header_auth_and_read_topics_only():
    b = Broker()
    replies = run_reader(b).read(["ro-currentstate", "rw-constatus", "ro-currentstate"])
    assert len(replies) == 2
    assert all(r.accepted and r.document["version"] == 5 for r in replies)
    assert b.endpoint == ("fixture-ats.iot.us-east-1.amazonaws.com", 443, 20)
    assert b.websocket["path"] == "/mqtt"
    assert b.websocket["headers"]["x-irobot-auth"] == "fixture-token"
    assert b.tls.verify_mode == ssl.CERT_REQUIRED and b.tls.check_hostname
    assert all(t.endswith("/get") and k == {"qos": 0, "retain": False} for t, _, k in b.published)
    assert len(b.topics) == 4
    assert b.closed and b.stopped
    assert "fixture" not in repr(replies[0])


def test_missing_optional_shadow_is_a_correlated_rejection_not_an_authentication_failure():
    b = Broker()
    b.rejected_shadow = True
    (reply,) = run_reader(b).read(["ro-sensor"])
    assert not reply.accepted and reply.document["code"] == 404


def test_all_shadows_subscribe_in_bounded_packets_before_publishing():
    b = Broker()
    replies = run_reader(b).read()
    assert len(replies) == 9
    assert [len(batch) for batch in b.batches] == [8, 8, 2]


@pytest.mark.parametrize(
    "attribute", ["reject_connect", "reject_subscribe", "subscribe_result", "publish_result"]
)
def test_rejected_transport_stages_close_without_retry(attribute):
    b = Broker()
    setattr(b, attribute, True if attribute.startswith("reject_") else 4)
    with pytest.raises(ProtocolError):
        run_reader(b).read(["ro-currentstate"])
    assert b.closed and b.stopped
    assert len(b.published) <= 1


def test_missing_response_times_out_and_closes_connection():
    b = Broker()
    b.deliver = False
    with pytest.raises(ProtocolError, match="responses timed out"):
        run_reader(b).read(["ro-currentstate"])
    assert b.closed and b.stopped


@pytest.mark.parametrize(
    "allow_partial,rejected,expected_count",
    [(False, False, 0), (True, True, 0), (True, False, 2)],
)
def test_missing_robot_responses_can_preserve_the_other_robots_data(
    allow_partial, rejected, expected_count
):
    broker = Broker()
    shadows = ("ro-currentstate", "rw-constatus")
    broker.rejected_shadow = rejected
    broker.dropped_topics = frozenset(
        f"$aws/things/fixture-silent/shadow/name/{shadow}/get" for shadow in shadows
    )
    profile = replace(
        MqttProfile.from_session(cloud_session(), 0),
        devices={"fixture-robot": "$aws", "fixture-silent": "$aws"},
    )
    reader = MqttShadowReader(profile, timeout=0.01, client_factory=lambda *a, **k: broker)
    if expected_count:
        replies = reader.read(shadows, allow_partial=allow_partial)
        assert len(replies) == expected_count
        assert all(reply.accepted and reply.robot_id == "fixture-robot" for reply in replies)
    else:
        with pytest.raises(ProtocolError, match="responses timed out"):
            reader.read(shadows, allow_partial=allow_partial)
    assert len(broker.published) == 4
    assert broker.closed and broker.stopped


@pytest.mark.parametrize("shadows", [[], ["delete"], ["ro-currentstate/../../update"]])
def test_unknown_shadow_is_rejected_before_connect(shadows):
    with pytest.raises(ValueError):
        run_reader(Broker()).read(shadows)


@pytest.mark.parametrize("timeout", [0, -1, 61])
def test_timeout_configuration_is_bounded(timeout):
    with pytest.raises(ValueError):
        run_reader(Broker(), timeout)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: s.discovery["deployments"]["fixture"].update(mqttAts="localhost"),
        lambda s: s.raw["connection_tokens"][0].update(iot_token="bad\r\nheader"),
        lambda s: s.raw["connection_tokens"][0].update(devices=["another-robot"]),
        lambda s: s.raw["connection_tokens"][0].update(devices=["robot/#"]),
        lambda s: s.raw["connection_tokens"][0].update(devices=[]),
        lambda s: s.discovery["deployments"]["fixture"].update(iotTopics="$aws/#"),
    ],
)
def test_mqtt_profile_rejects_foreign_hosts_header_injection_and_unauthorized_topics(mutation):
    s = cloud_session()
    mutation(s)
    with pytest.raises(ProtocolError):
        MqttProfile.from_session(s, 0)


def test_profile_does_not_expose_authentication_in_its_representation():
    assert repr(MqttProfile.from_session(cloud_session(), 0)) == "MqttProfile(<redacted>)"


def test_robot_deployment_selects_its_topic_prefix_independently_of_current_deployment():
    s = cloud_session()
    s.raw["robots"]["fixture-robot"]["svcDeplId"] = "different"
    s.discovery["deployments"]["different"] = {"iotTopics": "different-prefix"}
    assert MqttProfile.from_session(s, 0).devices == {"fixture-robot": "different-prefix"}


def test_live_map_channel_is_limited_to_the_robot_deployment():
    from custom_components.roomba_home.core.mqtt import live_map_topic

    session = cloud_session()
    deployment = session.discovery["deployments"]["fixture"]
    assert live_map_topic(session, "fixture-robot") is None
    deployment["irbtTopics"] = "invalid/#"
    assert live_map_topic(session, "fixture-robot") is None
    deployment["irbtTopics"] = "fixture-irbt"
    assert (
        live_map_topic(session, "fixture-robot")
        == "fixture-irbt/things/fixture-robot/livemap/update"
    )


@pytest.mark.parametrize("delivery", ["normal", "rejected", "missing", "burst"])
def test_optional_live_updates_preserve_ordinary_shadow_reads(delivery, monkeypatch):
    profile = MqttProfile.from_session(cloud_session(), 0)
    topic = "fixture-irbt/things/fixture-robot/livemap/update"
    timestamp = int(datetime.now(UTC).timestamp())
    if delivery == "burst":
        monkeypatch.setattr("custom_components.roomba_home.core.mqtt.MAX_PATH_POINTS", 2)

    class LiveBroker(Broker):
        def subscribe(self, topics):
            if topics[0][0] != topic:
                return super().subscribe(topics)
            self.reject_subscribe = delivery == "rejected"
            result = super().subscribe(topics)
            if delivery in {"rejected", "missing"}:
                return result
            frame = json.dumps(
                {
                    "timestamp": timestamp,
                    "update_expire_ts": timestamp + 30,
                    "pos_update": {"cur_path": [30, 4, 2, 0, 2, timestamp]},
                }
            ).encode()
            for name, payload, retained in (
                (topic, b"not-json", False),
                (topic, b"[]", False),
                (topic, frame, True),
                ("unrelated/topic", frame, False),
                (topic, frame, False),
            ):
                self.on_message(
                    self, None, SimpleNamespace(topic=name, payload=payload, retain=retained)
                )
            if delivery == "burst":
                body = json.loads(frame)
                for index in range(31, 65):
                    body["pos_update"]["cur_path"][0] = index
                    self.on_message(
                        self,
                        None,
                        SimpleNamespace(
                            topic=topic, payload=json.dumps(body).encode(), retain=False
                        ),
                    )
            return result

    broker = LiveBroker()
    positions = {}
    replies = MqttShadowReader(profile, timeout=0.02, client_factory=lambda *a, **kw: broker).read(
        ("ro-currentstate",),
        live_topics={topic: "fixture-robot"},
        positions=positions,
    )
    assert replies[0].document["state"]["reported"]["batPct"] == 77
    assert all(path.endswith("/get") for path, _, _ in broker.published)
    assert broker.closed and broker.stopped
    if delivery == "rejected":
        assert positions == {}
    elif delivery == "missing":
        assert positions == {"fixture-robot": []}
    elif delivery == "burst":
        assert [item.index for item in positions["fixture-robot"]] == [63, 64]
    else:
        assert positions["fixture-robot"][0].positions[0].x == 4


def test_optional_raw_route_uses_latest_nonretained_reference(make_raw_route_document):
    profile = MqttProfile.from_session(cloud_session(), 0)
    timestamp = int(datetime.now(UTC).timestamp())
    topic = "fixture-irbt/things/fixture-robot/livemap/update"

    class RawMapBroker(Broker):
        def subscribe(self, filters):
            result = super().subscribe(filters)
            if filters == [(topic, 0)]:
                for offset, robot, retained in (
                    (-1, "fixture-robot", False),
                    (-10, "fixture-robot", False),
                    (0, "different-robot", False),
                    (0, "fixture-robot", True),
                    (0, "fixture-robot", False),
                ):
                    document = make_raw_route_document(timestamp + offset, robot)
                    self.on_message(
                        self,
                        None,
                        SimpleNamespace(
                            topic=topic, payload=json.dumps(document).encode(), retain=retained
                        ),
                    )
            return result

    references = {}
    broker = RawMapBroker()
    reader = MqttShadowReader(profile, timeout=0.02, client_factory=lambda *args, **kwargs: broker)
    replies = reader.read(
        ("ro-currentstate",), live_topics={topic: "fixture-robot"}, raw_routes=references
    )
    assert replies[0].accepted
    assert set(references) == {"fixture-robot"}
    assert references["fixture-robot"].timestamp == timestamp


def test_timeline_read_uses_current_mission_and_ignores_invalid_reports():
    robot = "fixture-robot"
    prefix = f"fixture-irbt/things/{robot}"
    request_topic = f"{prefix}/mission/timeline/request"
    report_topic = f"{prefix}/mission/timeline/report"

    class TimelineBroker(Broker):
        def publish(self, topic, body, **kwargs):
            if topic != request_topic:
                return super().publish(topic, body, **kwargs)
            assert kwargs == {"qos": 1, "retain": False}
            reply = json.loads(body) | {"nMssn": 19, "event": [{"type": "start", "ts": 5}]}
            for payload, retained in (
                (json.dumps(reply).encode(), True),
                (b"not-json", False),
                (json.dumps(reply | {"nMssn": 18}).encode(), False),
                (json.dumps(reply).encode(), False),
            ):
                self.on_message(
                    self,
                    None,
                    SimpleNamespace(topic=report_topic, payload=payload, retain=retained),
                )
            return SimpleNamespace(rc=0)

    reports = {}
    broker = TimelineBroker()
    replies = run_reader(broker).read(
        ("ro-currentstate",),
        live_topics={f"{prefix}/livemap/update": robot},
        positions={},
        timeline_requests={robot: 19},
        timelines=reports,
    )
    assert replies[0].accepted
    assert reports[robot].mission_number == 19
    assert reports[robot].stage == "start"


@pytest.mark.parametrize("deliver_report", [True, False])
@pytest.mark.parametrize("sample_positions", [True, False])
def test_timeline_read_waits_after_shadow_and_position_window(
    monkeypatch, deliver_report, sample_positions
):
    monkeypatch.setattr(mqtt, "POSITION_SAMPLE_SECONDS", 0.01)
    prefix = "fixture-irbt/things/fixture-robot"
    request_topic = f"{prefix}/mission/timeline/request"

    class DelayedTimelineBroker(Broker):
        timer = None

        def publish(self, topic, body, **kwargs):
            if topic != request_topic:
                return super().publish(topic, body, **kwargs)
            if deliver_report:
                document = json.loads(body) | {"nMssn": 19, "event": [{"type": "zone", "ts": 5}]}
                message = SimpleNamespace(
                    topic=f"{prefix}/mission/timeline/report", payload=json.dumps(document).encode()
                )
                self.timer = threading.Timer(0.03, self.on_message, args=(self, None, message))
                self.timer.start()
            return SimpleNamespace(rc=0)

        def loop_stop(self):
            if self.timer is not None:
                self.timer.join()
            super().loop_stop()

    broker = DelayedTimelineBroker()
    reports = {}
    (shadow,) = run_reader(broker, timeout=0.25).read(
        ["ro-currentstate"],
        live_topics={LIVE_TOPIC: "fixture-robot"},
        positions={} if sample_positions else None,
        timeline_requests={"fixture-robot": 19},
        timelines=reports,
    )
    assert shadow.accepted and broker.closed and broker.stopped
    if deliver_report:
        assert reports["fixture-robot"].stage == "zone"
    else:
        assert reports == {}
