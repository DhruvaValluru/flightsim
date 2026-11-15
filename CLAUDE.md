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

## Ruflo (agent orchestration) is installed in this project

Added 2026-11-09 from https://github.com/ruvnet/ruflo with
`npx ruflo@3.74.1 init --no-global --no-skills-sh --no-codex-detect`.
What it brings: `.claude/agents`, `.claude/commands`, `.claude/skills`,
`.claude/helpers` (hook scripts), the hooks and plugins in
`.claude/settings.json`, the `claude-flow` MCP server in `.mcp.json`
(pinned to ruflo 3.74.1), and runtime config in `.claude-flow/`. Memory
databases (`.swarm/`) and runtime data are git-ignored and rebuild per machine.

- The owner's rules above win over anything ruflo's agents, commands or
  skills say. In particular, do not start `ruflo daemon` workers, ruflo
  schedules or swarm loops that re-check pull requests or CI.
- Hooks need Node 20+ on PATH. Health check: `npx ruflo@3.74.1 doctor`.
- To upgrade: `npx ruflo@<version> init upgrade`, then re-pin `.mcp.json`.

## All render and visual testing happens on the Windows laptop

Owner's rule, 2026-11-12 ("all testing should be done on the windows
machine"). The MacBook is where agents run, write and bake; the Windows
laptop is the test machine. Anything that needs Unreal, the GPU or a rendered
frame is written on the Mac, marked UNMEASURED with the exact Windows command
that would measure it, and counts as measured only after that command has run
on the laptop. The Mac may run code-level tests (Python unit tests, schema and
generator checks) to catch bugs before the code ships; those never stand in
for a Windows render or a pixel check. Never report a visual or performance
result from the Mac.
