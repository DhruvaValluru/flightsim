# X-Plane-12 sky: the design builders execute (sky steps 1-8)

Synthesised 2026-11-14 from three architects' designs against the worktree at
fbcbaa5d (branch `claude/xplane-sky`). The owner's brief and the reference
photograph are in `docs/visual/XPLANE_SKY_BRIEF.md`. Every line number below is
fbcbaa5d's; every look value is UNCALIBRATED and every visual claim is
UNMEASURED until the Windows laptop (Intel iGPU, D3D11 SM5) renders it with the
command named in that step. Nothing in this design was rendered, built or run.

Hard rules (CLAUDE.md wins over everything here): never build or run Unreal on
the Mac; look changes live under `-quality=beauty` (`FFlightSimWorldBeauty`,
FlightSimClouds.cpp) so measure renders stay byte-identical; labels, dataset
formats, flight dynamics and the exposure logic (EV100 in core/sky/plan.py,
beauty_look's meters) do not change; procedural noise only; everything
deterministic for a seed; every look amount labelled UNCALIBRATED; cloud base
>= 1 km above the flight (the c641a8c4 beauty exception that lowers a DEFAULT
cumulus layer below a high cruise is kept and said so); one commit per step,
`Sky step N: <what>`, ending with the two trailer lines; a repair amends.
Python is `/Users/dhruva/flightsim-old/.venv/bin/python`; the suite is
`cd <worktree> && /Users/dhruva/flightsim-old/.venv/bin/python -m pytest -q -p no:cacheprovider -W ignore -n auto`
in the background; API shape is `bash scripts/check_bridge_api.sh`. No test is
weakened, skipped or deleted; a legitimately moved pin is updated with the
reason in its docstring.

## 0. Where the brief is stale against the code (all three architects agree; verified)

1. **Step 2 is not FlightSimSky.cpp.** FlightSimSky.cpp 358-395 is the MEASURE
   host (stock `m_SimpleVolumetricCloud_Inst`, bottom/height from the plan). It
   runs under every quality; changing it changes measure bytes. The beauty host
   that already swaps the material is `FFlightSimWorldBeauty::ApplyClouds`
   (FlightSimClouds.cpp 1911; material path 849, needle 865, dynamic instance
   per layer 2102, missing-material note 1944-1953). Step 2 = ApplyClouds reads
   the plan's new fields; FlightSimSky.cpp changes only its parser (optional
   reads), never `Build`.
2. **Two generation stamps.** `WORLD_GRAPH_GENERATIONS` (scripts/ue_create_materials.py
   3692, tag `GRAPH_GENERATION_TAG` 954: a stale asset is set aside and rebuilt)
   and `WORLD_GENERATIONS` (3739, tag 3743: update in place). A shader-body change
   bumps BOTH for `M_FlightSimCloudLayers`: graph "7" -> "8", world "9" -> "10".
   tests/test_cloud_billow.py 96-103 pins the exact strings `"M_FlightSimCloudLayers": "7"`
   and `"M_FlightSimCloudLayers": "9"`; those two asserts move to `>= 8` / `>= 10`
   with the reason in the docstring (every other generation test already uses `>=`).
3. **No cirrus material exists.** `M_FlightSimDistantClouds` / distant_clouds.hlsl
   is a far deck at the layer's altitude (round 61). Cirrus is a new material,
   shader and disc (step 6).
4. **The VolumetricAdvanced node's multi-scattering pins are per pixel**
   (engine header MaterialExpressionVolumetricAdvancedMaterialOutput.h 31-40,
   VolumetricCloud.usf 749-755). A per-sample "thin-edge multi-scatter boost" is
   not expressible; light through thin edges comes from the extinction field
   (edge thinning) plus a stronger forward lobe.
5. **`ensure_volumetric_cloud_usage`** (2171) is the storm materials' in-place
   flag repair; `create_world_cloud_layers` (3885) sets `STORM_USAGE_PROPERTY`
   directly (3897, pinned by test_world_beauty.py 420). Nothing to add; do not
   call `ensure_...` for the world material (it would skip the rebuild).
6. **Wind already arrives**: `Advance` (FlightSimClouds.cpp 2882-2892) sets
   `WindOffsetM` from the card's drift. The owner's `Wind` is an alias.
7. **`storm_scattering` is shared with M_StormCell** (calls at 2236 and 3918).
   The beauty cloud needs its OWN constant table; the storm call is untouched
   (no quarter-hour storm recompile, no change to p3's storm look).
8. **The shared-noise pin shapes where shader code may go.** test_distant_clouds.py
   206 requires the block between `const float WISP_HEIGHT = 0.25;\n` and
   `FWorldCloud C;` in cloud_layers.hlsl to be text-equal to distant_clouds.hlsl's;
   test_world_beauty.py 743 extracts `struct FWorldCloud` to the first `\n};\n`;
   test_cloud_tiers.py `_shader_as_cpp` splits on `\nFWorldCloud C;\n`. Every new
   constant, struct and function goes AFTER `FWorldCloud C;` (292). The distant
   sheet's text is then untouched and needs no rebuild in step 1.
9. **MultiScatteringFactor on the iGPU.** FlightSimClouds.cpp 1742-1746 skips it
   because "ef361bd6 never set it"; the round-1 bisect named a8c964fc as a unit
   (march, shadow span, thinning, multi-scatter, fog-on-all-pixel together) and
   r87 later located the stall in `USkyLightComponent::UpdateSkyCaptureContents`
   and capped it. The factor is a per-frame uniform on the sky/AP shaders; the LUT
   is already computed at `r.SkyAtmosphere.MultiScatteringLUT.HighQuality=1` on
   every GPU by the render path (commandlet 4113). Nothing isolated the factor;
   nothing shows it stalls; nothing shows it does not. See step 4.
10. **Sun bloom has an owner already**, and it is not plan.py's post block (that
    block reaches measure renders via `FFlightSimSky::ApplyPostProcess`, commandlet
    3891-3897, no beauty gate). The lens bloom on beauty is beauty_look's row
    (FlightSimBeautyLook.cpp 1098-1142, applied last); the SUN bloom (light-shaft
    bloom) is written by `FFlightSimSunShafts::Apply` and then overwritten by
    `FFlightSimHeroLighting::Apply` (FlightSimHeroLighting.cpp 76-78, 283-294:
    0.12 / 6 / 50, off when overcast), which runs later and wins.
11. **The weather provider is wind-only.** core/environment/era5.py has
    `fetch_reanalysis_wind` (58-117), called from webapp/runs.py
    `apply_historical_weather` (3130-3177). No cloud cover anywhere in core.
    Both Open-Meteo endpoints serve hourly `cloud_cover_low/mid/high` (percent);
    the two DISAGREE hour by hour (probe saved under the scratchpad
    `xplane/openmeteo_probe/`). Clouds use the ERA5 `ARCHIVE_URL` (26).
12. **The physical sky is opt-in** (`FLIGHTSIM_SKY=physical`, webapp/runs.py
    2868-2879). scripts/visual_fix_round.ps1 160-162 sets only RENDER_QUALITY,
    BEAUTY_POST and RENDER_SWITCHES; the rounds relied on the Windows shell's
    environment. Step 8's script sets it explicitly and records it.
13. **The rounds' scenes have no card clouds.** `weather_visuals.cloud_layers ->
    card.look.clouds` runs only for randomized datasets (randomization.py 1723),
    so in every visual round `CardCover < 0` and the beauty layer is the plan's
    default slab, reshaped to the cumulus row's `default_cover` 0.35 and, above
    4 km, lowered to the 1.5-2.7 km fair slab (FlightSimClouds.cpp 2085-2094,
    round 95). That is the only thing drawing clouds in scene 13 today.
14. **Two cloud components, one draws.** Under a plan WITH a card `look.clouds[0]`
    both `FFlightSimSky::Build`'s `AVolumetricCloud` (FlightSimVisualScene.cpp 759)
    and `BuildClouds`' component (865, registered later) exist; `FScene` keeps the
    last-registered one (UE 5.7 VolumetricCloudRendering.cpp 577-614). ApplyClouds
    re-materials both and the occlusion rows count both. Step 2 records it.
15. **SKY_VERSION consumers are exactly two**: plan.py 47/403 and FlightSimSky.cpp
    34 (`SkySupportedVersion = 1`). No test pins the number. New keys are additive
    and read with `TryGet*`: no bump; the missing pin test is added (step 7).
16. **Step 3 collides with pinned laws.** test_world_beauty.py 930 pins
    `{2.0, 1.0, 80.0},   // constrained`, `if (!CloudConstrainedGpu())` within 200
    chars before `SetMultiScatteringFactor(`, `FogAll->Set(1, ECVF_SetByCode);`
    within 200 chars after `if (!bIntegratedGpu)`; test_cloud_jitter_blue_noise.py
    100 pins the constrained row again and that the COMMANDLET's `SetBeautyCvar`
    cloud cvars are exactly `r.VolumetricCloud`, `.HighQualityAerialPerspective`,
    `r.VolumetricRenderTarget.Mode`. The laptop IS the constrained class.
17. **The reference photo is a low camera** (a 737 climbing, 1-3 km). Scene 13 is a
    747 at 10 km, where a physically based zenith IS darker. Step 8 compares on
    scene 3 (A320 over New York, 600 m, 18 mm) first; 13 is the secondary camera.
18. **The hardware budget says nothing about the march** (tier 0 ran with
    `r.VolumetricCloud=0`). The only data: 192 view samples at 1080p rendered
    (rounds 5-95); 384 hung pre-r87 (cause later placed in the sky capture).

## 1. Decisions where the architects disagreed, and why

| # | question | architect 1 | architect 2 | architect 3 | decision and basis |
|---|---|---|---|---|---|
| D1 | the owner's `Coverage, Density, DetailStrength, NoiseScale, Wind` | documented aliases of existing scalars | new scalars the host must set | aliases | **Aliases**, recorded in render.json. test 395 pins the scalar set == what C++ sets and every input in the HLSL header; a new scalar is a Custom input, a rewiring, a harness signature and a rebuild for no behaviour. The five WISP scalars of step 1 ARE new inputs (they carry new behaviour). |
| D2 | plan `density`/`detail` | unitless multipliers of the row (1.0 = row) | multipliers | absolute extinction and erosion copied from the CLOUDS row into sky.json | **Multipliers** (clamped 0.5..1.5 and 0..1 after). One source of truth per type (the CLOUDS row); a plan that snapshots the table is a second source that drifts. |
| D3 | altocumulus | a new CLOUDS row | the stratocumulus row at the plan's base, recorded | a new row | **New row** (`CloudCount` 4 -> 5 on both sides). Altocumulus is not stratocumulus at another scale; the big twin test pins the two tables equal, so both move together honestly. |
| D4 | step 3 shape | raise the discrete row; opt-in `integrated_plus` | cvar table per class + `-cloud-march=` switch; constrained = engine defaults | `-sky-quality=default/high`, pinned rows untouched | **A2's cvar table and switch, with A1/A3's opt-in probe as a 4th word**: `-cloud-march=auto\|constrained\|discrete\|probe`. One switch word space, the pinned constrained row untouched, the raise reaches the laptop ONLY by the owner's probe. |
| D5 | multi-scattering on the iGPU | leave to A2 | lift the gate, auto = on everywhere, test 930 moved | keep off unless the quality switch | **Switch `-sky-multi-scatter=auto\|on\|off`, auto = today's gate (off on the constrained class).** A2's facts (uniform; LUT already HQ everywhere; r87 holds the stall site) are code-read and make the probe likely to pass, but the brief says "if it is affordable" and affordability is unmeasured. The probe is the FIRST Windows round (step 8); if it renders clean the compare rounds run with `-sky-multi-scatter=on` and a one-line follow-up flips auto. Test 930 keeps its literals and gains the switch. |
| D6 | `HighQualityAerialPerspective 1` on discrete (A1) | set it | render path owns it | n/a | **Not touched by the world lane**: it is the commandlet's (one-owner ledger; jitter test 100 pins the commandlet's set). Recorded by read-back only. |
| D7 | `ConservativeDensity` second Custom node (A1) | optional, off | n/a | n/a | **Deferred out of this wave.** A wrong bound punches holes; it is a second node and rebuild for a saving nobody measured. Listed as follow-up. |
| D8 | aerial perspective scale | clear row 1.0 -> 1.4 | stay 1.0 (world_beauty.py 112-119: it multiplies only opaque haze and breaks the Koschmieder single count) | n/a | **Stays 1.0.** The fix-pass note is in the code; the ridge layering comes from the fog shape fields and the AP LUT depth. |
| D9 | horizon haze knobs | n/a | 4 new ATMOSPHERE fields (fog falloff scale, start, max opacity, AP Rayleigh fade) | fog inscattering colour among them | **A2's four.** Under a plan the fog's inscattering is Black + `SkyAtmosphereAmbientContributionColorScale` White (FlightSimSky.cpp 252-253): the fog is already lit by the atmosphere; the band is a height/falloff question. |
| D10 | sun bloom | post setting | per-preset `HeroLighting` shaft-bloom rows | `bloom` delta in ATMOSPHERE | **A2's rows in FlightSimHeroLighting.cpp** (the writer that wins; verified at 283-294). plan.py's post block is never touched (measure path). |
| D11 | plan fields | 4 | 5 (+coverage_source) | 9 (+seed, cirrus, noise scale, density/m) | `cloud_type, coverage, density, detail, cirrus_coverage, coverage_source, cover_inputs, cloud_type_basis, seed, seed_source, quality_tier_requested`. No `noise_scale_km` (the row owns it; the owner's `NoiseScale` is an alias). |
| D12 | cirrus altitude law | clamp(max(9500, acft+1500), .., 12000) | max(10500, camera+1500) | 9-11 km, lift or DROP below the flight | **`max(CIRRUS_BASE_M 10000, camera_m + CIRRUS_CLEARANCE_M 1500)` capped at 13000.** Never below the camera: cirrus is above; the owner's clearance rule holds by construction. |
| D13 | cirrus sort priority | -110 | -101 | n/a | **-101** (the distant sheet is -100 at 2422; the cirrus is farther from every camera it can overlap, so it draws first). |
| D14 | step 8 camera | scene 3 primary, 13 secondary | scene 3 (or 1), 13 too | scene 13 primary, 3 optional | **Scene 3 primary** (the reference is a low camera, §0.17; bellies and rims against the sky), **13 secondary** (tops from above, cirrus overhead). |
| D15 | step 8 script shape | `visual_fix_round.ps1` calls + `sky_compare_sheet.py` | `sky_compare_round.ps1 -Round N -Scene 3` + `sky_contact_sheet.py` | `sky_compare_round.ps1 -Base N -Scene 13` + `sky_compare.py` with the requested/applied MISMATCH check | **`scripts/sky_compare_round.ps1 -Round N -Scene S -CompareWith M [-Switches ".."]`** + **`scripts/sky_compare.py`** with A3's requested-vs-applied check and A2's march/multi-scatter captions. |
| D16 | the shadowed plan component (§0.14) | n/a | skip its material swap, exclude from `CloudLayers`, `SetVisibleInRealTimeSkyCaptures(false)` | n/a | **Record and exclude from the layer bookkeeping; STILL re-material it.** The stack rule is read in source, not witnessed; a re-materialled inert component costs nothing and a wrong reading still shows the beauty material. `SetVisibleInRealTimeSkyCaptures(false)` only on the component recorded as shadowed. |

Names the steps must agree on: material scalars `Coverage, ExtinctionPerM, DetailErosion, ShapeScaleKm, WindOffsetM` (+ step 1's `WispAmount, CurlStrength, EdgeThinPower, TopDetailGain, BoundaryErosion`); plan keys `cloud_type, coverage, density, detail, cirrus_coverage, coverage_source, seed`; `PLAN_CLOUD_TYPES = ("clear", "cumulus", "stratocumulus", "altocumulus", "cirrus", "overcast", "nimbostratus")` defined once in core/scene/world_beauty.py and imported by core/sky/clouds.py.

## 2. Cross-cutting mechanics (every step)

- **Pure block.** Constants and laws go in `FlightSimWorldPure` (FlightSimClouds.cpp
  80-836, `// FLIGHTSIM-WORLD-PURE-BEGIN/END`, no FString/TEXT) with a Python twin
  in core/scene/world_beauty.py, pinned by test_world_beauty.py 170 (g++ compiles
  the block and compares every table) and 784 (march + sky). Every look constant
  carries the literal `UNCALIBRATED` nearby (test 348).
- **Cvar save/restore, one helper.** Replace `FString CloudFogAllPixelBefore`
  (FlightSimClouds.h 253; set 2048-2063; restored 1689-1701) with
  `TArray<FSavedCvar> WorldCvarsBefore` and
  `SetWorldCvar(const TCHAR* Name, double Value, TSharedPtr<FJsonObject>& Row)`
  modelled on `FFlightSimSunShafts::SetSunShaftsCvar` (FlightSimSunShafts.cpp
  245-272: save once, `ECVF_SetByCode`, record `[before, read_back]`, a
  "skipped: not registered" list). The literal `FogAll->Set(1, ECVF_SetByCode);`
  stays within 200 chars of `if (!bIntegratedGpu)` (test 930); only its SAVE is
  routed through the array. `RestoreCvars()` walks the array in reverse.
- **render.json.** Beauty records go under `look_applied.world_beauty.*`
  (`Record`, FlightSimClouds.h 128). Adding keys is free
  (test_render_json_contract.py 49 constrains only keys the verifier reads);
  core/capture/beauty_look.py's verifier is NOT told to read any new key.
- **One-owner ledger** (commandlet ~3966-4020): the world lane gains "the cloud
  march's sample caps and the sky-atmosphere LUT sample counts beyond the render
  path's on/off and LUT-format cvars; the cirrus sheet". The render path keeps
  `r.VolumetricCloud`, `.HighQualityAerialPerspective`, `r.VolumetricRenderTarget.Mode`,
  `FastSkyLUT`, `FastApplyOnOpaque`, `MultiScatteringLUT.HighQuality`, `LUT32`,
  `SampleCountMax`, `AerialPerspectiveLUT.SampleCountMaxPerSlice` (4106-4127);
  sun shafts keeps `r.VolumetricCloud.ShadowMap`, `SkyAO`,
  `Shadow.SampleAtmosphericLightShadowmap`, `r.SkyLight.RealTimeReflectionCapture.*`.
  No two lanes set one name (new source test, step 3).
- **Switches.** Parsed in `Build` next to 1127-1135 from `Params + FLIGHTSIM_RENDER_SWITCHES`,
  default word set first, an unknown word refuses `world_beauty.clouds: -<name>=%s is not ...`
  (pattern 1138-1148), registered in core/config_surface.py 234-239 and the
  refusal catalogue (test_distant_clouds.py 302 looks there).
- **Labels.** Label captures draw no cloud, fog or atmosphere (`ConfigureLabelCapture`,
  LABEL_OFF in test_render_json_contract.py 277-285); volumetric clouds and the
  sheets write no depth/stencil; every new actor goes in `Scene.BeautyOnlyActors`
  (hidden on every label capture; test_beauty_label_isolation.py 183 pins
  `HiddenActors.Append(BeautyOnlyActors)`).
- **Determinism.** Seeds: `CloudSeedOffsetKm(Seed)` for every noise (card
  `weather_look.seed` / `seed`, Build 1289-1290), fixed seed offsets in the HLSL,
  no time, no texture; wind from the scene's drift law in `Advance`.
- **Exposure.** plan.py `ev100` (373-457) and beauty_look's meters are untouched by
  every step; the plan's cloud fields are computed after the exposure dict and
  never read into it (test, step 7).
- **API shape.** Every new engine symbol gets a `sky_check` line in the world-lane
  block of scripts/check_bridge_api.sh (434-475) and every new cvar an `rp_cvar`
  line (273-280). Run `bash scripts/check_bridge_api.sh` and
  tests/test_cpp_brace_balance.py after each C++ edit.

## 3. Step 1: evolve M_FlightSimCloudLayers

Commit: `Sky step 1: wispy edges, cauliflower tops, thin-edge light, beauty scattering`.
Files: assets/shaders/world/cloud_layers.hlsl, scripts/ue_create_materials.py,
core/scene/world_beauty.py, FlightSimClouds.cpp/.h (the five scalars and the
switch), tests.

### 3.1 What is missing today (cloud_layers.hlsl 292-377)
`shape` -> quantile cut -> `density = Remap(shape, cut, cut+soft)` (346) -> erosion
by a 2-octave isotropic Worley `Detail` (348-362) -> `density * base * body *
ExtinctionPerM * ExtinctionScale * fadeOut` (377). Nothing stretches lobes into
wisps; one Worley pair at `DetailScaleKm`, no finer top octave; extinction is
linear in density so the soft band is optically thick at once (0.05/m x 100 m =
tau 5); `SkyLightCloudBottomOcclusion` is RAISED to 0.8 under the billow
(`CloudBottomOcclusionFor` 343-346) so a belly gets 20 % of the sky; the node's
MS constants are the thunderstorm's (contribution 0.5, occlusion 0.5).

### 3.2 New Custom inputs (appended in this order to `WORLD_CLOUD_SCALARS` 3524-3537 and `WORLD_CLOUD_INPUTS` 3539-3544; defaults are the OFF values, so an unset material draws round 95)
| input | default | meaning | Python twin (world_beauty.py) |
|---|---|---|---|
| `WispAmount` | 0.0 | master gate 0..1; 0 = round 95's arithmetic exactly | `CLOUD_WISP_AMOUNT = 1.0` |
| `CurlStrength` | 0.0 | flow-warp of the detail sample, in detail cells | `CLOUD_WISP_CURL = 0.6` |
| `EdgeThinPower` | 1.0 | extinction x density^power after erosion | `CLOUD_WISP_EDGE_POWER = 1.6` |
| `TopDetailGain` | 0.0 | third (finer) Worley octave's weight at the top | `CLOUD_WISP_TOP_DETAIL = 0.6` |
| `BoundaryErosion` | 0.0 | extra erosion at the boundary x (1 - density) | `CLOUD_WISP_BOUNDARY_EROSION = 0.5` |

Also: `CLOUD_WISP_SWITCH = "-look-cloud-wisp"` (on by default; off = round 95;
another word refuses `world_beauty.clouds: -look-cloud-wisp=%s is not on or off`),
`CLOUD_WISP_SHAPES = ("cumulus", "stratocumulus", "altocumulus")` (overcast and
nimbostratus keep flat veils), `cloud_wisp_applies(on, shape)`,
`cloud_wisp_row(applies) -> {WispAmount, CurlStrength, EdgeThinPower, TopDetailGain, BoundaryErosion}`
(0/0/1.0/0/0 when off), `CLOUD_WISP_BOTTOM_OCCLUSION = 0.45` with
`cloud_belly_occlusion(applies, occlusion) -> min(occlusion, 0.45) if applies else occlusion`,
applied AFTER `cloud_bottom_occlusion_for` so test_cloud_billow.py 77
(`test_the_bottom_occlusion_only_rises`) stands untouched. All UNCALIBRATED.

### 3.3 Shader (all after `FWorldCloud C;`, line 292)
Constants: `CURL_OCTAVE_SCALE = 0.5` (the warp is coarser than the lobes it moves:
lobes stretch, not jitter), `TOP_DETAIL_LACUNARITY = 4.1`, `TOP_DETAIL_MEAN =
<measured by the Python replica, like DETAIL_MEAN 114 / CLOUD_DETAIL_MEAN 645>`,
`TOP_DETAIL_LOD = 0.5` (fades out by `far` 0.5: at 13 km a 40 m lobe is ~2 px at
1080p/55 deg). Mirrored as `CLOUD_WISP_*`, pinned by `in HLSL` string asserts
(pattern test_cloud_tiers.py 458-477).

Local struct `FWorldWisp`:
- `float3 Flow(float3 p, uint seed)`: two 3D gradient noises
  (`C.Perlin(p, seed+701u)`, `C.Perlin(p, seed+733u)`) and their swap as the
  third component: a flow-noise warp, 16 lattice hashes. The comment says
  honestly: NOT a divergence-free curl (that is 6 partials = 48 hashes); Nubis
  uses a curl texture and we have no textures.
- `float TopDetail(float3 q, uint seed)`: `C.Worley(q * TOP_DETAIL_LACUNARITY, seed + 193u)` (27 hashes).

Inside the erosion branch (348-362), inside `if (footKm < DetailScaleKm)` (356):
```
float3 q = km / max(DetailScaleKm, 1e-3);
[branch] if (WispAmount > 0.0 && footKm == 0.0)        // view samples only
    q += (WispAmount * CurlStrength) * W.Flow(q * CURL_OCTAVE_SCALE, 23u);
detail = C.Detail(q, 13u);
float topW = WispAmount * TopDetailGain * smoothstep(WISP_HEIGHT, 1.0, h) * (1.0 - smoothstep(0.0, TOP_DETAIL_LOD, far));
[branch] if (topW > 0.0)
    detail += topW * (W.TopDetail(q, 13u) - TOP_DETAIL_MEAN);   // zero-mean: DETAIL_MEAN still holds
```
Line 361 becomes
```
float ero = DetailErosion * (1.0 - far) * wisp * (1.0 + WispAmount * BoundaryErosion * (1.0 - density));
density = C.Remap(density, ero, 1.0);
```
and after the branch, before `fadeOut`:
```
[branch] if (WispAmount > 0.0) density = lerp(density, pow(density, EdgeThinPower), WispAmount);
```
`pow(0, p) = 0`: the support is unchanged, so the drawn cover law
(test_world_beauty.py 684, measured on density > 0) keeps its form;
`BoundaryErosion` shrinks the drawn share a little. The test's 10 % band decides
whether `EROSION_CUT_SHARE`'s early start needs `+ 0.5 * BoundaryErosion *
DetailErosion * soft`; add that compensation ONLY if the measured share leaves
the band, and pin it. Shadow samples (footKm > 0) read the undistorted detail or
its mean as before but DO get the edge thinning (that is what lets the sun
through a rim). With `WispAmount` 0 every new branch is skipped and `q` is the
same float3 round 95 passed: `-look-cloud-wisp=off` is round 95 bit for bit
(extend test_cloud_tiers.py 392's switch-off equality).

Cost (UNMEASURED): clear air unchanged; a near in-cloud view sample +16 hashes
(flow) and, in the top half within 13 km, +27 (top octave) on today's 43 + 54:
up to +40 % on those samples only; shadow samples +0 hashes (+1 pow).

### 3.4 Python replica
`cloud_density(...)` (world_beauty.py 1205-1242) gains `wisp: Optional[Dict] = None`
(the `cloud_wisp_row` dict) and mirrors the three insertions number for number;
new `cloud_flow(x, y, z, seed)`, `cloud_top_detail(x, y, z, seed)`. The `_SHIMS` in
tests/test_cloud_tiers.py 333 gain `static float pow(float a, float b)` and
`float3 operator*(float s, float3 a)` as needed (harness only). `_INPUTS` (368)
gains the five names in order; the body test adds cases with the wisp row on and
asserts twin equality at `abs=2e-3 * extinction` as today.

### 3.5 The VolumetricAdvanced node: beauty constants
scripts/ue_create_materials.py, next to `STORM_SCATTERING` (571):
```
CLOUD_SCATTERING = {"phase_g": 0.85, "phase_g2": -0.3, "phase_blend": 0.3, "octaves": 2,
                    "contribution": 0.7, "occlusion": 0.25, "eccentricity": 0.4}   # UNCALIBRATED
```
Engine semantics (VolumetricCloud.usf 374-395, 1080): octave ms scatters
`S0 * c^(2^ms - 1)` and sees the sun through `exp(-tau * o^ms)`, its phase
`lerp(isotropic, base, e^(2^ms - 1))`: higher contribution and lower occlusion
make bodies and undersides glow; a lower eccentricity makes the second octave
near-isotropic (light wraps to the belly); g 0.85 sharpens the forward lobe that
lights a backlit rim. `bClampMultiScatteringContribution` stays engine default
True, `PerSamplePhaseEvaluation` False (no cost), `ground_contribution` True.
`storm_scattering(material, lib, x, y)` becomes
`storm_scattering(material, lib, x, y, constants=STORM_SCATTERING)`; call it with
`constants=CLOUD_SCATTERING` at 3918 ONLY; the M_StormCell call (2236) is
unchanged (pin: `create_storm_cell` still calls `storm_scattering(material, lib, -600, 700)`).
Python twin `world_beauty.CLOUD_SCATTERING` pinned equal to the script's dict.
Albedo stays `WORLD_CLOUD_ALBEDO = 0.98`.

### 3.6 The distant sheet (parameters only, no shader change, no rebuild)
`DISTANT_LOOK` (world_beauty.py 816-826) and its C++ twin `DistantLook` (pinned
C++ == Python by test_distant_clouds.py 115): `BaseDarkening 0.55 -> 0.70`,
`BaseSunShare 0.15 -> 0.25`, `SilverLining 0.6 -> 0.8`. UNCALIBRATED.

### 3.7 Host (material side; the plan side is step 2)
FlightSimClouds.cpp: parse `-look-cloud-wisp=` next to 1131/1136 (header
`FString CloudWispSwitch = TEXT("on");` after FlightSimClouds.h 196), refuse by
name after 1148; in the layer loop after 2131 set the five scalars from
`CloudWispRow(bWisp, Out[5])` (pure twin; constants `CloudWispCurl 0.6` etc. as
`constexpr double`, regex-pinned like test_cloud_billow.py 28-40), where
`bWisp = CloudWispApplies(CloudWispSwitch == TEXT("on"), State.Shape)`;
`BottomOcclusion = CloudBellyOcclusion(bWisp, CloudBottomOcclusionFor(bBillow, AtmRow[AtmCloudBottomOcclusion]))` at 2134.

render.json `look_applied.world_beauty.clouds.layers[]` gains: `cloud_wisp` (the
switch word), `cloud_wisp_applied`, `wisp_amount`, `curl_strength`,
`edge_thin_power`, `top_detail_gain`, `boundary_erosion`, `belly_occlusion_cap`,
`owner_aliases` = `{"Coverage": "Coverage", "Density": "ExtinctionPerM",
"DetailStrength": "DetailErosion", "NoiseScale": "ShapeScaleKm", "Wind": "WindOffsetM"}`
(Python `CLOUD_OWNER_ALIASES`, pinned: every target is in
`WORLD_CLOUD_SCALARS | WORLD_CLOUD_VECTORS`), `scattering` (the seven
CLOUD_SCATTERING values + `source: "scripts/ue_create_materials.py CLOUD_SCATTERING, baked at build; graph generation 8"`),
`material_graph_generation` (the asset's `FlightSimGraphGeneration` metadata tag
under `#if WITH_EDITORONLY_DATA`, else `"unread"`), `calibration: "UNCALIBRATED"`.

### 3.8 Generation stamps
`WORLD_GRAPH_GENERATIONS["M_FlightSimCloudLayers"]` "7" -> "8" (3692, with a
comment "Sky step 1: ..."); `WORLD_GENERATIONS["M_FlightSimCloudLayers"]` "9" ->
"10" (3740). Distant unchanged.

### 3.9 Tests
- test_world_beauty.py 395: the five inputs with OFF defaults; the HLSL header lists them.
- test_cloud_tiers.py 392 (compiled body == Python twin; switch-off equality), 458
  (constants in HLSL), 480 (generations `>=`), 550 (no march sample added).
- test_cloud_billow.py 96: the two exact-string stamps -> `>= 8` / `>= 10`, reason
  in the docstring; 77 untouched.
- test_distant_clouds.py 206 holds by construction; 115 (`DistantLook` C++ == Python): both sides updated.
- New tests/test_cloud_wisp.py: C++ constexpr == Python; HLSL consts == Python;
  `TOP_DETAIL_MEAN` re-measured (pattern test_cloud_tiers.py 206); `cloud_flow`
  mean ~0 and bounded; wisp off -> `cloud_density` unchanged for 200 random
  samples (float64 equality); wisp on keeps the support (density > 0 iff off > 0);
  drawn cover within the 10 % band with the wisp on (pattern 684); edge thinning
  monotone; `cloud_belly_occlusion` only lowers and only when applies;
  `cloud_wisp_applies` false for overcast/nimbostratus; the bridge parses,
  refuses and records the switch (pattern test_cloud_billow.py 105);
  `create_storm_cell`'s `storm_scattering(` call unchanged and `CLOUD_SCATTERING`
  only in `create_world_cloud_layers`; test 348 (UNCALIBRATED labels) still passes.

### 3.10 Risks, how held, measurement
- iGPU stall / TDR: cost rises only on in-cloud near view samples; the sky-light
  real-time capture renders the clouds too (r87's 887a0006 was there) at the
  capped reflection sample counts: the same +40 % per in-cloud sample. Held by
  the `[branch]` gates, the far LOD, no new shadow-sample cost, and the A/B
  switch. Kill criterion: `887a0006` in the log -> `-look-cloud-wisp=off`, filed.
- Measure byte-identity: FlightSimSky.cpp untouched (test 329).
- Labels: a Volume material writes no depth/stencil; nothing new is an actor.
- Compile: a Custom-node error makes `VerifyCloudMaterials` (FlightSimWeather.cpp
  1244+) REFUSE the render by name, not crash; the g++ harness catches syntax, not
  HLSL-only semantics. UNMEASURED until the material builds on Windows via the
  round's prep step (`scripts/ue_create_materials.py`).
- UNMEASURED: every value above; whether 0.6 cells of flow reads as wisps or
  smear; whether 1.6 lets the rim glow or hollows the cloud; the in-cloud cost.
- Windows: `.\scripts\visual_fix_round.ps1 -Round 101 -Scenes 3 -Switches "-cloud-type=cumulus -look-cloud-wisp=off" -CompareWith 98`
  (after the step 8 rounds), wall seconds per row in ROUND.json.

## 4. Step 2: the beauty host reads the plan's cloud fields

Commit: `Sky step 2: beauty host reads the plan's cloud fields; -cloud-type=; shadowed plan layer recorded`.

- **FlightSimSky.h 76-78 / FlightSimSky.cpp Load (116-160)**: `FFlightSimSkyPlan`
  gains `FString CloudType` (""), `double CloudCoverage = -1`, `CloudDensity = 1.0`,
  `CloudDetail = 1.0`, `CloudCirrusCoverage = 0.0`, `FString CloudCoverageSource`,
  `int64 CloudSeed = 0`; parsed AFTER the mandatory reads with
  `TryGetStringField/TryGetNumberField` (a v1 plan without them loads).
  `SkySupportedVersion` stays 1. `FFlightSimSky::Build` (240-404) is untouched:
  measure renders are byte-identical.
- **FlightSimClouds.h 100-103 / commandlet 3137**: `Build(..., const FFlightSimSkyPlan* SkyPlan, ...)`;
  the commandlet passes `bPhysicalSky ? &SkyPlan : nullptr` (local at 2530).
  `ApplyClouds` (h 154-156) takes the same pointer; stored as `SkyPlanRef` beside
  `bPhysicalSkyPlan`.
- **Switch `-cloud-type=clear|cumulus|stratocumulus|altocumulus|cirrus|overcast`**
  (Build 1104-1137 pattern; empty = not given; another word refuses
  `world_beauty.clouds: -cloud-type=%s is not one of ...`). It overrides the
  plan's `cloud_type` and sets the cover to the row's `default_cover` unless the
  card states one. The existing `-cloud-cover=` probe (commandlet 2866) builds a
  CARD layer, the wrong component for this; the doc says so.
- **Precedence** (pure `LayerSource(...)` in FlightSimWorldPure; Python
  `layer_source(switch, card_cover, plan_type, plan_cover, preset, fair) -> (cover, shape, source)`):
  `-cloud-type=` > `card.look.clouds[0]` (dataset truth, never overridden by data)
  > sky.json `clouds` (ERA5 or recorded default) > the shape's `default_cover`.
  `CloudShapeForPlanType(word)`: cumulus/stratocumulus/altocumulus/overcast ->
  their rows (altocumulus is step 5's new row); nimbostratus -> its row; cirrus ->
  no volumetric layer (step 6 draws the sheet); clear -> no layer. Recorded as
  `cover_basis`, `cloud_type_applied`, `cloud_type_source` in {"switch", "card", "plan", "shape default"}.
- **`bStatedLayer`** (2079) becomes true for a plan-stated cover or the switch, so
  the round-95 lowering (`CumulusLayerLowered` 2087) and thinning (2080) apply
  only to the DEFAULT case as now; the c641a8c4 exception is kept and recorded
  (`lowered_below_cruise`). A PLAN cumulus above 4 km is still drawn as the fair
  slab below a cruise; the camera stays clear.
- **"clear" / "cirrus" on the plan's component**: `Cloud->SetVisibility(false)` in
  beauty only (the measure path never sees ApplyClouds); recorded under
  `clouds.hidden_layers[] {component, reason: "plan cloud_type clear: no volumetric layer (beauty only)"}`.
- **Component classification (1954-1972, §0.14)**: owner `IsA<AVolumetricCloud>()`
  -> `source: "sky plan"`; name "VolumetricCloud" on a plain actor -> `"card look.clouds"`;
  "FairCumulus" -> `"fair"`. When both plan and card components exist, mark the
  plan's `engine_stack_shadowed: true` (the card's registers later,
  FlightSimVisualScene.cpp 865 vs 759), exclude it from `CloudLayers` (so
  `KeepAircraftClearOfClouds` 2266+, the occlusion rows and `ApplyDistantClouds`
  2375-2383 read only the drawn slab), call `SetVisibleInRealTimeSkyCaptures(false)`
  on it, but still re-material it (D16).
- **Material parameters (2102-2131)**: `ExtinctionPerM = row x clamp(plan.density, 0.5, 1.5)`,
  `DetailErosion = saturate(row x plan.detail)` when the plan states them (else 1.0
  multipliers); recorded `plan_density_scale`, `plan_detail_scale`. Wind unchanged.
- **Record** per layer: `source`, `engine_stack_shadowed`, `plan_cloud_type`,
  `plan_coverage`, `plan_density`, `plan_detail`, `cover_source`,
  `cloud_type_applied`, `cloud_type_source`, `seed_matches_card`; top level
  `clouds.plan: {cloud_type, coverage, density, detail, cirrus_coverage, coverage_source, seed}`
  or `clouds.plan_fields_source: "none: v1 plan or no -sky= plan"`,
  `exposure_sees_plan_clouds: false`; commandlet `scene.sky` (9850-9875) gains
  `cloud_type`, `coverage`, `coverage_source`, `density`, `detail`.
- Missing-material note (1944-1953), `VerifyCloudMaterials`, FlightSimSky.cpp's
  `CloudsNote` refusal: unchanged.
- Python twins: `world_beauty.PLAN_CLOUD_TYPES`, `cloud_shape_for_plan_type(word)`,
  `layer_source(...)`, `CLOUD_TYPE_SWITCH = "-cloud-type"`.
- Tests: test_world_beauty.py 170's generated main gains `CloudShapeForPlanType`
  over every word and `LayerSource` over a table; 640 (cover law) extended with the
  plan precedence; new tests/test_cloud_type.py (pattern test_cloud_billow.py):
  switch parse pins, unknown word refuses, precedence table, `Build` called with
  the plan pointer only at the `bBeauty` site (string pin at commandlet 3137),
  FlightSimSky.cpp `Build` body (358-394) contains none of the new identifiers
  and still loads `m_SimpleVolumetricCloud_Inst`, `Load` uses `TryGet` for the new
  keys, `SetVisibleInRealTimeSkyCaptures(false)` only on the shadowed branch;
  brace balance; check_bridge_api (no new engine symbol except
  `SetVisibleInRealTimeSkyCaptures`: add a `sky_check`).
- Risks: iGPU none (never more components marched); byte-identity held by the
  untouched measure `Build`; labels held (volumetric, no depth); determinism held
  (the seed is the card's, the mismatch is recorded, never silently resolved).
- UNMEASURED: that the engine draws the card's component and not the plan's (the
  stack rule is read in source); that the host applies the plan's type. Windows:
  the step 8 rounds; read `look_applied.world_beauty.clouds.layers[0].cloud_type_source`.

**Built (sky step 2, 2026-11-14): where the code proved this section wrong, or the
step narrowed it.** Commit `Sky step 2: beauty host reads the plan's cloud fields; -cloud-type=; shadowed plan layer recorded`.
- `bStatedLayer` stays `CardCover >= 0.0 || bFair`. The plan's bottom_km/thickness_km
  are its placement law (>= 1 km above the flight), not weather heights; keying the
  round-95 lowering on the plan's type would put a plan cumulus back at 11-14 km over
  a cruise. The lowering and the thinning apply to a plan-typed layer as to the default
  one; `lowered_below_cruise` records it. The sentence "becomes true for a plan-stated
  cover or the switch" is withdrawn; the sentence after it stands.
- The commandlet's `scene.sky` was NOT extended: it is written for every physical-sky
  render, and VISUAL_FIDELITY_PLAN.md §8's "a measure render.json gains no field"
  wins. Everything is under `look_applied.world_beauty.clouds.plan` (beauty only).
- The rain and storm presets stand above the plan's type (`LayerSource`): a plan
  `cumulus` never thins a rain world's deck to fair cumulus; the switch still can.
  This section was silent.
- `-cloud-type=` with a card layer keeps the card's cover under the switch's shape
  (as written); with a plan coverage and no card the switch uses its row's default
  cover (the switch overrides the plan whole: a clean A/B).
- `ApplyClouds`'s signature is unchanged; it reads the plan through the member
  `SkyPlanRef` that `Build` sets from its new `const FFlightSimSkyPlan* SkyPlan`
  parameter (before `Error`). The LayerCoverAndShape pin (test_world_beauty.py 640)
  stands; `LayerSource` runs right after it on the same cover and shape.
- Altocumulus draws the stratocumulus row until step 5's row exists
  (`CloudShapeForPlanType` case 3), recorded `cloud_type_applied: stratocumulus`.
  `PlanCloudTypeName` already carries all seven words; step 5 changes case 3 only.
- `cirrus_coverage` is parsed and recorded, not drawn (step 6).
- test_world_beauty.py 170's generated main was not extended; the new laws are
  compiled and compared in tests/test_cloud_type.py's own g++ test (same harness),
  so this step's diff stays out of that test.
- Verified in the 5.7 source, not witnessed (UNMEASURED): `SetVisibleInRealTimeSkyCaptures`
  exists on UVolumetricCloudComponent (header line 205; `sky_check` added);
  `SetVisibility(false)` hides a layer because `GetVisibleFlag()` gates the proxy in
  `CreateRenderState_Concurrent`; FScene keeps the LAST pushed proxy (`AddVolumetricCloud`).
- The switch is registered in core/config_surface.py's `render_switches` description
  and the `world_beauty.clouds` catalogue hint names the seven words (one refusal key,
  as for -look-cloud-tiers / -look-cloud-billow, which have no entries of their own).

## 5. Step 3: march and sky-LUT quality, tiered, recorded, restored

Commit: `Sky step 3: tiered march and sky-LUT cvars, recorded and restored; -cloud-march=`.

Current: per layer `SetViewSampleCountScale/SetShadowViewSampleCountScale/
SetShadowTracingDistance/SetTracingMaxDistance` (2136-2139) from `CloudMarch`
(238-246): discrete {6, 6, 50 km} = 576/60; constrained {2, 1, 80 km} = 192/10.
Engine defaults (UE 5.7 source): `r.VolumetricCloud.ViewRaySampleMaxCount` 768,
`.Shadow.ViewRaySampleMaxCount` 80, `.DistanceToSampleMaxCount` 15 km (samples
= max x saturate(in-layer path / 15 km): a 1.2 km slab seen obliquely gets
10-33 % of the row), `.SampleMinCount` 2, `.ShadowMap.RaySampleMaxCount` 128,
`.ShadowMap.MaxResolution` 2048, `.SkyAO.TraceSampleCount` 10, `.SkyAO.MaxResolution` 2048;
`r.SkyAtmosphere.AerialPerspectiveLUT.Depth` 96 km, `.DepthResolution` 16,
`.Width` 32, `.TransmittanceLUT.SampleCount` 10, `.MultiScatteringLUT.SampleCount` 15,
`.DistanceToSampleCountMax` 150 km. The render path already sets
`SampleCountMax` 256, per-slice 8, FastSkyLUT 0, FastApplyOnOpaque 0, VRT Mode 3
(commandlet 4111-4127): read those back, never set them here.

- **Pure table** `CloudCvar(int March, int Field)` beside `CloudMarch`, fields in
  order: `view_ray_sample_max, shadow_ray_sample_max, distance_to_sample_max_km,
  sample_min_count, shadowmap_ray_sample_max, shadowmap_max_resolution,
  skyao_trace_samples, ap_lut_depth_km, ap_lut_depth_resolution, ap_lut_width,
  transmittance_lut_samples, multiscatter_lut_samples, sky_distance_to_sample_max_km`;
  `CloudCvarName(Field)` holds the exact strings. Rows (UNCALIBRATED):
  **discrete** {768, 80, 8, 2, 256, 4096, 20, 160, 32, 32, 20, 30, 100};
  **constrained** = the engine defaults exactly {768, 80, 15, 2, 128, 2048, 10, 96, 16, 32, 10, 15, 150}
  (set and recorded: a no-op; the pinned history stands);
  **probe** = the constrained row with `distance_to_sample_max_km` 8.
- **`CloudMarch`** discrete row {6, 6, 50} -> {8, 8, 50} (768/80 = the caps; test
  784's cap asserts hold); constrained row untouched (tests 930 and jitter 100);
  new **probe** row {3.0, 2.0, 80.0} = 288 view / 20 shadow samples, UNCALIBRATED,
  reachable ONLY by the switch. `MarchCount` 2 -> 3 on both sides.
- **Switch** `-cloud-march=auto|constrained|discrete|probe` (auto = GPU class, as
  today; another word refuses). `discrete` or `probe` on the iGPU is the owner's
  measurement, one scene, one still; the Windows TDR / `887a0006` is pass-fail.
- **Apply** in `ApplyClouds` after the `FogAll` block (2061): `for F:
  SetWorldCvar(CloudCvarName(F), CloudCvar(March, F), CvarRow)`; record
  `march.tier`, `march.switch`, `march.cvars {name: [before, read_back]}`,
  `march.cvars_skipped[]`, `march.cvars_basis`, `march.render_path_read_back`
  (the commandlet-owned cvars, read only). The basis texts naming 15 km (2549,
  world_beauty.py 893-904) now name `r.VolumetricCloud.DistanceToSampleMaxCount`.
  `SetReflectionViewSampleCountScale` stays the sky-capture caps' (commandlet
  5872-5890): one owner.
- Python twins: `CLOUD_CVAR_FIELDS`, `CLOUD_CVARS = {"discrete", "integrated", "probe"}`,
  `CLOUD_CVAR_NAMES`, `ENGINE_CLOUD_CVAR_DEFAULTS`, `CLOUD_MARCH["probe"]`,
  `CLOUD_MARCH_SWITCH`.
- check_bridge_api.sh: `rp_cvar` lines for every new name (`ViewRaySampleMaxCount`,
  `Shadow.ViewRaySampleMaxCount`, `DistanceToSampleMaxCount`, `SampleMinCount`,
  `ShadowMap.RaySampleMaxCount`, `ShadowMap.MaxResolution`, `SkyAO.TraceSampleCount`,
  `SkyAO.MaxResolution`, `AerialPerspectiveLUT.Depth/.DepthResolution/.Width`,
  `TransmittanceLUT.SampleCount`, `MultiScatteringLUT.SampleCount`,
  `DistanceToSampleCountMax`).
- Tests: test_world_beauty.py 784 gains the cvar table and the probe row (same
  generated-main pattern; the constrained row == `ENGINE_CLOUD_CVAR_DEFAULTS`);
  930 untouched except a docstring line (the cvar row is a no-op on the
  constrained class); jitter 100 untouched (the commandlet's set is unchanged);
  new `test_sky_step3_cvars_have_one_owner` (every `SetWorldCvar` name is in
  `CloudCvarName` or the FogAll literal, and in no other lane's table: reads
  FlightSimSunShafts.cpp 92-110, FlightSimHeroLighting.cpp 601-609, the
  commandlet's `SetBeautyCvar` calls); every touched cvar restored (string pin on
  `RestoreCvars`); the switch registered and its refusal catalogued.
- Risks: iGPU stall held by the constrained row being the engine's own values
  and the march row unchanged; byte-identity (beauty only); labels (process-wide
  cvars, but no label capture draws cloud/fog/atmosphere); determinism none.
- UNMEASURED: every discrete value (no discrete GPU in the project: recorded as
  "set for a discrete GPU, never rendered"); the probe on the iGPU. Windows:
  `.\scripts\visual_fix_round.ps1 -Round 102 -Scenes 3 -Switches "-cloud-type=cumulus -cloud-march=probe" -CompareWith 98`,
  then the log for `887a0006` and ROUND.json's wall seconds against round 98's.

**Built (sky step 3, 2026-11-15): where the code proved this section wrong, or the
step narrowed it.** Commit `Sky step 3: tiered march and sky-LUT cvars, recorded and restored; -cloud-march=`.
- The constrained cvar row is NOT the engine's registration defaults. The render
  commandlet applies the Cinematic scalability group (BaseScalability.ini
  `[EffectsQuality@Cine]`) AFTER this lane, and that group sets
  `r.SkyAtmosphere.AerialPerspectiveLUT.DepthResolution` 32,
  `TransmittanceLUT.SampleCount` 30 and `MultiScatteringLUT.SampleCount` 20 on every
  beauty render; a code-priority set (what `SetWorldCvar` does) cannot be lowered by a
  scalability-priority one, so the design's 16 / 10 / 15 would have LOWERED the
  laptop's sky. The constrained row repeats the Cinematic values where the group
  speaks and the registration default elsewhere (`world_beauty.cloud_cvars_in_force`);
  that, not "engine defaults", is the no-op. The probe row follows it (8 km).
- The discrete row moved for the same reason: `{768, 80, 8, 2, 256, 4096, 20, 160, 64, 64, 40, 30, 100}`
  (AP depth resolution 64 and width 64, transmittance 40, multi-scatter 30: each above
  the Cinematic value; the design's transmittance 20 was below it).
- `march.render_path_read_back` is `march.render_path_owned` (names only). The render
  path runs after this lane, so a read-back here would show pre-Cinematic values;
  `render_settings.beauty_path.read_back` already holds the finals.
- `march.tier` and `march.switch` sit beside the existing `march.path` (kept: the
  verifier-facing key).
- The "iGPU raise" lands as the probe tier (D4): the default constrained render is a
  recorded no-op, pinned; the raise reaches the laptop only by `-cloud-march=probe`.
- test_world_beauty.py 784 gained the third row (its docstring says why); 930 and
  jitter 100 are untouched and pass. The cvar table's own pins are in
  tests/test_sky_step3_cvars.py (compiled with g++), with the engine-source check
  skipped where no UE 5.7 source exists.
- First Windows round is a NO-OP check, round 100 against 95 (identical beyond the
  still's noise), before the probe (101) and the design's 102; VISUAL_FIDELITY_PLAN.md §8.
- Repair round 1: the first record claimed the sky-light capture was "not this table's".
  False for the probe (and discrete) tier: `r.VolumetricCloud.DistanceToSampleMaxCount`
  sets `InvDistanceToSampleCountMax` once, for every trace (the engine's
  `bIsReflectionRendering` block re-derives only the two sample caps), so the probe's
  8 km lengthens the capture's march too (up to 15/8 x per short in-layer path, under
  the commandlet's reflection caps) in r87's `887a0006` submission. No value changed:
  the record strings, the C++ and Python comments and VISUAL_FIDELITY_PLAN now say so,
  and `test_sky_step3_cvars.py` plus an `rp_check` pin the engine block. Round 101
  remains the measurement.

## 6. Step 4: atmosphere and horizon

Commit: `Sky step 4: horizon haze fields, -sky-multi-scatter=, per-preset sun bloom`.
Files: `ApplyAtmosphere` (1710-1909), `AtmosphereDefault` rows (105-122) +
`AtmosphereFieldName` (88-97) + enum (98-103), world_beauty.py `ATMOSPHERE_FIELDS`
66-80 / `ATMOSPHERE` 121-147 / `validate_overrides` 1445-1452, `SkyMultiScattering`
364-372 / `SKY_MULTI_SCATTERING` 739, FlightSimHeroLighting.cpp 76-78 + 283-294,
core/scene/hero_lighting.py.

- **Multi-scattering switch** `-sky-multi-scatter=auto|on|off` (D5). The code at
  1743 becomes `if (bMultiScatter)` where `bMultiScatter = (word == on) || (word == auto && !CloudConstrainedGpu())`,
  written so the literal `if (!CloudConstrainedGpu())` still precedes
  `SetMultiScatteringFactor(` within 200 chars (test 930 holds; a helper
  `SkyMultiScatterApplies(word, constrained)` in the pure block is its twin).
  Record `multi_scattering_switch`, `multi_scattering_applied`,
  `multi_scattering_gate_basis` (§0.9's three facts and "UNMEASURED on the iGPU;
  measured by round 97"), keep `multi_scattering_factor_before/after`. Rows
  clear 1.25, hazy 1.15 stay. The FogAll constrained-off stays as is.
- **Four new ATMOSPHERE fields** (13 -> 17, appended so existing indices hold):
  `fog_height_falloff_scale` (x the scene's 0.0002, FlightSimVisualScene.cpp 730),
  `fog_start_distance_m` (scene 1500), `fog_max_opacity` (scene 0.92),
  `ap_rayleigh_fade_km` (the cloud component's
  `AerialPespectiveRayleighScatteringFadeDistance`, UPROPERTY without a setter:
  assign + `MarkRenderStateDirty()`; 0 = engine path unchanged). Clear row
  UNCALIBRATED: {2.0, 800, 0.96, 60}; hazy {1.5, 500, 0.98, 40};
  overcast/rain/storm {1.0, 1500, 0.92, 0} = today. Applied in the fog loop
  (1807-1839) with before/after per fog row and on each drawn layer in
  ApplyClouds. `DustHaze.Apply` (1377) and `RainHazeFog` (1472) read the fog live
  after and compose. The Koschmieder single count (`MieSplit` 1764) is untouched:
  a redistribution in height, not more extinction (test 907 still passes).
- **Aerial perspective**: `aerial_perspective_scale` stays 1.0 (D8). Record
  `atmosphere.aerial_perspective {view_distance_scale, ap_lut_depth_km,
  ap_lut_depth_resolution, basis}` (the LUT values from step 3's row).
- **Zenith paling, off by default**: field `sky_pale_gain` 1.0 everywhere; when != 1
  `SetSkyLuminanceFactor(FLinearColor(g, g, g))` (sky dome only), recorded as a
  non-physical look value. 18th field; overridable by `-world-beauty-overrides=`.
- **Sun bloom** (D10): the three `HeroLightingShaftBloom*` constants become
  per-preset rows `HeroLightingShaftBloom[Preset] = {scale, threshold, max}`:
  clear {0.25, 4.0, 60}, hazy {0.3, 4.0, 60}, overcast/rain/storm {0 (off), 6, 50}
  (UNCALIBRATED; today 0.12/6/50, off when overcast), `Preset` read from
  `Scene.LookApplied.world_beauty.preset` (Build 1336). Twin
  `hero_lighting.SHAFT_BLOOM = {...}` pinned by a source test. The lens bloom row
  in beauty_look.py (BM_SOG 0.25, threshold -1) is unchanged. Label-safe: label
  captures have Bloom off (test_render_json_contract.py 277). The sun-shafts
  record text says "inert: hero lighting owns it" for its bloom row.
- Record: `atmosphere.horizon_haze {fog_height_falloff_scale, fog_start_distance_m,
  fog_max_opacity, ap_rayleigh_fade_km, basis, calibration: "UNCALIBRATED"}`.
- Tests: test 170 re-pins the widened rows automatically (iterates
  `ATMOSPHERE_FIELDS`); 907 (haze counted once) passes; 930 keeps its literals and
  gains the switch assert; a source test that the fog-shape fields appear only in
  FlightSimClouds.cpp (beauty); hero_lighting twin test; test_render_json_contract.py
  259 (the world look leaves a plan's transmittance alone, literal at 1889-1892) survives.
- Risks: iGPU: fog shape and the uniform cost nothing per pixel; the only risk is
  the lifted multi-scatter, which is OFF by default and switchable; byte-identity:
  ApplyAtmosphere and hero lighting are beauty-only; exposure: unchanged code;
  labels: radiance only.
- UNMEASURED: the pale band, the ridge layering, the sun glow, and whether 1.25
  multi-scatter renders on the iGPU. Windows: round 97 below (the probe), then
  `.\scripts\visual_fix_round.ps1 -Round 103 -Scenes 1,3,11 -Switches "-cloud-type=cumulus -sky-multi-scatter=off" -CompareWith 98`.

## 7. Step 5: the plan's cloud fields and the ERA5 cover

Commit: `Sky step 5: sky plan cloud fields, altocumulus row, ERA5 cloud cover`.
Files: core/sky/plan.py `plan_sky` 373-475 (clouds block 398-400, 458-465), new
core/sky/clouds.py (pure laws), core/environment/era5.py (new fetch),
webapp/runs.py (`write_sky_plan` 2955-2996; the flow 4300-4310),
core/scene/world_beauty.py (altocumulus row), FlightSimClouds.cpp (the 5th row).

- **Signature**: `plan_sky(..., *, cloud_cover: Optional[Dict] = None, seed: Optional[int] = None)`
  keyword-only, so every positional caller (tests/test_sky.py 155-180,
  test_exposure_owner.py 27/156, test_round3 105, test_presets_colour.py 59/132,
  experiments/sky_check.py 139, webapp/runs.py 2988) is unchanged. `enabled`,
  `bottom_km`, `thickness_km`, `basis` are computed EXACTLY as today (measure
  byte-identity).
- **New keys in `"clouds"`**: `cloud_type` (one of `PLAN_CLOUD_TYPES`),
  `coverage` 0..1, `density` 1.0 (multiplier, D2), `detail` 1.0, `cirrus_coverage`
  0..1 (always carried: step 6 draws it beside any type), `coverage_source`
  (`"ERA5 reanalysis via Open-Meteo archive, <date>T<hour>Z, cloud_cover_low/mid/high"`
  or `"default (no weather_date): CLOUDS[<type>].default_cover"` or
  `"default (fetch failed: <error>)"`), `cover_inputs` `{low, mid, high, total}`
  fractions or null, `cloud_type_basis` (the thresholds that fired), `seed`,
  `seed_source` ("spec.seed" / "default"), `quality_tier_requested: "auto"`,
  `basis` = today's string + "; type/coverage/density/detail are BEAUTY ONLY
  inputs (FFlightSimWorldBeauty); the measure host reads bottom_km/thickness_km only".
- **Laws** (core/sky/clouds.py, thresholds UNCALIBRATED, each a world_beauty twin
  where the host needs it): `cloud_type_from_cover(low, mid, high, storm)`:
  storm -> nimbostratus (cover 0.98); `max(low, mid) >= CLOUD_OVERCAST_COVER 0.85`
  -> overcast (that max); `low >= STRATOCUMULUS_MIN_COVER 0.5` -> stratocumulus (low);
  `mid >= 0.3 and mid > low` -> altocumulus (mid); `low >= FAIR_CLOUD_SHADOW_MIN_COVER 0.1`
  -> cumulus (low); `high >= 0.2` -> cirrus (high); else clear (0).
  `cirrus_coverage = high`. Without `cloud_cover`: `cloud_type = "cumulus"`
  ("nimbostratus" for storm), `coverage = CLOUDS[type]["default_cover"]` (0.35 /
  0.98), density/detail 1.0, so the default beauty frame is round 95's by construction.
- **Altocumulus row** (world_beauty.CLOUDS + C++ `CloudDefault`, `CloudName`,
  `CloudMaxThicknessM`, `SelectCloud`, `LoadOverrides` `Section("clouds", CloudCount, ...)` 1035):
  `dict(extinction_per_m=0.03, shape_scale_km=1.2, detail_scale_km=0.12, detail_erosion=0.4,
  bottom_softness=0.15, top_rounding=0.5, coverage_contrast=1.1, default_cover=0.5)`,
  `CLOUD_MAX_THICKNESS_M["altocumulus"] = 900`, in `CLOUD_WISP_SHAPES`. `CloudCount`
  4 -> 5; `CLOUD_PRESETS` gains it; test 170 / 629 / 640 regenerated (`range(5)`),
  reason in the docstrings. `select_cloud` is NOT taught altocumulus (it is chosen
  by the plan's mid-level law, never by thickness).
- **ERA5**: `era5.fetch_reanalysis_cloud_cover(lat, lon, date_iso, hour_utc, timeout_s=15)`
  on `ARCHIVE_URL` with `hourly=cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high`,
  returns fractions + a `source` string ("ERA5 reanalysis via Open-Meteo archive
  API, hourly cloud fraction of a ~25 km grid cell; ERA5T values for recent months
  may be revised"), raises `WeatherUnavailableError`. The hour is the plan
  INSTANT's UTC hour (`resolve_instant`, already computed at write_sky_plan 2978);
  the wind keeps `HOUR_UTC = 12` (both docstrings state the difference). No effect
  on the wind edit (physics).
- **Webapp**: `historical_cloud_cover(spec) -> Optional[Dict]` in runs.py, called
  right before `write_sky_plan` (4307) only when `weather_date != "none"`, the
  scene is a real place (`pick_scene(spec)["key"] not in SYNTHESISED_SCENE_KEYS`,
  as 3156) and no sampled/stated cover exists (`_sampled_policy_values(spec).get("cloud_cover")`
  wins, recorded "sampled cover wins; ERA5 clouds not applied"). On
  `WeatherUnavailableError` it returns None and the plan records the DEFAULT with
  the error text: clouds are VISUAL ONLY, so unlike the wind this never refuses
  the run. `write_sky_plan` passes `seed=int(spec.seed.value)` and the cover dict.
  `run.conditions["sky"]` (4318-4325) appends `clouds <type> <cover> (<source>)`.
  The web app's weather stays ON by default; nothing becomes opt-in.
- **SKY_VERSION**: unchanged (§0.15); the pin test is added.
- Tests: tests/test_sky.py: (a) determinism with `cloud_cover` and `seed` (ascii
  JSON a == b); (b) byte-identity: for the four existing call signatures the
  sub-dict `{enabled, bottom_km, thickness_km}` equals literals pinned now;
  (c) ranges; (d) the type law table including every threshold boundary;
  (e) defaults recorded as defaults and equal to `CLOUDS[type]["default_cover"]`;
  (f) storm -> nimbostratus with today's 1.2 km / 6 km slab; (g)
  `SKY_VERSION == int(re.search(r"SkySupportedVersion = (\d+)", FlightSimSky.cpp))`;
  (h) `relight` leaves the clouds block byte-identical; (i) the exposure dict is
  byte-identical with and without `cloud_cover`. tests/test_webapp.py: stub the
  fetch like the wind stub (1373-1395): applied and recorded; sampled cover wins
  (`must_not_fetch`, like 1623-1650); a synthesised ridge never fetches;
  unavailable -> default recorded, run not refused; the seed is carried.
- Risks: determinism held (fetched values are copied into sky.json; the plan is
  pure on them); card.json unchanged (no new card key; digests stand); sky.json
  additive; the `weather_date` drape/sun coupling untouched.
- UNMEASURED: nothing here draws by itself; that the Open-Meteo values for a spec
  reproduce a photo's sky is never claimed.

**Built (sky step 5, 2026-11-15): where the code proved this section wrong, or the
step narrowed it.** Commit `Sky step 5: sky plan cloud fields, altocumulus row, ERA5 cloud cover`.
- The laws live in `core/sky/clouds.py` as written; `plan_sky` takes
  `cloud_cover`, `cloud_cover_note` and `seed` keyword-only, so every positional caller
  stands. The clouds block also carries `volumetric_row`, `march_tier`,
  `march_tier_basis` and `fields_basis` (the brief asks for the step 3 cvar set's name
  in the block); `quality_tier_requested` is spelled `march_tier` to match the
  `-cloud-march=` words.
- The seed: the spec's when the web app passes it (`seed_source: "spec.seed"`), else
  DERIVED from the inputs plan_sky already has (CRC-32 of instant, place, altitude),
  never a bare default, so a plan written outside the web app is still seeded.
- The web app's `historical_cloud_cover(spec, hour_utc)` is called INSIDE
  `write_sky_plan` (one caller, one place), not before it in the flow; it returns
  `(cover, reason)` and the reason lands in `coverage_source` as
  `default (<reason>): CLOUDS[<type>].default_cover`. The sampled-cover rule reads
  `spec.randomization.cloud_cover.source == "sampled"` (there is no
  `_sampled_policy_values`; the design named a helper that does not exist).
- The provider's null guard: the archive serves nulls for dates it has not assimilated;
  a null hour raises `WeatherUnavailableError` by name rather than returning a 0 % sky.
- The altocumulus row is APPENDED (index 4), not inserted after stratocumulus, so every
  existing row index, the override files and the step 3 pins stand; `CloudCount` 4 -> 5
  on both sides as designed. test_world_beauty.py's capped-top test runs over all five
  rows (docstring says why); test_cloud_type.py's two altocumulus pins moved to the new
  row (docstrings say why).
- The march tier reaches the host: `FFlightSimSkyPlan::CloudMarchTier` (TryGet),
  `CloudMarchWordInForce` in the pure block, weighed in `Build` after the switch's
  refusal and before the tables; `CloudMarchSwitch` becomes the word in force so the
  step 3 lines test_sky_step3_cvars.py pins are untouched; `switch_given` and
  `word_source` record the rest. The plan writes "auto": a no-op by construction.
- Not done here: `scene.sky` in the commandlet is still not extended (step 2's rule: a
  measure render.json gains no field); test_webapp.py's tests stub the fetch at
  `core.environment.era5.fetch_reanalysis_cloud_cover` like the wind's.
- Repair round 1 (two refutations, both reproduced): the first cut called
  `historical_cloud_cover(spec, instant.utc.hour)` and fetched `weather_date` at that
  hour. `weather_date` is the spec's LOCAL date; the plan's instant is UTC and crosses the
  day boundary for every local evening west of Greenwich (20:00 at New York on 2024-01-15
  = 2024-01-16T00:56Z: the fetch asked for 2024-01-15 00Z, 24 h early, and
  `coverage_source` misstated the moment) and every local morning east of it (02:00 at
  Tokyo = 2024-01-14T16:41Z). Now `write_sky_plan` passes the instant (`instant.utc`) and
  the scene dict it already holds; `historical_cloud_cover(spec, instant_utc, scene=...)`
  asks the archive for the instant's UTC date and hour, and the provider dict's `date`
  (hence `coverage_source`'s `...T00Z` stamp) names the UTC day fetched. Pinned by three
  day-rolling cases in test_webapp.py and a mirror in test_sky_clouds.py; the docstrings
  (era5.py, runs.py, clouds.py) and §8 say "UTC date and hour". The second refutation:
  rounds 104/105 use `-cloud-type=`, which stands above the plan, so they never exercised
  this path; §8 now gives the web app's exact `/compile` + `/run` lines for a dated prompt
  and the sky.json / render.json keys to read (no dated scene was added to
  run_test_scenarios.py: it would move the pinned scene count and a swarm lane's
  "scene 16" wording). Still UNMEASURED: nothing rendered.
- UNMEASURED: everything; VISUAL_FIDELITY_PLAN.md §8 "Sky step 5" names rounds 104 and 105
  for the row and the web-app lines for the plan path.

## 8. Step 6: the cirrus sheet (beauty only)

Commit: `Sky step 6: beauty-only cirrus sheet`.

- **Material** `M_FlightSimCirrus`, `create_world_cirrus()` copied from
  `create_world_distant_clouds` (ue_create_materials.py 4225-4274): UNLIT,
  TRANSLUCENT, two-sided, `use_translucency_vertex_fog` + `compute_fog_per_pixel`
  (AP and fog fade it), `apply_cloud_fogging` True (the volumetric layer below
  attenuates it), no custom depth, no velocity; inputs
  `WORLD_CIRRUS_INPUTS = ("WorldPos", "CameraPos", "SunDir", "SunIlluminance", "SkyLum") + WORLD_CIRRUS_SCALARS + ("SeedOffsetKm", "WindOffsetM")`;
  stamped "1" in both generation dicts.
- **Shader** assets/shaders/world/cirrus.hlsl: its own small `FCirrusNoise`
  (Pcg/Hash3/Perlin2 copied text-equal from `FWorldCloud` and pinned by a block
  test like test_distant_clouds.py 206, so the Python twin core/scene/cirrus.py
  reuses `world_beauty._perlin2`). Streaks: the km frame rotated by `StreakDirDeg`
  (the plan's high-level wind if present, else seeded) and stretched `StreakAspect`
  (8) along it; `fbm = 0.5 p2(q) + 0.3 p2(2.1 q) + 0.2 p2(4.3 q)` with the
  cross-stream axis at 1/8 the scale; coverage by the quantile cut
  `CIRRUS_FBM_MEAN/SIGMA` (measured on the replica, pinned); feathered ends
  `thick *= smoothstep(0, FeatherWidth, |p2(q_along * 0.3)|)`; opacity
  `min(CirrusMaxOpacity 0.55, thick) x fadeIn x rim` so blue reads through
  everywhere; light `L = SunIlluminance * Albedo/pi * (0.5 + 0.5 * HG(dot(V, SunDir), g 0.7)) + SkyLum * AmbientGain`.
  ~30 hashes per covered pixel, one translucent disc. Everything a parameter
  (`WORLD_CIRRUS_SCALARS == cirrus.CIRRUS_LOOK`, pinned, UNCALIBRATED).
- **Host** `FFlightSimWorldBeauty::ApplyCirrus(World, Scene, SkyPlan, Seed)` after
  `ApplyDistantClouds` (1384), modelled on it (2348-2585): a second earth-curved
  `UProceduralMeshComponent` disc (the ring builder 2430-2461 becomes a static
  helper; `CirrusRadiusKm` 400), `SetCastShadow(false)`, `SetRenderCustomDepth(false)`,
  `SetTranslucentSortPriority(-101)` (D13), `Scene.BeautyOnlyActors.Add(Actor)`
  (pattern 2499). Altitude law (pure, twin `cirrus_altitude_m(camera_m)`):
  `min(max(CIRRUS_BASE_M 10000, camera_m + CIRRUS_CLEARANCE_M 1500), 13000)` (D12);
  scene 13's 747 at 10 km gets cirrus at 11.5 km; faded over `DistantInsideRampM`
  when the camera is within it; recorded per frame `frames[].cirrus_altitude_m`.
  Coverage = the plan's `cirrus_coverage` (default 0 recorded as default); seed
  `CloudSeedOffsetKm`; `Advance` re-centres on the camera and drifts by the
  layer's drift law. Switch `-cirrus=on|off|auto` (auto = drawn when `cloud_type`
  is cirrus or `cirrus_coverage >= 0.1`; on = drawn with `CIRRUS_DEFAULT_COVER 0.4`
  when the plan says 0; off = not built). Record
  `world_beauty.cirrus {drawn, switch, altitude_m, coverage, coverage_source,
  material, labels: "BeautyOnlyActors; no depth, no custom depth; measure never builds it",
  visual_only: true, calibration: "UNCALIBRATED"}`.
- Tests: shader inputs == script == C++ sets (pattern test_distant_clouds.py 173);
  unlit/translucent/label-safe (222); `BeautyOnlyActors.Add(CirrusActor);`
  pinned (247, test_beauty_label_isolation.py 318-324 pattern); the replica's cut
  gives the stated cover; determinism; the altitude law in the pure-block test;
  the switch's refusal and registration.
- Risks: labels none (BeautyOnlyActors; no depth); TDR: one translucent disc, 6
  faces in the sky capture (`-sky-capture-beauty-only=1`, commandlet 5722-5748);
  determinism: seeded; procedural only (THIRD_PARTY_VISUAL.md untouched).
- UNMEASURED: whether the streaks read as veils; the capture cost. Windows:
  `.\scripts\visual_fix_round.ps1 -Round 104 -Scenes 3,13 -Switches "-cloud-type=cumulus -cirrus=off" -CompareWith 98`.

## 9. Step 7: tests

Commit: `Sky step 7: tests` (only the tests not already landed with their step:
the SKY_VERSION pin, the byte-identity pins, the webapp stubs, the one-owner
cvar test, the sky_compare unit test).

Tests that legitimately MOVE (reason in the docstring, never deleted):
test_cloud_billow.py 96 (two exact stamp strings -> `>=`);
test_world_beauty.py 170 / 629 / 640 (`CloudCount` 4 -> 5, altocumulus row),
395 (five wisp scalars), 454 (new `sky_check`/`rp_cvar` lines), 784 (probe row,
cvar table, discrete 8/8/50), 930 (docstring + the multi-scatter switch assert;
every pinned literal kept); test_distant_clouds.py 115 (`DistantLook` values).
Everything else is additive.

Run, targeted first:
`tests/test_sky.py tests/test_world_beauty.py tests/test_cloud_billow.py tests/test_cloud_tiers.py tests/test_cloud_wisp.py tests/test_cloud_type.py tests/test_distant_clouds.py tests/test_cloud_jitter_blue_noise.py tests/test_webapp.py -k "weather or sky" tests/test_cpp_brace_balance.py tests/test_powershell_scripts.py tests/test_beauty_label_isolation.py tests/test_ue_world_source.py tests/test_render_json_contract.py tests/test_check_bridge_api.py`,
then the full suite in the background with `-n auto`; `bash scripts/check_bridge_api.sh`
(on the Mac it lints shape; `rp_check` needs the engine source and runs on Windows).
Report real counts, including failures.

## 10. Step 8: the owner's compare

Commit: `Sky step 8: sky_compare_round.ps1, sky_compare.py, docs`.

- **`scripts/sky_compare_round.ps1 -Round <N> -Scene <S> -CompareWith <M> [-Switches "<extra>"] [-NoPush]`**
  (Windows PowerShell 5.1; tests/test_powershell_scripts.py lints it): sets
  `$env:FLIGHTSIM_SKY = "physical"` when unset and writes it into each ROUND.json
  (§0.12); runs `.\scripts\visual_fix_round.ps1 -Round N+k -Scenes <S> -Switches "-cloud-type=<w> <extra>" -CompareWith <M>`
  for k = 0..3 over clear, cumulus, stratocumulus, overcast (one still each; the
  pinned spec replays, so the camera is identical); then
  `python scripts\sky_compare.py --rounds N,N+1,N+2,N+3 --scene <S> --old <M> --out docs\visual\sky_compare\round_<N>_scene<S>`.
- **`scripts/sky_compare.py`** (numpy + PIL, pattern scripts/visual_compare.py):
  reads `docs/visual/round_<R>/<NN>_<slug>.jpg` (stem law:
  run_test_scenarios.py `collect` 348) and each round's `summary.json` run id ->
  render.json; writes `sheet.jpg` (row 1: the old frame "round M (old look)";
  row 2: the four frames, each captioned with the REQUESTED word and the APPLIED
  `look_applied.world_beauty.clouds.layers[0].cloud_type_applied` +
  `cloud_type_source`, `march.tier`, `atmosphere.multi_scattering_applied`,
  printing `MISMATCH` when requested != applied) and `compare.json` (per tile:
  visual_compare's mean_abs_change / moved_share / mean luma vs old,
  frame_metrics' blank/clipped/crushed, the march and cvar record,
  FLIGHTSIM_SKY as recorded). A missing frame is listed, never dropped. Unit test
  tests/test_sky_compare.py with synthetic frames and render.json stubs.
- **Docs**: docs/visual/sky_compare/README.md (location, the exact commands, how
  to read the sheet, "every frame is UNMEASURED until it exists"); README's
  "Physical sky" section (294) gains the clouds block schema;
  docs/VISUAL_FIDELITY_PLAN.md V6 rows (285-305, 687) and docs/WEATHER.md get the
  pointer; the `-cloud-cover=` probe note (step 2).
- **The Windows sequence** (one switch set per round, FIX_ROUND_PROTOCOL; wave-2
  numbering from r97; quote it in the PR):
  ```
  $env:FLIGHTSIM_SKY = "physical"
  # 97: the multi-scatter probe FIRST (step 4, D5). Pass = no 887a0006 in the log and a frame.
  .\scripts\visual_fix_round.ps1 -Round 97 -Scenes 3 -Switches "-cloud-type=cumulus -sky-multi-scatter=on" -CompareWith 95
  # 98-101: the owner's four frames on scene 3 (add -Switches "-sky-multi-scatter=on" if 97 passed)
  .\scripts\sky_compare_round.ps1 -Round 98 -Scene 3 -CompareWith 95
  # 102: the wisp A/B (step 1)
  .\scripts\visual_fix_round.ps1 -Round 102 -Scenes 3 -Switches "-cloud-type=cumulus -look-cloud-wisp=off" -CompareWith 99
  # 103: the march probe (step 3): watch for 887a0006, compare wall seconds with 99
  .\scripts\visual_fix_round.ps1 -Round 103 -Scenes 3 -Switches "-cloud-type=cumulus -cloud-march=probe" -CompareWith 99
  # 104: the cirrus A/B (step 6), both cameras
  .\scripts\visual_fix_round.ps1 -Round 104 -Scenes 3,13 -Switches "-cloud-type=cumulus -cirrus=off" -CompareWith 99
  # 105-108: the secondary camera
  .\scripts\sky_compare_round.ps1 -Round 105 -Scene 13 -CompareWith 95
  ```
  (Round 99 is the cumulus frame of the 98 set.) Wall seconds per row in
  ROUND.json are the only cost measurement there is.

## 11. UNMEASURED, in one place

Every look number: `CLOUD_SCATTERING`, the five wisp values, the belly occlusion
0.45, the three `DISTANT_LOOK` moves, the altocumulus row, the cirrus look, the
discrete and probe march rows and every discrete cvar (no discrete GPU in the
project), the four horizon-haze fields, the sun-bloom rows, the type-law
thresholds. Every cost: the in-cloud hash count and whether it stalls the iGPU or
the sky-light capture; multi-scattering 1.25 on the iGPU; the probe march; the
cirrus disc in the capture; render seconds per still against r95. Every
behaviour read in source but not witnessed: that the card's component is the one
the engine draws when both exist; that the material compiles in the Windows
editor; that `FLIGHTSIM_SKY=physical` is set on the laptop's shell. Every visual
outcome: wisps vs smear, rim glow vs hollow cloud, grey-blue bellies, the pale
band, the ridge layering, the veils, whether the owner's five traits appear, and
whether any Open-Meteo value reproduces the photo's sky.

Measured on the Mac: the Python/C++/HLSL twins (g++), the switch-off bit
identity, the cover law, plan determinism and laws, brace balance, PowerShell
lint, label safety by source, the measure path's untouched source, the
Open-Meteo field names (probe). Nothing else is claimed.

## 12. Follow-ups not in this wave

- `ConservativeDensity` empty-space skipping via a second small Custom node (D7).
- Flipping `-sky-multi-scatter=auto` to on-everywhere once round 97 renders clean.
- A divergence-free curl (48 hashes) if the flow warp reads as smear.
- `AerialPespectiveMieScatteringStartDistance` on the cloud component (UPROPERTY,
  no setter; needs a `sky_check`) if the clouds' own aerial perspective is wanted
  beyond the LUT.
