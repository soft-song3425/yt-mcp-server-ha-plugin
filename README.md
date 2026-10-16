# yt-mcp for Home Assistant

Home Assistant integration for a [yt-mcp](https://github.com/soft-song3425/yt-mcp-server)
server: server health (problems, Google authorisation, poller, backups, quota) and
playlist analytics (watched and added today, this week and over 30 days, backlog
and days to empty per playlist and per theme, the last watched video).

It reads two read-only JSON endpoints on the server and nothing else. It cannot
change playlists, call MCP tools or open `/admin`, and it costs no YouTube quota
(the server answers from its local database).

| Server version | What you get |
| --- | --- |
| 2.11.0 or newer | everything below |
| 2.10.x | health entities only (a repair notice says analytics need 2.11.0) |
| older | not supported (no `/admin/status.json`) |

Tested with Home Assistant 2026.2. Needs 2026.2 or newer.

## 1. Create the read-only token on the server

```sh
cd /opt/yt-mcp-server
sudo docker compose run --rm yt-mcp python -m ytmcp gen-status-token
```

It prints a token and a `YT_MCP_STATUS_TOKEN_HASH=...` line. Put the hash line in
`.env`, then `sudo docker compose up -d`. Keep the token for step 3: it is shown once
and the server only stores its hash. The token opens `/admin/status.json` and
`/admin/stats.json` and nothing else. MCP tokens and the admin passphrase do not
work there, and this token does not work anywhere else.

## 2. Install the integration

**HACS** (the repository must be public, as HACS cannot read private repositories):
HACS, three-dot menu, *Custom repositories*, add
`https://github.com/soft-song3425/yt-mcp-server-ha-plugin` with type *Integration*,
then download **yt-mcp** and restart Home Assistant.

**Manually:** copy `custom_components/yt_mcp` into `/config/custom_components/` on
the Home Assistant host (Samba, SSH or the File editor app) and restart.

## 3. Add it

*Settings, Devices & services, Add integration, yt-mcp*:

- **Server URL**: the base URL of the server, without `/admin` or `/mcp`
- **Status token**: the token from step 1 (with or without `Bearer `)
- **Verify the TLS certificate**: leave on unless the server uses a self-signed one

Options (*Configure*): health interval (default 5 min) and analytics interval
(default 15 min; the server reads YouTube every 15 minutes at best, so a shorter
interval adds nothing). If the token is replaced on the server, Home Assistant asks
for the new one (*Reconfigure* also changes the URL).

## Entities

One service device, **yt-mcp**, with a link to `/admin`.

**Health** (from `status.json`)

| Entity | Meaning |
| --- | --- |
| `binary_sensor.yt_mcp_problem` | on when the server reports a problem; attribute `problems` lists them |
| `binary_sensor.yt_mcp_google_authorisation` | on when the Google token is unusable (re-authorise on `/admin`) |
| `binary_sensor.yt_mcp_quota_exhausted` | on when Google reported today's quota as used up |
| `sensor.yt_mcp_quota_used`, `..._quota_used_percentage` | units spent today (Pacific day) |
| `sensor.yt_mcp_last_poll`, `..._poll_interval` | last background poll, interval in force |
| `sensor.yt_mcp_backup_age` | hours since the newest database backup |
| `sensor.yt_mcp_videos_without_metadata` | videos still waiting for title and channel |

**Analytics** (from `stats.json`, all tracked playlists; moves between tracked
playlists are not counted as arrivals)

| Entity | Meaning |
| --- | --- |
| `sensor.yt_mcp_watched_today`, `..._added_today`, `..._watch_time_today` | since local midnight |
| `sensor.yt_mcp_watched_this_week`, `..._added_this_week`, `..._watch_time_this_week` | last 7 days |
| `sensor.yt_mcp_watched_vs_previous_week` | % change against the 7 days before |
| `sensor.yt_mcp_watched_in_30_days`, `..._watched_per_day` | 30-day totals and rate |
| `sensor.yt_mcp_median_wait_before_watching` | days a video waited before being watched (30 days) |
| `sensor.yt_mcp_backlog`, `..._backlog_hours`, `..._days_to_empty` | backlog now and when it empties at the 30-day rate |
| `sensor.yt_mcp_last_watched`, `..._last_watched_at` | title, channel, playlist, theme of the latest watch |
| `sensor.yt_mcp_longest_wait` | days the oldest video has waited; attribute `videos` lists the top 3 |
| `sensor.yt_mcp_most_watched_theme` | top theme this week |
| `sensor.yt_mcp_stalled_themes` | themes with videos waiting and nothing watched in 14 days |
| `sensor.yt_mcp_attention_items` | the weekly digest's attention items (count, list in `items`) |
| `sensor.yt_mcp_quota_remaining`, `..._quota_reset` | units left today, 7-day history, next reset |
| `binary_sensor.yt_mcp_positioning_review_due` | theme order unchanged for 4+ weeks |

**Per tracked playlist** (for example New Videos): `<playlist> backlog`, `backlog hours`,
`watched today`, `watched this week`, `days to empty` (14-day trend).

**Per theme**: `<theme> backlog` (items waiting across playlists), with attributes
`status` (growing, shrinking, steady, quiet, stalled, empty), `hours`,
`watched_per_week`, `weeks_to_clear`, `median_age_days`, `position`.

New playlists and themes get entities as they appear. One that disappears (untracked
playlist, renamed theme) turns unavailable and can be deleted from its entity settings.

### Event

`yt_mcp_video_watched` fires once for each new watch the server detects, with
`title`, `channel`, `playlist`, `theme`, `minutes` and `watched_at`. Detection runs at
the server's poll cadence (15 minutes in your busy hours, hourly otherwise), plus up
to one analytics interval in Home Assistant.

## Examples

Notify on a server problem:

```yaml
automation:
  - alias: "yt-mcp: problem"
    triggers:
      - trigger: state
        entity_id: binary_sensor.yt_mcp_problem
        to: "on"
        for: "00:10:00"
    actions:
      - action: notify.notify
        data:
          title: yt-mcp
          message: "{{ state_attr('binary_sensor.yt_mcp_problem', 'problems') | join(', ') }}"
```

Log every watch to the logbook:

```yaml
automation:
  - alias: "yt-mcp: watched"
    triggers:
      - trigger: event
        event_type: yt_mcp_video_watched
    actions:
      - action: logbook.log
        data:
          name: YouTube
          message: "watched {{ trigger.event.data.title }} ({{ trigger.event.data.channel }})"
```

Dashboard card:

```yaml
type: entities
title: YouTube
entities:
  - sensor.yt_mcp_watched_today
  - sensor.yt_mcp_watched_this_week
  - sensor.yt_mcp_backlog
  - sensor.yt_mcp_days_to_empty
  - sensor.yt_mcp_last_watched
  - binary_sensor.yt_mcp_problem
```

## Development

```sh
python3.13 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/ruff check . && .venv/bin/pytest -q
```

Test fixtures in `tests/fixtures/` were produced by the yt-mcp 2.11.0 server code
(`ytmcp.health.report`, `ytmcp.stats.report`). When `stats.json` changes
incompatibly, the server bumps `schema` and this integration logs a warning until
it is updated.
