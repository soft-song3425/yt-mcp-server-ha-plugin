"""Small async client for the yt-mcp server's read-only JSON endpoints.

GET /admin/status.json  health (yt-mcp 2.10.0+)
GET /admin/stats.json   playlist analytics (yt-mcp 2.11.0+)

Both take the read-only status token (python -m ytmcp gen-status-token) as a bearer
token. The token opens nothing else on the server.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .const import REQUEST_TIMEOUT, STATS_PATH, STATUS_PATH


class YtMcpError(Exception):
    """Any failure talking to the server."""


class YtMcpConnectionError(YtMcpError):
    """Server unreachable, timed out, or answered with an unexpected status."""


class YtMcpAuthError(YtMcpError):
    """The token was refused (401/403)."""


class YtMcpNotSupportedError(YtMcpError):
    """The endpoint does not exist on this server version (404)."""


def normalize_url(url: str) -> str:
    """Trim whitespace and trailing slashes; add https:// when no scheme is given."""
    url = url.strip().rstrip("/")
    if url and "://" not in url:
        url = f"https://{url}"
    return url


def normalize_token(token: str) -> str:
    """Accept the token with or without a leading 'Bearer '."""
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


class YtMcpClient:
    """Fetches status.json and stats.json."""

    def __init__(self, session: aiohttp.ClientSession, url: str, token: str) -> None:
        self._session = session
        self.url = normalize_url(url)
        self._token = normalize_token(token)

    async def _get(self, path: str) -> dict[str, Any]:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT.total_seconds()):
                resp = await self._session.get(
                    f"{self.url}{path}",
                    headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
                    allow_redirects=False,
                )
                async with resp:
                    if resp.status in (401, 403):
                        raise YtMcpAuthError(f"token refused by {path} (HTTP {resp.status})")
                    if resp.status == 404:
                        raise YtMcpNotSupportedError(f"{path} not found: server too old or wrong URL")
                    if resp.status != 200:
                        raise YtMcpConnectionError(f"{path} answered HTTP {resp.status}")
                    try:
                        data = await resp.json(content_type=None)
                    except ValueError as err:
                        raise YtMcpConnectionError(f"{path} did not return JSON") from err
        except TimeoutError as err:
            raise YtMcpConnectionError(f"timeout fetching {path}") from err
        except aiohttp.ClientError as err:
            raise YtMcpConnectionError(f"error fetching {path}: {err}") from err
        if not isinstance(data, dict):
            raise YtMcpConnectionError(f"{path} returned unexpected JSON")
        return data

    async def status(self) -> dict[str, Any]:
        """Health report: ok, problems, token, poller, backups, quota."""
        return await self._get(STATUS_PATH)

    async def stats(self) -> dict[str, Any]:
        """Analytics report: today, week, month, playlists, themes, quota history."""
        return await self._get(STATS_PATH)
