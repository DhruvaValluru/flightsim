# lighting_exposure.physical_light_units.storm: integration

Status: **UNMEASURED**. Everything here was computed on the Mac. No frame was
rendered, so no tier is known to hold on the laptop and no visual claim is
made. Colour temperatures, the directional share and the wet-albedo factor are
**visual-only** choices.

## What this lane gives

`baked/storm_plu.json` states every light of the storm scene in physical
units, held to the project's own storm look (EV100 12.5 = band 14.5 at a 28
degree sun, minus 2 stops for the 0.25 deck fraction).

| Quantity | Value | Unit |
|---|---|---|
| Horizontal illuminance under the deck | 12 548 | lux |
| Manual exposure | 12.5 | EV100 |
| Incident-meter EV100 of that illuminance (C = 250) | 12.29 (0.21 under the look) | EV100 |
| Grey-card reflected-meter EV100 (K = 12.5) | 12.49 (0.01 under the look) | EV100 |
| Sky dome on the horizontal | 10 666 | lux |
| SkyLight intensity with the baked cube | 3 395 | cd/m2 |
| Sky zenith / horizon luminance | 4 365 / 1 455 | cd/m2 |
| Directional "bright patch", at the ground on its normal | 4 009 | lux |
| The same light before atmosphere transmittance (0.688) | 5 825 (0.0486 of the 120 000 sun) | lux |
| Wet ground albedo (0.17 dry x 0.5) | 0.085 | - |
| Lightning, first-stroke peak, 5 km channel | 1.91e10 | cd |

Both meter readings sit inside the +/-0.3 EV gate of the look, so the physical
set and the look agree on paper. Whether the rendered frame agrees is the
pixel gate below.

`baked/storm_overcast_sky_256x128.hdr` is the CIE overcast sky as a lat-long,
normalised so SkyLight intensity x pi = horizontal lux. It is azimuthally
symmetric: only "top row is zenith" matters at import.

## Proposed changes (for the integrator; this lane edited no shared file)

1. **Sky dome** (`FlightSimHeroLighting.cpp` or the world lane's skylight, storm
   deck only): import the `.hdr` as a TextureCube (HDR, no sRGB, max size per
   tier), set the SkyLight to `SLS_SpecifiedCubemap`, `Intensity = 3395.1`
   (cd/m2), real-time capture off. The existing `-storm-lower-hemisphere`
   owner keeps the lower hemisphere.
2. **Directional light** under a storm deck: `Intensity = 5825.4` lux (or the
   project sun x 0.04855), `CastShadows = false`, direction unchanged
   (storm_soft_sheen, 20 deg off the lens axis, 28 deg up). If the drawn deck
   already shadows the sun light, use the ground value instead and bypass the
   deck shadow for this light; the calibration quad says which (see below).
3. **Exposure**: no change to the number. Keep manual EV100 12.5 and the frame
   meter. The expected effect of 1 and 2 is that the frame meter has less to
   correct (`look_applied.storm_exposure` stops closer to 0).
4. **Lightning** (`core/scene/lightning.py` consumers): tier 0 pulses the
   SkyLight intensity by `1 + peak_over_ambient` for the flash frame (table in
   the JSON, by distance); tiers 1-3 use one unshadowed inverse-square point
   light at `peak_intensity_cd`. The exposure does not follow the flash.
5. **Fog and rain veil lanes**: in-scatter luminance at or below 1 455 cd/m2
   (the horizon), or the veil lifts the frame's p90 and the meter with it.

## Tiers (VRAM figures are estimates: RGBA16F cube with mips)

| Tier | Est. VRAM | What |
|---|---|---|
| 0 | 0.06 MB | constants, 32 px cube, lightning as a SkyLight pulse, no light actors, no capture |
| 1 | 0.25 MB | 64 px cube, lightning as one unshadowed point light |
| 2 | 1.0 MB | 128 px cube, plus the project's storm local-exposure block |
| 3 | 4.0 MB | 256 px cube, plus bloom on the flash |

No tier uses Lumen, ray tracing, shadowed flashes or a real-time sky capture.
The memory cost is small at every tier; the per-frame GPU cost of the point
light and bloom is unmeasured.

## Measuring it on the Windows laptop

Reference first (current code), then the candidate (changes 1-2 applied), same
scenario. Confirm the number with `--list`: it is "747 through a thunderstorm".

```
.venv\Scripts\python.exe scripts\run_test_scenarios.py --only 9 --still
.venv\Scripts\python.exe swarm\lanes\lighting_exposure\physical_light_units\storm\measure_frame.py --frame <candidate frame.png> --reference <reference frame.png>
```

Pass: `|ev_error| <= 0.3` display stops against the 0.40 p90 target, clipped
fraction at most 1 %, and no further from the target than the reference.

Two caveats on that metric. The frame meter already steers p90 toward 0.40, so
a pass on `ev_error` alone does not show the lights are right; also read the
meter's recorded stops in `look_applied.storm_exposure` for both runs, which
should shrink in size. And the subject meter may move the frame after the frame
meter, by up to 1 stop open.

Incident check of change 2 (does the deck shadow the directional light):
render with `--calibration` and compare the white quad's reading with
4 009 lux on the light's normal.

## Regenerate

```
python3 swarm/lanes/lighting_exposure/physical_light_units/storm/generate.py
```

Deterministic; the test pins the bytes to PROVENANCE.json.
