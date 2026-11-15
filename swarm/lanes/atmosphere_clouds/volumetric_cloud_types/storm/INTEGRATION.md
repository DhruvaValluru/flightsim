# atmosphere_clouds.volumetric_cloud_types.storm: integration

Status: **UNMEASURED**. Everything here was baked and checked on the Mac. No
frame was rendered, so no tier is known to hold on the laptop and no visual
claim is made. The cell's shape, the liquid-water and droplet-size picks and
the three scattering-octave factors are **visual-only**.

## What this lane gives

Three storm cloud types (`baked/storm_cloud_types.json`), with the render
extinction scaled once (x 0.19987) so the domain's mean diffuse transmittance
is the exposure lane's deck fraction, 0.25:

| Type | Base-top (m) | Extinction, physical / render (1/m) | Optical depth, physical / render |
|---|---|---|---|
| Cumulonimbus core | 600-11 000 | 0.150 / 0.030 | 1 560 / 312 |
| Nimbostratus deck | 600-3 000 | 0.067 / 0.013 | 160 / 32 |
| Scud (fractus) | 300-500 | 0.030 / 0.006 | 6 / 1.2 |

The physical types alone would transmit less than the look's 0.25; the scale
is the reconciliation, not a measurement. Core columns transmit 0.046, the
thinnest deck 0.40.

Radiometric budget against the SkyAtmosphere reference (clear sky, 28 degree
sun, 50 193.6 lux horizontal): dome 10 666 lux + directional patch 1 882 lux =
12 548 lux = reference x 0.25, residual 1e-5. Baked under-deck luminance runs
2 887 to 3 990 cd/m2 (zenith 3 392, horizon 3 425), well under the 15 977
cd/m2 a Lambert surface in the clear sky would show. The spread is small
(0.26 stops, p05 to p95) because at 3 km visibility the veil hides most of
the base; the darkest direction is toward the core.

Phase function for 20 um droplets (HG + Draine, mean cosine 0.879), as two HG
lobes for the engine: `PhaseG 0.9946`, `PhaseG2 0.7632`, `PhaseBlend 0.4982`.
The fit constants were transcribed and **not re-read against the paper** in
this session; check them against the PDF before they ship.

Baked files, all linear (sRGB off), no mip streaming needed at these sizes:

| File | Use |
|---|---|
| `storm_underdeck_256x64.hdr` | tier 0 sky dome, upper hemisphere, row 0 = zenith, column 0 = toward the core |
| `storm_weather_128.tga` | tiers 1-3: R optical depth, G top fraction, B rain-shaft mask; 32 km square |
| `storm_noise_32_atlas.tga` / `storm_noise_64_atlas.tga` | tiers 1-3 erosion noise, 8-wide slice atlases for a volume texture |

## Proposed changes (for the integrator; this lane edited no shared file)

1. **Tier 0, `FlightSimClouds.cpp`, storm preset only.** Hide the
   VolumetricCloud component (the `M_StormCell` march) and draw the panorama on
   the existing sky dome as an unlit emissive: `emissive = texture x 3395.1
   cd/m2 x the 7000 K tint`, lat-long lookup on the upper hemisphere, azimuth 0
   turned to the scenario's cell bearing. Below the horizon keep the
   `-storm-lower-hemisphere` owner. Suggested switch, default off until
   measured: `-storm-cloud-tier=0..3`, recorded per frame like the other cloud
   switches.
2. **Tier 0 in cloud.** The panorama is valid for a camera under the 600 m
   base. At or above it, draw only the exponential height fog as the veil,
   in-scatter at or under 1 455 cd/m2 (the exposure lane's ceiling).
3. **Tiers 1-3, `M_StormCell`.** Keep the material; feed it the weather map
   (world-aligned, 32 km, centred on the cell) and the noise volume, set
   `ExtinctionScale` from `extinction_per_m_render`, the three phase values
   above, and `MultiScatteringContribution / Occlusion / Eccentricity = 0.5`
   with 1, 2, 3 octaves by tier. Component and cvar values per tier are in the
   JSON's `tiers`. The cvar names are from memory of UE 5.x: check each with
   `help` in the pinned build before use.
4. **Google tiles stay the ground** at every tier; nothing here replaces or
   hides them. The web app's weather defaults are untouched.
5. **Other storm lanes** should read `shared_params` in the JSON: cloud base
   600 m, cell top 11 000 m, core radius 5 km at 6 km, haze 0.001304 1/m,
   rain-shaft mask in the weather map's B channel.

## Tiers (VRAM figures are estimates)

| Tier | Est. VRAM | What |
|---|---|---|
| 0 | 0.2 MB | no ray march; baked panorama on the dome, height fog as the in-cloud veil |
| 1 | 8 MB | quarter-resolution march, 32^3 noise, 1 octave, no cloud shadow map, 15 km trace |
| 2 | 14 MB | 64^3 noise, 2 octaves, sky AO, 25 km trace |
| 3 | 40 MB | half-resolution march, 3 octaves, cloud shadow map, 40 km trace |

Tier 0 is designed to be the stable one because it removes the march that
scene 9 ran when it lost the device; whether that march caused the 12 device
losses is not established.

## Measuring it on the Windows laptop

Reference first (current code), then the candidate (change 1 applied), same
scenario. Confirm the number with `--list`: it is "747 through a thunderstorm".

```
.venv\Scripts\python.exe scripts\run_test_scenarios.py --only 9 --still
.venv\Scripts\python.exe swarm\lanes\atmosphere_clouds\volumetric_cloud_types\storm\measure_frame.py --frame <candidate frame.png> --reference <reference frame.png> --horizon-row <horizon as a fraction of frame height>
```

Pass: `under_deck_error_ev <= 1.0` (median sky over median ground, in stops,
against the expected 3.559), no larger than the reference frame's,
`black_fraction <= 0.02`, and sky contrast within 1 stop of the baked 0.264.

Caveats. The metric is display-referred, so the tone curve compresses it by an
unmeasured amount. The expected 3.559 stops assumes a Lambert ground of albedo
0.085; the Google tiles' own albedo and the veil over distant ground both pull
the ratio down. The aircraft sits in one of the two regions; medians are used
to resist it. A still under the base is needed: a frame taken inside the cloud
has no sky region to measure.

## Regenerate

```
.venv/bin/python swarm/lanes/atmosphere_clouds/volumetric_cloud_types/storm/generate.py
.venv/bin/python -m pytest tests/test_swarm_atmosphere_clouds_volumetric_cloud_types_storm.py
```

Deterministic on this Mac; the test pins the bytes to PROVENANCE.json. The
bake uses `exp`, `sin` and `tan`, so another platform's maths library could
move an 8-bit value by one step and change a hash without changing the look.

## Considered and not adopted

Prague sky model and its altitude wrapper (clear and twilight skies, dataset
licence unverified), AT3D's LES fields (GPL-3.0, shallow cumulus), skytracer's
aerosol tables (aerosol, not droplets) and Poly Haven pure skies (partly
cloudy daylight). Nothing was downloaded or vendored.
