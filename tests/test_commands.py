"""Command tests use a broker fake and cannot move a physical robot."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.roomba_home.core.cleaning import CleaningMode, CleaningProfile
from custom_components.roomba_home.core.commands import Command, MqttCommandSender, command_body
from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.maps import AreaTarget, CleaningRegion, RegionKind
from custom_components.roomba_home.core.models import CloudSession
from custom_components.roomba_home.core.point_maps import PointTarget
from custom_components.roomba_home.core.settings_protocol import RobotSetting
from custom_components.roomba_home.core.voice_catalog import VoicePack


def session():
    return CloudSession.parse(
        {
            "credentials": {
                "AccessKeyId": "fixture-access",
                "SecretKey": "fixture-secret",
                "SessionToken": "fixture-token",
                "Expiration": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
            "robots": {"fixture-robot": {"sku": "X185240", "svcDeplId": "fixture"}},
            "connection_tokens": [
                {
                    "client_id": "fixture-client",
                    "devices": ["fixture-robot"],
                    "iot_token": "fixture-token",
                    "iot_authorizer_name": "fixture-auth",
                    "iot_signature": "fixture-signature",
                }
            ],
        },
        {
            "current_deployment": "fixture",
            "deployments": {
                "fixture": {
                    "mqttAts": "fixture-ats.iot.us-east-1.amazonaws.com",
                    "iotTopics": "$aws",
                    "irbtTopics": "fixture-irbt",
                }
            },
        },
    )


class Broker:
    def __init__(self, reject=False, rc=0, ack=True):
        self.reject, self.rc, self.ack = reject, rc, ack
        self.calls = []
        self.closed = self.stopped = False

    def ws_set_options(self, **kwargs):
        self.ws = kwargs

    def tls_set_context(self, value):
        self.tls = value

    def connect(self, *args):
        self.endpoint = args

    def loop_start(self):
        self.on_connect(self, None, None, SimpleNamespace(is_failure=self.reject), None)

    def publish(self, topic, payload, **kwargs):
        self.calls.append((topic, payload, kwargs))
        return SimpleNamespace(
            rc=self.rc, wait_for_publish=lambda **k: None, is_published=lambda: self.ack
        )

    def disconnect(self):
        self.closed = True

    def loop_stop(self):
        self.stopped = True


def test_mapping_command_requires_advertised_persistent_maps():
    auth = session()
    broker = Broker()
    sender = MqttCommandSender(auth, "fixture-robot", client_factory=lambda *a, **k: broker)
    with pytest.raises(ValueError, match="Mapping is not supported"):
        sender.send(Command.START_MAPPING)
    assert broker.calls == []
    auth.raw["robots"]["fixture-robot"]["cap"] = {"p2maps": 1}
    sender = MqttCommandSender(auth, "fixture-robot", client_factory=lambda *a, **k: broker)
    assert sender.send(Command.START_MAPPING).accepted_by_broker
    assert len(broker.calls) == 1
    assert json.loads(broker.calls[0][1])["command"] == "train"


@pytest.mark.parametrize("command", [c for c in Command if c is not Command.POINT_CLEAN])
def test_observed_command_payload_is_strict_and_only_start_requests_vacuum(command):
    value = json.loads(command_body(command, 123456))
    assert value["command"] == command.value
    assert value["time"] == 123456 and value["initiator"] == "rmtApp"
    if command is Command.VACUUM:
        assert value["params"] == {"operatingMode": 2}
    else:
        assert "params" not in value


POINT = PointTarget("example-map", "example-version", (12.4, -3.0))


def test_point_payload_pins_version_and_uses_vacuum_without_overriding_suction():
    assert json.loads(command_body(Command.POINT_CLEAN, 42, target=POINT)) == {
        "command": "point_clean",
        "time": 42,
        "initiator": "rmtApp",
        "p2map_id": "example-map",
        "user_p2mapv_id": "example-version",
        "geom": {"center": [12.4, -3.0]},
        "params": {"operatingMode": 2},
    }


@pytest.mark.parametrize(
    ("mode", "code"),
    [(CleaningMode.MOP, 4), (CleaningMode.VACUUM_MOP, 6), (CleaningMode.VACUUM_THEN_MOP, 512)],
)
def test_point_payload_sends_wet_mode_without_overriding_wetness(mode, code):
    profile = CleaningProfile(mode)
    value = json.loads(command_body(Command.POINT_CLEAN, 42, profile, POINT))
    assert value["params"] == {"operatingMode": code}
    assert value["geom"] == {"center": [12.4, -3.0]}


@pytest.mark.parametrize(
    ("command", "profile", "target"),
    [
        (Command.POINT_CLEAN, None, None),
        (Command.POINT_CLEAN, "mop", POINT),
        (Command.POINT_CLEAN, CleaningProfile(suction_level=2), POINT),
        (Command.VACUUM, None, POINT),
    ],
)
def test_point_payload_cannot_be_transformed_into_another_operation(command, profile, target):
    with pytest.raises(ValueError):
        command_body(command, 42, profile, target)


@pytest.mark.parametrize("capability", [0, 1, 2, 3, None])
def test_point_sender_requires_current_capability(capability):
    connection = session()
    connection.raw["robots"]["fixture-robot"]["cap"] = {"dSpot": capability, "oMode": 2}
    broker = Broker()
    sender = MqttCommandSender(connection, "fixture-robot", client_factory=lambda *a, **k: broker)
    if capability in (1, 2):
        sender.send(Command.POINT_CLEAN, CleaningProfile(), POINT)
        assert len(broker.calls) == 1
        assert json.loads(broker.calls[0][1])["geom"] == {"center": [12.4, -3.0]}
    else:
        with pytest.raises(ValueError, match="not supported"):
            sender.send(Command.POINT_CLEAN, CleaningProfile(), POINT)
        assert not broker.calls


def test_point_sender_does_not_publish_an_unsupported_mode():
    connection = session()
    connection.raw["robots"]["fixture-robot"]["cap"] = {"dSpot": 1, "oMode": 2}
    broker = Broker()
    sender = MqttCommandSender(connection, "fixture-robot", client_factory=lambda *a, **k: broker)
    with pytest.raises(ValueError, match="cleaning mode is not supported"):
        sender.send(Command.POINT_CLEAN, CleaningProfile(CleaningMode.MOP), POINT)
    assert not broker.calls


@pytest.mark.parametrize("timestamp", [0, -1, True, 1.5])
def test_invalid_timestamps_are_rejected(timestamp):
    with pytest.raises(ValueError):
        command_body(Command.PAUSE, timestamp)


def test_arbitrary_command_strings_are_rejected():
    with pytest.raises(ValueError):
        command_body("reset", 123456)


def test_command_acknowledgement_is_explicitly_not_physical_success():
    b = Broker()
    sender = MqttCommandSender(session(), "fixture-robot", client_factory=lambda *a, **k: b)
    result = sender.send(Command.PAUSE)
    assert result.accepted_by_broker and result.physical_result == "unconfirmed"
    assert b.calls[0][0] == "fixture-irbt/things/fixture-robot/cmd"
    assert b.calls[0][2] == {"qos": 1, "retain": False}
    assert b.closed and b.stopped
    assert "fixture-robot" not in repr(sender)


@pytest.mark.parametrize(
    "identifier,pack,valid",
    [
        ("LANG261125120000", VoicePack("cs-CZ", "picea_lang_pack/cs_CZ_v10.zip"), True),
        (None, VoicePack("cs-CZ", "picea_lang_pack/cs_CZ_v10.zip"), False),
        ("other-but-valid", VoicePack("cs-CZ", "picea_lang_pack/cs_CZ_v10.zip"), False),
        ("LANG261125120000", "any.zip", False),
    ],
)
def test_voice_package_uses_only_the_software_shadow_and_language_deployment(
    identifier, pack, valid
):
    broker = Broker()
    sender = MqttCommandSender(session(), "fixture-robot", client_factory=lambda *a, **k: broker)
    if not valid:
        with pytest.raises(ValueError):
            sender.install_voice_pack(identifier, pack)
        assert not broker.calls
        return
    sender.install_voice_pack(identifier, pack)
    [(topic, payload, _)] = broker.calls
    assert topic == "$aws/things/fixture-robot/shadow/name/rw-software/update"
    assert json.loads(payload) == {
        "state": {
            "desired": {"deploymentId": identifier},
            "reported": {"deploymentMpkg": "picea_lang_pack/cs_CZ_v10.zip"},
        }
    }


@pytest.mark.parametrize(
    ("setting", "value", "desired"),
    [
        (RobotSetting.SUCTION, 4, {"suctionLevel": 4}),
        (RobotSetting.WETNESS, 3, {"padWetness": {"padPlate": 3}}),
        (RobotSetting.SMART_SCRUB, True, {"swScrub": 1}),
        (RobotSetting.SMART_SCRUB, False, {"swScrub": 0}),
        (RobotSetting.TWO_PASS, True, {"twoPass": True}),
        (RobotSetting.CARPET_BOOST, False, {"carpetBoost": False}),
        (RobotSetting.AUTO_EVACUATION_AREA, 50, {"autoevacFreq": 50}),
        (RobotSetting.VOICE_VOLUME, 0, {"audio": {"volume": 0}}),
        (RobotSetting.VOICE_VOLUME, 100, {"audio": {"volume": 100}}),
        (RobotSetting.VOICE_LANGUAGE, "en-GB", {"langs2": {"sLang": "en-GB"}}),
        (RobotSetting.NAME, "Ático Test", {"name": "Ático Test"}),
        (RobotSetting.CHILD_PET_LOCK, False, {"childLock": False}),
        (RobotSetting.CHILD_PET_LOCK, True, {"childLock": True}),
        (RobotSetting.PAD_WASH_TEMPERATURE, 0, {"pwHeat": 0}),
        (RobotSetting.PAD_WASH_TEMPERATURE, 2, {"pwHeat": 2}),
        (RobotSetting.PAD_WASH_FREQUENCY, 100, {"pwReturn": 100}),
        (RobotSetting.PAD_WASH_FREQUENCY, 101, {"pwReturn": 101}),
        (RobotSetting.PAD_WASH_FREQUENCY, 102, {"pwReturn": 102}),
        (RobotSetting.PAD_DRY_DURATION, 3, {"padDryDur": 3}),
        (RobotSetting.PAD_DRY_DURATION, 5, {"padDryDur": 5}),
        (RobotSetting.AUTOMATIC_DETERGENT, True, {"detergent": 1}),
        (RobotSetting.AUTOMATIC_DETERGENT, False, {"detergent": 0}),
    ],
)
def test_robot_settings_write_to_the_native_shadow_once(setting, value, desired):
    cloud = session()
    cloud.raw["robots"]["fixture-robot"]["cap"] = {
        "oMode": 6,
        "suctionLvl": 4,
        "ppWetLvl": 3,
        "scrub": 3,
        "multiPass": 1,
        "carpetBoost": 3,
        "autoevac": 2,
    }
    broker = Broker()
    sender = MqttCommandSender(cloud, "fixture-robot", client_factory=lambda *a, **k: broker)

    sender.write_robot_setting(setting, value)

    assert len(broker.calls) == 1
    topic, body, options = broker.calls[0]
    assert topic == "$aws/things/fixture-robot/shadow/name/rw-settings/update"
    assert json.loads(body) == {"state": {"desired": desired}}
    assert options == {"qos": 1, "retain": False}
    assert broker.closed and broker.stopped


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("scrub_setting", True),
        (RobotSetting.SUCTION, 1),
        (RobotSetting.WETNESS, True),
        (RobotSetting.WETNESS, 0),
        (RobotSetting.WETNESS, 4),
        (RobotSetting.SMART_SCRUB, 1),
        (RobotSetting.TWO_PASS, False),
        (RobotSetting.CARPET_BOOST, True),
        (RobotSetting.AUTO_EVACUATION_AREA, 50),
        (RobotSetting.VOICE_VOLUME, True),
        (RobotSetting.VOICE_VOLUME, 101),
        (RobotSetting.VOICE_VOLUME, -1),
        (RobotSetting.VOICE_VOLUME, 2.0),
        (RobotSetting.VOICE_LANGUAGE, "English (United Kingdom)"),
        (RobotSetting.NAME, "\n"),
        (RobotSetting.CHILD_PET_LOCK, 1),
        (RobotSetting.PAD_WASH_FREQUENCY, 2),
        (RobotSetting.PAD_WASH_TEMPERATURE, False),
        (RobotSetting.PAD_WASH_TEMPERATURE, 3),
        (RobotSetting.PAD_DRY_DURATION, 6),
        (RobotSetting.AUTOMATIC_DETERGENT, 1),
    ],
)
def test_invalid_robot_setting_cannot_publish(setting, value):
    cloud = session()
    cloud.raw["robots"]["fixture-robot"]["cap"] = {"oMode": 4, "ppWetLvl": 3, "scrub": 3}
    broker = Broker()
    sender = MqttCommandSender(cloud, "fixture-robot", client_factory=lambda *a, **k: broker)

    with pytest.raises(ValueError, match="not supported"):
        sender.write_robot_setting(setting, value)

    assert not broker.calls


@pytest.mark.parametrize("invalid", [False, 0, 5, "2", 2.0])
def test_suction_setting_obeys_robot_limit_and_integer_type(invalid):
    cloud = session()
    cloud.raw["robots"]["fixture-robot"]["cap"] = {"oMode": 2, "suctionLvl": 4}
    broker = Broker()
    sender = MqttCommandSender(cloud, "fixture-robot", client_factory=lambda *a, **k: broker)
    with pytest.raises(ValueError, match="not supported"):
        sender.write_robot_setting(RobotSetting.SUCTION, invalid)
    assert not broker.calls


@pytest.mark.parametrize("options", [{"reject": True}, {"rc": 4}, {"ack": False}])
def test_failure_closes_the_client_and_never_retries_a_command(options):
    b = Broker(**options)
    sender = MqttCommandSender(session(), "fixture-robot", client_factory=lambda *a, **k: b)
    with pytest.raises(ProtocolError):
        sender.send(Command.PAUSE)
    assert len(b.calls) <= 1
    assert b.closed and b.stopped


@pytest.mark.parametrize("target", ["unassociated", "fixture-robot/#", None])
def test_target_must_be_associated_and_cannot_inject_a_topic(target):
    with pytest.raises(ProtocolError):
        MqttCommandSender(session(), target)


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.raw["robots"]["fixture-robot"].update(sku="UNVALIDATED"),
        lambda s: s.raw.update(connection_tokens=[]),
        lambda s: s.discovery["deployments"]["fixture"].update(irbtTopics="bad/#"),
    ],
)
def test_unvalidated_models_missing_authorization_and_bad_prefixes_are_rejected(change):
    s = session()
    change(s)
    with pytest.raises(ProtocolError):
        MqttCommandSender(s, "fixture-robot")


@pytest.mark.parametrize(
    "command,profile",
    [
        (Command.PAUSE, "invalid"),
        (Command.PAUSE, CleaningProfile()),
        (Command.VACUUM, {}),
    ],
)
def test_only_start_accepts_a_typed_profile(command, profile):
    with pytest.raises(ValueError):
        command_body(command, 123456, profile)


def test_sender_validates_capability_before_opening_a_connection():
    broker = Broker()
    sender = MqttCommandSender(session(), "fixture-robot", client_factory=lambda *a, **k: broker)
    with pytest.raises(ValueError):
        sender.send(Command.VACUUM, CleaningProfile(CleaningMode.MOP))
    assert not broker.calls and not broker.closed


def test_sender_validates_distinct_area_profiles_before_opening_a_connection():
    target = AreaTarget(
        "map",
        "version",
        (CleaningRegion("rid", RegionKind.ROOM, None),),
        (CleaningProfile(CleaningMode.MOP),),
    )
    broker = Broker()
    sender = MqttCommandSender(session(), "fixture-robot", client_factory=lambda *a, **k: broker)
    with pytest.raises(ValueError):
        sender.send(Command.VACUUM, target=target)
    assert not broker.calls


def test_sender_publishes_once_when_all_area_profiles_are_supported():
    value = session()
    value.raw["robots"]["fixture-robot"]["cap"] = {"oMode": 6, "ppWetLvl": 3}
    target = AreaTarget(
        "map",
        "version",
        (CleaningRegion("rid", RegionKind.ROOM, None),),
        (CleaningProfile(CleaningMode.MOP, wetness_level=2),),
    )
    broker = Broker()
    sender = MqttCommandSender(value, "fixture-robot", client_factory=lambda *a, **k: broker)
    assert sender.send(Command.VACUUM, target=target).accepted_by_broker
    assert len(broker.calls) == 1
    assert json.loads(broker.calls[0][1])["regions"][0]["params"] == {
        "operatingMode": 4,
        "padWetness": {"padPlate": 2},
    }


@pytest.mark.parametrize("explicit_profiles", [False, True])
def test_directed_sequence_places_mode_and_settings_in_each_destination(explicit_profiles):
    sequence = CleaningProfile(
        CleaningMode.VACUUM_THEN_MOP, suction_level=2, wetness_level=1, two_pass=False
    )
    target = AreaTarget(
        "map",
        "version",
        (
            CleaningRegion("room", RegionKind.ROOM, None),
            CleaningRegion("zone", RegionKind.ZONE, None),
        ),
        (CleaningProfile(), sequence) if explicit_profiles else (),
    )
    command = json.loads(command_body(Command.VACUUM, 123, sequence, target))
    assert "params" not in command and command["ordered"] == 1
    assert [item["region_id"] for item in command["regions"]] == ["room", "zone"]
    assert command["regions"][0]["params"]["operatingMode"] == (2 if explicit_profiles else 512)
    assert command["regions"][1]["params"] == {
        "operatingMode": 512,
        "suctionLevel": 2,
        "padWetness": {"padPlate": 1},
        "twoPass": False,
    }
