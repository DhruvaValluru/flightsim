# lighting_exposure.sun_time_of_day.coastal -- integration

Visual-only. Everything below is written and source-tested on the Mac.
**No render, pixel or performance result exists yet: all of it is UNMEASURED
until the Windows commands in "Pixel gate" have run on the laptop.**

## What this lane delivers

| File | Role |
| --- | --- |
| `bake_coastal_sun_tod.py` | Mac bake: sun lux, sky lux, sun colour and EV100 per sun elevation under sea haze; `sun_for_time()` turns place + date + clock time into a row |
| `coastal_sun_tod.json` | the table (13 rows, sun 2 to 60 deg) plus `nominal` and every constant |
| `coastal_sun_tod_curve.csv` | the same as a flat curve, for a CurveTable or the commandlet |
| `coastal_day_curve.csv` | a worked day at a stated example site (Half Moon Bay, day 265 of 2026), every 15 minutes |
| `measure_exposure.py` | the pixel gate, run on Windows on two frames |
| `PROVENANCE.json` | sources, generated-file sha256, candidates not adopted and why |

The idea: the laptop never meters. Tier 0 is a fixed manual EV100 looked up
once per shot on the CPU, so the histogram / eye-adaptation pass is not
needed. The table is about 10 KB of JSON and costs no VRAM.

What the coastal table changes against the repo's elevation bands
(`beauty_look.EV100_BANDS`):

1. **A continuous curve through the low sun.** The bands hold 13.0 from 8 to
   15 deg and jump to 13.9 at 15 deg. The coastal scenario lives exactly
   there. Table against band: 8 deg 12.16 vs 13.0 (0.84 stop), 12 deg 12.81
   vs 13.0 (0.19), 14.9 deg 13.17 vs 13.0, 15 deg 13.18 vs 13.9 (0.72),
   20 deg 13.66 vs 13.9 (0.24). Three of those are outside the 0.3 gate, and
   a clip that crosses 15 deg steps 0.9 stop in one frame under the bands.
2. **Sea haze.** Marine aerosol (optical depth 0.25 at 500 nm, about 15.7 km
   visibility) dims the direct beam and returns 60% of what it removed as sky
   light. The meter ends up 0.06 to 0.12 stop below the repo's clear-day
   model: a small exposure change, but the sun:sky ratio drops a lot (0.78 at
   12 deg), which is what makes coastal shadows soft.
3. **Sun colour against elevation**, for lanes that tint by hand (glass env
   strip, aircraft materials). Reference only for the directional light: see
   the warning below.

Nominal row (sea level, sun 12 deg): direct normal 37 721 lx, sky diffuse
10 092 lx, global horizontal 17 935 lx, **EV100 12.81**, direct-beam colour
3716 K. At the example site that sun is at 18:15 local, azimuth 262.7 deg
(over the water).

### Two things the integrator should know before merging

- **Colour temperature disagrees with the sibling lanes.** The
  `aircraft_exterior` coastal lanes proposed 4300 K at 12 deg as a stated
  pick. This lane's model gives 3716 K for the *direct beam alone* (Planck
  5778 K through Rayleigh and aerosol, no ozone; the model runs somewhat
  warm, e.g. 5031 K at 60 deg where measured direct sun is nearer 5300 K).
  Neither number is measured. One of them has to win; the table's
  `sun_linear_srgb_tint` at 12 deg is [1.0, 0.639, 0.270].
- **The white guard never fires.** `white_protect_ev` is 0 in every row: a
  sun-facing 0.80 white surface peaks at scene-linear 1.51 (8 deg), under the
  2.0 ceiling. It is kept so a brighter albedo or lower ceiling has a place
  to act, but today `target_ev100` equals `meter_ev100`.

Sea glitter is not exposed for. Its modelled peak is 17x sensor saturation at
12 deg (`sea_glitter_peak` in each row) and it clips, as it does on film.

## Tiers (VRAM and cost are ESTIMATES; none is claimed sustained)

| Tier | Render side | Est. added VRAM | Est. cost |
| --- | --- | --- | --- |
| 0 | `AEM_Manual`, EV100 = table `target_ev100` through the existing sidecar `exposure.ev100`; sun direction from `sun_for_time()`; sun stays 120 000 lx outer-space under engine transmittance; `r.EyeAdaptationQuality=0` | 0 MB | negative: removes the exposure histogram pass |
| 1 | tier 0 + SkyLight intensity pinned so the sky hemisphere delivers `sky_diffuse_horizontal_lux`, lower hemisphere set to sea bounce (albedo 0.06 x global horizontal / pi); captured once per shot, not real-time | 0 to 1 MB (existing cubemap) | none per frame |
| 2 | tier 1 + `AEM_Basic` auto exposure clamped to `target_ev100` +/- 0.3, for clips where the camera pans from the sun's glitter path to the land | about 1 MB (downsample chain) | one small downsample pass |
| 3 | tier 2 with `AEM_Histogram` and local exposure (highlight contrast 0.8) to hold the glitter path and the shaded shoreline together | about 8 to 16 MB (histogram + bilateral grid) | several full-screen passes; whether local exposure runs under D3D11 SM5 on this GPU is unknown |

Tier 0 adds no texture, no pass and no shader, so it cannot by itself cause a
device loss; that is an argument, not a measurement.

## Proposed change (for the integrator; this lane edits no shared file)

Host side: none. `FlightSimBeautyLook.cpp` already applies the sidecar's
`exposure.ev100` under `AEM_Manual`.

`core/scene/beauty_look.py`, where the base EV100 is chosen (today
`ev100_band(elevation)`), add a coastal base ahead of the band:

```python
_COASTAL_TOD = REPO / "swarm/lanes/lighting_exposure/sun_time_of_day/coastal/coastal_sun_tod.json"

def coastal_ev100(elevation_deg: float) -> Optional[Tuple[float, str]]:
    """(EV100, basis) from the baked coastal table, or None when it is absent
    or the sun is below its lowest row (2 deg): the band then stands."""
    if elevation_deg < 2.0 or not _COASTAL_TOD.is_file():
        return None
    plan = json.loads(_COASTAL_TOD.read_text())
    row = lookup(plan, elevation_deg)   # bake_coastal_sun_tod.lookup, moved here
    return row["target_ev100"], "coastal sun/time-of-day table v1 (MODEL, UNCALIBRATED)"
```

Call it when the card's surface is water / shoreline. `exposure_target()`
stays the one formula; only its `base_ev100` argument changes. Record the
basis string in the sidecar so render.json says which base ran.

Where the card states a clock time and a place but no sun, the sun direction
is `core.scenario.solar.solar_position` as today; nothing new is needed.
`sun_for_time()` in the bake is that call plus the table lookup.

`scripts/run_test_scenarios.py`, append one scenario so the gate has a frame
(the list has no coastal one today):

```python
("coastal A-4, low sun over the sea",
 "chase view of the a4 at 300 m over half moon bay at 18:15, flying south, for 6 seconds",
 {"sun_azimuth_deg": 262.7, "sun_elevation_deg": 12.0}),
```

The prompt wording is a proposal: it has not been compiled with either
interpreter. The lighting edits pin the sun, so the frame does not depend on
how the time is read.

**Do not** set the directional light's colour or temperature from
`sun_colour_temperature_k` while SkyAtmosphere transmittance is on: the
engine already reddens the 120 000 lx sun per pixel and the frame would be
tinted twice. The column is for lanes that have no atmosphere in their path.

**Do not** raise SkyAtmosphere Mie density to match the haze from this lane:
the haze lane owns that. The numbers to agree on are in
`constants` (`marine_aod_500nm` 0.25, `sea_haze_visibility_km` 15.7).

Google tiles stay the ground. Their sea is a photograph with its own baked
tone, so its effective albedo is not 0.06.

## Pixel gate (UNMEASURED; run on the Windows laptop)

```bat
rem 0. find the coastal scenario's number N after the integrator appended it
python scripts\run_test_scenarios.py --list

rem 1. baseline: the tree before the beauty_look change
python scripts\run_test_scenarios.py --still --only N
copy runs\test_scenarios\N_*.png runs\coastal_tod_baseline.png

rem 2. candidate: after the beauty_look change, same scenario
python scripts\run_test_scenarios.py --still --only N
copy runs\test_scenarios\N_*.png runs\coastal_tod_candidate.png

rem 3. gate. EV100 values: "exposure.ev100" in each run's beauty_look.json
python swarm\lanes\lighting_exposure\sun_time_of_day\coastal\measure_exposure.py --baseline runs\coastal_tod_baseline.png --baseline-ev100 <baseline ev100> --candidate runs\coastal_tod_candidate.png --target-ev100 <candidate ev100>
```

The frame's file name under `runs\test_scenarios\` is whatever the runner
writes; check the folder if the wildcard matches more than one camera.

- Metric 1, `ev_error_stops`: median log2(candidate/baseline) of linear
  luminance over the baseline's mid-tone pixels (0.02 to 0.50), minus the
  expected shift (baseline EV100 - candidate EV100). **Pass: |error| <= 0.3.**
- Metric 2, `clip_fraction` (all channels >= 250): **pass: candidate <= 0.03
  and at most 0.005 above the baseline.**
- Metric 3, `crush_fraction` (all channels <= 4): **pass: candidate <= 0.05.**

At 12 deg the expected shift is small (band 13.0, table 12.81: the candidate
should be 0.19 stop brighter). The stronger check is the same gate at 8 deg
and at 15 deg (edit `sun_elevation_deg` in the scenario), where the band is
0.84 and 0.72 stop away from the table.

The gate checks that the frame landed on the table. It does not prove the
table is the right look; that needs the grey-card probe the repo describes
for `EV100_BANDS`, at sun 8, 12 and 20 deg over water.

## Known limits

- Every constant under `constants.uncalibrated` is a stated model choice.
- Sea level only. The scenario is low VFR; above about 1 km the camera is
  over the marine layer and the repo's clear-day model is the better base.
- Clear sky with haze. Cloud or rain goes through `exposure_target`'s
  existing overcast stops, on top of this base.
- Below 2 deg and twilight are not covered; the band stands there. sosfuse2
  (twilight radiance tables) is the named follow-up; it was not fetched.
- The sun colour leaves out ozone and uses a Planck sun; see the warning
  above about the 4300 K disagreement.
- Calibration follow-up: the Poly Haven Qwantani time-of-day pure-sky series
  (CC0) would check the sun:sky ratio and colour per elevation. Not fetched.
