"""Constants for the yt-mcp integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Final

DOMAIN: Final = "yt_mcp"
LOGGER = logging.getLogger(__package__)

CONF_STATUS_INTERVAL: Final = "status_interval"
CONF_STATS_INTERVAL: Final = "stats_interval"

DEFAULT_STATUS_INTERVAL: Final = 5  # minutes; health is cheap and alerts should be quick
DEFAULT_STATS_INTERVAL: Final = 15  # minutes; the server itself polls YouTube every 15 min at best
MIN_STATUS_INTERVAL: Final = 1
MIN_STATS_INTERVAL: Final = 5

STATUS_PATH: Final = "/admin/status.json"
STATS_PATH: Final = "/admin/stats.json"
REQUEST_TIMEOUT: Final = timedelta(seconds=30)

# The stats.json schema this integration understands; a higher one may rename fields.
SUPPORTED_STATS_SCHEMA: Final = 1

EVENT_VIDEO_WATCHED: Final = "yt_mcp_video_watched"

UNIT_VIDEOS: Final = "videos"
UNIT_UNITS: Final = "units"
