"""Exercise actual HA entry setup, services, state, failures, and unload."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.motionblinds_hybrid.api import Blind, CloudError, LocalError, Metadata
from custom_components.motionblinds_hybrid.const import CONF_METADATA, DOMAIN

OFFICE = Blind("AABBCC000001", "Office blind")
FOUR = Blind("AABBCC000004", "Four")
METADATA = Metadata("fixture-account", "AABBCCDDEEFF", "Bridge", (OFFICE, FOUR))


@pytest.fixture
async def configured(hass):
    cloud = AsyncMock()
    cloud.metadata.return_value = METADATA
    local = AsyncMock()
    local.discover.return_value = (METADATA.gateway_mac, {OFFICE.identity, FOUR.identity})

    async def read(blind):
        return {
            "currentPosition": 0 if blind == OFFICE else 100,
            "operation": 2,
            "voltageMode": 1,
            "batteryLevel": 1084 if blind == OFFICE else 1191,
            "RSSI": -70,
        }

    local.read.side_effect = read
    entry = ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Bridge",
        data={
            "username": "fixture@example.invalid",
            "password": "private-password",
            "host": "192.0.2.1",
            CONF_METADATA: METADATA.to_dict(),
        },
        options={},
        source="user",
        unique_id=METADATA.gateway_mac,
        discovery_keys={},
        subentries_data=None,
    )
    with (
        patch("custom_components.motionblinds_hybrid.async_get_clientsession", return_value=None),
        patch("custom_components.motionblinds_hybrid.CloudClient", return_value=cloud),
        patch("custom_components.motionblinds_hybrid.coordinator.LocalClient", return_value=local),
    ):
        await hass.config_entries.async_add(entry)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        yield entry, cloud, local


def entity_id(hass, blind, key, platform):
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{blind.identity}_{key}")


async def test_setup_uses_cloud_names_and_local_sensor_values(hass, configured):
    entry, cloud, local = configured
    office = hass.states.get(entity_id(hass, OFFICE, "cover", "cover"))
    assert office.attributes["friendly_name"] == "Office blind"
    assert office.attributes["current_position"] == 100
    assert hass.states.get(entity_id(hass, OFFICE, "battery", "sensor")).state == "20"
    assert hass.states.get(entity_id(hass, FOUR, "battery", "sensor")).state == "100"
    assert hass.states.get(entity_id(hass, OFFICE, "voltage", "sensor")).state == "10.84"
    cloud.command.assert_not_called()


async def test_cover_service_sends_cloud_target_without_optimistic_state(hass, configured):
    entry, cloud, local = configured
    cover = entity_id(hass, OFFICE, "cover", "cover")
    await hass.services.async_call(
        "cover", "set_cover_position", {"entity_id": cover, "position": 90}, blocking=True
    )
    cloud.command.assert_awaited_once_with(OFFICE, {"targetPosition": 10})
    assert hass.states.get(cover).attributes["current_position"] == 100
    assert entry.runtime_data._readback_tasks
    coordinator = entry.runtime_data
    await hass.config_entries.async_unload(entry.entry_id)
    assert not coordinator._readback_tasks


async def test_cloud_outage_does_not_stop_local_reads(hass, configured):
    entry, cloud, local = configured
    cloud.metadata.side_effect = CloudError("Cloud unavailable")
    await entry.runtime_data.async_refresh_metadata()
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.last_update_success
    assert entry.runtime_data.cloud_metadata_available is False
    assert hass.states.get(entity_id(hass, OFFICE, "cover", "cover")).state == "open"


async def test_one_failed_local_blind_becomes_unavailable(hass, configured):
    entry, cloud, local = configured
    previous = local.read.side_effect

    async def read(blind):
        if blind == OFFICE:
            raise LocalError("No response")
        return await previous(blind)

    local.read.side_effect = read
    await entry.runtime_data.async_refresh()
    assert hass.states.get(entity_id(hass, OFFICE, "cover", "cover")).state == "unavailable"
    assert hass.states.get(entity_id(hass, FOUR, "cover", "cover")).state == "closed"


async def test_readback_observes_local_position_change(hass, configured):
    entry, cloud, local = configured
    cover = entity_id(hass, OFFICE, "cover", "cover")
    await hass.services.async_call(
        "cover", "set_cover_position", {"entity_id": cover, "position": 90}, blocking=True
    )
    local.read.side_effect = None
    local.read.return_value = {
        "currentPosition": 10,
        "operation": 2,
        "voltageMode": 1,
        "batteryLevel": 1084,
    }
    await asyncio.sleep(2.2)
    await hass.async_block_till_done()
    assert hass.states.get(cover).attributes["current_position"] == 90


async def test_diagnostics_omit_account_and_device_identifiers(hass, configured):
    import json

    from custom_components.motionblinds_hybrid.diagnostics import async_get_config_entry_diagnostics

    entry, _, _ = configured
    payload = json.dumps(await async_get_config_entry_diagnostics(hass, entry))
    for private in (
        "fixture@example.invalid",
        "private-password",
        OFFICE.mac,
        FOUR.mac,
        METADATA.account_id,
        METADATA.gateway_mac,
    ):
        assert private not in payload


async def test_metadata_rename_preserves_device_identity(hass, configured):
    entry, cloud, local = configured
    renamed = Blind(OFFICE.mac, "Study blind")
    cloud.metadata.return_value = Metadata(
        METADATA.account_id, METADATA.gateway_mac, METADATA.gateway_name, (renamed, FOUR)
    )
    before = entity_id(hass, OFFICE, "cover", "cover")
    await entry.runtime_data.async_refresh_metadata()
    await hass.async_block_till_done()
    assert entity_id(hass, OFFICE, "cover", "cover") == before
    assert hass.states.get(before).attributes["friendly_name"] == "Study blind"
