# hardware_perf.vram_budgeting.alpine: integration notes

Status: written and source-tested on the Mac. **Every VRAM, frame-time and
thermal figure is an ESTIMATE and UNMEASURED.** No tier is claimed sustained.
Label: performance budgeting; visual-only where it touches the frame.

## What this lane is

A byte ledger that splits the laptop's usable-VRAM cap (491 MB, from
`core/render/hardware_budget.py`, itself unmeasured) between named consumers,
plus a Windows-side gate that renders the alpine scene twice on the laptop
and reports GPU memory, device loss and ground sharpness for a tier. It does
not measure frame time.

| file | role |
|---|---|
| `bake_vram_budget.py` | offline generator (stdlib, deterministic) |
| `alpine_vram_budget.json` | the ledger: 4 tiers, bytes per consumer, cvars, tileset settings |
| `alpine_vram_tier{0..3}.ini` | `[SystemSettings]` cvar block per tier |
| `measure_vram_gate.py` | Windows gate: one command; starts the app, renders reference and tier, samples typeperf, reads render.log and the two frames |

## Finding the integrator should act on

`_integrated_budget` sets `r.Streaming.PoolSize` equal to `usable_vram_mb`
(491 = 491). The streaming pool is only one consumer. Render targets, shadow
maps and, to my reading of Cesium for Unreal, the Google tile textures
(created at runtime, not streamed, so not bounded by the pool) all sit on top
of it. With the pool allowed to fill the whole cap, anything else pushes the
shared-memory GPU over. This is a plausible contributor to the scene 9 device
losses; it is a hypothesis, not a diagnosis. Also `FlightSimGoogleTiles`
defaults to `MaximumScreenSpaceError = 8.0` and sets no `MaximumCachedBytes`,
so the tile cache is at the plugin default rather than a budgeted value.

## Tiers (ESTIMATES)

| tier | capture | CSM | tile cache / SSE / loads | stream pool | est. total | vs 491 MB cap |
|---|---|---|---|---|---|---|
| 0 | 1280x800 | 1x1024 | 160 MB / 24 / 4 | 128 MB | 424.6 MB | under, with 10% margin (441.9) |
| 1 | 1280x800 | 2x1024 | 224 MB / 16 / 6 | 160 MB | 522.6 MB | over |
| 2 | 1536x960 | 2x2048 | 320 MB / 12 / 8 | 256 MB | 757.7 MB | over |
| 3 | 1536x960 | 3x2048 | 512 MB / 8 / 12 | 384 MB | 1085.7 MB | over |

Tiers 1-3 exceed the cap on purpose: they are rungs for the stress ladder to
try, since the 491 MB cap is itself a guess (6% of an unrecorded RAM size).
Fixed in every tier: baked LUT allowance 16 MB (sibling alpine lanes hold
8.3 MB on disk today, `--scan-lanes`), fixed overhead 48 MB, render targets
at 64.3 B/px internal + 8 B/px swap chain (70.6 MB at 1280x800).

Alpine reasoning: snow and rock are low-frequency albedo, so coarser tile
SSE costs less here than over a city; hard snow shadows and long ridge lines
make full output resolution and one good near cascade worth their bytes.
Tier 0 therefore keeps `r.ScreenPercentage=100` and spends the saving on SSE.

## Proposed changes to shared files (not made here)

1. `core/render/hardware_budget.py`, `_integrated_budget`: stop setting
   `"r.Streaming.PoolSize": pool`. Take the tier-0 block from
   `alpine_vram_budget.json`:
   `r.Streaming.PoolSize=128`, `r.Streaming.LimitPoolSizeToVRAM=1`,
   `r.RenderTargetPoolMin=71`, `r.Shadow.MaxCSMResolution=1024`,
   `r.Shadow.CSM.MaxCascades=1`. Keep `usable_vram_mb` as the cap. Confirm each
   cvar name exists in the pinned engine build (written from memory).
2. `ue/Plugins/FlightSimBridge/.../FlightSimGoogleTiles.cpp`, next to
   `Tiles->SetMaximumScreenSpaceError(...)` (line ~180): add an env-read
   `FLIGHTSIM_GOOGLE_TILES_CACHE_MB` and `FLIGHTSIM_GOOGLE_TILES_LOADS`, and
   call `Tiles->SetMaximumCachedBytes(int64(CacheMb) * 1024 * 1024)` and
   `Tiles->SetMaximumSimultaneousTileLoads(Loads)`. Confirm the setter names
   against the vendored Cesium version. Tiles stay ON; this only bounds them.
   Until then tier 0's SSE alone works today with no code change:
   `set FLIGHTSIM_GOOGLE_TILES_SSE=24`.
3. Follow-up, not in this lane: BC1-encode tile textures at load (ICBC, MIT
   per discoveries.json, unvetted). The ledger shows a 512 tile going from
   1,398,100 to 174,776 bytes (8.0x), which would let tier 0 hold SSE 12-16
   in the same 160 MB. Needs a Cesium plugin patch and a pinned, read commit.

## Windows measurement (UNMEASURED until this runs on the laptop)

From the repo root in the venv, with the web app NOT running (the gate starts
its own, so the settings reach the render process):

```
python swarm\lanes\hardware_perf\vram_budgeting\alpine\measure_vram_gate.py --tier 0
```

Nothing to fill in. The gate does two passes and writes everything under
`runs\alpine_vram_gate\`:

1. `reference`: today's render path unchanged (`FLIGHTSIM_GOOGLE_TILES_SSE`
   and `FLIGHTSIM_RENDER_SWITCHES` removed from the app's environment, so
   SSE is the engine default 8). Produces `reference.png`, `reference_render.log`.
2. `tier0`: `FLIGHTSIM_GOOGLE_TILES_SSE=24` plus the tier's cvars as one
   `-ini:Engine:[SystemSettings]:...` token in `FLIGHTSIM_RENDER_SWITCHES`
   (`webapp/runs.py with_render_switches` puts it on the UE argv). Produces
   `tier0.png`, `tier0_render.log`, `tier0_gate.json`.

Each pass samples the adapter counters with the app stopped (idle), starts
`python -m uvicorn webapp.server:app --port 8008`, runs
`scripts\run_test_scenarios.py --still --only 11 --compiler regex` while a
thread samples `typeperf ... -sc 1` about every 2 s, copies the run's first
`frames\<camera>\frame_NNNN.png` and `render.log`, stops the app and
restores `runs\test_scenarios.json`.

Checked on the Mac by reading source (not by running):
- scenario 11 is "A-4 over the matterhorn" (`SCENARIOS[10]`; the unit test
  parses the file and asserts it, and the gate refuses if the row's name
  stops containing "matterhorn");
- `FLIGHTSIM_GOOGLE_TILES_SSE` is read in `FlightSimGoogleTiles.cpp:143`;
- the render log is `render.log` beside the run's frames (`webapp/runs.py`).

Not checked, and reported by the gate rather than assumed:
- whether the pinned UE build honours the `-ini:` override in the commandlet.
  `pool_cvar_seen_in_log` in the result says whether `r.Streaming.PoolSize`
  with the tier value appears in render.log; false or null means the pass
  measured SSE 24 only. `--no-cvars` runs SSE only on purpose.
- the cvar names themselves (written from memory).
- the thermal-zone counter exists on this laptop. If not, `temperature` is
  listed under `not_measured` and thermals need another tool.

Gate: both renders finished, zero device-lost lines in the tier pass, peak
GPU memory above idle <= 491 MB, and ground sharpness kept: the median, over
a 4x8 grid on the lower half of the frame, of candidate/reference Laplacian
variance >= 0.95 (cells flat in the reference are skipped; `--ground-box
x0,y0,x1,y1` overrides the region). 0.95 is a chosen threshold, unvalidated.
The peak is sampled at ~2 s, so it is a lower bound. If the reference pass
device-losts, the gate fails and that is itself the result.

Frame time is NOT measured here: a `--still` render is one commandlet frame
and there is no frame-time series to read. The earlier `-csvprofile` /
`--frames` path and the `measured=true` patch are removed. On a pass the gate
writes `tier0_budget_patch.json` listing `measured_fields` (peak_gpu_memory,
device_loss, temperature if present) and `not_measured` (frame_time); the
budget's own `measured` stays false until a frame-time lane measures it.
Repeat with `--tier 1`, `2`, `3` for the ladder.

## Mac checks

`python3 -m pytest tests/test_swarm_hardware_perf_vram_budgeting_alpine.py`
covers byte arithmetic, tier ordering, tier-0 margin, generator/committed
file agreement, PROVENANCE hashes, the gate's parsers, PNG reader and logic,
and that the Windows command names scenario 11 = matterhorn and real driver
flags. pytest is not installed on this Mac; the 9 test functions were run by
importing the file and calling each one (all returned without an assert
failing). It is not a render, VRAM, frame-time or thermal result, and the
gate's orchestration (typeperf, app start/stop, UE) has never executed.
