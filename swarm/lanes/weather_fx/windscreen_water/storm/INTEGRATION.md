# weather_fx.windscreen_water.storm: integration

Status: UNMEASURED. Baked and source-tested on the Mac; no frame has been
rendered. Visual-only: nothing here feeds a measured quantity. This lane edited
no shared file. Nothing was downloaded or vendored.

## What it is

`M_WindshieldRain` today draws its drops in a per-pixel loop of four hashed
cells (`assets/shaders/weather/windshield.hlsl`), and a drop only shifts where
the scene is sampled. In a storm the scene behind the glass is near-uniform
grey, so a shifted sample is the same grey and the drop barely shows.

The baked path moves the optics to the Mac. `generate.py` writes two tileable
RGBA textures per tier. A drop is a spherical cap (Marshall-Palmer size, 70
degree contact angle); each texel stores where a ray leaving the cap's curved
face points (Snell) and how much light gets through (Fresnel). Past 48.6
degrees of incidence the face reflects totally, which gives every drop the dark
rim that makes it visible against fog. The shift reaches 0.76 screen heights at
the rim, so a drop shows the whole scene small and upside down: bright sky at
its bottom edge, dark ground at its top. Run-off is a second texture of fixed
tracks up the glass; heads run along them, the tracks do not scroll.

`windshield_baked.hlsl` is the Custom node body: 10 lines, no loop, no hash, no
branch. `generate.py shade_texels` is its Python twin.

## Tiers (VRAM figures are estimates: both textures with mips)

| Tier | Est. VRAM | Textures | Taps per pixel | What |
|---|---|---|---|---|
| 0 | 0.7 MB | 256, RGBA8 uncompressed, never streamed | 2 texture + 2 scene | drops and tracks, one refracted scene tap. The ambientCG film maps are not loaded (`Film = 0`) |
| 1 | 2.8 MB | 512, RGBA8 uncompressed | 3 texture + 2 scene | adds a second drop layer at `Tiles x 1.77`, offset by (0.37, 0.61), max of the two masks |
| 2 | 2.8 MB | 1024, BC7 | 3 texture + 6 scene | adds a 4-tap blur of the scene between drops (the wet film), radius 0.004 screen heights, weighted by the existing film height map if loaded |
| 3 | 11.2 MB | 2048, BC7 | 3 texture + 12 scene | the drop's scene tap split into three (shift x 0.98, 1.0, 1.02 for R, G, B) and an 8-tap film blur |

The two scene taps of tier 0 are the unshifted one the material already has and
the shifted one. Tier 0's cost should be below today's material (which runs the
loop plus the film's two taps), but that is an expectation, not a measurement.
Tiers 2 and 3 are described here, not written: their extra taps go in the
material graph after tier 0 is measured. No tier adds a render target, a
capture or a pass. Whether any tier is sustained is for the stress ladder.

Import settings, all tiers: sRGB off, mip filter default, address wrap,
`TextureGroup` UI or World with `NeverStream` at tiers 0 and 1 (0.7 to 2.8 MB
is cheaper than a streaming pop on a 491 MB pool). Do not use DXT5 or BC5: the
alpha is a threshold, not a colour, and block noise in it makes drops flicker
as `Density` moves. Tier 0 texel = 0.53 mm of glass; a typical drop (2 mm) is
4 texels, so tier 0 reads as dots with a dark rim and only the larger drops
show an inverted view.

## Proposed changes (for the integrator)

1. `scripts/ue_create_materials.py create_windshield_rain` (generation 4):
   - import `baked/T_WSDrops_<n>.png`, `baked/T_WSRivulets_<n>.png` as
     `T_WSDrops`, `T_WSRivulets` (n by tier: 256, 512, 1024, 2048);
   - two TextureSample nodes at `float2(UV.x * Aspect, UV.y) * Tiles`
     (`Tiles` scalar, default 3.0), sampler type Linear Color;
   - Custom node from `windshield_baked.hlsl`, output float4, inputs `Drop`,
     `Riv`, `RivV = UV.y * Tiles`, `Aspect`, `Time`, `Wet` (vector), `Lens`
     (scalar, default 0.763326);
   - emissive = `lerp(Scene(UV), Scene(saturate(UV + out.rg)) * out.a, out.b)`.
     The `* out.a` (shade) and the `saturate` are new; the rest is today's
     wiring. Keep the post-process after the tonemapper;
   - add `Wet`, `Lens`, `Tiles` to `WINDSHIELD_PARAMETERS`; keep `Glass`,
     `Seed`, `Film`, `FilmV` so generation 3 stays buildable when the baked
     PNGs are absent (same fallback rule as the film maps);
   - copy `windshield_baked.hlsl` to `assets/shaders/weather/`.
2. `FlightSimWeather.cpp`, where it sets `Glass` on a cockpit camera: also set
   - `Lens = 0.881413 / (2 tan(vfov / 2))` from the camera's real field of view;
   - `Wet = (drop density, rivulet density, head rate, trail)` by the law in
     `generate.py host_wet`, fed with the card's `weather.rain.windshield`
     (`impinge_per_m2_s`, `runoff_mps`) and the static lifetime it already has.
     `baked/windscreen_water_storm.json` holds the `density_to_cover` table
     and two worked examples.
3. A switch, so the gate can render both: `-windshield=baked|procedural`
   (`FLIGHTSIM_WINDSHIELD` for the web app), default `procedural` until the
   gate passes on the laptop, recorded in `look_applied.weather_look`.
4. Lightning needs no change here: the material runs after the tonemapper, so
   a flash frame's bright sky is what the drops refract.

Not changed: Google tiles stay on, the web app's weather defaults stay on, the
exposure is untouched (the shade only darkens rims; the gate checks p90).

## Things the integrator should know

- The project's run-off law gives 10.3 m/s up the glass at 100 kt. At 30 fps a
  head crosses the whole glass several times per frame, so heads land at
  unrelated places frame to frame. `host_wet` passes the law through unchanged
  (`head_rate_tiles_per_s`), and sets the trail from the shutter with a floor
  of a quarter tile. If the clip strobes, the law's constants are the place to
  look (they are stated, not measured, in `rain_field.py`); this lane did not
  change them.
- Stated, not measured: contact angle 70 degrees, rim floor 0.15, eye to glass
  0.35 m, 3 tiles per screen height, standing cover capped at 0.30, 14 tracks
  per tile, and the split between standing drops and tracks (`V_SHED / V`).
- Not modelled: drops merging, wipers, ice, the glass's tilt in the optics
  (rays are taken along the glass normal), splash on impact.
- The alpha threshold is box-filtered in the mips, so a drop's edge grows a
  little as `Density` rises. That is intended (drops appear small and fill out).

## Measuring it on the Windows laptop (the pixel gate)

Reference first (current material), then the candidate (change 3's switch),
same prompt, same seed, 1280x720, one render job at a time:

```
.venv\Scripts\python.exe scripts\debug_storm_render.py --prompt "fly the c172 through a thunderstorm at 900 m with 25 mm/h rain, cockpit camera" --seconds 2 --width 1280 --height 720 --out runs\wsw_reference
set FLIGHTSIM_WINDSHIELD=baked
.venv\Scripts\python.exe scripts\debug_storm_render.py --prompt "fly the c172 through a thunderstorm at 900 m with 25 mm/h rain, cockpit camera" --seconds 2 --width 1280 --height 720 --out runs\wsw_baked
.venv\Scripts\python.exe swarm\lanes\weather_fx\windscreen_water\storm\measure_glass.py --candidate runs\wsw_baked --reference runs\wsw_reference
```

Metric: `glass_bandpass_rms`, the RMS of luma (0..255) between a 1 px and an
8 px Gaussian blur, averaged over the clip's frames.

Pass, all four: candidate at least 1.25 x the reference; candidate at most
14.0; p90 luma within 8 of the reference; no device-loss line in either run's
logs. The script exits 0 on a pass.

Caveats. The thresholds are stated, not measured. The metric shows the water
is visible where it was not; it cannot show it is photoreal, so look at the
frames too. `FLIGHTSIM_WINDSHIELD` does not exist until change 3 is made. The
debug script's default quality may not be the beauty path; if the reference
shows no windscreen at all, add the flag that selects it to both runs. Frame
time for both runs should be read from the render log; no cost is claimed here.

## Regenerate

```
.venv/bin/python swarm/lanes/weather_fx/windscreen_water/storm/generate.py
```

Deterministic (its own splitmix64 stream); the test pins the bytes to
PROVENANCE.json. About 7 s on the Mac.
