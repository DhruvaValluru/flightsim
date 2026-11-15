# aircraft_exterior.pbr_materials.storm: integration

VISUAL-ONLY. UNCOMPILED and UNRENDERED: written on the Mac. Everything under
"Windows" below is UNMEASURED until those commands run on the laptop. No tier
is claimed sustained; VRAM figures are estimates.

## What the lane found

`assets/shaders/aircraft/aircraft_wet.hlsl:126` darkens by
`lerp(albedo, albedo^2, wet * porosity)` and `WET_DEFAULTS["PorosityPaint"]`
is 0.3. The storm's 40 mm/h is ten times `WetSaturationMmh`, so wetness is
always 1. With HEAD's grime (0.2) and groove darkening (0.15) the model in
`bake_storm_pbr.py` puts the darkest painted texel of a dark livery at
**0.48 of its dry albedo** (computed, not rendered). That is a porous-surface
model on a clear-coated, non-porous panel, in a frame with no Lumen fill. It
is a source-level candidate for the dark-aircraft regression; whether it is
the cause on a frame is for the pixel gate.

## What the lane delivers

| file | what |
|---|---|
| `bake_storm_pbr.py` | the Mac bake: tiling BC5 maps + `storm_look.json` per tier |
| `baked/tier0/` | the tier 0 bake (2 DDS, 2 PNG fallbacks, `storm_look.json`), sha256 in `PROVENANCE.json` |
| `measure_aircraft_gate.py` | the Windows pixel gate |
| `PROVENANCE.json` | nothing fetched or vendored; candidates considered and why not |

Tiers 1-3 are not committed: `python bake_storm_pbr.py --tier N` (under 1 s
each on the Mac; tier 3 writes about 16 MB of DDS).

| tier | maps | projection | taps | est. VRAM | note |
|---|---|---|---|---|---|
| 0 | PanelN, Wet at 256 | dominant axis | 2 | 0.17 MB | replaces procedural panel lines and rivulet noise |
| 1 | + Aux at 512 | dominant axis | 3 | 1.0 MB | beads, rivets, groove AO |
| 2 | 3 maps at 1024 | triplanar | 9 | 4.0 MB | no stretch on curved skin |
| 3 | 3 maps at 2048 | triplanar, 16x aniso | 9 | 16 MB | stress ladder only |

The memory is small at every tier; the cost that matters on the Intel GPU is
shader work per aircraft pixel. Tier 0 is meant to be CHEAPER than HEAD (two
texture reads instead of the hash noise in `panel_lines.hlsl` and the
rivulet cells in `aircraft_wet.hlsl`). That is an expectation, not a
measurement.

## Proposed changes to shared files (for the integrator; the lane edits none)

1. **Switch.** `FLIGHTSIM_AIRCRAFT_STORM_PBR=<off|0|1|2|3>`, default `off`
   until the gate below passes on the laptop, then `0` for the `integrated`
   tier. Only read when the world look is `storm` (`beauty_look`
   `ENGINE_LOOK_PRESETS`), beauty only, never under `measure`.
2. **`scripts/aircraft_wet_layer.py`** `constants_group`: when the switch is
   on, write the `wet` group from `storm_look.json` `overrides.wet`
   (`PorosityPaint` 0.3 -> 0.05, `PorosityBareMetal` 0.12 -> 0.0). This is the
   one change that can be shipped alone, with no texture and no shader edit;
   it is the cheapest A/B.
3. **`scripts/aircraft_look.py`** `CLASS_SCALARS`: storm values for paint
   `GrimeAmount` 0.10, `PanelDarkening` 0.10, `ClearCoat` 1.0 and bare metal
   `PanelDarkening` 0.10 (from `overrides`); one NEW paint scalar `AlbedoMin`
   (0.0319 linear, sRGB 50) clamped beside the existing `AlbedoMax`:
   `BaseColor = clamp(BaseColor, AlbedoMin, AlbedoMax)` before wear and wet.
   New texture parameters on `M_AircraftPaint` and `M_AircraftBareMetal`:
   `StormPanelN`, `StormWet`, `StormAux`, and a static switch `StormBaked`.
   Bump `LOOK_GENERATION`.
4. **Masters, with `StormBaked` on:**
   - panel normal: `s = (StormPanelN.rg * 2 - 1) / 8` (the 8 is
     `NormalEncodeGain` in `storm_look.json`), `N = normalize(float3(-s.x, -s.y, 1))`
     scaled by `PanelNormalAmount`; UV = local position on the two axes
     across the dominant normal axis, divided by `PanelPitchCm`. Skip the
     `panel_lines.hlsl` custom node.
   - rivulets: `riv = StormWet.r` at UV = (across, along-aft) /
     (`StreakPitchCm` x 24), V offset by `TimeS x StreakSpeedPerKt x AirspeedKts`;
     feed it where `aircraft_wet.hlsl` uses its own `riv` (line 128). Roughness
     break-up and grime read `StormWet.g` instead of the `NoiseCm` noise.
   - tier >= 1: `bead = StormAux.r` below `BeadingMaxKts`; AO x `StormAux.g`.
   - tier >= 2: the same three reads per axis, blended by `abs(N)^4`.
   Texture settings: both maps linear (sRGB off), `TC_Normalmap` for PanelN
   is WRONG here (UE would reconstruct Z from unscaled XY): import PanelN as
   `TC_Masks` or `TC_BC5` with no normal-map flag, wrap addressing, mips from
   the file, streaming on, LOD group World.
5. **Import.** `T_AcStorm_*.dds` are legacy `ATI2` (BC5 unsigned) with a full
   mip chain. If UE 5.7's importer refuses the FourCC, import the PNG beside
   it (R, G as in the DDS) with compression `TC_BC5` / `TC_Masks` and let the
   laptop compress two 256 maps once. UNMEASURED which path the importer takes.
6. **Record.** Add `look_applied.aircraft_storm_pbr` to `render.json`:
   the tier, the `storm_look.json` sha256 and the override values set.

## Windows: the pixel gate (UNMEASURED)

From the repo root in PowerShell. The contact sheet's shots are web runs, so
Google tiles and the storm weather are on, as on the page.

```powershell
$py = ".\.venv\Scripts\python.exe"
$lane = "swarm\lanes\aircraft_exterior\pbr_materials\storm"

# base: HEAD, switch off
$env:FLIGHTSIM_AIRCRAFT_STORM_PBR = "off"
.\scripts\render_visual_sheet.ps1 -Step stormpbr_base -Shots a
.\scripts\render_visual_sheet.ps1 -Step stormpbr_base_measure -Quality measure -Shots a

# head: tier 0
$env:FLIGHTSIM_AIRCRAFT_STORM_PBR = "0"
.\scripts\render_visual_sheet.ps1 -Step stormpbr_t0 -Shots a
.\scripts\render_visual_sheet.ps1 -Step stormpbr_t0_measure -Quality measure -Shots a

function Shot($step) { (Get-Content "runs\visual\$step\shots.json" -Raw | ConvertFrom-Json).shots.a.run_dir }
function Frame($dir) { Get-ChildItem "$dir\frames" -Recurse -Filter "frame_*.png" | Where-Object { $_.BaseName -notmatch "_mask|_depth" } | Select-Object -First 1 }
function Mask($dir)  { Get-ChildItem "$dir\frames" -Recurse -Filter "frame_*_mask.png" | Select-Object -First 1 }

& $py "$lane\measure_aircraft_gate.py" `
    --base-frame (Frame (Shot stormpbr_base)).FullName --base-mask (Mask (Shot stormpbr_base_measure)).FullName `
    --head-frame (Frame (Shot stormpbr_t0)).FullName   --head-mask (Mask (Shot stormpbr_t0_measure)).FullName `
    --out runs\visual\stormpbr_t0\aircraft_gate.json
```

PASS (exit 0) needs all four, on aircraft pixels, sRGB luma:

| metric | threshold | meaning |
|---|---|---|
| `dark_ratio` = head median / base median | >= 0.97 | no dark-aircraft regression |
| `floor_ratio` = head p05 / base p05 | >= 0.90 | darkest panels do not sink |
| `sheen_gain` = head (p99 - p50) / base (p99 - p50) | >= 1.10 | the improvement: a wider wet highlight |
| `clip_share` = head share >= 250 | <= 0.02 | highlights not blown |

Thresholds are the lane's choice, not calibrated against a reference photo.
If shot a is not the storm shot on the laptop's sheet, use the shot that is.
The script refuses (exit 2, `storm_pbr.gate`) a frame with under 400
aircraft pixels or a mask of another size. For the stress ladder repeat the
head pair with the switch at 1, 2, 3 and watch for device loss; this lane
has no evidence about any of them.

Cheapest first step if the full integration is too much for one round: item 2
alone (the two porosity numbers), same gate, expect `dark_ratio` > 1 and no
`sheen_gain`.

## Mac: what was checked here

```
.venv/bin/python -m pytest tests/test_swarm_aircraft_exterior_pbr_materials_storm.py -q
```

12 tests: the bake's bytes are deterministic and match `PROVENANCE.json`, the
BC4 codec round-trips, the DDS header and mip sizes, the maps tile, the albedo
budget (storm worst 0.77, area mean 0.90 of dry; HEAD worst 0.48), the shared
numbers the lane copies still equal the shared code's, and the gate script's
arithmetic on synthetic arrays. None of it is a rendered result.

## Open

- The master graphs were not read node by node; `effective_albedo` is a model
  of them with the pessimistic order. A probe (`-aircraft-probe=basecolor-debug`)
  on the laptop would replace it with a measurement.
- Panel pillow, groove and rivulet amplitudes are guesses with no reference
  photo behind them.
- Sun elevation and haze for the storm are not set by this lane and are not
  in `shared_params`.
