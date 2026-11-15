# terrain.detail_normals.alpine: integration notes

VISUAL ONLY. Nothing here has been rendered. Every visual, VRAM, frame-time
and device-loss statement below is UNMEASURED until the Windows command in
"Pixel gate" has run on the laptop. VRAM figures are estimates. That command
refuses today: the switch it compares does not exist in the engine until
changes 1 to 3 below are applied.

## What this lane adds

The Google tiles stay the ground. Their mesh and photograph carry no relief
finer than themselves, so near slopes shade as smooth blobs. Two tileable
detail normal maps, baked on the Mac, perturb the tiles' shading normal:

| map | file (tier 0) | ground repeat | wavelengths | strength 1 -> 0 between |
|---|---|---|---|---|
| rock strata | `out/alpine_detail_rock_t0.dds` 512, BC5, 10 mips | 48 m | 0.75 to 6 m | 934 m and 3736 m |
| wind-packed snow | `out/alpine_detail_snow_t0.dds` 256, BC5, 9 mips | 96 m | 1.5 to 12 m | 1868 m and 7472 m |
| rock, far (tier 1+) | same rock map, second tap | 311 m | 4.9 to 19.4 m | 3026 m and 12103 m |

The fade distances come from the capture (1280 px wide, hfov 54.4 deg, 0.80 m
per pixel at 1 km): a layer's strength reaches exactly 0 where its longest
wavelength spans two pixels. Past that distance the frame is untouched, which
is what protects the horizon. All numbers are in `out/alpine_detail_t0.json`;
read them from there, do not retype them.

Regenerate: `.venv/bin/python swarm/lanes/terrain/detail_normals/alpine/bake_alpine_detail_normals.py [--tier N] [--png]`.
Only tier 0 is committed (0.44 MB). Tiers 1 to 3 bake on demand in under a
second each and carry the same surface at higher resolution.

## Tiers (estimates; none is claimed sustained)

| tier | textures | est. VRAM | taps per tile pixel | projection |
|---|---|---|---|---|
| 0 | rock 512 + snow 256 | 0.42 MB | 2 | dominant axis |
| 1 | rock 1024 + snow 512 | 1.67 MB | 3 (adds far rock layer) | dominant axis |
| 2 | rock 2048 + snow 1024 | 6.67 MB | 6 | biplanar, height/slope snow mask |
| 3 | rock 2048 + snow 2048 | 10.67 MB | 9 | triplanar, roughness from mip normal length |

Tier 0 adds two samples and about 25 scalar instructions to a material that
already runs on every tile pixel, no render target, no extra pass, no extra
draw call. That is the reason to expect it to be stable; it is not evidence.

## Proposed changes (for the integrator; this lane edited no shared file)

### 1. Import the textures (Windows, editor or commandlet)

Import the two DDS files to `/Game/FlightSim/Terrain/T_AlpineDetailRock` and
`T_AlpineDetailSnow`: compression `TC_Normalmap` (BC5), sRGB off, address
mode wrap, mip gen "leave existing mips", texture group World Normal Map,
`NeverStream` on (0.44 MB; keeps them out of the 491 MB streaming pool's
churn). UNMEASURED whether the pinned UE build keeps a DX10-header BC5 DDS as
is. If it refuses or recompresses, bake with `--png` and import the PNGs with
the same settings: UE then builds the mips itself, which loses the baked
renormalised chain but nothing else.

### 2. Tiles beauty material (the one `FFlightSimGoogleTiles` sets with `SetMaterial`)

Google's tiles carry no tangents, so the perturbation is done in world space
and fed to the material's Normal input with "Tangent Space Normal" OFF. If
the beauty material is unlit, skip to "Unlit variant" below.

Add a Custom node (output float3) wired to Normal. Inputs: `P` = Absolute
World Position (cm), `N` = Vertex Normal WS, `Base` = the tile's base colour,
`CamDist` = distance from camera in metres, textures `RockTex`, `SnowTex`
with a shared wrap sampler, scalar parameter `Strength` (default 1), vector
parameter `Wind` = (cos, sin) of the wind bearing in the local east/north
frame.

```hlsl
// tier 0: 2 taps. Constants are out/alpine_detail_t0.json; keep them in sync.
float3 a = abs(N);
// one projection per pixel: top-down on slopes, side-on on walls
float2 uvm; float3 T; float3 B;                 // metres, and the world axes of u and v
if (a.z >= 0.6)      { uvm = P.xy * 0.01; T = float3(1,0,0); B = float3(0,1,0); }
else if (a.x >= a.y) { uvm = P.yz * 0.01; T = float3(0,1,0); B = float3(0,0,1); }
else                 { uvm = P.xz * 0.01; T = float3(1,0,0); B = float3(0,0,1); }

float lum = dot(Base, float3(0.2126, 0.7152, 0.0722));
float sat = (max(Base.r, max(Base.g, Base.b)) - min(Base.r, min(Base.g, Base.b))) / max(lum, 1e-3);
float snow = smoothstep(0.55, 0.75, lum) * (1.0 - smoothstep(0.12, 0.25, sat));

float2 uvs = float2(dot(uvm, Wind), dot(uvm, float2(-Wind.y, Wind.x)));   // sastrugi along the wind
float2 dr = RockTex.Sample(RockTexSampler, uvm / 48.0).rg * 2.0 - 1.0;
float2 ds = SnowTex.Sample(SnowTexSampler, uvs / 96.0).rg * 2.0 - 1.0;
ds = float2(ds.x * Wind.x - ds.y * Wind.y, ds.x * Wind.y + ds.y * Wind.x); // back to the uvm frame

float fr = 1.0 - smoothstep(934.0, 3735.9, CamDist);
float fs = 1.0 - smoothstep(1868.0, 7471.8, CamDist);
float2 d = Strength * lerp(dr * fr, ds * fs, snow);
return normalize(N + d.x * T + d.y * B);
```

Use `Texture2DSample` / the material's own sampler names if the Custom node
in the pinned build wants them; the arithmetic is what matters. The `if`
chain makes a visible line where the projection switches (about 53 deg of
slope). It is a line in fine relief only, never in colour. Tier 2 removes it
by blending two projections (biplanar), tier 3 by three.

Tier 1 adds, before the `lerp`:
`dr = dr * fr + (RockTex.Sample(RockTexSampler, uvm / 311.0).rg * 2 - 1) * (1 - smoothstep(3025.7, 12102.8, CamDist));`
and uses `dr` in place of `dr * fr`.

Tier 2 replaces the photograph-only snow mask with
`snow = max(snow, smoothstep(SnowlineM - 150, SnowlineM + 150, HeightM) * smoothstep(0.55, 0.80, N.z))`
(`SnowlineM` 3000: a round figure typed from memory for the Zermatt area, not
read from a dataset; the atmosphere and lighting lanes must agree on it).

Tier 3 raises roughness where mips flatten the normal (Toksvig):
`Roughness = sqrt(Roughness^2 + (1 - len) / len)`, `len` from
`mip_normal_length` in the JSON for the sampled mip.

Unlit variant (if the tiles material writes the photograph to Emissive):
multiply the photograph by `1 + 0.6 * (dot(Nd, L) - dot(N, L))`, clamped to
[0.6, 1.4], `Nd` the node's output and `L` the sun direction parameter the
scene already sets. This is relief shading, not lighting; say so in the
material comment.

### 3. Switch (`FlightSimGoogleTiles.cpp`, where the beauty material is set)

Read `FLIGHTSIM_ALPINE_DETAIL_NORMALS`: `off` sets the material's `Strength`
to 0 (the baseline for the gate); `0`..`3` picks the tier (static switch or
one material instance per tier); unset = `off` until the gate has passed on
the laptop, then `0`. Log one line with the tier and the two texture paths,
and refuse by name (`terrain.detail_normals: texture missing`) if a tier is
asked for and a texture did not load. Google tiles stay ON either way; this
changes only their normal.

`Wind` comes from the scenario card's wind bearing. Until it is wired, (1, 0).

### 4. Things that will fight this, in order of likelihood

- The tile photograph already contains the sun's shading and shadows of the
  day it was taken. Detail relief lit from the scenario's sun is added on
  top; on slopes the photograph shows in shadow the result is lit relief
  inside a painted shadow. The de-lighting item owns that, not this lane.
- Shadowed snow in the photograph is dark and blue, so the tier 0 mask calls
  it rock and gives it rock relief. Tier 2's height/slope mask is the fix.
- Flat sunlit ground darkens by 2.7 % under the rock map and 0.5 % under the
  snow map at full strength (`diffuse_energy_shift` in the JSON). The
  exposure lane's snow figures were derived for a flat normal.
- With temporal AA off, 0.75 m relief at 934 m is near one pixel. The mips
  handle it only if the sampler is trilinear; do not set mip bias below 0.

## Pixel gate (UNMEASURED; run on the Windows laptop)

One command, no argument to fill in, from the repository root with the app
stopped:

```bat
.venv\Scripts\python.exe swarm\lanes\terrain\detail_normals\alpine\run_gate.py
```

State today: it prints `terrain.detail_normals: NOT WIRED` and exits 3
without rendering, because no engine file reads
`FLIGHTSIM_ALPINE_DETAIL_NORMALS`. It becomes a measurement only after
changes 1 to 3. It has never run on the laptop.

What `run_gate.py` does once the switch exists:

1. Starts the web app itself, three times, with the switch in the app's
   environment: `off`, `off`, then the tier (`--tier`, default 0). The value
   is set through the process API, not a shell `set`, so it carries no
   trailing space. The app must not already be running: UnrealEditor-Cmd is
   started by the app, so a switch set only for the scenario driver would
   never reach it. That the app hands its environment to the engine process
   is assumed from how `FLIGHTSIM_GOOGLE_TILES` is read; not verified here.
2. Each time runs `scripts\run_test_scenarios.py --still --only 11 --spec-dir
   runs\alpine_detail_gate\specs` (scenario 11 is the Matterhorn frame; the
   spec is compiled once and replayed, so all three renders are one scene).
3. Takes each run's own frame from `runs\webapp\<run_id>\frames\<camera>\`
   (the first `frame_NNNN.png`, the file the gallery calls `frame.png`), by
   the run id in `runs\test_scenarios.json`, and the first run's
   `frame_NNNN_depth.f32`. No glob over the gallery. A run that did not
   finish (device lost included) stops the gate with the run's own reason.
4. Runs `measure_detail_gsd.py` on the three frames and the depth image and
   writes `runs\alpine_detail_gate\gate.json` and `near_crops.png`.

Nobody chooses a box. The regions come from the baseline's depth image
(converted to slant range), never from the candidate:

| region | rule |
|---|---|
| ground | finite depth, 200 m or farther (nearer is the airframe) |
| near box | the 96 px box wholly on ground with the smallest median range; must be within 1868 m (the largest `fade_start_m` in the bake JSON) |
| far mask | ground at or beyond 7472 m (the largest `fade_end_m`; the tier's own JSON for `--tier 1` and up, which must be baked first) |
| skyline | per column, the first ground row under sky |

Exit codes: 0 `provisional_pass`, 1 `fail`, 2 `not_applicable`, 3 refused
before rendering.

| name | meaning | pass |
|---|---|---|
| `gsd_ratio` | candidate / baseline effective ground sample distance in the near box. Effective GSD = pixel footprint / (2 x f95), f95 the frequency holding 95 % of the box's luminance gradient power | <= 0.85 |
| `diff_coherence` | lag-1 autocorrelation of candidate minus baseline in the near box. Per-pixel noise scores about 0, relief spanning pixels scores higher | >= 0.10 |
| `clip_increase` | rise in the near box's fraction of pixels at 250 or above | <= 0.005 |
| `far_contrast` | candidate / baseline RMS contrast over the far mask | 0.95 to 1.05 |
| `far_mean_abs` | mean absolute difference over the far mask, 8-bit levels | <= 2.0 |
| `skyline_shift` | median row shift of the skyline edge, pixels | <= 1.0 |

Before any check:

- `not_applicable` if the two detail-off frames differ (mean absolute
  difference over ground above 1.0 level, or their near-box GSD apart by more
  than 5 %). Rain, cloud motion or camera shake that survives `--still` would
  otherwise be read as detail. The web app's default weather stays on; this
  lane does not turn it off to make the gate easier.
- `not_applicable` if the nearest ground box is beyond 1868 m.
- `fail` with `no_effect` if the candidate is no farther from the baseline
  than the repeat is: switch not wired, textures not loaded, or Strength 0.
- far and skyline checks are skipped and listed under `not_checked` if the
  frame holds fewer than 1024 far pixels or 16 skyline columns.

### What a pass does and does not mean

- A pass is PROVISIONAL and the output says so (`thresholds_provisional`).
  0.85, 0.10 and the rest were chosen before any frame existed. After the
  first real run they should be reset from `null_gsd_ratio`, `null_mean_abs`
  and the measured ratio, and the gate rerun.
- `gsd_ratio` is a proxy for resolved fine detail, not for realism. f95 rises
  with any fine pattern. `diff_coherence` rejects per-pixel sparkle (tested
  on synthetic noise) but not a coherent pattern that is simply wrong, such
  as visible tiling or the projection seam. Someone must look at
  `near_crops.png` (baseline left, candidate right). No claim of
  photorealism rests on this gate.
- Scenario 11 may come back `not_applicable`. The prompt flies at 5000 m and
  the summit is about 4478 m (figure from memory, not read from a dataset).
  If 5000 m is above sea level, the only ground inside 1868 m is the summit
  area, and whether a 96 px patch of it is in the chase frame is unknown
  until the depth image exists. If it is not, tier 0 does little in this
  scenario and the fade distances, not the gate, are what to revisit.
- Tonemapped PNGs only. Device loss, frame time and VRAM per tier are not
  covered: read them from the same runs (the run log's device-lost count and
  `stat unit`), tier 0 first. Each render is its own app and engine process.
