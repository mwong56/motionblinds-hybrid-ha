"""Battery and RSSI sensors use only local readings."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricPotential,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MotionConfigEntry
from .api import battery_percent
from .const import CONF_BATTERY_METHOD, DEFAULT_BATTERY_METHOD
from .entity import MotionEntity

SENSORS = (
    SensorEntityDescription(
        key="battery",
        name="Battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="voltage",
        name="Battery voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="rssi",
        name="Signal strength",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: MotionConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        MotionSensor(entry.runtime_data, blind, description)
        for blind in entry.runtime_data.metadata.blinds
        for description in SENSORS
    )


class MotionSensor(MotionEntity, SensorEntity):
    def __init__(self, coordinator, blind, description) -> None:
        super().__init__(coordinator, blind, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        match self.entity_description.key:
            case "battery":
                return battery_percent(
                    self.status,
                    self.coordinator.entry.options.get(CONF_BATTERY_METHOD, DEFAULT_BATTERY_METHOD),
                )
            case "voltage":
                value = self.status.get("batteryLevel")
                return (
                    value / 100
                    if self.status.get("voltageMode") == 1 and isinstance(value, (int, float))
                    else None
                )
            case "rssi":
                return self.status.get("RSSI")
        return None

    @property
    def extra_state_attributes(self):
        if self.entity_description.key == "battery":
            return {
                "estimation_method": self.coordinator.entry.options.get(
                    CONF_BATTERY_METHOD, DEFAULT_BATTERY_METHOD
                ),
                "battery_voltage": self.status.get("batteryLevel", 0) / 100
                if isinstance(self.status.get("batteryLevel"), (int, float))
                else None,
            }
        return None
