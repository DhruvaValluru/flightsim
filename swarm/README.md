# Hyper-realism swarm

Runs hundreds of agents, one per work item in `manifest.json`
(domain x component x scenario, 439 items), each writing only inside its own
lane directory.

## Order of operations

1. **On your Windows PC** (a cloud agent cannot see your hardware):

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\hw_probe.ps1
   ```

   Commit `docs/hardware/hardware_profile.json`.
2. `core/render/hardware_budget.py` turns it into a starting budget (tier,
   usable VRAM, ray tracing, capture width, UE cvars). `measured` stays
   `false` until the `hardware_perf.stress_ladder.*` items measure it on the PC.
3. Launch the swarm in waves of at most 200 items (about 500 agents, under
   the 1000-agent cap per run). Pass `items` (a manifest slice), `budget`
   and `wave` as `args`, with `scriptPath: swarm/hyperreal.workflow.js`.
4. Each item goes build -> two skeptics (licence, honesty) -> one repair.
   The result lists what is verified, what is rejected, and every
   `needs_windows` command to run on the PC.
5. Run those Windows commands; only a Windows measurement turns UNMEASURED
   into measured.

## Limits worth knowing

* Cloud agents write and source-test code. They cannot render UE or load
  your GPU, so "pushed to the max" is only real after the stress-ladder
  items run on your machine.
* At most ~16 agents run at once; 500 agents is hours, not minutes.
* Rules from `CLAUDE.md` still apply (Google tiles, no scheduled check-ins).
* ruflo (`npx ruflo`) is not wired in. The Workflow tool already does the
  fan-out and verification here; ruflo can be layered on for persistent
  memory across waves if you want it.
