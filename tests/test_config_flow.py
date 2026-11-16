"""HA forms validate identity, persist metadata, and support recovery."""

from unittest.mock import AsyncMock, patch

from homeassistant.data_entry_flow import FlowResultType

from custom_components.motionblinds_hybrid.api import AuthenticationError, Metadata
from custom_components.motionblinds_hybrid.const import CONF_METADATA, DOMAIN
from tests.test_integration import METADATA, OFFICE, entity_id
from tests.test_integration import configured as configured

INPUT = {"username": "fixture@example.invalid", "password": "private-password", "host": "192.0.2.1"}


async def test_user_flow_persists_cloud_mapping(hass):
    with (
        patch("custom_components.motionblinds_hybrid.config_flow.validate", return_value=METADATA),
        patch(
            "custom_components.motionblinds_hybrid.async_setup_entry",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "custom_components.motionblinds_hybrid.async_unload_entry",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_METADATA]["blinds"][0]["name"] == "Office blind"
        await hass.async_block_till_done()
        await hass.config_entries.async_unload(result["result"].entry_id)


async def test_user_flow_handles_rejected_password(hass):
    with patch(
        "custom_components.motionblinds_hybrid.config_flow.validate",
        side_effect=AuthenticationError("Rejected"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data=INPUT
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_duplicate_gateway_is_rejected(hass, configured):
    with patch("custom_components.motionblinds_hybrid.config_flow.validate", return_value=METADATA):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data=INPUT
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_rejects_different_account(hass, configured):
    entry, _, _ = configured
    other = Metadata(
        "another-account", METADATA.gateway_mac, METADATA.gateway_name, METADATA.blinds
    )
    with patch("custom_components.motionblinds_hybrid.config_flow.validate", return_value=other):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "reauth", "entry_id": entry.entry_id}, data=entry.data
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "wrong_account"}


async def test_options_reload_changes_battery_method(hass, configured):
    entry, _, local = configured
    with patch("custom_components.motionblinds_hybrid.config_flow.LocalClient", return_value=local):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                "host": "192.0.2.1",
                "poll_interval": 15,
                "battery_method": "ha_estimate",
            },
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert hass.states.get(entity_id(hass, OFFICE, "battery", "sensor")).state == "28"


async def test_successful_reauth_updates_credentials_and_host_option(hass, configured):
    entry, _, _ = configured
    with patch("custom_components.motionblinds_hybrid.config_flow.validate", return_value=METADATA):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "reauth", "entry_id": entry.entry_id}, data=entry.data
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                **INPUT,
                "password": "replacement-password",
                "host": "192.0.2.2",
            },
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "replacement-password"
    assert entry.options["host"] == "192.0.2.2"
