# max-push picks: the Windows rounds that finish them

Owner, 2026-11-13: review the max-push branch, build the best of it, and
polish it on Windows. Four picks are merged into claude/vibrant-gauss-olema4
(merges 51c9fb3f, d42ff9ab, 5a0af6f1, c0e23ae9). Every one is UNRENDERED until
these rounds run. All are beauty-only; labels, masks and depth do not change.

Run these after flightsim-83's r82/r83, in order, one message per round
(FIX_ROUND_PROTOCOL.md). The numbers assume r83 was the last; shift them if not.
Every round adds `-CompareWith <reference round>` so ROUND.json carries the
pixel report (blank, clipped, crushed, SSIM, flicker).

| Round | Command | Checks |
|---|---|---|
| 84 | `.\scripts\visual_fix_round.ps1 -Round 84 -Scenes "9,15,7"` | Reference with the new defaults: unshadowed lightning flash and the 160 MB tile cache on the iGPU. **Does #09 render now?** render.json: `google_tiles.tile_cache.route` must not say "not found"; `look_applied.weather.lightning.flash_light` shows shadows off. |
| 91 (only if #09 still hangs in 84; run it next) | `... -Round 91 -Scenes "9" -Switches "-tiles-cache-mb=128 -tiles-sse=16"` | If this holds, the hang is memory. If not, add `-rain-layers=on` (no particles) as the next A/B. |
| 85 | `... -Round 85 -Scenes "9,15" -Switches "-wet-porosity=low" -CompareWith 84` | Dark-aircraft A/B: aircraft mean luma should rise in rain. Keep it if it does and nothing clips. |
| 86 | `... -Round 86 -Scenes "9,15,7" -Switches "-rain-layers=on" -CompareWith 84` | Baked rain instead of particles. `rain.drawn_as` is `baked_layers`. Rain must fall down, not up, and must not ghost. |
| 87 | `set FLIGHTSIM_RENDER_SWITCHES=-windscreen-baked=on` then `.venv\Scripts\python.exe scripts\debug_storm_render.py --prompt "fly the c172 through a thunderstorm at 900 m with 25 mm/h rain, cockpit camera" --seconds 2 --width 1280 --height 720 --out runs\wsw_baked`, and the same without the switch into `runs\wsw_ref` | Windscreen drops (cockpit cameras only). `windshield.drawn_as` in render.json. |
| 88 | `... -Round 88 -Scenes "1,4,8,12"` | Reference for glass. The materials prep rebuilds every aircraft master once (LOOK_GENERATION 11). |
| 89 | `... -Round 89 -Scenes "1,4,8,12" -Switches "-canopy-reflect=on" -CompareWith 88` | Canopy reflection, tier 0. #12 must show `interior_camera: true`, gain 0, and an unchanged frame. Optional: tier 1 with `-canopy-reflect-tier=1`. |
| 90 | `.\scripts\stress_ladder.ps1` | Tier 0 three times on #11; writes docs\hardware\hardware_budget_measured.json. Exit 0 held, 1 failed, 3 refused. If every run says `tier_not_applied`, the log doesn't echo the command line: report it, don't loop. |

## What decides a pick
- A switch becomes the default only when its round shows it better by eye
  and in the pixel report, with no new failure (blank frame, clipping, a
  device loss), and the verify run on a final sweep still passes.
- A material that fails to compile falls back by name in render.json;
  report the first error lines, don't retry.
- Unwired today: hardware_budget.py's capped streaming pool (163 MB) is not
  applied to any render; wiring it is a follow-up once r90 measures the budget.

## Handed to flightsim-83 (not in these rounds)
Storm-cell weather map and noise (volumetric_cloud_types/storm tiers 1-3),
the sun's top-of-atmosphere lux check (#02 suspect), valley fog.
