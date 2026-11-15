# terrain.horizon_lod.alpine: integration notes

VISUAL-ONLY. Everything below is UNMEASURED: written and source-tested on the
Mac, never rendered. No tier has been run on the Windows laptop.

## What this lane is

The ground stays the Google Photorealistic 3D Tiles drawn by Cesium for
Unreal. This lane decides how finely Cesium refines them and what it may hold
in memory, per tier, and predicts what the frame should then show:

- `bake_alpine_horizon_lod.py` writes `alpine_horizon_lod.json` (tier ladder,
  predicted horizon, predicted geometric-error bound per distance) and
  `alpine_horizon_lod_curve.csv`. Standard library only.
- `measure_horizon_lod.py` is the pixel gate (numpy, Pillow).

No terrain data, texture or third-party code ships.

## What the model says (estimates, not measurements)

- Horizon from 5000 m over the 500 m Swiss plateau: 239.5 km, dip 2.15 deg.
  The engine draws straight rays, so that is the rendered horizon; the real,
  refracted one is about 257 km (recorded, not a target).
- Tile count goes as 1/SSE^2 but only as the log of the range: drawing to the
  239 km horizon instead of stopping at 100 km is under 35 % more tiles, while
  SSE 6 to SSE 3 is 4 times the tiles. Range is cheap; fineness is not.
- Tile memory per tier, with ASSUMED constants (16 geometric errors per tile
  side, 0.45 MB per tile; the count is uncertain by 4x either way):

| tier | SSE | est tiles | est MB (drawn + cache cap) | predicted GSD vs today |
|------|-----|-----------|----------------------------|------------------------|
| 0    | 6   | 601       | 335                        | 1.00                   |
| 1    | 5   | 866       | 486                        | 0.83                   |
| 2    | 4   | 1353      | 737                        | 0.67                   |
| 3    | 3   | 2406      | 1339                       | 0.50                   |

  Against a 491 MB budget the central estimate already puts tier 0 at two
  thirds of the pool. If tier 0 loses the device, fall back to
  `FLIGHTSIM_GOOGLE_TILES_SSE=8` (est 338 tiles, about 216 MB), an existing
  switch that needs no code change.

## Tiers (render side)

All tiers: Direct3D 11, capture at most 1280 wide, one render job, nothing
sampled per pixel by this lane (zero shader cost; the cost is tile memory and
draw calls).

- Tier 0: SSE 6 (today's selection, unchanged). Tile cache 64 MB, 4
  simultaneous loads, descendant limit 8, no sibling preload, no LOD
  cross-fade. Aim: the same frame as today with a lower memory peak.
- Tier 1: SSE 5, cache 96 MB, fog culling off.
- Tier 2: SSE 4, cache 128 MB, fog culling off, holes forbidden.
- Tier 3: SSE 3, cache 256 MB, sibling preload and LOD cross-fade (0.5 s) for
  the 6 s clip.

## Proposed changes (for the integrator; this lane edits no shared file)

1. `ue/Plugins/FlightSimBridge/.../FlightSimGoogleTiles.cpp`, after
   `Tiles->SetMaximumScreenSpaceError(...)` in the setup function: read
   `FLIGHTSIM_HORIZON_LOD` (`off`, `0`..`3`; default `off` until the gate has
   run). For a tier, load `swarm/lanes/terrain/horizon_lod/alpine/alpine_horizon_lod.json`,
   take `tiers[n].tileset` and set each key on the `ACesium3DTileset` by
   reflection by name (`FindPropertyByName`, then the matching `Set<Name>`
   UFunction when one exists so Cesium reacts to the change), the same way
   `ApplyBeautyLook` reaches `GenerateSmoothNormals`. The property names were
   typed from memory of Cesium for Unreal 2.x; a name that is not found is
   recorded, never an error.
2. Same file: `tiers[n].maximum_screen_space_error` becomes the SSE unless
   `FLIGHTSIM_GOOGLE_TILES_SSE` states one (the stated value still wins), and
   `ApplyBeautyLook` must not lower it again when a tier is active.
3. Same file, the record written into `render.json`: add a `horizon_lod`
   object with `tier`, each property `{requested, found, applied}`. For
   calibration also set `LogSelectionStats` true when
   `FLIGHTSIM_HORIZON_LOD_STATS=1`, so `render.log` carries Cesium's
   visited / culled / rendered tile counts. Divide the rendered count by
   `est_tiles_drawn` to correct `tile_span_per_geometric_error` in the bake.
4. Not proposed: any DEM backdrop behind the tiles. It would be non-Google
   ground in a terrain render.

Open points the Windows run must settle:

- Whether Cesium's fog culling drops anything at 5000 m. From memory its fog
  density at that height is too low to cull inside 240 km, so tier 1's
  "fog culling off" may change nothing. Unverified.
- Whether anything else cuts the far terrain (a sky dome mesh of finite
  radius, a tile-load timeout before far tiles arrive). The horizon half of
  the gate is there to show it.
- The commandlet already writes `frame_NNNN_depth.f32`. A range read from
  depth would not saturate the way the skyline does; its format was not read
  in this lane, so the gate does not use it yet.

## Pixel gate (UNMEASURED; run on the Windows laptop)

Scenario 11 is the Matterhorn shot (as the atmosphere lane's notes state).
Tiers 1 to 3 can be gated today on SSE alone, before any code change, because
`FLIGHTSIM_GOOGLE_TILES_SSE` already exists; tier 0 needs change 1.

```bat
rem baseline: today's frame
set FLIGHTSIM_GOOGLE_TILES_SSE=
python scripts\run_test_scenarios.py --still --only 11
copy runs\test_scenarios\11_*.png runs\alpine_hlod_baseline.png

rem candidate: tier 1 (SSE 5). After change 1 use: set FLIGHTSIM_HORIZON_LOD=1
set FLIGHTSIM_GOOGLE_TILES_SSE=5
python scripts\run_test_scenarios.py --still --only 11
copy runs\test_scenarios\11_*.png runs\alpine_hlod_candidate.png

python swarm\lanes\terrain\horizon_lod\alpine\measure_horizon_lod.py --baseline runs\alpine_hlod_baseline.png --candidate runs\alpine_hlod_candidate.png --tier 1 --pitch-deg <camera pitch of the shot> --gsd-box <x0,y0,x1,y1 of textured ground> --columns <c0,c1 clear of the aircraft>
```

Pass (exit code 0) when both hold:

- `gsd_ratio` (candidate effective ground sample distance over baseline, in
  the same ground box) is at most 1.10 for tier 0, 0.92 for tier 1, 0.80 for
  tier 2, 0.65 for tier 3;
- `horizon_range_km` is at least 100 km and at least 95 % of the baseline's
  (capped at 178.9 km, past which the skyline moves under two pixels).

and the render itself finished without a device loss. The gate cannot see a
crash; check the run's exit code and `render.log`.

Limits of the gate: the range is a lower bound from the skyline, so a ridge
above the horizon hides a cut behind it; the box metric follows texture
power, so both frames must share post-process settings; camera roll is taken
as zero.

## Shared look parameters

Other alpine components should agree with: camera 5000 m AMSL heading north,
horizontal field of view 54.4 deg, capture 1280 x 720, far ground reference
500 m AMSL, unrefracted horizon 239.5 km at 2.15 deg dip, visible terrain to
the horizon (haze, not a cut, must be what hides the far ground), Earth radius
6371.0088 km here against 6360 km in the atmosphere lane.

## Mac checks

`.venv/bin/python -m pytest tests/test_swarm_terrain_horizon_lod_alpine.py`
(geometry, file hashes, gate arithmetic on synthetic images; not a render).
