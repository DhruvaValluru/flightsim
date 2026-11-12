# Hyper-realism swarm

Runs hundreds of agents, one per work item in `manifest.json`
(domain x component x scenario, 439 items), each writing only inside its own
lane directory.

**Where things run.** Every agent runs on the MacBook, in a Claude Code
session opened in this repo. The Windows PC is only the test machine: it runs
the hardware probe and the measurements, never agents.

## Order of operations

1. **On the Windows PC** (the target hardware; nothing else can see it):

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\hw_probe.ps1
   ```

   Commit `docs/hardware/hardware_profile.json` and pull it on the Mac.
2. **On the Mac:** `core/render/hardware_budget.py` turns the profile into a
   starting budget (tier, usable VRAM, ray tracing, capture width, UE cvars).
   `measured` stays `false` until the `hardware_perf.stress_ladder.*` items
   are measured on the PC.
3. **On the Mac:** open Claude Code in the repo and launch the swarm in waves
   of at most 200 items (about 500 agents, under the 1000-agent cap per run).
   Pass `items` (a manifest slice), `budget` and `wave` as `args`, with
   `scriptPath: swarm/hyperreal.workflow.js`.
4. Each item goes build -> two skeptics (licence, honesty) -> one repair.
   The result lists what is verified, what is rejected, and every
   `needs_windows` command to run on the PC.
5. **On the Windows PC:** pull the branch and run those commands; only a
   Windows measurement turns UNMEASURED into measured.

## Limits worth knowing

* Mac agents write and source-test code. They cannot run the pinned UE 5.7
  Windows build or load the PC's GPU, so "pushed to the max" is only real
  after the stress-ladder items run on the PC.
* About 16 agents run at once (fewer on a laptop with few cores); 500 agents
  is hours, not minutes. Keep the Mac awake and plugged in.
* Rules from `CLAUDE.md` still apply (Google tiles, no scheduled check-ins).
* ruflo (`npx ruflo`) is not wired in. The Workflow tool already does the
  fan-out and verification; ruflo can be layered on for persistent memory
  across waves if you want it.
