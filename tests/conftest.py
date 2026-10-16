"""Fixtures for the yt-mcp integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from homeassistant.const import CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.yt_mcp.const import DOMAIN, STATS_PATH, STATUS_PATH

URL = "https://yt.example.test"
TOKEN = "t" * 43
FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ in every test."""
    return


@pytest.fixture
def status_json() -> dict[str, Any]:
    return load("status.json")


@pytest.fixture
def stats_json() -> dict[str, Any]:
    return load("stats.json")


@pytest.fixture
def mock_server(aioclient_mock: AiohttpClientMocker, status_json, stats_json) -> AiohttpClientMocker:
    aioclient_mock.get(f"{URL}{STATUS_PATH}", json=status_json)
    aioclient_mock.get(f"{URL}{STATS_PATH}", json=stats_json)
    return aioclient_mock


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="yt-mcp (yt.example.test)",
        unique_id=URL,
        data={CONF_URL: URL, CONF_TOKEN: TOKEN, CONF_VERIFY_SSL: True},
    )
