"""Cover commands go exclusively through the cloud."""

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import MotionConfigEntry
from .api import AuthenticationError, CloudError
from .entity import MotionEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: MotionConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        MotionCover(entry.runtime_data, blind, "cover")
        for blind in entry.runtime_data.metadata.blinds
    )


class MotionCover(MotionEntity, CoverEntity):
    _attr_name = None
    _attr_device_class = CoverDeviceClass.SHADE
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    @property
    def current_cover_position(self) -> int | None:
        position = self.status.get("currentPosition")
        return 100 - position if isinstance(position, int) else None

    @property
    def is_closed(self) -> bool | None:
        position = self.current_cover_position
        return position == 0 if position is not None else None

    @property
    def is_opening(self) -> bool:
        return self.status.get("operation") == 1 and self.current_cover_position != 100

    @property
    def is_closing(self) -> bool:
        return self.status.get("operation") == 0 and self.current_cover_position != 0

    async def _command(self, data: dict[str, int]) -> None:
        try:
            await self.coordinator.async_command(self.blind, data)
        except AuthenticationError as err:
            self.coordinator.entry.async_start_reauth(self.hass)
            raise HomeAssistantError("Motionblinds cloud login needs updating") from err
        except CloudError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_open_cover(self, **kwargs) -> None:
        await self._command({"operation": 1})

    async def async_close_cover(self, **kwargs) -> None:
        await self._command({"operation": 0})

    async def async_stop_cover(self, **kwargs) -> None:
        await self._command({"operation": 2})

    async def async_set_cover_position(self, **kwargs) -> None:
        await self._command({"targetPosition": 100 - kwargs[ATTR_POSITION]})
