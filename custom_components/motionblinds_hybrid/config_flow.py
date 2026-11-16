"""Configure the Bridge account and local gateway through Home Assistant."""

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthenticationError, CloudClient, CloudError, LocalClient, LocalError, Metadata
from .const import (
    CONF_BATTERY_METHOD,
    CONF_METADATA,
    CONF_POLL_INTERVAL,
    DEFAULT_BATTERY_METHOD,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)


def account_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
        }
    )


async def validate(hass, data: dict[str, Any]) -> Metadata:
    local = LocalClient(data[CONF_HOST])
    gateway, local_macs = await local.discover()
    client = CloudClient(async_get_clientsession(hass), data[CONF_USERNAME], data[CONF_PASSWORD])
    return await client.metadata(gateway, local_macs)


class MotionFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            try:
                metadata = await validate(self.hass, user_input)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except CloudError, LocalError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(metadata.gateway_mac)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=metadata.gateway_name,
                    data={
                        **user_input,
                        CONF_METADATA: metadata.to_dict(),
                    },
                )
        return self.async_show_form(
            step_id="user", data_schema=account_schema(user_input or {}), errors=errors
        )

    async def async_step_reauth(self, entry_data) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        defaults = {**entry.data, CONF_HOST: entry.options.get(CONF_HOST, entry.data[CONF_HOST])}
        errors = {}
        if user_input is not None:
            try:
                metadata = await validate(self.hass, user_input)
                old = Metadata.from_dict(entry.data[CONF_METADATA])
                if (metadata.account_id, metadata.gateway_mac) != (old.account_id, old.gateway_mac):
                    errors["base"] = "wrong_account"
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except CloudError, LocalError:
                errors["base"] = "cannot_connect"
            else:
                if not errors:
                    return self.async_update_reload_and_abort(
                        entry,
                        options={**entry.options, CONF_HOST: user_input[CONF_HOST]},
                        data_updates={
                            **user_input,
                            CONF_METADATA: metadata.to_dict(),
                        },
                    )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=account_schema({**defaults, **(user_input or {})}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return MotionOptionsFlow()


class MotionOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            try:
                gateway, _ = await LocalClient(user_input[CONF_HOST]).discover()
                if gateway != Metadata.from_dict(self.config_entry.data[CONF_METADATA]).gateway_mac:
                    errors["base"] = "wrong_gateway"
            except LocalError:
                errors["base"] = "cannot_connect"
            else:
                if not errors:
                    return self.async_create_entry(title="", data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOST, default=options.get(CONF_HOST, self.config_entry.data[CONF_HOST])
                ): str,
                vol.Required(
                    CONF_POLL_INTERVAL,
                    default=options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=300)),
                vol.Required(
                    CONF_BATTERY_METHOD,
                    default=options.get(CONF_BATTERY_METHOD, DEFAULT_BATTERY_METHOD),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value="app_indicator", label="App indicator (0, 10, 20, 50, 100%)"
                            ),
                            selector.SelectOptionDict(
                                value="ha_estimate", label="HA voltage estimate"
                            ),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
