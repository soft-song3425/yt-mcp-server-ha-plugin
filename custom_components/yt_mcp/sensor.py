"""Sensors from status.json (health) and stats.json (analytics).

Fixed sensors cover the server and the totals across all tracked playlists. Each
tracked playlist and each theme gets its own sensors, added as they appear in
stats.json; one that disappears (untracked playlist, renamed theme) goes unavailable
and can be removed from the entity settings.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import UNIT_UNITS, UNIT_VIDEOS
from .coordinator import YtMcpConfigEntry, YtMcpStatsCoordinator, _YtMcpCoordinator
from .entity import YtMcpEntity

PARALLEL_UPDATES = 0
MAX_STATE_LEN = 255


def _ts(value: Any) -> datetime | None:
    return dt_util.parse_datetime(value) if isinstance(value, str) and value else None


def _get(d: dict[str, Any], *path: str) -> Any:
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)  # type: ignore[assignment]
    return d


def _last_poll(d: dict[str, Any]) -> datetime | None:
    checked, ago = _ts(d.get("checked_at")), _get(d, "poller", "last_run_min_ago")
    if checked is None or ago is None:
        return None
    return checked - timedelta(minutes=ago)


@dataclass(frozen=True, kw_only=True)
class YtMcpSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], StateType | datetime]
    attr_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _count(key: str, fn: Callable[[dict[str, Any]], StateType], **kw: Any) -> YtMcpSensorDescription:
    return YtMcpSensorDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=UNIT_VIDEOS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=fn,
        **kw,
    )


def _hours(key: str, fn: Callable[[dict[str, Any]], StateType], **kw: Any) -> YtMcpSensorDescription:
    return YtMcpSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=fn,
        **kw,
    )


def _days(key: str, fn: Callable[[dict[str, Any]], StateType], **kw: Any) -> YtMcpSensorDescription:
    return YtMcpSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=fn,
        **kw,
    )


STATUS_SENSORS: tuple[YtMcpSensorDescription, ...] = (
    YtMcpSensorDescription(
        key="last_poll",
        translation_key="last_poll",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_last_poll,
        attr_fn=lambda d: {
            "in_busy_hours": _get(d, "poller", "in_busy_hours"),
            "last_result": _get(d, "poller", "last_result"),
        },
    ),
    YtMcpSensorDescription(
        key="poll_interval",
        translation_key="poll_interval",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _get(d, "poller", "current_interval_min"),
    ),
    _hours("backup_age", lambda d: d.get("backup_age_h"), entity_category=EntityCategory.DIAGNOSTIC),
    YtMcpSensorDescription(
        key="quota_used",
        translation_key="quota_used",
        native_unit_of_measurement=UNIT_UNITS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _get(d, "quota", "spent"),
        attr_fn=lambda d: {"budget": _get(d, "quota", "budget"), "percent": _get(d, "quota", "pct")},
    ),
    YtMcpSensorDescription(
        key="quota_used_pct",
        translation_key="quota_used_pct",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _get(d, "quota", "pct"),
    ),
    _count("metadata_pending", lambda d: d.get("metadata_pending"), entity_category=EntityCategory.DIAGNOSTIC),
)


def _week_attrs(d: dict[str, Any]) -> dict[str, Any]:
    w = d.get("week") or {}
    return {
        "added": w.get("added"),
        "dropped": w.get("dropped"),
        "net": w.get("net"),
        "previous_week": w.get("previous"),
    }


def _last_watched_attrs(d: dict[str, Any]) -> dict[str, Any]:
    lw = d.get("last_watched") or {}
    return {
        "channel": lw.get("channel"),
        "playlist": lw.get("playlist"),
        "theme": lw.get("theme"),
        "minutes": lw.get("minutes"),
        "watched_at": lw.get("at"),
    }


def _title(d: dict[str, Any]) -> str | None:
    t = _get(d, "last_watched", "title")
    return t[:MAX_STATE_LEN] if isinstance(t, str) else None


def _stalest_days(d: dict[str, Any]) -> StateType:
    s = d.get("stalest") or []
    return s[0].get("days_waiting") if s else None


def _most_watched_theme(d: dict[str, Any]) -> str | None:
    m = d.get("most_watched_themes_7d") or []
    return m[0].get("theme") if m else None


STATS_SENSORS: tuple[YtMcpSensorDescription, ...] = (
    _count(
        "watched_today",
        lambda d: _get(d, "today", "watched"),
        attr_fn=lambda d: {"added": _get(d, "today", "added"), "net": _get(d, "today", "net")},
    ),
    _count("added_today", lambda d: _get(d, "today", "added")),
    _hours("watched_hours_today", lambda d: _get(d, "today", "watched_hours")),
    _count("watched_7d", lambda d: _get(d, "week", "watched"), attr_fn=_week_attrs),
    _count("added_7d", lambda d: _get(d, "week", "added")),
    _hours("watched_hours_7d", lambda d: _get(d, "week", "watched_hours")),
    YtMcpSensorDescription(
        key="watched_change_7d",
        translation_key="watched_change_7d",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _get(d, "week", "watched_change_pct"),
        attr_fn=lambda d: {"added_change_pct": _get(d, "week", "added_change_pct")},
    ),
    _count(
        "watched_30d",
        lambda d: _get(d, "month", "watched"),
        attr_fn=lambda d: {
            "added": _get(d, "month", "added"),
            "net": _get(d, "month", "net"),
            "watched_hours": _get(d, "month", "watched_hours"),
        },
    ),
    YtMcpSensorDescription(
        key="watched_per_day",
        translation_key="watched_per_day",
        native_unit_of_measurement="videos/d",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: _get(d, "month", "watched_per_day"),
        attr_fn=lambda d: {"added_per_day": _get(d, "month", "added_per_day")},
    ),
    _days("median_wait", lambda d: _get(d, "month", "median_wait_days")),
    _count("backlog_items", lambda d: _get(d, "backlog", "items")),
    _hours("backlog_hours", lambda d: _get(d, "backlog", "hours")),
    _days("days_to_empty", lambda d: _get(d, "backlog", "days_to_empty")),
    YtMcpSensorDescription(
        key="last_watched", translation_key="last_watched", value_fn=_title, attr_fn=_last_watched_attrs
    ),
    YtMcpSensorDescription(
        key="last_watched_at",
        translation_key="last_watched_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: _ts(_get(d, "last_watched", "at")),
    ),
    _days("stalest_wait", _stalest_days, attr_fn=lambda d: {"videos": d.get("stalest") or []}),
    YtMcpSensorDescription(
        key="most_watched_theme",
        translation_key="most_watched_theme",
        value_fn=_most_watched_theme,
        attr_fn=lambda d: {"themes": d.get("most_watched_themes_7d") or []},
    ),
    YtMcpSensorDescription(
        key="stalled_themes",
        translation_key="stalled_themes",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(d.get("stalled_themes_14d") or []),
        attr_fn=lambda d: {"themes": d.get("stalled_themes_14d") or []},
    ),
    YtMcpSensorDescription(
        key="attention",
        translation_key="attention",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(d.get("attention") or []),
        attr_fn=lambda d: {"items": d.get("attention") or []},
    ),
    YtMcpSensorDescription(
        key="quota_remaining",
        translation_key="quota_remaining",
        native_unit_of_measurement=UNIT_UNITS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _get(d, "quota", "remaining"),
        attr_fn=lambda d: {"history": _get(d, "quota", "history") or []},
    ),
    YtMcpSensorDescription(
        key="quota_reset",
        translation_key="quota_reset",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _ts(_get(d, "quota", "resets_at")),
    ),
)

# Per tracked playlist; value_fn gets the playlist's dict from stats.json "playlists".
PLAYLIST_SENSORS: tuple[YtMcpSensorDescription, ...] = (
    _count(
        "playlist_items",
        lambda p: p.get("items"),
        attr_fn=lambda p: {
            "playlist_id": p.get("id"),
            "avg_minutes": p.get("avg_minutes"),
            "top_themes": p.get("top_themes") or [],
            "net_per_day_14d": p.get("net_per_day_14d"),
            "added_7d": p.get("added_7d"),
            "net_7d": p.get("net_7d"),
            "added_30d": p.get("added_30d"),
            "watched_30d": p.get("watched_30d"),
            "watched_per_day_30d": p.get("watched_per_day_30d"),
            "median_wait_days_30d": p.get("median_wait_days_30d"),
        },
    ),
    _hours("playlist_hours", lambda p: p.get("hours")),
    _count(
        "playlist_watched_today",
        lambda p: p.get("watched_today"),
        attr_fn=lambda p: {"added_today": p.get("added_today")},
    ),
    _count("playlist_watched_7d", lambda p: p.get("watched_7d")),
    _days("playlist_days_to_empty", lambda p: p.get("days_to_empty")),
)

THEME_SENSOR = _count(
    "theme_items",
    lambda t: t.get("items"),
    attr_fn=lambda t: {
        "status": t.get("status"),
        "position": t.get("position"),
        "hours": t.get("hours"),
        "watched_per_week": t.get("watched_per_week"),
        "weeks_to_clear": t.get("weeks_to_clear"),
        "median_age_days": t.get("median_age_days"),
        "net_14d": t.get("net_14d"),
    },
)


async def async_setup_entry(
    hass: HomeAssistant, entry: YtMcpConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    rd = entry.runtime_data
    entities: list[SensorEntity] = [YtMcpSensor(rd.status, entry, d) for d in STATUS_SENSORS]
    stats = rd.stats
    if stats is None:
        async_add_entities(entities)
        return
    entities += [YtMcpSensor(stats, entry, d) for d in STATS_SENSORS]
    async_add_entities(entities)

    known_playlists: set[str] = set()
    known_themes: set[str] = set()

    @callback
    def _add_new() -> None:
        new: list[SensorEntity] = []
        for p in (stats.data or {}).get("playlists") or []:
            pid = p.get("id")
            if pid and pid not in known_playlists:
                known_playlists.add(pid)
                new += [YtMcpPlaylistSensor(stats, entry, d, pid, p.get("name") or pid) for d in PLAYLIST_SENSORS]
        for t in (stats.data or {}).get("themes") or []:
            name = t.get("theme")
            if name and name not in known_themes:
                known_themes.add(name)
                new.append(YtMcpThemeSensor(stats, entry, name))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(stats.async_add_listener(_add_new))


class YtMcpSensor(YtMcpEntity, SensorEntity):
    entity_description: YtMcpSensorDescription

    def __init__(
        self, coordinator: _YtMcpCoordinator, entry: YtMcpConfigEntry, description: YtMcpSensorDescription
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    def _source(self) -> dict[str, Any] | None:
        return self.data

    @property
    def native_value(self) -> StateType | datetime:
        src = self._source()
        return self.entity_description.value_fn(src) if src is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        src, fn = self._source(), self.entity_description.attr_fn
        return fn(src) if fn and src is not None else None


class YtMcpPlaylistSensor(YtMcpSensor):
    """One of a tracked playlist's sensors, matched by playlist id."""

    def __init__(
        self,
        coordinator: YtMcpStatsCoordinator,
        entry: YtMcpConfigEntry,
        description: YtMcpSensorDescription,
        playlist_id: str,
        name: str,
    ) -> None:
        super().__init__(coordinator, entry, description)
        self._playlist_id = playlist_id
        self._attr_unique_id = f"{entry.entry_id}_{description.key}_{playlist_id}"
        self._attr_translation_placeholders = {"playlist": name}

    def _source(self) -> dict[str, Any] | None:
        return next((p for p in self.data.get("playlists") or [] if p.get("id") == self._playlist_id), None)

    @property
    def available(self) -> bool:
        return super().available and self._source() is not None


class YtMcpThemeSensor(YtMcpSensor):
    """Backlog of one theme across all tracked playlists, matched by theme name."""

    def __init__(self, coordinator: YtMcpStatsCoordinator, entry: YtMcpConfigEntry, theme: str) -> None:
        super().__init__(coordinator, entry, THEME_SENSOR)
        self._theme = theme
        self._attr_unique_id = f"{entry.entry_id}_theme_{slugify(theme)}"
        self._attr_translation_placeholders = {"theme": theme}

    def _source(self) -> dict[str, Any] | None:
        return next((t for t in self.data.get("themes") or [] if t.get("theme") == self._theme), None)

    @property
    def available(self) -> bool:
        return super().available and self._source() is not None
