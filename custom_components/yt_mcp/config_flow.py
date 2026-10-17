"""Config flow for yt-mcp: server URL + read-only status token."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    YtMcpAuthError,
    YtMcpClient,
    YtMcpConnectionError,
    YtMcpError,
    YtMcpForbiddenError,
    YtMcpNotSupportedError,
    normalize_token,
    normalize_url,
)
from .const import (
    CONF_STATS_INTERVAL,
    CONF_STATUS_INTERVAL,
    DEFAULT_STATS_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DOMAIN,
    LOGGER,
    MIN_STATS_INTERVAL,
    MIN_STATUS_INTERVAL,
)
from .coordinator import YtMcpConfigEntry

TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
URL_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))


def _user_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_URL, default=defaults.get(CONF_URL, vol.UNDEFINED)): URL_SELECTOR,
            vol.Required(CONF_TOKEN): TOKEN_SELECTOR,
            vol.Required(CONF_VERIFY_SSL, default=defaults.get(CONF_VERIFY_SSL, True)): bool,
        }
    )


async def _validate(hass: HomeAssistant, url: str, token: str, verify_ssl: bool) -> dict[str, Any]:
    """Fetch status.json once; raises YtMcpError subclasses. Returns the status payload."""
    client = YtMcpClient(async_get_clientsession(hass, verify_ssl=verify_ssl), url, token)
    status = await client.status()
    if "ok" not in status or "problems" not in status:
        raise YtMcpConnectionError("not a yt-mcp status.json")
    return status


def _error_key(err: YtMcpError) -> str:
    if isinstance(err, YtMcpAuthError):
        return "invalid_auth"
    if isinstance(err, YtMcpForbiddenError):
        return "forbidden"
    if isinstance(err, YtMcpNotSupportedError):
        return "not_supported"
    return "cannot_connect"


class YtMcpConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for yt-mcp."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = normalize_url(user_input[CONF_URL])
            token = normalize_token(user_input[CONF_TOKEN])
            await self.async_set_unique_id(url.lower())
            self._abort_if_unique_id_configured()
            try:
                await _validate(self.hass, url, token, user_input[CONF_VERIFY_SSL])
            except YtMcpError as err:
                LOGGER.debug("validation of %s failed: %s", url, err)
                errors["base"] = _error_key(err)
            except Exception:  # noqa: BLE001
                LOGGER.exception("unexpected error validating %s", url)
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"yt-mcp ({urlparse(url).hostname or url})",
                    data={CONF_URL: url, CONF_TOKEN: token, CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL]},
                )
        return self.async_show_form(step_id="user", data_schema=_user_schema(user_input or {}), errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The token was refused: ask for a new one."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            token = normalize_token(user_input[CONF_TOKEN])
            try:
                await _validate(self.hass, entry.data[CONF_URL], token, entry.data.get(CONF_VERIFY_SSL, True))
            except YtMcpError as err:
                errors["base"] = _error_key(err)
            except Exception:  # noqa: BLE001
                LOGGER.exception("unexpected error during reauth")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_TOKEN: token})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): TOKEN_SELECTOR}),
            errors=errors,
            description_placeholders={"url": entry.data[CONF_URL]},
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change the server URL (and token) of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            url = normalize_url(user_input[CONF_URL])
            token = normalize_token(user_input[CONF_TOKEN])
            other = self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, url.lower())
            if other is not None and other.entry_id != entry.entry_id:
                return self.async_abort(reason="already_configured")
            try:
                await _validate(self.hass, url, token, user_input[CONF_VERIFY_SSL])
            except YtMcpError as err:
                errors["base"] = _error_key(err)
            except Exception:  # noqa: BLE001
                LOGGER.exception("unexpected error during reconfigure")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=url.lower(),
                    title=f"yt-mcp ({urlparse(url).hostname or url})",
                    data_updates={CONF_URL: url, CONF_TOKEN: token, CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL]},
                )
        return self.async_show_form(
            step_id="reconfigure", data_schema=_user_schema(user_input or entry.data), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: YtMcpConfigEntry) -> YtMcpOptionsFlow:
        return YtMcpOptionsFlow()


class YtMcpOptionsFlow(OptionsFlowWithReload):
    """Polling intervals."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={k: int(v) for k, v in user_input.items()})
        opts = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_STATUS_INTERVAL, default=opts.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL)
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_STATUS_INTERVAL,
                            max=60,
                            step=1,
                            unit_of_measurement="min",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_STATS_INTERVAL, default=opts.get(CONF_STATS_INTERVAL, DEFAULT_STATS_INTERVAL)
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_STATS_INTERVAL,
                            max=240,
                            step=1,
                            unit_of_measurement="min",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
