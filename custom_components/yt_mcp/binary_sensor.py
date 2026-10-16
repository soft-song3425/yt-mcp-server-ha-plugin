"""Binary sensors: overall problem, Google authorisation, quota, positioning review due."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import YtMcpConfigEntry, _YtMcpCoordinator
from .entity import YtMcpEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class YtMcpBinaryDescription(BinarySensorEntityDescription):
    is_on_fn: Callable[[dict[str, Any]], bool | None]
    attr_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


STATUS_BINARY: tuple[YtMcpBinaryDescription, ...] = (
    YtMcpBinaryDescription(
        key="problem",
        translation_key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda d: not d.get("ok", False),
        attr_fn=lambda d: {"problems": list(d.get("problems") or []), "checked_at": d.get("checked_at")},
    ),
    YtMcpBinaryDescription(
        key="google_token",
        translation_key="google_token",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda d: not d.get("google_token_usable", False),
    ),
    YtMcpBinaryDescription(
        key="quota_exhausted",
        translation_key="quota_exhausted",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda d: bool((d.get("quota") or {}).get("google_reported_exhausted")),
    ),
)

STATS_BINARY: tuple[YtMcpBinaryDescription, ...] = (
    YtMcpBinaryDescription(
        key="positioning_review_due",
        translation_key="positioning_review_due",
        is_on_fn=lambda d: d.get("positioning_review_due"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: YtMcpConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    rd = entry.runtime_data
    entities: list[YtMcpBinarySensor] = [YtMcpBinarySensor(rd.status, entry, d) for d in STATUS_BINARY]
    if rd.stats is not None:
        entities += [YtMcpBinarySensor(rd.stats, entry, d) for d in STATS_BINARY]
    async_add_entities(entities)


class YtMcpBinarySensor(YtMcpEntity, BinarySensorEntity):
    entity_description: YtMcpBinaryDescription

    def __init__(
        self, coordinator: _YtMcpCoordinator, entry: YtMcpConfigEntry, description: YtMcpBinaryDescription
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.is_on_fn(self.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attr_fn
        return fn(self.data) if fn else None
