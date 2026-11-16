"""Diagnostics deliberately omit account, address, and device identifiers."""

from homeassistant.core import HomeAssistant

from . import MotionConfigEntry
from .const import (
    CONF_BATTERY_METHOD,
    CONF_POLL_INTERVAL,
    DEFAULT_BATTERY_METHOD,
    DEFAULT_POLL_INTERVAL,
)

FIELDS = {
    "currentPosition",
    "currentAngle",
    "currentState",
    "operation",
    "type",
    "voltageMode",
    "wirelessMode",
    "batteryLevel",
    "RSSI",
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: MotionConfigEntry):
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None:
        return {"loaded": False, "version": 1}
    return {
        "version": 1,
        "cloud_metadata_available": coordinator.cloud_metadata_available,
        "local_update_success": coordinator.last_update_success,
        "blind_count": len(coordinator.metadata.blinds),
        "poll_interval": entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        "battery_method": entry.options.get(CONF_BATTERY_METHOD, DEFAULT_BATTERY_METHOD),
        "local_status": {
            f"blind_{index}": {
                key: value
                for key, value in coordinator.data.get(blind.identity, {}).items()
                if key in FIELDS and isinstance(value, (int, float, bool))
            }
            for index, blind in enumerate(coordinator.metadata.blinds, start=1)
        },
    }
