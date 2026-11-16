"""Small real-HA fixture, matched to the deployed Core release."""

import asyncio
from pathlib import Path

import pytest
from homeassistant import config_entries, loader
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry, entity, entity_registry, frame, translation


@pytest.fixture
async def hass(tmp_path):
    (tmp_path / "custom_components").symlink_to(Path(__file__).parents[1] / "custom_components")
    hass = HomeAssistant(str(tmp_path))
    hass.config.skip_pip = True
    loader.async_setup(hass)
    frame.async_setup(hass)
    entity.async_setup(hass)
    translation.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {"_": "test"})
    await hass.config_entries.async_initialize()
    device_registry.async_setup(hass)
    await device_registry.async_load(hass)
    await entity_registry.async_load(hass)
    yield hass
    for entry in hass.config_entries.async_entries():
        if entry.state is config_entries.ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_stop(force=True)
    await asyncio.sleep(0)
