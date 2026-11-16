# Owner's brief and reference, 2026-11-14

## X-Plane-12-level sky, clouds and atmosphere — the owner's brief (2026-11-14)

## The owner's words (verbatim)

GOAL
Make the sky, clouds and atmosphere in this repo's Unreal renders look like
X-Plane 12 at its best: a real-photo look, not a toy look. Reference look:
thin translucent stratocumulus/altocumulus with ragged, wispy edges and fine
cauliflower detail; bright white tops, soft grey-blue bellies, light bleeding
through thin edges; a sky that shades from deeper blue at the zenith to a pale
hazy band at the horizon; distant mountain ridges that each fade paler and
bluer than the one before (aerial perspective); natural warm sun with soft
shadows. Current output instead has smooth rounded gray blobs with dark
undersides, a flat navy frame, and no horizon haze.

Follow-up (same day): "keep fixing and making this better until the clouds
and sky look like this level of hyper realism" — the attached photo is the
target (described below).

READ FIRST: /CLAUDE.md (no scheduled check-ins, no PR polling; report once
after a PR and stop; Google tiles ON by default; the web app's weather ON by
default; do not make either opt-in). docs/VISUAL_FIDELITY_PLAN.md (V1, V2,
V6 and §8 status), docs/WEATHER.md, NEXT.md.

DO (in this order, one commit per step)
1. Custom cloud material M_CloudLayer (scripts/ue_create_materials.py):
   shape = low-frequency Perlin-Worley base noise x height-gradient profile
   (flat base, billowing top) x coverage; detail = higher-frequency
   Worley/curl noise eroding the edges (stronger near the boundary and top)
   for wispy, ragged edges; lighting = VolumetricAdvancedMaterialOutput with
   multi-scattering contribution, occlusion and eccentricity set so
   undersides glow and thin edges let light through; albedo near white;
   wind drift via the existing cloud_drift_mps keys; expose scalar
   parameters Coverage, Density, DetailStrength, NoiseScale, Wind; keep the
   usage flag and ensure_volumetric_cloud_usage.
2. Host (FlightSimSky.cpp): load M_CloudLayer instead of the stock instance,
   set the parameters from sky.json, keep the existing refusal / note
   behaviour if the material is missing. Do not break
   FFlightSimWeather::VerifyCloudMaterials.
3. Quality (offline renders can afford it): raise cloud view ray samples,
   shadow ray samples, sky ambient quality and aerial-perspective sampling
   via cvars, set only for the beauty capture path. Record the cvar values
   in the manifest.
4. Atmosphere and horizon: tune SkyAtmosphere (aerosol / Mie, ground albedo,
   multi-scattering), ExponentialHeightFog (density, height falloff, fog
   inscattering color, start distance) and aerial perspective so the
   horizon is pale and hazy and ridges layer blue. Add a subtle sun bloom.
   Keep exposure logic (EV100 in plan.py) unchanged.
5. Sky plan (core/sky/plan.py): add cloud_type (cumulus / stratocumulus /
   altocumulus / cirrus / overcast), coverage 0..1, density, detail and the
   cvar set to the "clouds" block, deterministic and seeded. Bump
   SKY_VERSION only if needed and update every consumer and test. Where a
   weather_date is available, derive coverage from Open-Meteo/ERA5
   cloud_cover_low/mid/high (plan item V6); otherwise use a stated default
   and record it as a default.
6. Cirrus: UE draws one volumetric layer, so add a separate thin high cirrus
   layer (high-altitude textured mesh or sky material) if steps 1-4 still
   leave the upper sky empty. Label it visual only.
7. Tests: unit tests for the plan fields (determinism, ranges, defaults,
   manifest recording). Do not weaken or skip any existing test. Run the
   suite and report real results, including failures.
8. Verify path for the owner: a script or documented command that renders 4
   fixed frames (clear, scattered cumulus, broken stratocumulus, overcast)
   at the same camera, plus a side-by-side contact sheet against the old
   look, so the owner can judge on the Windows laptop. Put the frames'
   expected location in docs.

CONSTRAINTS: no new proprietary assets or imagery; procedural noise only, or
CC0 textures with the licence noted in NOTICE.md / THIRD_PARTY_VISUAL.md. Do
not change flight dynamics, labels, or dataset formats. Cloud base stays
>= 1 km above the flight so the camera stays clear (existing rule) unless an
explicit in-cloud mode is added. All new behaviour deterministic for a seed.
UE cannot be rendered on the Mac: anything not rendered is UNMEASURED in
code comments, docs and the PR; never claim it looks right.

DONE MEANS: code, material script, plan fields and tests committed; draft
PR with a short honest report (what changed, what was tested here, what is
UNMEASURED and needs a Windows render, the exact command for the 4-frame
comparison). Then stop.

## The reference photograph (the owner's attachment), described

A twin-engine airliner (737-class, white, unmarked) seen from below and
behind-left, climbing away, gear up, against a daytime sky. Sun high and to
the upper left; the fuselage underside is in soft shadow with a warm bounce,
the wing leading edges catch the light. The sky: saturated medium blue at
the top of the frame (sRGB roughly 70/150/220), paling smoothly toward the
bottom to a milky light blue (about 170/205/235) — a hazy, brighter lower
sky, not a hard horizon band. Across the upper half: thin high cirrus /
cirrostratus, drawn as long translucent wisps and streaks with feathered
ends, brighter white where thicker, letting the blue through everywhere —
they read as veils, not blobs. In the lower half: fair-weather cumulus and
cumulus-congestus heaps. Their tops are brilliant white with crisp
cauliflower detail (many small rounded lobes, sharp sunlit edges, dark
crevices between lobes). Their bellies are soft grey-blue (about
150/165/185), not dark grey or black, and the shading grades smoothly from
lit top to shadowed base. Edges are ragged and partly transparent; thin
edges glow where the sun comes through from behind. The clouds overlap in
depth; farther ones are smaller, paler and bluer. No dark navy anywhere, no
smooth rounded blob shapes, no flat uniform undersides.

The current frames (e.g. round 95 #13, round 83 #03) differ in exactly the
ways the owner names: rounded grey blobs, dark flat undersides, a navy upper
sky, no cirrus, no horizon haze, no light through thin edges.

## What actually exists on branch claude/vibrant-gauss-olema4 (fbcbaa5d), verified 2026-11-14

The owner's "what exists" list predates the visual overhaul rounds. The
current state, by file:

- ue/.../Private/FlightSimSky.cpp ~358-395: the MEASURE-path host. It still
  spawns one AVolumetricCloud with the engine's stock
  m_SimpleVolumetricCloud_Inst and sets only layer bottom/height from
  Plan.CloudBottomKm / CloudThicknessKm (FlightSimSky.h 76-78, parsed from
  sky.json "clouds"). Measure renders must stay byte-identical, so this path
  is NOT where the look changes; it is the host the beauty pass re-materials.
- ue/.../Private/FlightSimClouds.cpp (3011 lines) FFlightSimWorldBeauty:
  under -quality=beauty, ApplyClouds (line ~1911) finds every
  UVolumetricCloudComponent, replaces the stock material with
  /Game/FlightSim/M_FlightSimCloudLayers (a dynamic instance per layer),
  sets its parameters from core/scene/world_beauty.py's CLOUDS table rows
  (cumulus, stratocumulus, overcast, nimbostratus — shape, extinction,
  coverage contrast, detail scale/erosion, bottom softness, top rounding),
  the per-layer march (SetViewSampleCountScale / SetShadowViewSampleCountScale
  capped by r.VolumetricCloud.ViewRaySampleMaxCount 768 / Shadow 80, lower on
  a constrained GPU: CloudConstrainedGpu(), line 844), shadow tracing
  distance, SkyLightCloudBottomOcclusion, ground albedo, and records all of
  it in render.json look_applied.clouds. Switches already parsed there:
  -look-cloud-billow=on|off (round 82), -look-cloud-tiers, -beauty-clouds=,
  -sky-capture-clouds, -contrails; c641a8c4 lowers a DEFAULT cumulus layer
  above 4 km to 1.5–2.7 km in beauty (cumulus below a 10 km cruise, as in the
  reference photo; the camera stays clear). ApplyAtmosphere (~1712) sets
  Mie scale height / anisotropy / aerial-perspective distance scale, ground
  albedo and (NOT on a constrained GPU, ef361bd6) MultiScatteringFactor from
  world_beauty.ATMOSPHERE rows (clear/hazy/overcast/rain/storm) and
  SKY_MULTI_SCATTERING.
- assets/shaders/world/cloud_layers.hlsl (377 lines): the extinction Custom
  node body of M_FlightSimCloudLayers. ALREADY Nubis-style: Perlin-Worley
  weather field on the plane (cluster term, three rounded Worley cell
  scales, one 3D billow octave), height-raised cut (domed tops, flat bases),
  Worley-fbm erosion inside the cloud, LOD by camera distance, HeightDensity
  gradient (round 82), dome taper (round 92), dithered/soft shadow samples
  (round 52/61), far fade to the distant sheet. All hashed-lattice noise, no
  textures. Inputs listed at its top (WORLD_CLOUD_INPUTS in
  ue_create_materials.py line ~3539). The Python replica and constants live
  in core/scene/world_beauty.py (cloud_shape, cloud_detail, cloud_density)
  and are pinned by tests/test_world_beauty.py, test_cloud_tiers.py,
  test_cloud_billow.py.
- assets/shaders/world/distant_clouds.hlsl + M_FlightSimDistantClouds: a far
  cloud sheet beyond the march (round 61).
- scripts/ue_create_materials.py: create_world_cloud_layers() (~3885) builds
  M_FlightSimCloudLayers: Volume domain, additive, STORM_USAGE_PROPERTY
  ("used_with_volumetric_cloud"), extinction -> MP_SUBSURFACE_COLOR, Albedo
  scalar WORLD_CLOUD_ALBEDO -> base colour, and storm_scattering() (~1837)
  adds the VolumetricAdvancedMaterialOutput node with STORM_SCATTERING
  (phase g 0.8 / -0.5 blend 0.5, 2 octaves, contribution 0.5, occlusion 0.5,
  eccentricity 0.5, ground_contribution True) — the same constants as the
  thunderstorm's M_StormCell. ensure_volumetric_cloud_usage(name) at ~2171.
  WORLD_GRAPH_GENERATIONS / the generation stamp at ~3740 ("9" for
  M_FlightSimCloudLayers) must be bumped when the graph changes.
- ue/.../Private/FlightSimVisualScene.cpp ~655-860: SkyAtmosphere
  (MultiScatteringFactor 1.0, SetMieScatteringScale from
  weather_visuals aerosol_scale x 0.003996/km), ExponentialHeightFog
  (density from Options, height falloff 0.0002, start distance 1500 m,
  inscattering colour = horizon), SkyLight (real-time capture), sun/sky
  intensity scales. All qualities; beauty-only changes belong in
  FFlightSimWorldBeauty (FlightSimClouds.cpp) or a beauty-gated branch.
- core/sky/plan.py plan_sky() ~373-475: "clouds" block = {enabled, bottom_km
  (max(2 km, agl+1 km); 1.2 km in storms), thickness_km 3 (6 storm), basis
  "VISUAL ONLY"}; SKY_VERSION = 1 (line 47); "Pure: same inputs, same
  bytes". Exposure (ev100) is computed above it and must not change.
- core/scene/weather_visuals.py: cloud_layers(cover, base, top) -> the
  card's look.clouds[0]; cloud_drift_mps / cloud_drift_from_deg and
  cloud_drift_at_base (the drift the material's WindOffsetM advances).
- core/scene/world_beauty.py (1721 lines): CLOUDS rows, ATMOSPHERE rows,
  SKY_MULTI_SCATTERING, mie_split (Koschmieder split of haze between Mie and
  fog), FAIR_LAYER, CUMULUS_MAX_BASE_M, all the cloud constants' Python
  twins.
- FFlightSimWeather::VerifyCloudMaterials (FlightSimWeather.cpp 1244):
  refuses by name any cloud component whose material is not Volume-domain
  and flagged for the volumetric cloud; the render commandlet calls it.
- Hardware: the Windows laptop is an Intel iGPU, D3D11 SM5 (no Lumen, VSM,
  Nanite, RT); Windows TDR resets a GPU after a ~2 s stall (r87's
  DXGI 887a0006 inside the sky-light capture). docs/hardware/
  hardware_budget_measured.json: ~4.1 GB shared GPU peak at tier 0; RAM,
  not the GPU, is the next limit. Quality raises must respect
  CloudConstrainedGpu() tiers and the still accumulation.
- Rounds: docs/visual/FIX_ROUND_PROTOCOL.md; scripts/visual_fix_round.ps1
  -Round N -Scenes "a,b" [-Switches "..."] [-CompareWith M]; the scene list
  is scripts/run_test_scenarios.py (1-based: 1 golden-hour A-4, 3 A320 over
  New York, 4 desert A-4 sun behind, 6 A320 SFO rain, 9 747 thunderstorm,
  11 A-4 Matterhorn, 12 C172 cockpit Grand Canyon, 13 747 cruise over the
  ocean, 15 747 hurricane-like). Rounds 1–95 have run; wave-2 numbering
  starts at r97 (r96 is a verify sweep). The last pixel results are in
  docs/VISUAL_FIDELITY_PLAN.md §8.
- docs/visual/final/REVIEW.md does not exist on this branch (it was on
  phase-2-final / vis-windows); do not block on it.
- Tests: pytest -q -p no:cacheprovider -n auto -W ignore (minutes; run in the
  background). API shape: bash scripts/check_bridge_api.sh. A brace-balance
  test guards the C++. Python: /Users/dhruva/flightsim-old/.venv/bin/python.

## How the brief maps onto what exists (the design agents refine this)

- Step 1 "M_CloudLayer" = evolve M_FlightSimCloudLayers (do not fork a second
  beauty cloud material): add curl-noise distortion of the detail noise,
  boundary- and top-weighted erosion (ragged wisps), a thin-edge
  transmittance term (light through thin edges), beauty-specific
  CLOUD_SCATTERING constants for the VolumetricAdvanced node (separate from
  STORM_SCATTERING; undersides glow: higher multi-scatter contribution,
  lower occlusion; near-white albedo), and expose the owner's parameter
  names (Coverage, Density, DetailStrength, NoiseScale, Wind) either as the
  existing parameters' documented aliases or as new scalars that drive them,
  pinned by tests. Bump the generation stamp.
- Step 2 = the beauty host already swaps the material; make it read the new
  sky.json "clouds" fields (cloud_type, coverage, density, detail) through
  the plan -> card -> ApplyClouds path, keep the stock material on the
  measure path (byte-identical), keep the missing-material note/refusal and
  VerifyCloudMaterials.
- Step 3 = raise the march (view/shadow sample scales, shadow tracing,
  r.VolumetricCloud.* caps, r.SkyAtmosphere.* sample counts, aerial
  perspective LUT quality) in the beauty path only, tiered by
  CloudConstrainedGpu() so the iGPU never sees one long submission; record
  every cvar value in render.json.
- Step 4 = ATMOSPHERE rows + ApplyAtmosphere + the beauty fog: pale hazy
  horizon band (fog inscattering toward the sky's horizon colour, height
  falloff, start distance), aerial perspective so ridges layer blue
  (AerialPerspectiveViewDistanceScale, Mie), multi-scattering on every GPU
  if it is affordable (ef361bd6 left it off on the iGPU: find out why), a
  subtle sun bloom in the beauty post. EV100 unchanged.
- Step 5 = plan.py "clouds" gains cloud_type, coverage, density, detail,
  cvar set, seed; from Open-Meteo/ERA5 cloud_cover_low/mid/high when
  weather_date is given (core/environment already has a weather provider:
  find it), else stated defaults recorded as defaults. Deterministic.
- Step 6 = a beauty-only cirrus layer (procedural translucent high sheet or
  sky-dome material at 9–11 km, no depth, listed in BeautyOnlyActors),
  wispy streaks with feathered ends, letting the blue through.
- Step 7 = tests. Step 8 = scripts/sky_compare_round.ps1 (or a documented
  visual_fix_round.ps1 invocation) rendering one fixed camera (scene 13 or
  3) under -cloud-type=clear|cumulus|stratocumulus|overcast, plus a PIL
  contact sheet against the previous round's frame; docs state the
  location docs/visual/sky_compare/.
