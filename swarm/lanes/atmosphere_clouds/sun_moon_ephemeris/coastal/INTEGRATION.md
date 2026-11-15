# atmosphere_clouds.sun_moon_ephemeris.coastal: integration

Status: **UNMEASURED**. Everything here was computed on the Mac. No frame was
rendered, no tier is claimed sustained, and the engine behaviour this lane
leans on is recalled, not read from the UE 5.7 source. The pixel gate at the
bottom is what turns any of it into a measurement, on the Windows laptop.

Not visual-only: the numbers are radiometric (lux, transmittance). The site is
a stated choice (Half Moon Bay, KHAF, coordinates recalled) because no coastal
card exists yet; pass the card's own `--lat --lon --date` and re-bake.

## What the lane holds

| File | What |
|---|---|
| `bake_ephemeris.py` | the offline generator, the `lookup()` the planner would call, and the `measure` gate |
| `out/ephemeris_coastal.json` | evening track every 5 min (sun and moon direction, phase, lux above the atmosphere, SkyAtmosphere transmittance, ground lux), dusk times, the table `T(elevation, altitude)`, the gate's reference ratios, `shared_params` |
| `out/T_SunMoonTransmittance_64x16.png` | the table as a 989-byte linear strip (value = sqrt(T)), for tier 2 only |
| `PROVENANCE.json` | sources, licences, sha256 of both outputs; nothing fetched |

Re-bake: `.venv/bin/python swarm/lanes/atmosphere_clouds/sun_moon_ephemeris/coastal/bake_ephemeris.py`

## The key instant (2026-03-21 01:17:28 UTC, 18:17 local)

| | value |
|---|---|
| sun | azimuth 260.90 deg true, apparent elevation 12.00 deg |
| sun above the atmosphere | 134 172 lx |
| SkyAtmosphere transmittance at the ground (linear Rec.709) | 0.751, 0.517, 0.280 |
| sun at the ground, normal incidence, engine-default atmosphere | 73 794 lx |
| same, Bird & Hulstrom (`core/scenario/solar.py`) | 55 554 lx |
| tint on a D65 sun | about 4080 K (three-band estimate) |
| moon | azimuth 257.3 deg, elevation 37.6 deg, 5.3 % lit waxing crescent, 0.0009 lx |
| sunset / civil dusk | 02:22:24 / 02:48:11 UTC |

The thin crescent sits 26 deg above the setting sun on this date, in frame for
a west-looking shot.

## Two things the arithmetic predicts about today's scene

Both are predictions for the gate, not observations.

1. **Which lux the sun is given.** `FlightSimVisualScene.cpp` sets
   `SetAtmosphereSunLight(true)`, and its own record says the atmosphere's
   transmittance is "applied on top of the stated lux". So the stated lux has
   to be the value above the atmosphere. A card that states the Bird & Hulstrom
   ground value (55.6 klx here) drives the sky's scattering with 0.41 of the
   real sun: the sky comes out about 1.3 stops dark against the sunlit ground.
2. **`TransmittanceMinLightElevationAngle = 90.0f`.** As recalled, this floors
   the elevation used for the light's ground transmittance. At 90 the 12 deg
   sun would light the ground with the zenith tint (0.940, 0.868, 0.762): too
   bright by 1.25 / 1.68 / 2.72 in R / G / B, so the low-sun warmth never
   reaches the ground or the aircraft. The comment beside it describes a
   different effect (evaluating from the camera's position), so one of the two
   readings is wrong; the gate's reference pair settles it.

## Proposed changes (for the integrator; this lane edits no shared file)

**A. `core/sky/plan.py`, `plan_sky`:** add to the `sun` block
`toa_lux = solar.SUN_LUX_MAX * (astro.AU_KM / sun.distance_km) ** 2` and
`transmittance_rgb` from this lane's table (`lookup(table, elevation, 0.0)`),
and to the `moon` block `transmittance_rgb` the same way. Promote the table to
`assets/sky/` when adopting.

**B. Commandlet, where `Options.SunLux` is resolved:** when the sun is an
atmosphere sun light, use `sun.toa_lux`. Keep `-sun-lux=` as the override.

**C. `FlightSimVisualScene.cpp`, atmosphere block:**

```cpp
// was 90.0f: the light's ground transmittance was taken at the zenith
Atmosphere->TransmittanceMinLightElevationAngle = -1.0f;
```

If the "ground blacks out at altitude" problem the old comment guards against
comes back with the tiles' georeferenced origin, revert C and instead set the
light explicitly: `SunLight->SetLightColor(T(e) / T(90))` with intensity
`toa_lux`. That fixes the ground but dims the sky by the same tint, so it is
the fallback, not the first choice.

**D. `FlightSimSky.cpp`, moon material:** set a `Tint` vector parameter on the
`M_Moon` instance to `moon.transmittance_rgb` (needs the parameter added to
the material).

## Tiers (VRAM and cost are estimates)

| Tier | Est. VRAM | What runs on the laptop |
|---|---|---|
| 0 | 0 MB | A to D. CPU constants only: no texture, no pass, no extra light. The engine already builds its transmittance LUT. |
| 1 | ~0.1 MB | tier 0 + the moon as a second directional light with `SetAtmosphereSunLight(true)`, `SetAtmosphereSunLightIndex(1)`, no shadows, lux from the track, so the sky scatters moonlight after dusk. |
| 2 | ~0.2 MB | tier 1 + `bPerPixelAtmosphereTransmittance` on the sun (aircraft aloft gets the thinner-air tint: at 3 km, 0.823 / 0.620 / 0.423 instead of 0.751 / 0.517 / 0.280) and the 64x16 strip sampled across the sun and moon discs for limb reddening at the horizon. |
| 3 | ~8 MB | tier 2 + the moon casts shadows after dusk (2 cascades at 1024). |

Import for the strip: linear (sRGB off), no mips, clamp, uncompressed (it is
4 KB). `u -> elevation = -3 + 93 u^2` deg, `v -> altitude = 15 v` km,
`T = sample^2`.

## Pixel gate (Windows laptop only)

Four still frames of the same view with a flat neutral surface (runway or
apron) partly in the aircraft's shadow, fixed exposure, clouds off so the
shadow edge is clean. Flag names are the ones the commandlet parses; their
exact behaviour is unverified here.

```powershell
.\scripts\render_ue_scenario.ps1 <coastal card> runs\swarm\ephem_coastal\ref_lo  -calibration -sun-azim=260.9 -sun-elev=12
.\scripts\render_ue_scenario.ps1 <coastal card> runs\swarm\ephem_coastal\ref_hi  -calibration -sun-azim=260.9 -sun-elev=60
# apply A to C, rebuild, then:
.\scripts\render_ue_scenario.ps1 <coastal card> runs\swarm\ephem_coastal\cand_lo -calibration -sun-azim=260.9 -sun-elev=12
.\scripts\render_ue_scenario.ps1 <coastal card> runs\swarm\ephem_coastal\cand_hi -calibration -sun-azim=260.9 -sun-elev=60
.\.venv\Scripts\python.exe swarm\lanes\atmosphere_clouds\sun_moon_ephemeris\coastal\bake_ephemeris.py measure `
  --ref-low runs\swarm\ephem_coastal\ref_lo\<frame>.png --ref-high runs\swarm\ephem_coastal\ref_hi\<frame>.png `
  --low runs\swarm\ephem_coastal\cand_lo\<frame>.png --high runs\swarm\ephem_coastal\cand_hi\<frame>.png `
  --lit-rect <x,y,w,h> --shadow-rect <x,y,w,h>
```

Metric: sun-only light = lit patch minus shadowed patch, in linear RGB. Take
its R/G and B/G at 12 deg divided by the same at 60 deg (albedo, exposure and
the cosine cancel) and compare with the SkyAtmosphere reference, 1.3229 and
0.6292. `chroma_stops` is the larger `|log2(measured / reference)|`.

Threshold: candidate `chroma_stops <= 0.15`, and below the reference pair's.
If reading 2 above is right the reference pair scores about 0.67; if it scores
under 0.15 already, change C is unnecessary and should be dropped.

Also printed, not gating: `level_g_stops`, the green 12/60 level against
0.1463 for a horizontal surface (needs identical exposure in both frames;
within 0.25).

Limits of the gate: the frames must be unclipped in both patches (the script
refuses otherwise), and a tone curve left on by `-calibration` would bend the
ratios; pass `--encoding linear` if the frames are written linear.
