"""Entities share cloud-provided metadata and locally read status."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Blind
from .const import DOMAIN
from .coordinator import MotionCoordinator


class MotionEntity(CoordinatorEntity[MotionCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: MotionCoordinator, blind: Blind, key: str) -> None:
        super().__init__(coordinator)
        self.blind = blind
        self._attr_unique_id = f"{blind.identity}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, blind.identity)},
            name=blind.name,
            manufacturer="Motionblinds",
            model="Bidirectional blind",
            via_device=(DOMAIN, coordinator.metadata.gateway_mac),
        )

    @property
    def available(self) -> bool:
        return super().available and self.blind.identity in (self.coordinator.data or {})

    @property
    def status(self):
        return (self.coordinator.data or {}).get(self.blind.identity, {})
