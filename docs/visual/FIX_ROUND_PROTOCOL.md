# Visual fix rounds: how the Windows render box runs them unattended

Owner, 2026-11-11: "change the workflow ... so it is more efficient for the
rest of the plan ... so that I can leave my desk and it finishes on its own,
communicating to you and everything."

Two Claude sessions share the work:

- **flightsim-83** (Mac) writes the fixes, pushes them to
  `claude/vibrant-gauss-olema4`, reviews frames and decides the next round.
- **The Windows session** renders. It does not change code; it runs one
  command per round and reports back.

## Sizing a round

| Round | What renders | Command |
|---|---|---|
| Fix round | only the scenes the fix touches, one still each | `.\scripts\visual_fix_round.ps1 -Round N -Scenes 11,15` |
| Final sweep | every scene, plus head shots against the last head | `.\scripts\visual_fix_round.ps1 -Round N -Full` |

The script rebuilds, recreates materials and re-imports aircraft **only when
their inputs changed** since the last prepared commit
(`runs\visual\prep_stamp.txt`). A round where only Python or a scene changed
goes straight to rendering. It refuses by name (`REFUSED <rule>: ...`, exit 3)
rather than guessing; the rules are listed in the script's header.

There are no A/B pairs, probes or `flightsim.verify` runs in a fix round
unless the request names them. The label check (`flightsim.verify`) runs once,
at the final sweep, as the request will say.

## The loop (Windows session)

1. A message from flightsim-83 names the round number and the command line.
   Run exactly that command in `C:\Users\kanth\flightsim`.
2. When it ends, whatever the exit code, send **one** message to
   `flightsim-83`. If that send fails, send it to `p3-mac`. Put in it:
   - the first line: `Visual round N on <commit>: X of Y rendered` (or the
     `REFUSED` line);
   - the contents of `docs\visual\round_N\ROUND.json`;
   - the pushed vis-windows commit;
   - anything that looked wrong in the log (a hang, a tiles timeout, a
     crash), quoted from the log, short.
3. Then wait for the next message. Do not poll, schedule, or send interim
   updates.

When a round fails:

- **A tiles timeout (DNS, `terrain.google_tiles`):** re-run the same command
  once. The batch keeps finished scenes only on `--resume`, so a rerun of a
  2-scene round costs little.
- **A hang (no log progress for 15 min):** kill `UnrealEditor-Cmd.exe`,
  report it with the scene number, and wait. Do not retry a hang.
- **A build error or `MATERIAL-FAILED`:** report the first error lines and
  wait. flightsim-83 fixes the code.

The rules are unchanged: never on the Mac, Google tiles always on
(never `FLIGHTSIM_GOOGLE_TILES=off`), storm weather on by default, no
schedules or PR polling, and no ruflo daemon.
