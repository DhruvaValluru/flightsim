# aircraft_exterior.glass.coastal -- integration notes (visual-only)

Status: written and source-tested on the Mac. **Every render-side claim below is
UNMEASURED.** Nothing here has been drawn by Unreal or the laptop GPU. No tier is
sustained until the stress ladder runs it on the Windows laptop.

## What the lane bakes (Mac, `bake_glass.py bake`)

| File (`out/`) | Size | Content | UE import |
|---|---|---|---|
| `T_GlassFresnel_LUT.png` | 64x1 | R = sqrt(slab reflectance), G = sqrt(single-face Fresnel), B = slab transmittance; u = N.V | linear, BGRA8, no mips, clamp |
| `T_GlassEnv_{64,128,256}.png` | 2:1 lat-long | coastal low-sun sky + Fresnel sea, sun disc excluded, u = 0.5 faces the sun | sRGB, BGRA8, wrap U / clamp V |
| `T_GlassMicro_N_{256,512,1024}.png` | square, tiles | tangent normal, green down (DirectX/UE) | TC_Normalmap (BC5), do not flip green |
| `T_GlassFilm_M_{256,512,1024}.png` | square, tiles | R roughness add, G salt-film coverage, B scratch mask | TC_Masks (BC1, linear) |
| `glass_coastal.json` | -- | all scalars, tiers, sha256 | read by `scripts/aircraft_look.py` |

The env strip is an **analytic stand-in** (gradient sky, haze, sun glow, Fresnel
sea). If a sky lane ships a baked sky LUT for "coastal", regenerate the strip from
it; until then keep `shared_params` in `glass_coastal.json` equal to that lane's
sun elevation, haze and colours, or the canopy mirrors a different sky from the one
behind it.

## Tiers (VRAM is an estimate: texture bytes with mips)

| Tier | Est. MB | Blend | Samples per pixel | What it adds |
|---|---|---|---|---|
| 0 | 0.011 | opaque `M_AircraftGlass` | 2 (LUT, env 64) | view-angle reflection of the baked sky/sea; no translucency pass, no SSR |
| 1 | 0.167 | opaque | 4 (+ micro N, film M at 256) | scratches catching the low sun, salt-film roughness, env 128 |
| 2 | 0.542 | Thin Translucent `MI_<slot>_thin` on unlabelled frames | 4 (512) | see-through canopy; B channel of the LUT scales Transmittance; SSR off |
| 3 | 2.167 | Thin Translucent | 4 (1024, env 256) | tier 2 + SSR on the canopy |

Tiers 0 and 1 keep the opaque master, so they are label-safe and add no sorted
translucent pass: the pass most likely to matter on a D3D11 integrated GPU that
has lost the device 12 times. Tiers 2 and 3 follow the existing rule in
`FlightSimAircraftFX.h` (`bLabels` keeps the opaque instance).

## Proposed changes to shared files (the integrator applies these; this lane edits none)

### 1. `M_AircraftGlass` and `M_AircraftGlassThin` (master graphs)

New parameters: textures `GlassFresnelLUT`, `GlassEnv`, `GlassMicroN`, `GlassFilmM`;
scalars `GlassEnvGain` (default 0 = today's look), `GlassMicroTileM` (0.35),
`GlassMicroStrength` (0), `GlassSaltCoverage` (0); vector `GlassSunAzimuthDir`
(world XY unit vector toward the sun).

Custom node, SM5-safe, no branches on textures:

```hlsl
// N: world normal (after micro normal), V: camera vector, both normalised
float  ndv  = saturate(dot(N, V));
float3 lut  = Texture2DSample(GlassFresnelLUT, GlassFresnelLUTSampler, float2(ndv, 0.5)).rgb;
float  Rs   = lut.r * lut.r;          // slab reflectance
float  Tsl  = lut.b;                  // slab transmittance (thin master only)
float3 R    = reflect(-V, N);
float2 sd   = GlassSunAzimuthDir.xy;  // toward the sun, horizontal
float  az   = atan2(R.x * sd.y - R.y * sd.x, R.x * sd.x + R.y * sd.y);
float2 uv   = float2(az / 6.2831853 + 0.5, 0.5 - asin(clamp(R.z, -1, 1)) / 3.14159265);
float3 env  = Texture2DSampleLevel(GlassEnv, GlassEnvSampler, uv, 0).rgb;  // sRGB sampler decodes
float3 Emis = env * 1.5 * Rs * GlassEnvGain;   // 1.5 = shared_params.env_encode_scale
```

* `Emis` goes to Emissive Color. `GlassEnvGain` is the horizon-haze luminance of
  the drawn sky in the engine's scene units, so decoded strip value 0.74 / 1.5 (the haze colour, red) equals the sky at
  the anti-sun horizon. The integrator takes it from the sky the render builds; this lane
  cannot know it and ships 0 as the default.
* Double counting: the baked strip **replaces** the sky-light specular on the
  glass slot. With `GlassEnvGain > 0`, set the material's Specular to 0 on the
  opaque master is NOT acceptable (it also kills the sun glint), so instead drive
  the sky light's contribution down on this slot only if the engine exposes it;
  if it does not, use the strip only where the sky-light capture is static or
  absent (the integrated-tier budget has `r.DynamicGlobalIlluminationMethod 0`)
  and leave `GlassEnvGain = 0` otherwise. UNMEASURED which case the laptop is in.
* Roughness = `0.02 + 0.10 * FilmM.r * (GlassSaltCoverage or 1)`; Base Color =
  `lerp(GlassTint, 0.75, FilmM.g * 0.12 * GlassSaltCoverage)`; Normal = blend of
  the mesh normal with `GlassMicroN` scaled by `GlassMicroStrength`. Micro UVs are
  object-space triplanar or the mesh UV times `1 / GlassMicroTileM`.
* Thin master: Transmittance = `THIN_VECTORS.Transmittance * Tsl / Tsl(ndv=1)`.

### 2. `scripts/aircraft_look.py`

Add a `GLASS_BAKE` block read from
`swarm/lanes/aircraft_exterior/glass/coastal/out/glass_coastal.json`, importing the
tier's textures under `Look/Glass/` and setting the parameters above on `MI_<slot>`
(and `MI_<slot>_thin` at tiers 2-3). `GLASS_IOR`, `GlassTint` and `THIN_VECTORS`
are unchanged: the bake reads the same numbers (1.49, (0.018, 0.022, 0.026),
(0.80, 0.84, 0.82)); if they change there, re-bake.

### 3. `FlightSimAircraftFX.cpp` / the commandlet

New switch `-aircraft-glass-tier=off|0|1|2|3`, default `off` until the pixel gate
below passes on the laptop. Record the tier, `GlassEnvGain` and the texture names
in `render.json` under `aircraft_look.glass_bake`. Set `GlassSunAzimuthDir` from
the directional light each step. A tier whose textures are missing is RECORDED and
falls back to `off` (the look decorates a complete run), same as the other look
elements.

Google tiles and the weather defaults are untouched by this lane.

## Pixel gate (Windows laptop only)

After the three changes above are in, from the repo root in PowerShell, with
`<card>` the coastal scenario run card (hero exterior camera, canopy in frame):

```powershell
.\scripts\render_ue_scenario.ps1 <card> runs\swarm\glass_coastal\ref -aircraft-glass-tier=off
.\scripts\render_ue_scenario.ps1 <card> runs\swarm\glass_coastal\t0  -aircraft-glass-tier=0
.\.venv\Scripts\python.exe swarm\lanes\aircraft_exterior\glass\coastal\bake_glass.py measure `
  --ref  (Get-ChildItem runs\swarm\glass_coastal\ref\frame_*.png | Select-Object -First 1).FullName `
  --cand (Get-ChildItem runs\swarm\glass_coastal\t0\frame_*.png  | Select-Object -First 1).FullName `
  --canopy-roi <x0,y0,x1,y1> --aircraft-roi <x0,y0,x1,y1>
```

The two ROIs are pixel boxes read off the reference frame (canopy pane; whole
airframe). Exit code 0 = pass. All four must hold, luma in sRGB /255:

* canopy contrast (p97 - p5) of the candidate exceeds the reference by **>= 10**;
* aircraft-ROI p50 falls by **<= 2** (no dark-aircraft regression);
* canopy pixels below 8: **<= 2 %** (no blacked-out canopy, the round-22 failure);
* canopy pixels above 250: **<= 2 %**.

Repeat with `-aircraft-glass-tier=1..3` for the stress ladder; record device-lost
events and frame time per tier there. None of that is known today.

## What is and is not known

Checked on the Mac (`tests/test_swarm_aircraft_exterior_glass_coastal.py`):
Fresnel maths, LUT/env/micro file contents, tileability, salt-film albedo inside
the stated 0.015-0.90 bound, sha256 against PROVENANCE.json, the gate arithmetic on
synthetic images. The "predicted canopy luma" in `glass_coastal.json` is arithmetic
on the bake, not a render.

Not known: how any tier looks, its frame time, its real VRAM, whether the emissive
strip double-counts sky-light specular on the laptop, whether tiers 2-3 survive.
