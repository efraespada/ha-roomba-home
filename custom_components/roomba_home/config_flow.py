"""Configure a private account identity and select supported robots."""

import hashlib
from dataclasses import asdict

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_COUNTRY, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_PROFILE, CONF_ROBOTS, CONF_SHOW_MAPS, DOMAIN, SUPPORTED_SKU, selected_robots
from .core.client import RoombaClient
from .core.errors import AuthenticationError, ProtocolError, RateLimited
from .core.models import AppProfile, LoginDetails
from .core.transport import AiohttpTransport


async def validate_account(hass, values, profile):
    client = RoombaClient(
        AiohttpTransport(async_get_clientsession(hass)),
        LoginDetails(values[CONF_USERNAME].strip(), values[CONF_PASSWORD]),
        AppProfile.from_mapping(profile),
        values[CONF_COUNTRY],
    )
    session = await client.ensure_session()
    identity = session.raw["credentials"].get("CognitoId")
    if not isinstance(identity, str) or not identity:
        raise ProtocolError("Stable account identity is missing")
    robots = {
        k: v.get("name") or "Roomba"
        for k, v in session.raw["robots"].items()
        if v.get("sku") == SUPPORTED_SKU
    }
    return hashlib.sha256(identity.encode()).hexdigest(), robots


def error_key(error):
    if isinstance(error, AuthenticationError):
        return "invalid_auth"
    if isinstance(error, RateLimited):
        return "rate_limited"
    if isinstance(error, ProtocolError):
        return "unsupported_response"
    if isinstance(error, ValueError):
        return "invalid_country"
    return "cannot_connect"


def robot_selection(robots, selected):
    return vol.Schema(
        {
            vol.Required(CONF_ROBOTS, default=selected): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    multiple=True,
                    options=[
                        selector.SelectOptionDict(value=key, label=name)
                        for key, name in robots.items()
                    ],
                )
            ),
        }
    )


class RoombaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.profile = asdict(AppProfile.native())
        self.pending = {}
        self.robots = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return RoombaOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                identity, self.robots = await validate_account(self.hass, user_input, self.profile)
            except Exception as error:
                errors["base"] = error_key(error)
            else:
                if not self.robots:
                    return self.async_abort(reason="no_supported_robots")
                await self.async_set_unique_id(identity)
                self._abort_if_unique_id_configured()
                self.pending = {
                    **user_input,
                    CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                    CONF_COUNTRY: user_input[CONF_COUNTRY].upper(),
                    CONF_PROFILE: self.profile,
                }
                return await self.async_step_robots()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                    vol.Required(CONF_COUNTRY, default="ES"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_robots(self, user_input=None):
        errors = {}
        if user_input is not None:
            selected = user_input.get(CONF_ROBOTS, [])
            if not selected or not set(selected).issubset(self.robots):
                errors["base"] = "invalid_selection"
            else:
                return self.async_create_entry(
                    title="Roomba Home", data={**self.pending, CONF_ROBOTS: list(selected)}
                )
        return self.async_show_form(
            step_id="robots",
            data_schema=robot_selection(self.robots, list(self.robots)),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            values = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            try:
                identity, robots = await validate_account(
                    self.hass, values, entry.data[CONF_PROFILE]
                )
            except Exception as error:
                errors["base"] = error_key(error)
            else:
                if identity != entry.unique_id:
                    return self.async_abort(reason="reauth_different_account")
                if not set(selected_robots(entry)).intersection(robots):
                    return self.async_abort(reason="no_supported_robots")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )


class RoombaOptionsFlow(config_entries.OptionsFlowWithReload):
    def __init__(self):
        self.robots = {}

    async def async_step_init(self, user_input=None):
        entry = self.config_entry
        if user_input is None:
            try:
                identity, self.robots = await validate_account(
                    self.hass, entry.data, entry.data[CONF_PROFILE]
                )
            except Exception as error:
                return self.async_abort(reason=error_key(error))
            if identity != entry.unique_id:
                return self.async_abort(reason="reauth_different_account")
            if not self.robots:
                return self.async_abort(reason="no_supported_robots")

        previous = selected_robots(entry)
        errors = {}
        if user_input is not None:
            selected = list(dict.fromkeys(user_input[CONF_ROBOTS]))
            if selected and set(selected).issubset(self.robots):
                options = dict(entry.options)
                if set(selected) != set(previous):
                    options[CONF_ROBOTS] = selected
                show_maps = user_input[CONF_SHOW_MAPS]
                if show_maps != entry.options.get(CONF_SHOW_MAPS, False):
                    options[CONF_SHOW_MAPS] = show_maps
                return self.async_create_entry(data=options)
            errors["base"] = "invalid_selection"

        return self.async_show_form(
            step_id="init",
            data_schema=robot_selection(
                self.robots, [key for key in previous if key in self.robots]
            ).extend(
                {
                    vol.Required(
                        CONF_SHOW_MAPS, default=entry.options.get(CONF_SHOW_MAPS, False)
                    ): selector.BooleanSelector(),
                }
            ),
            errors=errors,
        )
