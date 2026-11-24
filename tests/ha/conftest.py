from pathlib import Path

import pytest

pytest.importorskip("homeassistant")

from pytest_homeassistant.common import MockConfigEntry  # noqa: E402

from custom_components.roomba_home.const import CONF_PROFILE, CONF_ROBOTS, DOMAIN  # noqa: E402
from custom_components.roomba_home.core.capabilities import DeviceCapabilities  # noqa: E402
from custom_components.roomba_home.core.cleaning import CleaningCapabilities, CleaningMode  # noqa: E402
from custom_components.roomba_home.core.models import AppProfile  # noqa: E402
from custom_components.roomba_home.core.state import RobotState  # noqa: E402


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir):
    path = Path(hass_tmp_config_dir)
    (path / "custom_components").symlink_to(
        Path(__file__).resolve().parents[2] / "custom_components"
    )
    return str(path)


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    pass


@pytest.fixture
def robot_states():
    return {
        f"fixture-{i}": RobotState(
            f"fixture-{i}",
            f"Robot {i}",
            "X185240",
            True,
            100 - i,
            "charge",
            "none",
            2,
            0,
            capabilities=DeviceCapabilities(
                CleaningCapabilities(frozenset(CleaningMode), 4, 3, True, True, True),
                docking=True,
            ),
        )
        for i in range(3)
    }


@pytest.fixture
def entry(hass):
    from dataclasses import asdict

    value = MockConfigEntry(
        domain=DOMAIN,
        title="Roomba Home",
        unique_id="fixture-account",
        data={
            "username": "fixture-login",
            "password": "fixture-password",
            "country": "ES",
            CONF_PROFILE: asdict(AppProfile.native()),
            CONF_ROBOTS: [f"fixture-{i}" for i in range(3)],
        },
    )
    value.add_to_hass(hass)
    return value


@pytest.fixture
def cloud_session():
    from datetime import UTC, datetime, timedelta

    from custom_components.roomba_home.core.models import CloudSession

    robot_ids = [f"fixture-{i}" for i in range(4)]
    tokens = [
        {
            "client_id": f"fixture-client-{i}",
            "devices": robot_ids[i : i + 2],
            "iot_token": "fixture-token",
            "iot_authorizer_name": "fixture-authorizer",
            "iot_signature": "fixture-signature",
        }
        for i in (0, 2)
    ]
    return CloudSession.parse(
        {
            "credentials": {
                "AccessKeyId": "fixture-access",
                "SecretKey": "fixture-secret",
                "SessionToken": "fixture-token",
                "CognitoId": "fixture-account-id",
                "Expiration": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
            "robots": {
                k: {
                    "sku": "X185240" if i < 3 else "OLDMODEL",
                    "svcDeplId": "fixture",
                    "name": f"Robot {i}",
                }
                for i, k in enumerate(robot_ids)
            },
            "connection_tokens": tokens,
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
