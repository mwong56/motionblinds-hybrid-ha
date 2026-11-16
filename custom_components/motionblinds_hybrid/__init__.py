"""Motionblinds cloud commands with local status reads."""

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import async_get
from homeassistant.helpers.event import async_track_time_interval

from .api import CloudClient, Metadata
from .const import CONF_METADATA, DOMAIN
from .coordinator import MotionCoordinator

PLATFORMS = [Platform.COVER, Platform.SENSOR]
type MotionConfigEntry = ConfigEntry[MotionCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: MotionConfigEntry) -> bool:
    metadata = Metadata.from_dict(entry.data[CONF_METADATA])
    cloud = CloudClient(
        async_get_clientsession(hass), entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
    )
    coordinator = MotionCoordinator(hass, entry, cloud, metadata)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    registry = async_get(hass)
    registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, metadata.gateway_mac)},
        name=metadata.gateway_name,
        manufacturer="Motionblinds",
        model="Wi-Fi bridge",
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(
        async_track_time_interval(hass, coordinator.async_refresh_metadata, timedelta(hours=1))
    )
    entry.async_create_background_task(
        hass, coordinator.async_refresh_metadata(), "Motionblinds metadata"
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MotionConfigEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()
        return True
    return False
