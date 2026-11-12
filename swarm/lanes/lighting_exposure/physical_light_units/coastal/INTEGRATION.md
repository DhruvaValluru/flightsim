# lighting_exposure.physical_light_units.coastal -- integration

Visual-only. Everything below is written and source-tested on the Mac.
**No render, pixel or performance result exists yet: all of it is UNMEASURED
until the Windows commands in "Pixel gate" have run on the laptop.**

## What this lane delivers

| File | Role |
| --- | --- |
| `bake_coastal_plu.py` | Mac bake: lux, cd/m2 and EV100 per (sea-haze visibility, sun elevation) |
| `coastal_plu.json` | the table (52 rows, 4 visibilities x 13 sun elevations) plus `nominal` |
| `coastal_plu_curve.csv` | the main columns as a flat curve, for a CurveTable or the commandlet |
| `coastal_gate.py` | the pixel gate: reads two sheet steps' `shots.json` and `beauty_look.json`, refuses by name when it cannot measure |
| `measure_exposure.py` | the gate's pixel arithmetic (called by `coastal_gate.py`) |
| `PROVENANCE.json` | sources, generated-file sha256, candidates not adopted and why |

The idea: the laptop never meters. Tier 0 is a fixed manual EV100 looked up
from the table on the CPU once per shot, so the histogram / eye-adaptation
pass is not needed. The table is about 30 KB of JSON and costs no VRAM.

What the coastal table changes against the repo's elevation bands
(`beauty_look.EV100_BANDS`):

1. **A continuous low-sun curve.** The coastal shot lives between 4 and 20
   deg of sun, where the bands step by 0.9 to 1.0 EV. Model values at 15 km
   visibility against the band: 8 deg 12.19 (band 13.0), 12 deg 12.83 (band
   13.0), 15 deg 13.20 (band 13.9). Two of those three differ by more than
   the 0.3 EV gate. Which one is the better look is not known until the
   grey-card probe runs on Windows.
2. **Sea haze moves the light from the sun to the sky, not out of the
   scene.** In this model the incident meter moves at most 0.16 EV between 8
   and 60 km visibility, but the sun:sky ratio at 12 deg goes from 1.68
   (60 km) to 0.57 (15 km) to 0.22 (8 km). That ratio is what makes haze
   read as haze, so tier 1 pins the sky fill to it.
3. **White guard.** In clear air under a very low sun, a sun-facing white
   fuselage receives several times what the horizontal meter reads.
   `white_protect_ev` (0 to 1.0 stop) darkens the frame until that surface
   sits at scene-linear 2.0. It is zero in every row at 30 km visibility or
   less, and zero from 12 deg up at 60 km.
4. **Glitter is reported, not chased.** `glitter_over_saturation_stops` is
   how far the centre of the sun's reflection on the sea sits above sensor
   saturation (3.8 stops at the nominal row). No exposure holds it; the
   water lane should clamp or bloom it, and the gate allows for it.

Nominal row (sea level, sun 12 deg, visibility 15 km): direct normal
31 805 lx, sky diffuse 11 600 lx, global horizontal 18 213 lx, sea away from
the sun 348 cd/m2, mean sky 3 692 cd/m2, **EV100 12.83**.

## Tiers (VRAM and cost are ESTIMATES; none is claimed sustained)

| Tier | Render side | Est. added VRAM | Est. cost |
| --- | --- | --- | --- |
| 0 | `AEM_Manual`, EV100 = table `target_ev100` through the existing sidecar `exposure.ev100`; sun stays 120 000 lx outer-space under engine transmittance; `r.EyeAdaptationQuality=0` | 0 MB | negative: removes the exposure histogram pass |
| 1 | tier 0 + SkyLight intensity pinned so the sky's horizontal illuminance equals `sky_diffuse_horizontal_lux`; `LowerHemisphereColor` set to the sea (`sea_luminance_cd_m2`, a dark blue-grey); haze extinction taken from `haze_extinction_550_per_km` by ONE owner (height fog or SkyAtmosphere Mie, not both); captured once, not real-time | 0 to 1 MB (existing cubemap) | none per frame |
| 2 | tier 1 + `AEM_Basic` auto exposure clamped to `target_ev100` +/- 0.3 (`AutoExposureMinBrightness`/`Max`), for clips that turn from up-sun glitter to down-sun shoreline | about 1 MB (downsample chain) | one small downsample pass |
| 3 | tier 2 with `AEM_Histogram` and local exposure (highlight contrast 0.8) to hold the glitter path and the shaded shoreline together | about 8 to 16 MB (histogram + bilateral grid) | several full-screen passes; whether local exposure runs at all under D3D11 SM5 on this GPU is unknown |

Tier 0 is the one intended for the laptop. It adds no texture, no pass and no
shader, so it cannot by itself cause a device loss; that is an argument, not
a measurement.

## Proposed change (for the integrator; this lane edits no shared file)

Host side: none. `FlightSimBeautyLook.cpp` already applies the sidecar's
`exposure.ev100` under `AEM_Manual`.

`core/scene/beauty_look.py`, where the base EV100 is chosen (today
`ev100_band(elevation)`), add a coastal base ahead of the band:

```python
_COASTAL_PLU = REPO / "swarm/lanes/lighting_exposure/physical_light_units/coastal/coastal_plu.json"

def coastal_ev100(elevation_deg: float, visibility_km: float = 15.0) -> Optional[Tuple[float, str]]:
    """(EV100, basis) from the baked coastal table, or None when it is absent
    or the sun is below its lowest row (1 deg): the band then stands."""
    if elevation_deg < 1.0 or not _COASTAL_PLU.is_file():
        return None
    plan = json.loads(_COASTAL_PLU.read_text())
    # bilinear, clamped: bake_coastal_plu.lookup, moved here by the integrator
    row = lookup(plan, visibility_km, elevation_deg)
    return row["target_ev100"], "coastal physical-light-units table v1 (MODEL, UNCALIBRATED)"
```

and call it when the shot's surface is water / shoreline (the same `surface`
switch `hero_lighting.plan_sidecar` takes). `exposure_target()` stays the one
formula: only its `base_ev100` argument changes. Record the basis string in
the sidecar so render.json says which base ran. The alpine lane proposes the
same shape (`alpine_ev100`); one dispatcher on the surface covers both.

The web app's weather defaults stay on. Under the storm weather the deck's
overcast stops in `exposure_target` still apply on top of this base; the
table itself is the clear-above-haze case.

Tier 1, same file, where the skylight row is written: intensity such that
the sky hemisphere delivers `sky_diffuse_horizontal_lux`; lower hemisphere
luminance `sea_luminance_cd_m2`. If `core/scene/hero_lighting.py` fill is
active on the same frame, the two must not both add bounce: one owner, the
integrator's choice.

Tier 1 haze, one owner only:

- Height fog: extinction `haze_extinction_550_per_km` at sea level, falling
  with a 1.2 km scale height. From memory of the engine source, UE's
  `FogDensity` is extinction per metre times 10 (so 15 km visibility is
  about `FogDensity 0.0026`, `FogHeightFalloff 0.0083`). That mapping is
  UNVERIFIED against the pinned build; check it there before use.
- Or SkyAtmosphere Mie: scattering + absorption = extinction minus Rayleigh
  (0.249 /km at 15 km), split 0.9 / 0.1, exponential distribution 1.2 km.

If neither is set to the table's extinction, the engine's sun will be
brighter and the sky dimmer than the table says, and tier 0's EV100 is still
valid for the meter (which haze barely moves) but the sun:sky ratio is not.

Google tiles stay the ground. Their sea and beach are photographs with baked
shading and often baked glitter, so the effective water albedo is not 0.06;
`sea_luminance_cd_m2` is the row most likely to need a Windows correction.

No coastal entry exists in `scripts/run_test_scenarios.py`, and no coastal
place exists in `core/terrain/glo30.py` `LOCATIONS`, so the prompt below does
not resolve to a place today (UNVERIFIED: not compiled here). Proposed entry,
once a coastal location is added:

```python
("coastal VFR, low sun over the sea",
 "chase view of the a320 at 300 m along the coast near monterey at 18:30, flying north, for 6 seconds",
 {"sun_elevation_deg": 12.0}),
```

## Shared look parameters for the coastal scenario

Proposals for the other coastal lanes to converge on. They restate the
coastal PBR lane's values (sun 12 deg, 4300 K, visibility 15 km, water
albedo 0.06) and replace its "exposure left to auto-exposure" with a number.

| Parameter | Value | Basis |
| --- | --- | --- |
| sun elevation | 12 deg | coastal PBR lane's proposal |
| sea-haze visibility | 15 km | coastal PBR lane's proposal |
| exposure | EV100 12.83, manual | this table, nominal row |
| sun, outer space | 120 000 lx | `core/sky/plan.py` |
| sun at sea level, direct normal | 31 805 lx | this table |
| sky diffuse horizontal | 11 600 lx | this table |
| sun:sky ratio on the horizontal | 0.57 | this table |
| haze extinction (550 nm) | 0.261 /km | Koschmieder |
| aerosol optical depth (550 nm) | 0.30 | 1.2 km scale height, UNCALIBRATED |
| water albedo (away from glitter) | 0.06 | coastal PBR lane's proposal |
| sea luminance | 348 cd/m2 | this table |
| sun colour temperature | 4300 K | coastal PBR lane's proposal; not derived here |
| wind for the glitter width | 5 m/s | UNCALIBRATED pick |

## Source tests (Mac)

```
.venv/bin/python -m pytest tests/test_swarm_lighting_exposure_physical_light_units_coastal.py -q
```

They check the bake is reproducible and matches PROVENANCE, the table's
ordering, the haze and Fresnel arithmetic, agreement with the repo's meter
and constants, and the gate's maths on synthetic ramps. None of that is a
render result.

## Pixel gate (UNMEASURED and currently BLOCKED; Windows laptop, repo root)

Status: **not runnable to a result today.** Two things it needs do not exist
in the tree, and this lane may not add them:

1. **A coastal shot.** `experiments/visual_contact_sheet.py` `SHOTS` has four
   shots (a, d Matterhorn; b Grand Canyon; c Yosemite) and
   `core/terrain/glo30.py` `LOCATIONS` has six places, all inland (everest,
   flint_hills, fuji, grand_canyon, matterhorn, yosemite). The earlier draft
   of this file used shot `a` as a "carrier"; that claim is withdrawn: an
   alpine frame says nothing about coastal exposure, and the proposed change
   does not act on it anyway (it dispatches on a water surface).
2. **The candidate.** The candidate frame is the same shot rendered after the
   `beauty_look.py` change above is merged. No switch in the tree produces it
   before then, so the gate is a post-integration, two-render gate, not a
   self-contained command.

For the integrator, the two additions that unblock it: a coastal entry in
`LOCATIONS` plus a fifth `SHOTS` entry (key `e` below; the prompt must be one
the offline interpreter compiles, as `tests/test_visual_contact_sheet.py`
checks for the other four), and the `beauty_look.py` change applied on BOTH
exposure branches: the band branch and the `physical_sky` branch (where the
base today is the `-sky=` plan's EV100, not the band). The basis string the
change writes into the sidecar's `exposure.basis` must contain the word
`coastal`; the gate keys on it.

Then, on the laptop (`scripts\render_visual_sheet.ps1` is the runner: Google
tiles on, web-app weather on; it writes `runs\visual\<step>\e.png` and
`shots.json` with `shots.e.run_dir`, see `write_shots` and `main` in
`experiments/visual_contact_sheet.py`):

```powershell
# 1. baseline: on the commit BEFORE the beauty_look change
.\scripts\render_visual_sheet.ps1 -Step coastal_plu_ref -Shots e
# 2. candidate: on the commit WITH it, same shot
.\scripts\render_visual_sheet.ps1 -Step coastal_plu_t0 -Shots e
# 3. the gate: every number comes from the two runs' beauty_look.json
.\.venv\Scripts\python.exe swarm\lanes\lighting_exposure\physical_light_units\coastal\coastal_gate.py --baseline-step coastal_plu_ref --candidate-step coastal_plu_t0 --shot e
```

Step 3 is the only command this lane owns. It takes no hand-typed EV100 or
sun elevation: it reads `sun_elevation_deg` and `exposure.ev100` /
`exposure.base_ev100` / `exposure.basis` from each run's sidecar. Run today
(with `-Shots a`, or before the merge) it exits 2 with a named refusal
rather than a number:

| Refusal | When |
| --- | --- |
| `shots.missing`, `shot.missing`, `shot.refused`, `shot.failed`, `frame.missing` | the step did not render that shot |
| `sidecar.missing` | no `beauty_look.json` in the run (measure quality) |
| `exposure.ev100_null` | the sidecar's `exposure.ev100` is null: sun at or below the horizon, or the physical-sky path with no plan EV100. The host's own exposure stands and there is nothing to gate against |
| `sun.mismatch` | the two runs' sun elevations differ by more than 0.05 deg |
| `candidate.not_coastal_base` | the candidate's `exposure.basis` does not name the coastal table (change not merged, or an inland shot) |
| `exposure.unchanged` | both runs are at the same EV100 |
| `exposure.shift_below_gate` | the two EV100s differ by 0.3 stop or less, so a frame that did not move at all would pass the tolerance |
| `pixels.too_few_midtones` | fewer than 1000 mid-tone pixels to compare |

Checks (exit 0 all pass, 1 any fail):

- `table_base_error_ev`: candidate `exposure.base_ev100` minus the table's
  `target_ev100` at the sidecar's sun elevation and `--visibility-km`
  (default 15). **Pass: |error| <= 0.01.** A sidecar check, not a pixel one.
- `ev_error_stops`: median log2(candidate/baseline) of linear luminance over
  the baseline's mid-tone pixels (0.02 to 0.50), minus the expected shift
  (baseline `exposure.ev100` - candidate `exposure.ev100`). **Pass: |error|
  <= 0.3.**
- `highlight_clip_fraction` (all channels >= 250): **pass: candidate <=
  0.02, or not above the baseline.**

Limits of the gate itself:

- **The nominal row cannot be gated.** At sun 12 deg and 15 km the table
  (12.83) is 0.17 stop from the band (13.0), inside the 0.3 tolerance; the
  gate refuses there (`exposure.shift_below_gate`). The gate shot `e` must
  put the sun where the two differ by more: by the model, about 8 deg (12.19
  against 13.0) or 15 deg (13.20 against 13.9). The shot's real sun elevation
  is whatever the sidecar records, so this is settled only when it renders.
- It checks that the frame landed on the table. It does not prove the table
  is the right look; that needs the grey-card probe the repo already
  describes for `EV100_BANDS` (sunlit 18% card near 18% of white after the
  tonemapper), at sea level with the sun at 6, 12 and 20 deg.
- The sidecar's `exposure.meter` block says the host re-meters the beauty
  frame once "only when the host finds Lumen GI unsupported on its shader
  platform". The D3D11 laptop has no Lumen, so the host may move the exposure
  off the sidecar's EV100 there, and `ev_error_stops` would report that as
  error. Whether it does is UNMEASURED; if it does, tier 0's "fixed manual
  EV100" needs that meter held off for coastal shots (integrator's call).
- The Mac tests run the gate on synthetic frames and on sidecars written by
  the repo's own `plan_beauty_look` and `write_shots`. That shows the gate
  reads the real file shapes and refuses correctly; it is not a render result.

## Known limits

- The aerosol scale height, Angstrom exponent, the haze-scattered sky term,
  water albedo, wind and the white-guard constants are UNCALIBRATED model
  choices, listed in `coastal_plu.json`.
- Rows at 1 to 3 deg are the least certain: Bird & Hulstrom's air mass and
  the IES diffuse fit are both at the edge of their range there, and the
  60 km / 1 deg row hits the white guard's 1.0 stop cap.
- The meter is at sea level. The aircraft at 300 to 1500 m sits partly
  above the haze and receives a stronger direct beam than the table's.
- Clear sky above the haze only. Cloud goes through `exposure_target`'s
  overcast stops on top of this base.
- Twilight is not covered; the band stands below 1 deg.
- Calibration follow-up: the Prague Sky Model data (visibility and low sun)
  or the Poly Haven Qwantani pure-sky series would check the sun:sky ratio.
  Neither was fetched; the Prague licence is unverified.
