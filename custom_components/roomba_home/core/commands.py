"""Observed command vocabulary; broker acknowledgement is not physical success."""

import json
import re
import ssl
import threading
import time
from dataclasses import dataclass

import paho.mqtt.client as paho

from ..compatibility import VALIDATED_MODEL
from .actions import Command
from .capabilities import supports_point_clean
from .capability_protocol import project_capabilities
from .cleaning import CleaningProfile
from .cleaning_protocol import CleaningSetting, cleaning_parameters
from .errors import ProtocolError
from .maps import AreaTarget
from .models import CloudSession
from .mqtt import MqttProfile
from .point_maps import PointTarget


def command_body(
    command: Command,
    timestamp: int,
    profile: CleaningProfile | None = None,
    target: AreaTarget | PointTarget | None = None,
) -> bytes:
    if not isinstance(command, Command):
        raise ValueError("Use a supported command enum.")
    if type(timestamp) is not int or timestamp <= 0:
        raise ValueError("Use a positive timestamp in seconds.")
    value = {"command": command.value, "time": timestamp, "initiator": "rmtApp"}
    if command is Command.POINT_CLEAN:
        if not isinstance(target, PointTarget) or profile not in (None, CleaningProfile()):
            raise ValueError("Point cleaning requires a mapped point and the vacuum profile.")
        value.update(
            p2map_id=target.map_id,
            user_p2mapv_id=target.version_id,
            geom={"center": target.center},
            params=cleaning_parameters(CleaningProfile()),
        )
        return json.dumps(value, separators=(",", ":")).encode()
    if profile is not None and (
        not isinstance(profile, CleaningProfile) or command is not Command.VACUUM
    ):
        raise ValueError("Only a new cleaning mission accepts a cleaning profile.")
    if target is not None and (
        not isinstance(target, AreaTarget)
        or not target.regions
        or command is not Command.VACUUM
        or target.profiles
        and len(target.profiles) != len(target.regions)
    ):
        raise ValueError("Only a new cleaning mission accepts a map and regions.")
    if command is Command.VACUUM:
        value["params"] = cleaning_parameters(profile or CleaningProfile())
    if target is not None:
        value["p2map_id"] = target.map_id
        value["user_p2mapv_id"] = target.version_id
        value["regions"] = [
            {
                "region_id": region.region_id,
                "type": region.kind.value,
                "region_type": region.kind.value,
                **({"region_name": region.name} if region.name else {}),
            }
            for region in target.regions
        ]
        if target.profiles:
            value["params"] = {}
            value["ordered"] = 1
            for region, selection in zip(value["regions"], target.profiles, strict=True):
                region["params"] = cleaning_parameters(selection)
    return json.dumps(value, separators=(",", ":")).encode()


@dataclass(frozen=True)
class CommandReceipt:
    command: Command
    accepted_by_broker: bool
    # A separate state read must establish the requested physical transition.
    physical_result: str = "unconfirmed"


class MqttCommandSender:
    """Send once with QoS 1, bounded waits, verified TLS, and no automatic retry.

    Each blocking call owns and closes its connection. The application use case
    confirms the result through subsequent semantic state reads.
    """

    def __init__(self, session: CloudSession, robot_id: str, *, client_factory=paho.Client):
        try:
            if not isinstance(robot_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", robot_id):
                raise ValueError
            robot = session.raw["robots"][robot_id]
            if robot["sku"] != VALIDATED_MODEL:
                raise ValueError
            device = project_capabilities(robot, {})
            self.capabilities = device.cleaning
            self.point_clean = supports_point_clean(device.digital_spot)
            index = next(
                i
                for i, t in enumerate(session.raw["connection_tokens"])
                if robot_id in t["devices"]
            )
            self.profile = MqttProfile.from_session(session, index)
            prefix = session.discovery["deployments"][robot["svcDeplId"]]["irbtTopics"]
            if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z0-9_$-]+", prefix):
                raise ValueError
        except (KeyError, TypeError, ValueError, StopIteration) as error:
            raise ProtocolError("An authorized, validated modern robot is required.") from error
        self.topic = f"{prefix}/things/{robot_id}/cmd"
        self._settings_topic = (
            f"{self.profile.devices[robot_id]}/things/{robot_id}/shadow/name/rw-settings/update"
        )
        self.client_factory = client_factory

    def __repr__(self):
        return "MqttCommandSender(<private robot>)"

    def send(
        self,
        command: Command,
        profile: CleaningProfile | None = None,
        target: AreaTarget | PointTarget | None = None,
    ) -> CommandReceipt:
        body = command_body(command, int(time.time()), profile, target)
        if profile is not None:
            profile.validate(self.capabilities)
        if command is Command.POINT_CLEAN:
            if not self.point_clean:
                raise ValueError("Point cleaning is not supported by the robot.")
            CleaningProfile().validate(self.capabilities)
        if isinstance(target, AreaTarget):
            for selection in target.profiles:
                selection.validate(self.capabilities)
        self._publish(self.topic, body)
        return CommandReceipt(command, True)

    def write_cleaning_setting(self, setting: CleaningSetting, value: int | bool) -> None:
        """Write one supported preference. The caller must verify reported state."""
        if not isinstance(setting, CleaningSetting) or not setting.accepts(
            value, self.capabilities
        ):
            raise ValueError("This cleaning setting is not supported by the robot.")
        body = json.dumps(
            {"state": {"desired": setting.desired(value)}}, separators=(",", ":")
        ).encode()
        self._publish(self._settings_topic, body)

    def _publish(self, topic: str, body: bytes) -> None:
        connected = threading.Event()
        rejected = []

        def on_connect(client, userdata, flags, reason, properties):
            if reason.is_failure:
                rejected.append(True)
            connected.set()

        client = self.client_factory(
            paho.CallbackAPIVersion.VERSION2,
            client_id=self.profile.client_id,
            transport="websockets",
            reconnect_on_failure=False,
        )
        client.ws_set_options(path="/mqtt", headers=self.profile.headers)
        client.tls_set_context(ssl.create_default_context())
        client.on_connect = on_connect
        try:
            client.connect(self.profile.host, 443, 20)
            client.loop_start()
            if not connected.wait(12) or rejected:
                raise ProtocolError("MQTT command connection was not accepted.")
            info = client.publish(topic, body, qos=1, retain=False)
            if info.rc != paho.MQTT_ERR_SUCCESS:
                raise ProtocolError("MQTT command could not be submitted.")
            info.wait_for_publish(timeout=8)
            if not info.is_published():
                raise ProtocolError("MQTT command acknowledgement timed out; do not blindly retry.")
        finally:
            client.disconnect()
            client.loop_stop()
