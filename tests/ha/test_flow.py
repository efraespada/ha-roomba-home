from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType, InvalidData

from custom_components.roomba_home.const import DOMAIN
from custom_components.roomba_home.core.errors import (
    ApiError,
    AuthenticationError,
    ProtocolError,
    RateLimited,
)

INPUT = {"username": "fixture-login", "password": "fixture-password", "country": "ES"}
VALIDATE = "custom_components.roomba_home.config_flow.validate_account"


async def test_account_flow_selects_multiple_robots_and_creates_private_identity(hass):
    with patch(
        VALIDATE, AsyncMock(return_value=("fixture-account", {"a": "Robot A", "b": "Robot B"}))
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
        assert result["step_id"] == "robots"
        with patch("custom_components.roomba_home.async_setup_entry", AsyncMock(return_value=True)):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"robots": ["a", "b"]}
            )
            await hass.async_block_till_done()
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["robots"] == ["a", "b"]
        assert result["data"]["client_profile"]["app_id"].startswith("ANDROID-PRIME-")


@pytest.mark.parametrize(
    "error,key",
    [
        (AuthenticationError(403042), "invalid_auth"),
        (ApiError(403), "cannot_connect"),
        (ProtocolError("fixture"), "unsupported_response"),
        (RateLimited(), "rate_limited"),
        (OSError(), "cannot_connect"),
        (ValueError(), "invalid_country"),
    ],
)
async def test_flow_classifies_failures_without_provider_details(hass, error, key):
    with patch(VALIDATE, AsyncMock(side_effect=error)):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data=INPUT
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}


async def test_unsupported_inventory_aborts(hass):
    with patch(VALIDATE, AsyncMock(return_value=("fixture-account", {}))):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data=INPUT
        )
    assert result["reason"] == "no_supported_robots"


async def test_duplicate_account_is_not_created(hass, entry):
    with patch(VALIDATE, AsyncMock(return_value=("fixture-account", {"a": "Robot"}))):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data=INPUT
        )
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize("selection", [[], ["foreign"]])
async def test_selection_must_include_authorized_robots(hass, selection):
    with patch(VALIDATE, AsyncMock(return_value=("fixture-account", {"a": "Robot"}))):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data=INPUT
        )
        if selection == ["foreign"]:
            with pytest.raises(InvalidData):
                await hass.config_entries.flow.async_configure(
                    result["flow_id"], {"robots": selection}
                )
            return
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"robots": selection}
        )
    assert result["errors"] == {"base": "invalid_selection"}


async def test_reauth_preserves_profile_selection_and_entity_identity(hass, entry):
    original = entry.data["client_profile"]
    with (
        patch(VALIDATE, AsyncMock(return_value=("fixture-account", {"fixture-0": "Robot"}))),
        patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)),
    ):
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "fixture-replacement"}
        )
        await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert entry.unique_id == "fixture-account"
    assert entry.data["client_profile"] == original
    assert entry.data["robots"] == ["fixture-0", "fixture-1", "fixture-2"]


async def test_validate_account_filters_old_models_and_hashes_account_identity(hass, cloud_session):
    from dataclasses import asdict

    from custom_components.roomba_home.config_flow import validate_account
    from custom_components.roomba_home.core.models import AppProfile

    with patch("custom_components.roomba_home.config_flow.RoombaClient") as client:
        client.return_value.ensure_session = AsyncMock(return_value=cloud_session)
        identity, robots = await validate_account(hass, INPUT, asdict(AppProfile.native()))
    assert len(identity) == 64 and "fixture-account-id" not in identity
    assert len(robots) == 3 and "fixture-3" not in robots


async def test_validate_account_requires_a_stable_identity(hass, cloud_session):
    from dataclasses import asdict

    from custom_components.roomba_home.config_flow import validate_account
    from custom_components.roomba_home.core.models import AppProfile

    cloud_session.raw["credentials"].pop("CognitoId")
    with patch("custom_components.roomba_home.config_flow.RoombaClient") as client:
        client.return_value.ensure_session = AsyncMock(return_value=cloud_session)
        with pytest.raises(ProtocolError):
            await validate_account(hass, INPUT, asdict(AppProfile.native()))


@pytest.mark.parametrize(
    "identity,robots,reason",
    [
        ("other-account", {"fixture-0": "Robot"}, "reauth_different_account"),
        ("fixture-account", {}, "no_supported_robots"),
    ],
)
async def test_reauth_rejects_account_changes_and_missing_selected_devices(
    hass, entry, identity, robots, reason
):
    with patch(VALIDATE, AsyncMock(return_value=(identity, robots))):
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "fixture-new"}
        )
    assert result["reason"] == reason


async def test_reauth_error_preserves_existing_entry(hass, entry):
    with patch(VALIDATE, AsyncMock(side_effect=AuthenticationError())):
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "fixture-new"}
        )
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data["password"] == "fixture-password"


@pytest.mark.parametrize(
    ("result", "error", "reason"),
    [
        (None, AuthenticationError(), "invalid_auth"),
        (("fixture-account", {}), None, "no_supported_robots"),
        (("other-account", {"fixture-0": "Robot"}), None, "reauth_different_account"),
    ],
)
async def test_options_preserves_selection_if_account_validation_fails(
    hass, entry, result, error, reason
):
    with patch(VALIDATE, AsyncMock(return_value=result, side_effect=error)):
        form = await hass.config_entries.options.async_init(entry.entry_id)
    assert form["reason"] == reason
    assert entry.options == {}
    assert len(entry.data["robots"]) == 3


async def test_options_reselects_robot_with_registry_and_saved_preferences(
    hass, entry, robot_states
):
    from homeassistant.helpers import entity_registry

    from custom_components.roomba_home.coordinator import RoombaCoordinator

    async def refresh(account):
        return {key: value for key, value in robot_states.items() if key in account.selected}

    names = {key: value.name for key, value in robot_states.items()}
    with (
        patch(VALIDATE, AsyncMock(return_value=(entry.unique_id, names))),
        patch.object(RoombaCoordinator, "_async_update_data", refresh),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        account = entry.runtime_data
        form = await hass.config_entries.options.async_init(entry.entry_id)
        unchanged = await hass.config_entries.options.async_configure(
            form["flow_id"], {"robots": list(reversed(robot_states)), "show_maps": False}
        )
        await hass.async_block_till_done()
        assert unchanged["type"] is FlowResultType.CREATE_ENTRY
        assert entry.runtime_data is account and not entry.options

        registry = entity_registry.async_get(hass)
        first = registry.async_get("vacuum.robot_0")
        registry.async_update_entity(first.entity_id, name="Custom vacuum name")
        await entry.runtime_data.async_set_profile("fixture-0", suction_level=2)
        initial_profile = entry.options["cleaning_profiles"]["fixture-0"]

        form = await hass.config_entries.options.async_init(entry.entry_id)
        invalid = await hass.config_entries.options.async_configure(
            form["flow_id"], {"robots": [], "show_maps": False}
        )
        assert invalid["errors"] == {"base": "invalid_selection"}
        await hass.config_entries.options.async_configure(
            form["flow_id"], {"robots": ["fixture-1"], "show_maps": True}
        )
        await hass.async_block_till_done()
        assert entry.runtime_data.selected == {"fixture-1"}
        assert entry.runtime_data.show_maps is True
        assert registry.async_get(first.entity_id).id == first.id
        assert hass.states.get(first.entity_id).state == "unavailable"
        await entry.runtime_data.async_set_profile("fixture-1", suction_level=3)
        assert entry.options["cleaning_profiles"]["fixture-0"] == initial_profile

        form = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(
            form["flow_id"], {"robots": ["fixture-0", "fixture-1"], "show_maps": False}
        )
        await hass.async_block_till_done()
        assert entry.runtime_data.selected == {"fixture-0", "fixture-1"}
        assert entry.runtime_data.show_maps is False
        assert entry.runtime_data.profile("fixture-0").suction_level == 2
        restored = registry.async_get(first.entity_id)
        assert restored.id == first.id
        assert restored.device_id == first.device_id
        assert restored.name == "Custom vacuum name"
        assert hass.states.get(restored.entity_id).state == "docked"
        assert entry.data["robots"] == list(robot_states)
