# weather_fx.lightning.storm: integration

Status: UNMEASURED. Everything here was computed or written on the Mac. No
frame was rendered, nothing was downloaded, nothing was vendored. Visual-only.

## What the arithmetic says (baked/lightning_glow.json, `by_distance`)

The project's first return stroke, whole inside a 1/60 s exposure, at the storm
look's EV100 12.5 and assumed 3000 m visibility (sky at the horizon 1455 cd/m2,
ambient 12 548 lux):

| Bolt at | Optical thickness | Core, rain applied | Core / sky | Rain glow peak | Flash light / ambient |
|---|---|---|---|---|---|
| 1 km | 1.30 | 5646 cd/m2 | 3.9 | 11 cd/m2 | 0.8 % |
| 2 km | 2.61 | 766 cd/m2 | 0.53 | 5.4 cd/m2 | 0.2 % |
| 3 km | 3.91 | 139 cd/m2 | 0.095 | 3.6 cd/m2 | 0.09 % |
| 5 km | 6.52 | 6.1 cd/m2 | 0.004 | 2.1 cd/m2 | 0.03 % |
| 8 km | 10.4 | 0.08 cd/m2 | 0.0001 | 1.3 cd/m2 | 0.01 % |

Three consequences:

1. **The flash light is the expensive part and it is worth under 1 % of the
   daylight.** `FlightSimWeather.cpp` builds a movable point light with
   `SetCastShadows(true)` and a 30 km attenuation radius. On a stroke frame that
   is a cube shadow pass over the whole scene, for a change in scene
   illuminance of 0.03 % to 0.8 %. Tier 0 drops it.
2. **The rain glow is a wide, faint veil in daylight**, under 1 % of the sky
   behind it at every distance. It is baked and ready, but it does not earn its
   overdraw in this scenario's daytime exposure. It is tier 2, not tier 0. It
   would matter at a night exposure (about ten stops lower); that is another
   scenario's call.
3. **Whether the channel shows at all (WX.5) depends on distance against
   visibility.** With rain extinction applied the core is 53 % over the sky at
   2 km and gone by 5 km. Whether the engine's fog already dims the ribbon is
   not known here; see change 2.

## Proposed changes (shared files: for the integrator, not applied)

### 1. Tier 0: no flash light actor

`ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimWeather.cpp`,
`BuildLightning`, the block that creates `FlashLight`:

```cpp
// was: unconditional, SetCastShadows(true)
if (LightningTier >= 1)   // the stress ladder's tier; 0 on the integrated laptop
{
	FlashLight = NewObject<UPointLightComponent>(LightningActor, TEXT("FlashLight"));
	...
	FlashLight->SetCastShadows(LightningTier >= 3);
	...
}
```

`Advance` already guards on `FlashLight != nullptr`, and `FlashLux`, the storm
material's `Flash` vector and `LastFlashLux()` do not depend on the light, so
rain, splashes, cloud glow and the sky pulse keep their flash. Record
`flash_light: none | unshadowed | shadowed` in the lightning row of the weather
record. This agrees with tier 0 of
`swarm/lanes/lighting_exposure/physical_light_units/storm` (lightning as a
SkyLight pulse, no light actors).

### 2. Rain transmittance on the channel core (tier 1 and up, off by default)

`assets/shaders/weather/lightning_emissive.hlsl`: one new scalar input
`RainSigmaPerM` (default 0 = today's picture), last line becomes

```hlsl
float transmittance = exp(-RainSigmaPerM * Depth / 100.0);
return tint * (luminance * profile * tip * transmittance);
```

Set it to `shared_params.rain_extinction_per_m` (0.001304) only if the Windows
measurement shows the engine's fog is not already dimming the ribbon (compare
the stroke frame's core against the table's "no rain" and "rain applied"
columns). This is a decision, not a fix: at the storm's default 5 km the
physically dimmed core fails WX.5, and the clause says the channel shows.

### 3. The baked rain glow (tier 2 and up)

Import `baked/lightning_apsf_line_64x32.png` (and `_point_` for tier 3) as
`TC_Grayscale` G16, sRGB off, no mips, clamp, bilinear. Add one additive unlit
quad per lit flash (the main channel's ribbon again with `Side` scaled to
`GlowHalfAngle = 0.5 rad`: world offset `side * Side * dist * tan(GlowHalfAngle)`)
whose emissive custom node includes `baked/lightning_apsf.hlsl` and returns

```hlsl
float distM = Depth / 100.0;
float T = RainSigmaPerM * distM;
float k = FsApsfKernel(Lut, LutSampler, T, abs(Side) * GlowHalfAngle, FS_APSF_LINE_LN_MIN, FS_APSF_LINE_LN_MAX);
float kEdge = FsApsfKernel(Lut, LutSampler, T, GlowHalfAngle, FS_APSF_LINE_LN_MIN, FS_APSF_LINE_LN_MAX);
float luxPerRad = lumensPerM / (3.14159265 * 3.14159265 * distM);   // the line source at the eye
return tint * luxPerRad * max(k - kEdge, 0.0) * tip;                 // cd/m2, as the core
```

`lumensPerM`, `tint` and `tip` as in `lightning_emissive.hlsl`. The material
script (`scripts/ue_create_materials.py`) would create it as
`M_LightningGlow`; a missing material must refuse by name
(`weather.lightning_material`), as the core's does.

## Tiers (estimates; none is claimed sustained)

| Tier | Est. VRAM | Glow | Flash light |
|---|---|---|---|
| 0 | 0 MB added | none | none (FlashLux scalar only) |
| 1 | 0.01 MB | none | one unshadowed point light |
| 2 | 0.02 MB | line LUT, one additive quad per lit flash, about a third of the frame in overdraw on stroke frames | one unshadowed point light |
| 3 | 12 MB | line LUT quad + point LUT billboard | today's shadow-casting point light (1024 px cube shadow, estimate) + bloom |

No tier uses Lumen, ray tracing, D3D12 or Nanite. Per-frame GPU cost of every
tier is unmeasured.

## Measuring it on the Windows laptop

Reference first (current code), then the candidate (change 1), same pinned
spec. Scenario 9 is "747 through a thunderstorm" (confirm with `--list`). At 6
flashes a minute, a quarter cloud-to-ground, a short clip may hold no stroke:
check `weather.lightning.flashes` in the run's card and lengthen `--clip` until
one `kind: cg` flash falls inside it.

```
.venv\Scripts\python.exe scripts\run_test_scenarios.py --only 9 --clip 6 --spec-dir runs\wx_lightning_specs
.venv\Scripts\python.exe swarm\lanes\weather_fx\lightning\storm\measure_frame.py --frames <candidate run>\frames\<camera> --reference-frames <reference run>\frames\<camera>
```

Gate: `stroke_contrast >= 3.0` on the candidate and `>= 0.9 x` the
reference's, with the render finishing without a device-lost error. Exit 0
pass, 1 fail, 2 not exercised (no stroke in the clip). The gate shows the
channel survived losing the light; the claim that tier 0 is steadier is only
shown by the stress ladder completing scene 9, which this script does not
measure. `halo_ratio` is printed for tier 2 comparisons and has no threshold
yet.

## Regenerating

```
.venv/bin/python swarm/lanes/weather_fx/lightning/storm/generate.py
.venv/bin/python -m pytest tests/test_swarm_weather_fx_lightning_storm.py -q
```

Regenerating changes the hashes in `PROVENANCE.json` only if the numbers
change; update them there if so.

## Not claimed

* Any rendered result, any frame time, that any tier is sustained.
* q = 0.9 as a measurement: it is the wide end of the paper's range for rain.
  The series was written from the published form and not re-read against the
  PDF in this session; its sphere integral is checked numerically.
* The (1 - e^-T) energy scale is this lane's approximation, and the table
  assumes uniform rain from camera to channel.
* None of the research candidates was downloaded or adopted (reasons in
  `PROVENANCE.json`): the project already owns the channel geometry and the
  stroke curve, and its thunder is tied to them.
