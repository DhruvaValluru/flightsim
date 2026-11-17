# Live look-dev log: sky, clouds, atmosphere (p3-monolith / ue-47)

Role: live look-dev in the editor (owner, relayed by p3-mac on 2026-11-14).
Edited assets are never saved. The winning parameter sets go to p3-mac and
flightsim-83 as lists of: asset, parameter, old -> new value, why.

## Reference runs (latest render of each scene)

| Scene | Run | Sun | Notes |
|---|---|---|---|
| 13: 747 at 10 000 m over the ocean, noon | webapp/c03d090b9ee7 | az 109.7, el 89.9, lat/lon 0/0, equinox | ref_runs/scene13_747_ocean |
| 3: A320 at 600 m over New York, morning, 18 mm lens | webapp/43337c12e088 | az 121.4, el 31.2, 40.71 N 74.01 W | ref_runs/scene03_a320_nyc |

The repo has no .umap; the commandlet spawns the world at runtime. The
look-dev level is a transient, unsaved level built from these sky.json values.

## Iterations

(format: id | time | scene | asset.parameter old -> new | screenshot | verdict)

## Real reference photos (refs/real_photos/)

| File | Source | Licence | Use |
|---|---|---|---|
| s13_cumulus_from_10-11km.jpg | commons.wikimedia.org/wiki/File:Cumulus_clouds_as_seen_from_an_airplane.JPG (Jakec, 2014, shot at 10-11 km) | CC BY-SA 3.0 | scene 13: sky gradient, horizon haze, cumulus from above |

## Gap list, scene 13 baseline (ref_runs/scene13_747_ocean/render_beauty_post.png) vs the 10-11 km photo

1. Sky: flat saturated navy everywhere, dark band at the horizon. Real: navy at the zenith -> cyan-blue -> near-white haze band at the horizon.
2. Horizon: hard dark line. Real: distant cloud and haze merge into a bright white band (aerial perspective over 300+ km).
3. Clouds: flat white discs (cumulus 1.5-2.7 km, cover 0.35, sun at 89.9 deg, sun_cast_cloud_shadows False). Real: lumpy cauliflower cumulus with self-shadowing, bright tops and grey undersides.
4. Sea in the gaps: saturated blue to the horizon with streaks. Real: dark, desaturated and hazed with distance.
5. Possible sun conflict: render.json look_applied.sun = elevation 12 deg, intensity 8 (unitless), but sky.json = 89.88 deg / 120000 lux. To check in code: is a stale sun block applied after the sky plan?

## Baseline applied values (scene 13), from render.json look_applied
SkyAtmosphere: MieScatteringScale 0.04549/km, MieAbsorptionScale 0.005055/km, MieExponentialDistribution 1.2 km, MieAnisotropy 0.8, MultiScatteringFactor 1.0, AerialPerspectiveViewDistanceScale 1.0, GroundAlbedo sRGB 40,52,60, TransmittanceMinLightElevationAngle 90.
HeightFog: density 0.0012, falloff 0.0002, max opacity 0.92, start 1500 m, inscattering black, sky-atmosphere ambient x1, volumetric fog 8000 m, scattering distribution 0.75, directional inscattering exponent 2.
SkyLight: intensity 1.6, min occlusion 0.2, cloud AO 0.5 (captured once in the render; real-time capture in look-dev).
Cloud layer 0 (M_FlightSimCloudLayers): Coverage 0.35, CoverageContrast 2.25, ShapeScaleKm 2.5, DetailScaleKm 0.15, DetailErosion 0.5, BottomSoftness 0.08, TopRounding 0.75, ExtinctionPerM 0.05, HeightDensity 0.6, SideBulge 0.35, base 1500 m, top 2700 m (component built to 14000 m).
Exposure: manual, ISO 100, 1/60 s, f/4, bias -5.4511; filmic slope 0.88, toe 0.55, shoulder 0.26, white clip 0.04, blue correction 1.0; bloom 0.5.

## Iterations, scene 13 (look-dev /Temp level built by scripts/build_lookdev.py; shots/ at 1280x720)

Look-dev vs render: the editor has no hero lighting or beauty fallback pass, so it reads about 1 to 1.5 stops darker than the render. The cloud shape and atmosphere response match. Every result below is RELATIVE (editor viewport) and UNMEASURED until a Windows render confirms it.

| id | change (old -> new) | shot | verdict |
|---|---|---|---|
| ld000 | first build (cloud layer wrongly 1.5-14 km) | s13_ld000_baseline.png | builder bug, fixed |
| ld001 | baseline as rendered (layer 1.5-2.7 km) | s13_ld001_baseline_fixedlayer.png | matches render: flat discs, dark horizon |
| ld002 | HeightFog.FogDensity 0.0012 -> 0.0 | s13_ld002_fog0.png | KEEP: the dark horizon band is the height fog (black inscatter, nearly opaque over ~350 km); the sky gradient appears |
| ld003 | SkyAtmosphere.AerialPerspectiveViewDistanceScale 1.0 -> 2.0; MieScatteringScale 0.0455 -> 0.09 | s13_ld003_fog0_ap2_mie2x.png | KEEP: sea and distant cloud haze toward the horizon like the photo |
| ld004 | SkyAtmosphere.MieAnisotropy 0.8 -> 0.6; MultiScatteringFactor 1.0 -> 1.5 | s13_ld004_aniso06_ms15.png | KEEP: whiter, brighter horizon haze at 90 deg from an overhead sun |
| ld005 | Cloud ShapeScaleKm 2.5 -> 1.2, CoverageContrast 2.25 -> 1.2, DetailErosion 0.5 -> 0.75, DetailScaleKm 0.15 -> 0.25, Coverage 0.35 -> 0.45; Sun.bCastCloudShadows false -> true | s13_ld005_cloudsA.png | KEEP: puffy cumulus cells, distant deck merges |
| ld006 | Cloud ExtinctionPerM 0.05 -> 0.08, DetailScaleKm 0.25 -> 0.12, DetailErosion 0.75 -> 0.85, TopRounding 0.75 -> 0.5, layer 1.2 -> 1.8 km (component LayerHeight + LayerThicknessKm) | s13_ld006_cloudsB.png | KEEP: vertical cauliflower cumulus, shaded sides |
| ld007 | Post AutoExposureBias -5.4511 -> -4.4511 | s13_ld007_ev_plus1.png | relative only: the editor is darker than the render; check on Windows before changing the exposure code |

## Iterations, scene 3 (A320 at 600 m over New York, morning; ground = M_Ground_City stand-in, no Google tiles in the editor)

Reference: refs/real_photos/s03_manhattan_1500ft.jpg (commons File:Downtown_Manhattan_from_1,500_ft_over_East_River.jpg, CC BY-SA 3.0, 2014-09-15): light blue sky, pale whitish horizon haze, distant city grey-blue, ~40+ km visibility.
Render baseline (ref_runs/scene03_a320_nyc/render_beauty_post.png): dark navy ominous sky, murky grey horizon band, smeared lenticular-like clouds with dark undersides, crunchy local-exposure grade.

| id | change (old -> new) | shot | verdict |
|---|---|---|---|
| ld001 | baseline as rendered (cumulus 2-5 km, cover 0.35, fog 0.0012) | s03_ld001_baseline.png | reproduces the gloom and the smeared clouds |
| ld002 | batch-1 atmosphere (AP 1->2, Mie 0.0455->0.09, g 0.8->0.6, MS 1->1.5), fog kept | s03_ld002_batch1atm_fogkept.png | REJECT at low altitude: grey smog, ~15 km visibility |
| ld003 | AP 2->1, Mie 0.09->0.0455 (g 0.6, MS 1.5 kept); Fog 0.0012 -> 0.0003 | s03_ld003_mie1x_ap1_fog03.png | KEEP: clean haze, whitish horizon band |
| ld004 | batch-1 cumulus (shape 1.2, contrast 1.2, erosion 0.85, detail 0.12, top rounding 0.5, ext 0.08); layer 3.0 -> 1.8 km; cloud shadows on | s03_ld004_cumulus_batch1.png | KEEP: separate fair cumulus with flat bases |
| ld005 | HeightDensity 0.6 -> 0 | s03_ld005_heightdensity0.png | REJECT: boxy columns (the owner's "boxy") |
| ld006 | HeightDensity back to 0.6; ViewSampleCountScale 2 -> 4 | s03_ld006_hd06_viewsamples4.png | no change: the streaks are not view sampling; reverted to 2 |
| ld007 | ShadowViewSampleCountScale 1 -> 3 | s03_ld007_shadowsamples3.png | no change: not shadow sampling; reverted to 1 |
| ld008 | SideBulge 0.35 -> 0 | s03_ld008_sidebulge0.png | no change: not the bulge; reverted to 0.35 |

Open: dark horizontal streaks inside cells at mid-height (s03_ld004..008). Not sampling, not SideBulge. HeightDensity 0 removes them but makes boxes. Suspect the base/body transition in assets/shaders/world/cloud_layers.hlsl (body = lerp(1-HeightDensity, 1, smoothstep(0, HEIGHT_DENSITY_RISE, h)) and the wisp/billow flip at WISP_HEIGHT). For flightsim-83.

## Session note 2026-11-15 09:45
Editor closed: Claude Code stopped the render guard (system critically low on memory). Nothing was dirty in /Game (list_dirty_packages = 0). The background-throttle change was runtime-only and ended with the process. To resume: open the editor, then run scripts/build_lookdev.py scene13|scene03 and scripts/tweak.py.

## Weather scenes: gap lists from the existing renders (no editor; prep for the next slot)

Reference photos added (refs/real_photos/), all from commons.wikimedia.org:
| File | Source | Licence |
|---|---|---|
| s07_heavy_rain.jpg | File:Heavy_Rain.jpg (Pridatko Oleksandr) | Public domain |
| s09_cb_rain_shaft.jpg | File:Cumulonimbus_cloud_with_visible_precipitation_shaft.jpg (OkEj1000) | CC0 |
| s10_tornado_dimmitt_noaa.jpg | File:Dimmitt_Tornado1_-_NOAA.jpg | Public domain (NOAA) |
| s10_tornado_anadarko_noaa.jpg | File:Occluded_mesocyclone_tornado1_-_NOAA.jpg (NSSL) | Public domain (NOAA) |
| s03_manhattan_aerial_2008.jpg | File:Downtown_Manhattan_Aerial_2008.jpg | CC BY-SA 4.0 |

Renders: ref_runs/<scene>/render_beauty_post.png (scene 7 = run 655df7e91299, 9 = a848570cc7d5, 10 = 1cdac04f68f8, 11 = 081e659dc08d).

Scene 7, tower view at 250 mm, heavy rain:
- Render: the whole frame is a flat mid-grey with full-height vertical streak columns (like scratched film); no depth, no veil gradient.
- Real (s07): streaks show only against DARK backgrounds and vanish against a bright sky; distant rain is a white veil that lifts the blacks and cuts contrast with distance; at 250 mm the near drops are out of focus, so a 1 km tele view of rain is mostly veil, not streaks.
- Editor tests: rain streak opacity tied to background luminance (additive, sky-lit, not darkening); streak layers fade with depth into the veil; streak density at the tele lens.

Scene 9, 747 through a thunderstorm:
- Render: the cloud base is a flat dark blob with a soft airbrushed edge (the "rubbery" look); uniform screen-length rain lines over everything; the ground is black with white crackle lines.
- Real (s09 + common CB views): sharply defined dark base; rain shafts are translucent grey curtains BRIGHTER than the base, graded and ragged at the bottom; streaks only in the near field.
- Editor tests: storm cell (M_StormCell) edge sharpness / detail erosion; rain shaft (M_RainShaft) brightness vs the base; near-field-only streaks.

Scene 10, C172 near a tornado:
- Render: a smooth tapered dark cone with fine noise and a grey sheath that ends at the frame top with no cloud base; dust = a few small brown blobs; the sky is a flat grey; the ground is black with white speckle and scratch lines.
- Real (Dimmitt, Anadarko): ragged multi-scale funnel that WIDENS into the wall cloud / mesocyclone base (no visible top end); a wide, dark, turbulent debris cloud as broad as the funnel base or wider; bright backlit sky behind gives silhouette contrast; greenish-grey colour.
- Editor tests: once the VDB flipbook is baked (M_TornadoFlipbook), compare against the mesh funnel; wall-cloud lowering; debris size x3-5 and darker.

Wet ground (scenes 9, 10):
- Render: black, with white scratch/crackle lines.
- Real (s07): wet surfaces darken but stay mid-tone, gain sheen, and at grazing angles reflect the sky (brighter, not darker); puddles are local.
- WET_DARKENING = 0.30 (world_beauty) is reasonable, so the black comes from elsewhere: suspect the tile wet specular reflecting a dark storm sky and the scratch lines from the wet normal/roughness. Needs the editor.

Scene 11, A-4 over the Matterhorn at 5000 m:
- Render: excellent terrain; the clouds above are smeared horizontal streaks with YELLOW-fringed edges (artefact); dark blue horizon band again.
- The horizon is covered by the batch 1/2 altitude rule (5 km: fog ~0, Mie ~0.08, AP ~1.8). The yellow fringes look like the distant sheet (M_FlightSimDistantClouds) handover or the tonemapper's hue shift on bright edges; needs the editor.

## Sun-block check (2026-11-15, code read, no Unreal)
render.json look_applied.sun (12 deg / intensity 8 unitless) is a STALE record, not what lit the frame.
- FlightSimVisualScene.cpp:627-655 writes SunRecord from the legacy Options (12 deg, unitless 8).
- Then FlightSimVisualScene.cpp:758 calls PhysicalSky.Build -> FlightSimSky.cpp:235-239 re-aims the
  same ADirectionalLight to the sky plan (az 109.7, el 89.88) and SetIntensity(120000 lux),
  atmosphere sun light on, per-pixel transmittance per plan. Nothing updates look_applied.sun after.
- render.json scene.sky (89.88 deg / 120000 lux) and beauty_look.plan.sun.source=physical_sky agree:
  the physical sky lit scene 13.
Fix (record only, not a look change): after PhysicalSky.Build succeeds, overwrite the SunRecord fields
(sun_elevation_deg, engine_sun_yaw_deg, intensity, light_units=lux, lux_source=sky_plan) or add
"superseded_by": "scene.sky (FFlightSimSky::Build)". Check tests/test_render_json_contract.py first.

## Port interaction: the Google-tiles haze clamp (FlightSimGoogleTiles.cpp ~760-830)
Scene 13 render.json google_tiles.beauty_ground.haze: at 10 km AGL the beauty ground scales the height
fog AND the Mie layer by ONE factor so the optical depth along a 10-deg read ray is <= 1.5.
Before: fog depth 3.10 + Mie depth 0.35 -> scale 0.434 -> fog 0.0012 -> 0.00052, Mie 0.0455 -> 0.0198.
So the shipped frame rendered Mie at ~0.02, not 0.0455: the clamp, driven by the fog, thinned the
aerosol. The editor level had no clamp, so the batch-1 values are relative to an unclamped scene.
With the recipe (fog 0 at >= 4 km, Mie 0.09): Mie depth ~0.35 x 0.09/0.0455 ~= 0.69 < 1.5 -> scale 1,
the clamp stops biting and Mie 0.09 survives. At 600 m read_min_agl_m 1000 keeps it off.
Port rule: apply haze_for_agl() BEFORE the clamp, keep the clamp; check render.json
haze.scale == 1 at cruise on the first Windows round. UNMEASURED.
