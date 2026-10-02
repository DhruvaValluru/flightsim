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
