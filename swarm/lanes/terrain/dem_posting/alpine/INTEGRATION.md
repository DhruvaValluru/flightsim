# terrain.dem_posting.alpine: integration notes

**Visual-only. Nothing here has been rendered. Every visual and performance
claim is UNMEASURED until the Windows command in "Pixel gate" has run on the
laptop.** No shared file was edited; the proposed changes are below.

## What this lane found (arithmetic and data, not a render)

With the scenario camera (35 mm lens, 1280 px wide, 0.80 mrad per pixel):

- One pixel covers 4 m of ground at 5 km, 16 m at 20 km, 129 m at 160 km.
- A 30 m DEM post is under one pixel beyond 37 km, a 90 m post beyond 112 km.
  Inside 10 km a 30 m post is 4 px or more, so near-field shape has to come
  from the Google tiles mesh, as it does now. A finer near DEM is not this
  lane's lever; the tiles' screen-space error is.
- From 5000 m the sea-level horizon is 271 km away (refraction k = 0.13).
  Predicted from GLO-90 for the north view over the Matterhorn, the skyline is
  formed by terrain beyond 30 km in every azimuth and beyond 160 km in 59% of
  them. If the tiles do not draw that far, the horizon is wrong, and that is
  what the gate measures.
- GLO-90 reads sharp summits low (Dufourspitze 106 m, Dom 82 m, Mont Blanc
  13 m). At 30 km, 100 m is 4 px. The far ring is therefore a backdrop behind
  the tiles, never a replacement for them.

## Files

| File | What it is |
| --- | --- |
| `bake_alpine_dem_posting.py` | the Mac generator (numpy; rasterio to read tiles) |
| `alpine_dem_posting.json` | posting ladder, per-tier settings, ring file layout |
| `alpine_far_ring_t0..t3.bin` | far ring 30-280 km, polar grid: hmax u16, hmin u16, sRGB8 + snow alpha |
| `alpine_skyline_ref.bin` | skyline reference 2-280 km (96 x 4096 hmax), used by the gate only |
| `glo90_tiles.json` | URL and sha256 of each of the 54 GLO-90 tiles read |
| `measure_dem_posting.py` | the pixel gate, run on Windows on two frames |

Rebake: `.venv/bin/python -I swarm/lanes/terrain/dem_posting/alpine/bake_alpine_dem_posting.py --cache <dir outside the repo>`
(downloads 252 MB of tiles on first run, about 30 s to bake).

## Tiers (VRAM figures are ESTIMATES; no tier is claimed sustained)

| Tier | Tiles SSE | Tile cache cap | Far ring (radial x azimuth) | Est. VRAM |
| --- | --- | --- | --- | --- |
| 0 | 16 | 128 MB | 24 x 2048, vertex every 3.8 px | 130 MB |
| 1 | 8 (today's default) | 192 MB | 32 x 2048 | 195 MB |
| 2 | 4 | 256 MB | 48 x 4096, every 1.9 px | 265 MB |
| 3 | 2 | 384 MB | 48 x 8192, every 1.0 px | 401 MB |

The estimate is the cache cap plus the ring's vertex and index buffers. Cesium's
cap is soft (visible tiles are kept even over it), so the real figure can be
higher. Tier 0 doubles today's screen-space error: it gives up ground detail to
cut tile count, which is the only memory lever this lane has on a 491 MB budget.

## Proposed changes (for the integrator)

1. `FlightSimGoogleTiles.cpp`: read `FLIGHTSIM_GOOGLE_TILES_CACHE_MB` and set
   `Tiles->MaximumCachedBytes = MB * 1024 * 1024` next to the existing
   `SetMaximumScreenSpaceError` call. `FLIGHTSIM_GOOGLE_TILES_SSE` already
   exists; a tier is these two numbers. Note `FLIGHTSIM_GOOGLE_TILES_BEAUTY_SSE`
   (default 6) lowers the SSE again on the beauty pass, so tier 0 must set it
   to 16 as well or the tier is not what the table says.
2. New far-ring actor in the bridge plugin (one `UProceduralMeshComponent` or a
   static mesh built once at scene start), only for the matterhorn location:
   - Read `alpine_dem_posting.json` -> `rings`, and the tier's `.bin`.
   - Vertex (i, j): range = geometric mean of radial edges i and i+1
     (`geomspace(r_inner_m, r_outer_m, n_r + 1)`), azimuth `(j + 0.5) * 360 / n_az`
     clockwise from north, about `centre_lat`, `centre_lon`. Height = `hmax * 0.1` m.
   - Place through the Cesium georeference (longitude, latitude, height), which
     supplies earth curvature. Heights are EGM2008 orthometric: add the same
     undulation the tiles code already uses (`UndulationM`).
   - Unlit-under-sky is wrong here: use a plain lit opaque material with the
     vertex colour as base colour, roughness 0.9, no shadow casting, and
     **Pixel Depth Offset = 500 m + 5% of distance** so the tiles always win
     the depth test where they exist. The ring then only shows where the
     tiles left sky. Aerial perspective and fog apply as to any opaque mesh.
   - `hmin` is there for a variant that sits strictly under the true surface
     if the depth offset shows artefacts.
3. No change to `core/scene`, `core/render` or `webapp`. Google tiles stay on;
   the ring is refused (by name) if the tiles are off, since alone it is a
   90 m height-coloured mesh and not a ground.

Known limits: the ring's colours are a height rule (vegetation, rock, snow at
3100 m), uncalibrated; pooled maxima can stand 1-2 px proud of a coarse tile
ridge; the ring is centred on the summit and valid for cameras within about
10 km of it.

## Pixel gate (UNMEASURED; run on the Windows laptop)

Scenario 11 is the Matterhorn frame. Camera position, heading and pitch come
from that run's compiled spec / camera record.

```bat
rem 1. baseline: today's tree and defaults
python scripts\run_test_scenarios.py --still --only 11
copy runs\test_scenarios\11_*.png runs\alpine_dem_baseline.png

rem 2. candidate: after the integrator's change, tier 0
set FLIGHTSIM_GOOGLE_TILES_SSE=16
set FLIGHTSIM_GOOGLE_TILES_BEAUTY_SSE=16
set FLIGHTSIM_GOOGLE_TILES_CACHE_MB=128
python scripts\run_test_scenarios.py --still --only 11
copy runs\test_scenarios\11_*.png runs\alpine_dem_candidate.png

rem 3. gate (tier 0 allows 4 px ground detail; tiers 1-3 use the default 2)
python swarm\lanes\terrain\dem_posting\alpine\measure_dem_posting.py --baseline runs\alpine_dem_baseline.png --candidate runs\alpine_dem_candidate.png --camera-lat <deg> --camera-lon <deg> --camera-alt-m <m MSL> --heading-deg <deg> --pitch-deg <deg> --exclude-cols <first:last columns covered by the aircraft> --max-detail-px 4.0
```

Pass (exit 0): candidate `horizon_range_km >= max(120, baseline)` and
`skyline_match_fraction >= max(0.80, baseline)` and `detail_px <= 4.0`
(tier 0) or `<= 2.0` (tiers 1-3). `effective_gsd_m` is `detail_px` times the
pixel footprint at `--roi-range-m` (default 6000 m; set it from the run's depth
or geometry, the default is a guess).

What may need a Windows correction: the skyline detector takes the strongest
vertical luminance edge within 60 px of the prediction, which haze or bright
snow against a bright sky can defeat (pass `--baseline-sky-mask` /
`--candidate-sky-mask` if the renderer can write a sky mask); the 0.15 degree
tolerance; and `detail_px`, which temporal anti-aliasing or sharpening shifts.
If the baseline already reaches the horizon, the ring adds nothing visible and
the gate will say so by passing on equal numbers.

## Shared look parameters this lane assumes

Eye 5000 m MSL, sun elevation 30 degrees (the sibling alpine lanes' nominal),
snow albedo 0.90, snowline 3100 m, refraction k 0.13, capture 1280 x 720 at
54.4 degrees horizontal.
