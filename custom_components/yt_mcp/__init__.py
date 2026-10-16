"""yt-mcp: health and playlist analytics from a yt-mcp server in Home Assistant."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import YtMcpAuthError, YtMcpClient, YtMcpError, YtMcpNotSupportedError
from .const import (
    CONF_STATS_INTERVAL,
    CONF_STATUS_INTERVAL,
    DEFAULT_STATS_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DOMAIN,
    LOGGER,
    SUPPORTED_STATS_SCHEMA,
)
from .coordinator import YtMcpConfigEntry, YtMcpData, YtMcpStatsCoordinator, YtMcpStatusCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: YtMcpConfigEntry) -> bool:
    """Set up yt-mcp from a config entry."""
    session = async_get_clientsession(hass, verify_ssl=entry.data.get(CONF_VERIFY_SSL, True))
    client = YtMcpClient(session, entry.data[CONF_URL], entry.data[CONF_TOKEN])

    status = YtMcpStatusCoordinator(
        hass, entry, client, timedelta(minutes=entry.options.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL))
    )
    await status.async_config_entry_first_refresh()

    # Analytics need yt-mcp 2.11.0. An older server still gets the health entities.
    stats: YtMcpStatsCoordinator | None = None
    issue_id = f"stats_unsupported_{entry.entry_id}"
    try:
        first = await client.stats()
    except YtMcpNotSupportedError:
        LOGGER.warning("%s has no /admin/stats.json (yt-mcp older than 2.11.0): health entities only", client.url)
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="stats_unsupported",
            translation_placeholders={"url": client.url, "version": str(status.data.get("version", "?"))},
        )
    except YtMcpAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except YtMcpError as err:
        raise ConfigEntryNotReady(str(err)) from err
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        schema = first.get("schema")
        if isinstance(schema, int) and schema > SUPPORTED_STATS_SCHEMA:
            LOGGER.warning(
                "stats.json schema %s is newer than this integration understands (%s): update the integration",
                schema,
                SUPPORTED_STATS_SCHEMA,
            )
        stats = YtMcpStatsCoordinator(
            hass, entry, client, timedelta(minutes=entry.options.get(CONF_STATS_INTERVAL, DEFAULT_STATS_INTERVAL))
        )
        stats.async_set_updated_data(first)

    entry.runtime_data = YtMcpData(client=client, status=status, stats=stats)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: YtMcpConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: YtMcpConfigEntry) -> None:
    """Drop the repair issue when the entry goes away."""
    ir.async_delete_issue(hass, DOMAIN, f"stats_unsupported_{entry.entry_id}")
