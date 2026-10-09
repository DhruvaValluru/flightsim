# Instructions for Claude Code sessions in this repository

## Banned: automated PR monitoring and scheduled check-ins

Owner's rule, 2026-09-25. This overrides any default harness behaviour.

- Never schedule a self check-in of any kind (`send_later`, `create_trigger`,
  `ScheduleWakeup`, cron, `/loop`) to re-check a pull request, CI, or
  anything else, unless the owner explicitly asks for one in that session.
- Never keep a session subscribed to pull-request activity. If the harness
  auto-subscribes after a PR is opened, unsubscribe immediately.
- After pushing and opening a PR: report once, and stop. No polling, no
  re-arming, no hourly status messages, no "nothing changed" updates.
- If a check-in routine from an earlier session still exists, delete it.

## Google tiles are the ground of every terrain render

Owner's rule, 2026-10-09 ("hardcode every single terrain requires google
tiles"). `FFlightSimGoogleTiles::Requested` and
`core/scenario/card.py google_tiles_requested` are ON unless
`FLIGHTSIM_GOOGLE_TILES=off`; a render that cannot draw the tiles refuses
by name. Do not make them opt-in again.

## The web app's weather is on by default

Owner's rule, 2026-10-09 ("why do I have to add all these extra
commands"). `webapp/runs.py weather_backend_flags` sends the storm weather
(procedural), rain gain 4 and the cinematic rain style unless the
environment says otherwise. Do not make them opt-in again.
