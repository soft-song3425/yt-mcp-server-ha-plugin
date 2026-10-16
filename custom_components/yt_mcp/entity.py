"""Base entity: one service device per yt-mcp server."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import YtMcpConfigEntry, _YtMcpCoordinator


class YtMcpEntity(CoordinatorEntity[_YtMcpCoordinator]):
    """Common device info and unique ids."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: _YtMcpCoordinator, entry: YtMcpConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        status = entry.runtime_data.status.data if getattr(entry, "runtime_data", None) else {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="yt-mcp",
            manufacturer="yt-mcp",
            model="YouTube playlist server",
            sw_version=(status or {}).get("version"),
            configuration_url=f"{entry.runtime_data.client.url}/admin",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def data(self) -> dict[str, Any]:
        return self.coordinator.data or {}
