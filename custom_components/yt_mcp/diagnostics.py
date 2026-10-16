"""Diagnostics: the config entry (token redacted) and the last status and stats payloads."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant

from .coordinator import YtMcpConfigEntry

TO_REDACT = {CONF_TOKEN}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: YtMcpConfigEntry) -> dict[str, Any]:
    rd = entry.runtime_data
    return {
        "entry": {"data": async_redact_data(dict(entry.data), TO_REDACT), "options": dict(entry.options)},
        "status": {"last_update_success": rd.status.last_update_success, "data": rd.status.data},
        "stats": None
        if rd.stats is None
        else {"last_update_success": rd.stats.last_update_success, "data": rd.stats.data},
    }
