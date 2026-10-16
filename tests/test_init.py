"""Setup, entities, old servers, auth failures, the watched event, diagnostics."""

from __future__ import annotations

import copy
from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_capture_events, async_fire_time_changed
from pytest_homeassistant_custom_component.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.yt_mcp.const import DOMAIN, EVENT_VIDEO_WATCHED, STATS_PATH, STATUS_PATH

from .conftest import TOKEN, URL


def _state(hass: HomeAssistant, unique_suffix: str, platform: str = "sensor") -> str:
    reg = er.async_get(hass)
    entry = next(e for e in reg.entities.values() if e.unique_id.endswith(f"_{unique_suffix}") and e.domain == platform)
    st = hass.states.get(entry.entity_id)
    assert st is not None, entry.entity_id
    return st


async def _setup(hass: HomeAssistant, config_entry) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_creates_entities(hass: HomeAssistant, mock_server, config_entry) -> None:
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    assert _state(hass, "problem", "binary_sensor").state == "off"
    assert _state(hass, "google_token", "binary_sensor").state == "off"
    assert _state(hass, "quota_used").state == "1240"
    assert _state(hass, "backup_age").state == "5.2"
    assert _state(hass, "last_poll").state == "2026-10-16T15:23:00+00:00"

    assert _state(hass, "watched_today").state == "1"
    assert _state(hass, "watched_7d").state == "4"
    assert _state(hass, "backlog_items").state == "9"
    assert _state(hass, "days_to_empty").state == "90.0"
    lw = _state(hass, "last_watched")
    assert lw.state == "War update" and lw.attributes["channel"] == "DW News"
    assert lw.attributes["theme"] == "World Politics"
    assert _state(hass, "stalest_wait").state == "46"
    assert _state(hass, "quota_remaining").state == "8995"

    # per playlist and per theme
    nv = _state(hass, "playlist_items_PLnew")
    assert nv.state == "8" and nv.name == "yt-mcp New Videos backlog"
    assert _state(hass, "playlist_watched_7d_PLnew").state == "4"
    assert _state(hass, "playlist_days_to_empty_PLlong").state == "unknown"
    wp = _state(hass, "theme_world_politics")
    assert wp.state == "3" and wp.attributes["status"] == "shrinking"
    assert wp.name == "yt-mcp World Politics backlog"
    assert hass.states.get("sensor.yt_mcp_economy_money_backlog") is not None

    dev = next(iter(er.async_get(hass).entities.values())).device_id
    assert dev is not None


async def test_token_never_lands_in_state_or_diagnostics(
    hass: HomeAssistant, hass_client, mock_server, config_entry
) -> None:
    await _setup(hass, config_entry)
    for st in hass.states.async_all():
        assert TOKEN not in str(st.attributes) and TOKEN not in st.state
    diag = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)
    assert diag["entry"]["data"]["token"] == "**REDACTED**"
    assert diag["stats"]["data"]["schema"] == 1


async def test_old_server_gets_health_only_and_a_repair(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status_json, config_entry
) -> None:
    aioclient_mock.get(f"{URL}{STATUS_PATH}", json=status_json)
    aioclient_mock.get(f"{URL}{STATS_PATH}", status=404)
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data.stats is None
    assert _state(hass, "problem", "binary_sensor").state == "off"
    assert not [e for e in er.async_get(hass).entities.values() if e.unique_id.endswith("_watched_today")]
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"stats_unsupported_{config_entry.entry_id}")


async def test_refused_token_starts_reauth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry
) -> None:
    aioclient_mock.get(f"{URL}{STATUS_PATH}", status=401)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_unreachable_server_retries(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, config_entry
) -> None:
    aioclient_mock.get(f"{URL}{STATUS_PATH}", status=502)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_problem_turns_on_with_reasons(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status_json, stats_json, config_entry
) -> None:
    bad = {
        **status_json,
        "ok": False,
        "google_token_usable": False,
        "problems": ["google token not usable: re-authorise YouTube on /admin"],
    }
    aioclient_mock.get(f"{URL}{STATUS_PATH}", json=bad)
    aioclient_mock.get(f"{URL}{STATS_PATH}", json=stats_json)
    await _setup(hass, config_entry)
    p = _state(hass, "problem", "binary_sensor")
    assert p.state == "on" and p.attributes["problems"] == bad["problems"]
    assert _state(hass, "google_token", "binary_sensor").state == "on"


async def test_new_watch_fires_event_and_new_playlist_appears(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status_json, stats_json, config_entry
) -> None:
    aioclient_mock.get(f"{URL}{STATUS_PATH}", json=status_json)
    aioclient_mock.get(f"{URL}{STATS_PATH}", json=stats_json)
    await _setup(hass, config_entry)
    events = async_capture_events(hass, EVENT_VIDEO_WATCHED)

    # same data again: no event
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=16))
    await hass.async_block_till_done()
    assert events == []

    newer = copy.deepcopy(stats_json)
    newer["last_watched"] = {
        **newer["last_watched"],
        "title": "Rail in Japan",
        "channel": "Not Just Bikes",
        "at": "2026-10-16T18:00:00+00:00",
    }
    newer["playlists"].append(
        {**newer["playlists"][1], "id": "PLthird", "name": "Discovery Queue", "key": "discovery_queue", "items": 50}
    )
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{URL}{STATUS_PATH}", json=status_json)
    aioclient_mock.get(f"{URL}{STATS_PATH}", json=newer)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=32))
    await hass.async_block_till_done()

    assert len(events) == 1 and events[0].data["title"] == "Rail in Japan"
    assert events[0].data["channel"] == "Not Just Bikes"
    assert _state(hass, "last_watched").state == "Rail in Japan"
    assert _state(hass, "playlist_items_PLthird").state == "50"


async def test_unload(hass: HomeAssistant, mock_server, config_entry) -> None:
    await _setup(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED
