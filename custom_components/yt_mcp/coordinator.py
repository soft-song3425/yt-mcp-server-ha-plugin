"""Data update coordinators: one for health (status.json), one for analytics (stats.json)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import YtMcpAuthError, YtMcpClient, YtMcpError
from .const import DOMAIN, EVENT_VIDEO_WATCHED, LOGGER


@dataclass
class YtMcpData:
    """Runtime data stored on the config entry."""

    client: YtMcpClient
    status: YtMcpStatusCoordinator
    stats: YtMcpStatsCoordinator | None  # None when the server predates /admin/stats.json


type YtMcpConfigEntry = ConfigEntry[YtMcpData]


class _YtMcpCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    config_entry: YtMcpConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: YtMcpConfigEntry, client: YtMcpClient, kind: str, interval: timedelta
    ) -> None:
        super().__init__(hass, LOGGER, config_entry=entry, name=f"{DOMAIN} {kind}", update_interval=interval)
        self.client = client

    async def _fetch(self) -> dict[str, Any]:
        raise NotImplementedError

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._fetch()
        except YtMcpAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except YtMcpError as err:
            raise UpdateFailed(str(err)) from err


class YtMcpStatusCoordinator(_YtMcpCoordinator):
    """Polls /admin/status.json."""

    def __init__(self, hass: HomeAssistant, entry: YtMcpConfigEntry, client: YtMcpClient, interval: timedelta) -> None:
        super().__init__(hass, entry, client, "status", interval)

    async def _fetch(self) -> dict[str, Any]:
        return await self.client.status()


class YtMcpStatsCoordinator(_YtMcpCoordinator):
    """Polls /admin/stats.json and fires yt_mcp_video_watched when a new watch shows up."""

    def __init__(self, hass: HomeAssistant, entry: YtMcpConfigEntry, client: YtMcpClient, interval: timedelta) -> None:
        super().__init__(hass, entry, client, "stats", interval)

    async def _fetch(self) -> dict[str, Any]:
        new = await self.client.stats()
        self._maybe_fire_watched(self.data, new)
        return new

    def _maybe_fire_watched(self, old: dict[str, Any] | None, new: dict[str, Any]) -> None:
        """Fire once per newly detected watch; never for the value already there at startup."""
        if not old:
            return
        before = (old.get("last_watched") or {}).get("at")
        latest = new.get("last_watched") or {}
        if latest.get("at") and latest.get("at") != before:
            self.hass.bus.async_fire(
                EVENT_VIDEO_WATCHED,
                {
                    "entry_id": self.config_entry.entry_id,
                    "title": latest.get("title"),
                    "channel": latest.get("channel"),
                    "playlist": latest.get("playlist"),
                    "theme": latest.get("theme"),
                    "minutes": latest.get("minutes"),
                    "watched_at": latest.get("at"),
                },
            )
