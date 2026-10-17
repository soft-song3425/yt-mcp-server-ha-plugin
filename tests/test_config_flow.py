"""Config, reauth, reconfigure and options flows."""

from __future__ import annotations

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.yt_mcp.const import CONF_STATS_INTERVAL, CONF_STATUS_INTERVAL, DOMAIN, STATUS_PATH

from .conftest import TOKEN, URL


async def test_user_flow_creates_entry(hass: HomeAssistant, mock_server: AiohttpClientMocker) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["errors"] == {}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "yt.example.test/ ", CONF_TOKEN: f"Bearer {TOKEN}", CONF_VERIFY_SSL: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "yt-mcp (yt.example.test)"
    assert result["data"] == {CONF_URL: URL, CONF_TOKEN: TOKEN, CONF_VERIFY_SSL: True}
    # the token went out as a bearer header
    _, _, _, headers = mock_server.mock_calls[0]
    assert headers["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize(
    ("status", "error"), [(401, "invalid_auth"), (403, "forbidden"), (404, "not_supported"), (502, "cannot_connect")]
)
async def test_user_flow_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status_json, status: int, error: str
) -> None:
    aioclient_mock.get(f"{URL}{STATUS_PATH}", status=status)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: URL, CONF_TOKEN: TOKEN, CONF_VERIFY_SSL: True}
    )
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": error}
    # recovers once the server answers
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{URL}{STATUS_PATH}", json=status_json)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: URL, CONF_TOKEN: TOKEN, CONF_VERIFY_SSL: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_not_yt_mcp_json(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{URL}{STATUS_PATH}", json={"hello": "world"})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: URL, CONF_TOKEN: TOKEN, CONF_VERIFY_SSL: True}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_duplicate_aborts(hass: HomeAssistant, mock_server, config_entry) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: URL + "/", CONF_TOKEN: TOKEN, CONF_VERIFY_SSL: True}
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"


async def test_reauth(hass: HomeAssistant, mock_server, config_entry) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TOKEN: "new-token"})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_TOKEN] == "new-token"


async def test_reconfigure(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status_json, mock_server, config_entry
) -> None:
    config_entry.add_to_hass(hass)
    new_url = "https://other.example.test"
    aioclient_mock.get(f"{new_url}{STATUS_PATH}", json=status_json)
    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: new_url, CONF_TOKEN: TOKEN, CONF_VERIFY_SSL: False}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_URL] == new_url and config_entry.data[CONF_VERIFY_SSL] is False
    assert config_entry.unique_id == new_url


async def test_options(hass: HomeAssistant, mock_server, config_entry) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_STATUS_INTERVAL: 2, CONF_STATS_INTERVAL: 30}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_STATUS_INTERVAL: 2, CONF_STATS_INTERVAL: 30}
    await hass.async_block_till_done()
    assert config_entry.runtime_data.stats.update_interval.total_seconds() == 30 * 60
