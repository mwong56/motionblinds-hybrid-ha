"""Local polling, independent cloud metadata, and command readback."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AuthenticationError,
    Blind,
    CloudClient,
    CloudError,
    LocalClient,
    LocalError,
    Metadata,
)
from .const import CONF_METADATA, CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class MotionCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, cloud: CloudClient, metadata: Metadata
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            ),
        )
        self.entry = entry
        self.cloud = cloud
        self.local = LocalClient(entry.options.get(CONF_HOST, entry.data[CONF_HOST]))
        self.metadata = metadata
        self._poll_lock = asyncio.Lock()
        self._command_locks: dict[str, asyncio.Lock] = {}
        self._readback_tasks: dict[str, asyncio.Task] = {}
        self.cloud_metadata_available: bool | None = None

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        async with self._poll_lock:
            try:
                gateway, discovered = await self.local.discover()
                if gateway != self.metadata.gateway_mac:
                    raise LocalError("Gateway identity changed")
            except LocalError as err:
                raise UpdateFailed("Local gateway is unavailable or its identity changed") from err
            result = {}
            for blind in self.metadata.blinds:
                if blind.identity not in discovered:
                    continue
                try:
                    result[blind.identity] = await self.local.read(blind)
                except LocalError:
                    continue
            if not result:
                raise UpdateFailed("No configured blind returned local status")
            return result

    async def async_refresh_metadata(self, _now=None) -> None:
        """Cloud failures never stop local status polling."""
        try:
            gateway, local_macs = await self.local.discover()
            if gateway != self.metadata.gateway_mac:
                return
            metadata = await self.cloud.metadata(gateway, local_macs)
            if metadata.account_id != self.metadata.account_id:
                raise AuthenticationError("Cloud account identity changed")
        except AuthenticationError:
            self.cloud_metadata_available = False
            self.entry.async_start_reauth(self.hass)
            return
        except CloudError, LocalError:
            self.cloud_metadata_available = False
            return
        self.cloud_metadata_available = True
        if metadata != self.metadata:
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, CONF_METADATA: metadata.to_dict()}
            )
            self.hass.async_create_task(self.hass.config_entries.async_reload(self.entry.entry_id))

    async def async_command(self, blind: Blind, data: dict[str, int]) -> None:
        """Serialize per blind; never optimistically report an unobserved position."""
        lock = self._command_locks.setdefault(blind.identity, asyncio.Lock())
        async with lock:
            await self.cloud.command(blind, data)
        existing = self._readback_tasks.get(blind.identity)
        if existing:
            existing.cancel()
        self._readback_tasks[blind.identity] = self.entry.async_create_background_task(
            self.hass, self._readback(blind, data), f"{DOMAIN} command readback"
        )

    async def _readback(self, blind: Blind, command: dict[str, int]) -> None:
        """Poll local cache quickly after commands, then resume ordinary polling."""
        target = command.get("targetPosition")
        if command.get("operation") in (0, 1):
            target = 100 if command["operation"] == 0 else 0
        stable = 0
        try:
            for _ in range(30):
                await asyncio.sleep(2)
                async with self._poll_lock:
                    try:
                        status = await self.local.read(blind)
                    except LocalError:
                        continue
                    previous = (self.data or {}) if self.last_update_success else {}
                    self.async_set_updated_data({**previous, blind.identity: status})
                arrived = (
                    status.get("currentPosition") == target
                    if target is not None
                    else status.get("operation") == 2
                )
                stable = stable + 1 if arrived else 0
                if stable >= 2:
                    break
        finally:
            if self._readback_tasks.get(blind.identity) is asyncio.current_task():
                self._readback_tasks.pop(blind.identity, None)

    async def async_stop(self) -> None:
        tasks = list(self._readback_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._readback_tasks.clear()
