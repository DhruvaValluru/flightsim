# hardware_perf.stress_ladder.alpine -- integration

Status: **UNMEASURED.** Written and source-tested on the Mac. No frame time,
VRAM or thermal number exists yet, and no tier is sustained. The budget's
`measured` flag flips only when `run_ladder.py` has run on the Windows laptop.

## What is here

| File | Role |
|---|---|
| `build_ladder.py` | Mac generator: tiers, cvars, launch arguments, VRAM estimates |
| `alpine_ladder.json` | the ladder (4 tiers) and the pass thresholds |
| `run_ladder.py` | Windows: renders scenario 11 three times per tier, samples with `typeperf`, stops at the first failure |
| `measure_ladder.py` | judges a run (log, frame times, memory, throttle, picture) and writes the measured budget |
| `measured/hardware_budget_measured.json` | written on Windows only; absent until then |

## Tiers (VRAM figures are estimates)

| Tier | Capture | Changes | Est. MB |
|---|---|---|---|
| 0 | 960x600 | FXAA, 2x1024 cascades, no SSAO / SSR / volumetric clouds, 192 MB pool, 96 MB tile cache (SSE 32) | 453 |
| 1 | 1280x800 | TAA, 3x2048 cascades, SSAO, 320 MB pool, 160 MB tile cache (SSE 24) | 726 |
| 2 | 1280x800 | + SSR, quarter-res volumetric clouds, 491 MB pool, 256 MB tile cache (SSE 16) | 1026 |
| 3 | 1536x960 | 4x2048 cascades, 640 MB pool, 384 MB tile cache (SSE 12) | 1356 |

Every tier keeps Lumen, virtual shadow maps and TSR off and passes `-dx11`.
Tier 0 leans on the scenario's Mac-baked tables (aerial perspective, exposure)
instead of screen-space passes. The estimate treats the Google tile cache as
separate from the texture pool because tile textures arrive uncompressed; that
term is the first thing to cut if tier 0 fails.

## Changes the integrator must make (shared files, not edited by this lane)

Without change 1 the ladder cannot apply a tier, and every run is refused as
`tier_not_applied`.

1. **`webapp/runs.py`, where the FlightSimRender command is built** (just
   before `command = [str(EDITOR), str(project), "-run=FlightSimBridge.FlightSimRender"]`):

   ```python
   _STRESS_TIER = REPO / "runs" / "stress_ladder" / "active_tier.json"

   def stress_tier() -> Optional[dict]:
       """The tier run_ladder.py is measuring, or None (the normal case)."""
       return json.loads(_STRESS_TIER.read_text()) if _STRESS_TIER.is_file() else None
   ```
   ```python
   tier = stress_tier()
   if tier:
       extra += tier["launch_args"]
       width, height = tier["width"], tier["height"]
   ```
   `launch_args` is `-dx11 -FlightSimStressTier=N -DPCVars=<cvar=value,...>`.
   `-DPCVars` is assumed to reach a commandlet; if render.log shows the cvars
   were not set, pass the same pairs as `-ExecCmds="r.X v, ..."` instead.

2. **The Google tiles tileset** (`FFlightSimGoogleTiles`): when a tier is
   active, set `MaximumScreenSpaceError` and `MaximumCachedBytes` from
   `tier["tileset"]` (`maximum_cached_mb` x 1048576). Tiles stay on.

3. **`core/render/hardware_budget.py`**: overlay the measured file.

   ```python
   _MEASURED = REPO / "swarm/lanes/hardware_perf/stress_ladder/alpine/measured/hardware_budget_measured.json"

   def budget_from_file(path="docs/hardware/hardware_profile.json") -> dict:
       b = budget(load_profile(path))
       if b["tier"] == "integrated" and _MEASURED.is_file():
           m = json.loads(_MEASURED.read_text())
           if m.get("measured"):
               b.update(m["budget"])   # measured=True, cvars, capture size
       return b
   ```

## Pixel gate (UNMEASURED; run on the Windows laptop)

With the web app serving on 127.0.0.1:8008 and change 1 in place:

```bat
python swarm\lanes\hardware_perf\stress_ladder\alpine\run_ladder.py
```

It prints `sustained_tier=<n> device_lost_total=<n> measured=<bool>` and exits
0 only when tier 0 held. To try tier 0 alone first: add `--max-tier 0`
(about 3 renders and 3 minutes of cooldown).

Gate: **`sustained_tier >= 0`**, which requires three consecutive tier-0 runs
of scenario 11 each with

- 0 device-lost / GPU-crash / out-of-memory lines in render.log (the reference
  is the 12 device-lost crashes on scene 9),
- at least 8 frames, p95 wall time between frames <= 1000 ms,
- free RAM never under 1024 MB,
- `% Processor Performance` in the last third >= 0.80 of the first third, and
  thermal zone <= 95 C where Windows exposes the counter,
- first, middle and last frame not black (black fraction <= 0.5) and not flat
  (luma standard deviation >= 2.0).

Limits of what this measures:

- Frame time is wall clock between frame files, so it includes readback and
  PNG encode. It bounds GPU frame time from above; a slow disk can fail it.
- The 1000 ms limit is a chosen margin (half the default 2 s GPU timeout), not
  a calibrated one.
- On machines with no thermal-zone counter the thermal check is the throttle
  ratio alone, and `temperature_c_max` is recorded as null.
- `typeperf` is killed at the end of each run; if its redirected output comes
  back empty the run is refused as `sampler_empty` rather than passed blind.
- `usable_vram_mb` in the measured budget is the peak GPU memory seen at the
  sustained tier, which is a safe amount, not the machine's limit.

## Mac checks

```
python -m pytest tests/test_swarm_hardware_perf_stress_ladder_alpine.py -q
```
