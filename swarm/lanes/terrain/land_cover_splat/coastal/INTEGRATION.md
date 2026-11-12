# terrain.land_cover_splat.coastal: integration notes

**Visual-only. Nothing in this lane has been rendered.** Every look value and
every memory figure is UNMEASURED until the gate below has run on the Windows
laptop. The Mac ran the Python tests only.

## What this lane adds

The Google tiles stay the ground and its colour (they are not cached, edited
or replaced). The Mac turns the repo's existing ESA WorldCover class map into
two small textures; the tile material samples them so the laptop classifies
nothing at run time.

| File | What it is |
|---|---|
| `bake_coastal_splat.py` | Mac bake: `class_map.png` to splat + shoreline distance field + sidecar |
| `measure_ground.py` | the pixel gate's measurement (run on Windows on Windows frames) |
| `run_gate.py` | the one Windows command: renders splat off, then on, and calls the measurement |
| `PROVENANCE.json` | sources, licences, sha256 of the lane's code |
| `tests/test_swarm_terrain_land_cover_splat_coastal.py` | arithmetic and refusal checks; synthetic arrays and made-up run directories |

Bake output (per scene, not committed; `land_cover_splat.json` carries the
sha256 of each file and embeds the scene's `landcover.json` with the CC BY 4.0
attribution):

- `splat_bgra_mips.bin`: full mip chain, `PF_B8G8R8A8`, **sRGB off**.
  R vegetation, G bare/sand, B built, A water; the four sum to 255 in every
  texel of every mip. Feathered once ([1 4 6 4 1]/16) so 10 m class steps do
  not show as blocks.
- `shore_sdf_mips.bin`: full mip chain, `PF_G8`. Metres to the water line =
  `(v - 128) / 127 * 320`, land positive. Wetland and mangrove count as land.
- `splat_rgba.png`, `shore_sdf.png`: the top mips, for inspection.

## Bake command (Mac)

```sh
# after core.terrain.landcover has written <key>_landcover/ for the coastal scene
.venv/bin/python swarm/lanes/terrain/land_cover_splat/coastal/bake_coastal_splat.py \
  --class-map <cache>/<key>_landcover/class_map.png \
  --landcover-json <cache>/<key>_landcover/landcover.json \
  --extent-m <X> <Y> --tier 0 --out <cache>/<key>_splat_t0
```

The window must be square (within 1 %) and the texel must be 5 m or coarser
(`extent / edge >= 5`), otherwise the bake refuses by name
(`terrain.land_cover_splat`). `--synthetic` bakes a made-up coast for dry
runs; its sidecar says `synthetic: true` and it must never reach a render.

## Tiers (memory figures are ESTIMATES, uncompressed with mips)

| Tier | Edge | Material work | Est. texture memory | Est. per-pixel cost |
|---|---|---|---|---|
| 0 | 512 | roughness and specular lerped by splat; water mask handed to the water lane | 1.7 MB | 1 extra sample (splat), a few ALU |
| 1 | 1024 | tier 0 + wet-sand band and foam line from the distance field | 6.7 MB | 2 samples, arithmetic only |
| 2 | 2048 | tier 1 + one 512 tiled detail normal per land group (from the detail-map lane), faded out by 1.5 km | 27.7 MB | 5 samples |
| 3 | 4096 | tier 2 with 1024 detail normals + shallow-water tint from the water-side distance | 110.7 MB | 5 samples, larger footprint |

Tier 0 is the one meant to be stable on the laptop; that is a design intent,
not a result. No tier is claimed sustained. With the 491 MB pool, tier 3 is a
stress-ladder step only. If the integrator imports through the editor as
BC3 + BC4, the first two textures cost about a quarter of the figures above.

Look values the material uses (authored, in the sidecar under `material`,
`wet_sand`, `foam_line`): roughness 0.85 vegetation, 0.75 sand, 0.70 built;
wet sand within 12 m of the water line: albedo x 0.6, roughness 0.35; foam
line +-4 m about the water line at 0.5 opacity. Water roughness is the water
lane's.

## Proposed changes to shared files (for the integrator; not made here)

1. **`core/scenario/card.py`**: add `land_cover_splat_tier()` reading
   `FLIGHTSIM_LAND_COVER_SPLAT` (`off`, `0`..`3`). Default `off` until the
   gate has passed on the laptop, then `0`. This switch never touches
   `google_tiles_requested`: tiles stay ON. Strip the value before comparing
   (`cmd`'s `set X=off && ...` stores `"off "`), and refuse any other value by
   name. Write the request into the run's `card.json` as top-level
   `"land_cover_splat": {"tier": "off" | 0..3}`.
2. **Scene bake (where `core.terrain.landcover` is called)**: after the
   land-cover bake, call `bake_coastal_splat.build()` / `write()` (or the CLI)
   and put the output directory in the render request as
   `land_cover_splat_dir`.
3. **`FlightSimGoogleTiles.cpp`** (the place that already sets the tile
   material's roughness/specular): when `land_cover_splat_dir` is set, read
   the sidecar, create two transient `UTexture2D` with the listed mip edges,
   `SRGB = false`, `Filter = TF_Trilinear`, address clamp, memcpy each mip
   from the `.bin`, and set on the tile material instance: `LandCoverSplat`,
   `ShoreSDF`, `SplatOriginExtent` (origin x, north-edge y, 1 / extent in UE
   units). Missing or unreadable files: refuse by name
   `terrain.land_cover_splat`, do not fall back silently. **After** both
   textures are set on the tile material, and only then, the commandlet adds
   to that camera's `frames/<camera>/render.json` the top-level echo
   `"land_cover_splat": {"applied": true, "tier": N, "sidecar_sha256": "<sha256 of land_cover_splat.json>"}`.
   The gate reads this echo and refuses without it; a render with the switch
   off writes no such key (or `"applied": false`).
4. **Tile material**, one custom node (SM5-safe, no derivatives beyond the
   sampler's own):

```hlsl
float2 uv = float2(WorldPos.x - Origin.x, Origin.y - WorldPos.y) * InvExtent; // check axis signs against the bake grid
float4 s  = Texture2DSample(LandCoverSplat, LandCoverSplatSampler, uv);       // r veg, g sand, b built, a water (PF_B8G8R8A8 upload of the BGRA bytes)
float land = max(1.0 - s.a, 1e-3);
float rough = (s.r * 0.85 + s.g * 0.75 + s.b * 0.70) / land;
float spec  = (s.r * 0.30 + s.g * 0.35 + s.b * 0.40) / land;
// tier 1+
float d   = (Texture2DSample(ShoreSDF, ShoreSDFSampler, uv).r * 255.0 - 128.0) / 127.0 * 320.0;
float wet = saturate(1.0 - d / 12.0) * step(0.0, d) * saturate(s.g * 4.0);
rough = lerp(rough, 0.35, wet);
BaseColor *= lerp(1.0, 0.6, wet);
float foam = saturate(1.0 - abs(d) / 4.0) * 0.5;
```

   The channel swizzle and the world-axis signs are written from the file
   layout, not from a running material: confirm both with the inspection PNGs
   on the first render (water must be the mask's A, north must be up).

5. **`scripts/run_test_scenarios.py` `SCENARIOS`**: the list has no coastal
   entry. Append one whose name contains the word `coastal` (the gate finds it
   by that word, not by a number). The sun_time_of_day lane proposes
   `("coastal A-4, low sun over the sea", "chase view of the a4 at 300 m over
   half moon bay at 18:15, flying south, for 6 seconds", {"sun_azimuth_deg":
   262.7, "sun_elevation_deg": 12.0})`; one shared entry is enough for all
   coastal lanes. That prompt has not been compiled, and no file under
   `core/terrain/glo30.py`, `webapp/runs.py` or `core/scenario/` names Half
   Moon Bay or Monterey (grep, this session), so a coastal place has to be
   added first. The gate's shot must be a level camera (roll within 0.5 deg)
   that sees ground between 1 and 3 km; a chase view at 300 m does on paper.

## Pixel gate (UNMEASURED; cannot run on today's tree)

One command, on the Windows laptop, with the web app **stopped** (the gate
starts its own, once per side, because the switch is read by the app):

```bat
.venv\Scripts\python.exe swarm\lanes\terrain\land_cover_splat\coastal\run_gate.py --tier 0
```

`--tier 1`, `2`, `3` are the stress-ladder steps. `--check` renders nothing
and only says whether the gate could run.

**On the tree as it is today this command exits 3**, `REFUSED
terrain.land_cover_splat.gate.not_integrated`, because changes 1 and 3 are not
merged; once they are, it refuses `no_coastal_scenario` until change 5 is. It
does not render two copies of the same scene and call that a pass. The Mac
test `test_driver_on_this_tree_refuses_until_the_integration_lands` holds it
to that. `run_gate.py` itself has never been executed on Windows.

What the command does once the changes are in:

1. Starts `python -m uvicorn webapp.server:app --port 8008` with
   `FLIGHTSIM_LAND_COVER_SPLAT=off` in that process's environment (set by the
   script, so no shell quoting is involved), renders the coastal scenario as
   one still through the runner's `run_batch` with `--compiler regex` and the
   compiled spec pinned under `runs\coastal_splat_gate\tier<N>\specs`, and
   stops the app. Then the same with the switch at the tier. The runner's own
   `runs\test_scenarios.json` and gallery are left alone; the gate's rows are
   in `runs\coastal_splat_gate\tier<N>\summary_<value>.json`.
2. A candidate render that does not end `done` (for example device lost) is
   a FAIL of the tier, exit 1. A failed baseline is a refusal, exit 3.
3. Calls `measure_ground.py --baseline-run runs\webapp\<id> --candidate-run
   runs\webapp\<id>`. Per run it takes the first camera's first
   `frames\<camera>\frame_*[0-9].png` (the same pick the runner's gallery
   makes; the beauty-post copies are not used) and that frame's record in
   `capture_manifest.json`: height = `position_alt_m` minus
   `--surface-elevation-m` (default 0), pitch below level = `-pitch_deg`,
   vertical field of view = `2 atan(height_px / (2 fy_px))`. Those field
   names are read from `core/capture/manifest.py`; no manifest of a coastal
   run has been read, because none exists.
4. Refuses, exit 2, when: the candidate's `render.json` has no
   `land_cover_splat.applied == true` echo, the baseline's has one, the two
   cameras differ, the camera rolls more than 0.5 deg, fewer than 8 image rows
   see ground between 1 and 3 km, or the two frames have identical pixels.

Exit code 0 = pass, 1 = fail, 2 = could not measure, 3 = refused before
rendering. Pass needs all of:

- `gsd_ratio` = candidate / baseline `effective_gsd_m` (ground band 1 to
  3 km) **<= 1.02**: the splat must not blur the ground. Tiers 2 and 3 are
  expected below 1.0 (detail normals); tier 0 and 1 near 1.0.
- `range_ratio` = candidate / baseline `visible_range_km` **>= 0.95**.
- candidate `visible_range_km` **<= 1.15 x 15.7 km = 18.1 km** (or 1.05 x the
  baseline if the baseline is already past that): roughness detail must not
  show through the sea haze. 15.7 km is the sun_time_of_day lane's figure,
  taken over as is, not derived or checked here.
- candidate mean linear luminance **>= 0.005** (a black frame is a failed
  render).
- no "device lost" line in any `render.log` of the candidate run. The pattern
  is UE's usual D3D11 wording, not checked against this build's log; also
  read the log by eye.

What a pass would and would not mean: tier 0 only changes roughness and
specular, so a pass says the splat was drawn (the engine's echo) and did no
measurable harm to ground sharpness or range in one frame. It is not evidence
the frame looks better; the thresholds are authored, and how much two renders
of the same scene differ on this laptop (rain, temporal AA) has not been
measured, so a ratio inside 2 % may be noise.

`measure_ground.py --baseline a.png --candidate b.png --altitude-m ..
--pitch-down-deg .. --vfov-deg ..` still works on bare PNGs for a look at the
numbers; its report says `splat_evidence: none` and it is not this gate.

## Known limits

- The gate shows the splat did no harm to ground sharpness and range and, at
  tier 2+, added resolvable detail. It does not prove the shoreline looks
  right; that needs eyes on the frame.
- WorldCover is 10 m and 2021; it reports about 75 % overall accuracy in
  North America. Beach width and the water line are only as good as that.
  Tide is not modelled: the wet band follows the mapped water line.
- Nodata is treated as sea (WorldCover has no tile over open ocean). Wrong
  for an inland nodata hole; the sidecar records `nodata_fraction`.
- Albedo per group is an authored, uncited pick, used only for the sidecar's
  `scene_mean_albedo` and `land_mean_albedo`. No source was read for it; do
  not quote those two figures as measured ground albedo.
- `measure_ground.py` assumes no refraction and refuses a rolled camera. The
  camera height is `position_alt_m` minus a sea surface assumed at 0 in the
  manifest's datum; which datum a coastal scene's heights are in was not
  checked. Both sides share the error, so the ratios hold; the absolute
  `effective_gsd_m` and `visible_range_km` shift with it.
- The `--class-map` path has run only on a made-up mode-L code map with a
  `landcover.json` of the right shape (the bake now refuses a class map whose
  sha256 is not the one `landcover.json` states). No WorldCover crop was on
  the Mac, so no real place has been baked.
