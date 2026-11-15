# lighting_exposure.physical_light_units.alpine -- integration

Visual-only. Everything below is written and source-tested on the Mac.
**No render, pixel or performance result exists yet: all of it is UNMEASURED
until the Windows command in "Pixel gate" has run on the laptop.**

## What this lane delivers

| File | Role |
| --- | --- |
| `bake_alpine_plu.py` | Mac bake: lux, cd/m2 and EV100 per (altitude, sun elevation) |
| `alpine_plu.json` | the table (52 rows, 4 altitudes x 13 sun elevations) plus `nominal` |
| `alpine_plu_curve.csv` | the same columns as a flat curve, for a CurveTable or the commandlet |
| `measure_exposure.py` | the pixel gate, run on Windows on two frames |
| `PROVENANCE.json` | sources, generated-file sha256, candidates not adopted and why |

The idea: the laptop never meters. Tier 0 is a fixed manual EV100 looked up
from the table on the CPU once per shot, so the histogram / eye-adaptation
pass is not needed at all. The table is 20 KB of JSON and costs no VRAM.

What the alpine table changes against the repo's elevation bands
(`beauty_look.EV100_BANDS`):

1. **Thin air.** The direct beam is brighter at altitude (already in
   `solar.illuminance_lux`) but the sky is dimmer; the IES diffuse term is
   scaled by p/p0. At 5000 m the meter sits 0.10 to 0.17 EV below the repo
   model from 25 deg up, 0.24 EV at 15 deg, and 0.32 EV at 10 deg (outside the
   0.3 gate, so the low-sun rows matter most and are the least certain).
2. **Snow guard.** With the sun low, a slope facing the sun receives several
   times the horizontal illuminance the meter reads. `snow_protect_ev`
   (0 to 1.0 stop, zero from 15 deg up) darkens the frame until sun-facing
   snow sits at scene-linear 2.0 before the tonemapper.
3. A continuous curve instead of six steps: the bands jump 0.5 to 1.0 EV at
   their edges, more than the gate allows.

Nominal row (5000 m, sun 30 deg): direct normal 90 232 lx, sky diffuse
6 270 lx, global horizontal 51 386 lx, **EV100 14.33** (band value: 14.5).

## Tiers (VRAM and cost are ESTIMATES; none is claimed sustained)

| Tier | Render side | Est. added VRAM | Est. cost |
| --- | --- | --- | --- |
| 0 | `AEM_Manual`, EV100 = table `target_ev100` through the existing sidecar `exposure.ev100`; sun stays 120 000 lx outer-space under engine transmittance; `r.EyeAdaptationQuality=0` | 0 MB | negative: removes the exposure histogram pass |
| 1 | tier 0 + SkyLight intensity pinned so the sky's diffuse horizontal illuminance equals `sky_diffuse_horizontal_lux`, and `LowerHemisphereColor` set to snow bounce (`snow_bounce_luminance_cd_m2`, neutral white); captured once, not real-time | 0 to 1 MB (existing cubemap) | none per frame |
| 2 | tier 1 + `AEM_Basic` auto exposure clamped to `target_ev100` +/- 0.3 (`AutoExposureMinBrightness`/`Max`), for clips where the camera turns from sun to shade | about 1 MB (downsample chain) | one small downsample pass |
| 3 | tier 2 with `AEM_Histogram` and local exposure (highlight contrast 0.8) to hold sun-facing snow and shaded rock together | about 8 to 16 MB (histogram + bilateral grid) | several full-screen passes; whether local exposure runs at all under D3D11 SM5 on this GPU is unknown |

Tier 0 is the one intended for the laptop. It adds no texture, no pass and no
shader, so it cannot by itself cause a device loss; that is an argument, not
a measurement.

## Proposed change (for the integrator; this lane edits no shared file)

Host side: none. `FlightSimBeautyLook.cpp` already applies the sidecar's
`exposure.ev100` under `AEM_Manual`.

`core/scene/beauty_look.py`, where the base EV100 is chosen (today
`ev100_band(elevation)`), add an alpine base ahead of the band:

```python
_ALPINE_PLU = REPO / "swarm/lanes/lighting_exposure/physical_light_units/alpine/alpine_plu.json"

def alpine_ev100(elevation_deg: float, altitude_m: float) -> Optional[Tuple[float, str]]:
    """(EV100, basis) from the baked alpine table, or None when it is absent
    or the sun is below its lowest row (2 deg): the band then stands."""
    if elevation_deg < 2.0 or not _ALPINE_PLU.is_file():
        return None
    plan = json.loads(_ALPINE_PLU.read_text())
    # bilinear, clamped: bake_alpine_plu.lookup, moved here by the integrator
    row = lookup(plan, altitude_m, elevation_deg)
    return row["target_ev100"], "alpine physical-light-units table v1 (MODEL, UNCALIBRATED)"
```

and call it for a snow / alpine surface (the same `surface` switch
`hero_lighting.plan_sidecar` takes), with `altitude_m` the **terrain** height
under the camera's subject when the shot is of the ground, or the aircraft's
altitude for an air-to-air frame. `exposure_target()` stays the one formula:
only its `base_ev100` argument changes. Record the basis string in the
sidecar so render.json says which base ran.

Tier 1, same file, where the skylight row is written: intensity such that
the sky hemisphere delivers `sky_diffuse_horizontal_lux`, lower hemisphere
luminance `snow_bounce_luminance_cd_m2`. If `core/scene/hero_lighting.py`
fill is active on the same frame, the two must not both add snow bounce:
one owner, the integrator's choice.

Do not scale SkyAtmosphere's Rayleigh density by p/p0: the engine already
thins the air with camera height. The p/p0 factor here applies only to the
table's meter column.

Google tiles stay the ground. Their snow is a photograph with its own baked
shading, so its effective albedo is not 0.90; the snow guard is the row most
likely to need a Windows correction.

## Pixel gate (UNMEASURED; run on the Windows laptop)

Scenario 11 is the Matterhorn frame (`python scripts\run_test_scenarios.py --list`).

```bat
rem 1. baseline: the tree before the beauty_look change
python scripts\run_test_scenarios.py --still --only 11
copy runs\test_scenarios\11_*.png runs\alpine_plu_baseline.png

rem 2. candidate: after the integrator's change, same scenario
python scripts\run_test_scenarios.py --still --only 11
copy runs\test_scenarios\11_*.png runs\alpine_plu_candidate.png

rem 3. gate. EV100 values: "exposure.ev100" in each run's beauty_look.json
python swarm\lanes\lighting_exposure\physical_light_units\alpine\measure_exposure.py --baseline runs\alpine_plu_baseline.png --baseline-ev100 <baseline ev100> --candidate runs\alpine_plu_candidate.png --target-ev100 <candidate ev100>
```

The frame's file name under `runs\test_scenarios\` is whatever the runner
writes for scenario 11; check the folder if the wildcard matches more than
one camera.

- Metric 1, `ev_error_stops`: median log2(candidate/baseline) of linear
  luminance over the baseline's mid-tone pixels (0.02 to 0.50), minus the
  expected shift (baseline EV100 - target EV100). **Pass: |error| <= 0.3.**
- Metric 2, `snow_clip_fraction` (all channels >= 250): **pass: candidate
  <= 0.01 and not above the baseline.**
- Improvement against the reference means: metric 1 passes (the table's
  exposure actually reached the frame) and metric 2 is lower than or equal
  to the baseline's.

The gate checks that the frame landed on the table. It does not prove the
table is the right look; that needs the grey-card probe the repo already
describes for `EV100_BANDS` (sunlit 18% card near 18% of white after the
tonemapper), at 5000 m with the sun at 10, 30 and 60 deg.

## Known limits

- All of `snow_albedo`, the snow-guard ceiling and cap, and the p/p0 sky
  scaling are UNCALIBRATED model choices, listed in `alpine_plu.json`.
- Snow-to-sky inter-reflection (bright ground relighting the sky) is left
  out; it would raise the global illuminance by a few percent (under 0.1 EV).
- Clear sky only. Cloud or storm over the Alps goes through
  `exposure_target`'s existing overcast stops, on top of this base.
- Below 2 deg and twilight are not covered; the band stands there.
- Calibration follow-up: the Prague Sky Model data or a Poly Haven pure-sky
  HDRI would check the thin-air sun:sky ratio. Neither was fetched; the
  Prague licence is unverified.
