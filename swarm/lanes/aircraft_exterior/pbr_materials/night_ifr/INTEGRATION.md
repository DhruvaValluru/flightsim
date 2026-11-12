# aircraft_exterior.pbr_materials.night_ifr: integration notes

Visual-only. Written and baked on the Mac on 2026-11-12. **Nothing here has
been compiled in Unreal or rendered.** Every look number is UNCALIBRATED and
every VRAM figure is an estimate until the commands under "Pixel gate" have
run on the Windows laptop. No tier is claimed sustained.

## What the lane delivers

| File | What it is |
|---|---|
| `bake_night_pbr.py` | Offline generator (numpy + Pillow). Writes tileable ORM and normal DDS files with a hand-built mip chain, and `night_pbr.json`. |
| `baked/T_AcNight_ORM_512.dds`, `baked/night_pbr.json` | The tier 0 bake (1.4 MB). Tiers 1-3 are baked on demand: `--tiers all` takes about 8 s on the Mac. |
| `measure_gate.py` | The pixel gate's measuring half. Runs on the laptop over rendered frames. BLOCKED today: see "Pixel gate". |
| `PROVENANCE.json` | Sources, licences, sha256 of every generated file. Nothing was downloaded. |
| `tests/test_swarm_aircraft_exterior_pbr_materials_night_ifr.py` | Code-level tests (bake arithmetic, file format, gate logic on synthetic images and a fake run folder). |

## Why this, for a night approach on an integrated GPU

1. **Cost.** The paint and bare-metal masters compute panel lines, wear and
   grime per pixel (`panel_lines.hlsl`, `aircraft_wear.hlsl`). Tier 0
   replaces that with two samples of one 512 BC1 texture.
2. **Glint stability.** A night frame is a dark airframe under a few small,
   very bright lamps. Each roughness mip is widened by the variance of the
   normals it averages (Toksvig 2005; clamp of Tokuyoshi and Kaplanyan
   2019), so groove highlights should not crawl when the aircraft is small
   on screen. This costs nothing at render time. Whether it is visible at
   1280 wide is unmeasured.
3. **No dark aircraft, by construction.** Occlusion goes to the AO pin only;
   the baked grime can darken base colour to 0.65 of itself at most; the
   final base colour is clamped to linear [0.023, 0.9] (sRGB 42 to 243).

## Texture contract

Period: 360 cm of surface per tile (3 panels of 120 cm along the airflow,
4 of 90 cm across), so the baked grid lands on the procedural one.

- `T_AcNight_ORM_<size>`: R = AO (>= 0.55), G = roughness baked about 0.5
  (mean 0.53 because grime is matter than paint), B = albedo gain in
  [0.65, 1]. Import: sRGB **off**, compression Masks (BC1),
  `MipGenSettings = LeaveExistingMips`, address Wrap, LOD group World.
- `T_AcNight_N_<size>` (tiers 1-3): tangent-space normal, +Z out, X along the
  airflow. Import: Normalmap (BC5), `LeaveExistingMips`, Wrap.

The DDS files are uncompressed BGRA8 with every mip present, so the engine's
own compressor does the BC step once at import on the laptop (CPU, cached in
the DDC). If the importer rebuilds the mips instead of keeping them, the
roughness widening is lost: check the imported asset reports the same mip
count as `night_pbr.json` and that mip 4 of G is brighter than a box filter
of mip 0 would be.

## Tiers (estimates)

| Tier | Textures | Sampling | Shading | Est. VRAM |
|---|---|---|---|---|
| 0 | ORM 512 | 2 planar projections | Default Lit, no normal map, no procedural wear | 0.17 MB |
| 1 | ORM + N 1024 | 2 planar projections | Default Lit | 2.0 MB |
| 2 | ORM + N 2048 (rivets baked) | triplanar | master's Clear Coat model, type's own ClearCoat value | 8.0 MB |
| 3 | ORM + N 4096 | triplanar | as 2, plus the existing procedural edge wear and soot | 32 MB |

Texture memory is small at every tier against the 491 MB pool; what the
tiers really step is instruction count and shader permutations. Tier 0's
point is one cheap Default Lit permutation.

## Proposed changes to shared files (for the integrator; not applied)

### 1. `scripts/ue_create_materials.py`: import the textures and add a night branch

Import with the existing `import_texture(source, name, srgb=False,
normal_map=..., flat=...)`, then set `mip_gen_settings` to
`TMGS_LEAVE_EXISTING_MIPS` on both. Destination
`/Game/FlightSim/Aircraft/Night/T_AcNight_ORM`, `.../T_AcNight_N`.

In `M_AircraftPaint` and `M_AircraftBareMetal`, add a static switch
`NightBaked` (default false, so every existing render compiles the same
graph) whose true side is:

```hlsl
// Custom node "NightBakedSurface". Inputs: LocalPos (cm, mesh local),
// LocalN (unit, mesh local), Orm (Texture2D), OrmSampler, InvPeriod (1/360).
// X is the airflow in both projections, so streaks run aft on every face.
float wTop = saturate(abs(LocalN.z) * 4.0 - 1.5);          // 1 on wings and spine
float2 uvTop  = LocalPos.xy * InvPeriod;
float2 uvSide = LocalPos.xz * InvPeriod;
float3 orm = lerp(Orm.Sample(OrmSampler, uvSide).rgb,
                  Orm.Sample(OrmSampler, uvTop).rgb, wTop);
return orm;   // r = AO, g = roughness, b = albedo gain
```

Outputs of the true side:

- BaseColor = `clamp(Base * lerp(1, orm.b, GrimeAmount / 0.2), 0.023, AlbedoMax)`
  where `Base` is what the master feeds BaseColor today before wear and
  grime, and 0.2 is the paint master's default GrimeAmount.
- Roughness = `saturate(orm.g + (Roughness - 0.5))`
- AmbientOcclusion = `lerp(1, orm.r, PanelAoAmount)`
- Normal: tier 0 the vertex normal; tiers 1-3 the same projection blend of
  `T_AcNight_N` (triplanar, whiteout blend, at tiers 2-3), scaled by
  `PanelNormalAmount`.
- Metallic and Specular unchanged. Tiers 0-1: shading model Default Lit.

The procedural panel, wear and grime nodes sit only on the false side, so
with `NightBaked` on they are not compiled in (tier 3 keeps wear and soot).

### 2. `scripts/ue_aircraft_materials.py create_look_instances`

Also create `MI_<slot>_night` for every paint and bare_metal slot (parent
the same master, `NightBaked` = true, textures from the chosen tier), the
way `MI_<slot>_thin` is made for glass.

### 3. `FlightSimAircraftFX.cpp`

Add `-aircraft-night-pbr=off|0|1|2|3` (default `off` until the gate has
passed; then `0` when the card's sun elevation is at or below -6 deg,
`core/scene/night.py NIGHT_SUN_ELEVATION_DEG`). When not `off` and the
render is `-quality=beauty`, apply `MI_<slot>_night` in place of
`MI_<slot>`. Record `aircraft_look.night_pbr = {tier, orm_sha256}` in
`render.json`. A missing night instance refuses by name
(`aircraft_look.night_pbr_missing`), never falls back silently. A
`-quality=measure` render is untouched, as with the rest of the look.

Add `scripts/check_bridge_api.sh` lines for any engine symbol the C++ uses.

### 4. `scripts/run_test_scenarios.py SCENARIOS`: a night scene

The round list has 15 scenes and none is at night, so there is nothing for
a night gate to render. Append one row; it becomes scene 16:

```python
    ("a320 at night, tower view (night approach materials gate)",
     "tower view of the a320 at 300 m at night with a 250 mm lens for 6 seconds", {}),
```

Checked on the Mac, code level only: the offline (regex) compiler reads this
prompt as `environment.time_of_day = night` and the spec validates with no
violation. Not checked: what the LLM compiler makes of it, whether the
frame shows runway lighting, and whether the aircraft is lit enough to
measure (the gate answers VOID under mean luma 2). Any test that pins the
list's length changes with the row.

## Pixel gate (UNMEASURED, and BLOCKED until changes 1-4 are in)

**This gate cannot be run today.** Two of its inputs do not exist in the
repository yet, and this lane may not add them:

- `-aircraft-night-pbr` is only a proposal (change 3). No C++, Python or
  PowerShell source knows it. Passed today it would be ignored, and both
  rounds would render the same aircraft.
- scene 16 is only a proposal (change 4).

`tests/test_swarm_aircraft_exterior_pbr_materials_night_ifr.py` asserts both
are still missing, so it fails on the day they land and this section has to
be rewritten then.

Once changes 1-4 are integrated and built, on the Windows laptop:

```powershell
$env:FLIGHTSIM_CAPTURE_PASSES = "albedo"
# reference: today's procedural materials
.\scripts\visual_fix_round.ps1 -Round 90 -Scenes 16 -NoPush -Switches "-aircraft-night-pbr=off"
# candidate: tier 0
.\scripts\visual_fix_round.ps1 -Round 91 -Scenes 16 -NoPush -Switches "-aircraft-night-pbr=0"
Remove-Item Env:FLIGHTSIM_CAPTURE_PASSES
.\.venv\Scripts\python.exe swarm\lanes\aircraft_exterior\pbr_materials\night_ifr\measure_gate.py --reference-round 90 --candidate-round 91 --scene 16 --out runs\swarm\night_pbr_gate.json
```

Rounds 90 and 91 are free numbers picked here; use any two unused ones.

Where the gate's inputs come from. All of this was read in the source on
the Mac; none of it was observed in a run:

- **ID image.** `visual_fix_round.ps1` has no labels option and needs none:
  the web app's camera pass adds `-labels` to every run itself
  (`webapp/capture.py render_passes`), and the engine then writes
  `frame_NNNN_mask.png` beside the frame. Do not put `-labels` in
  `-Switches`. The image is 8-bit grey, one `int_id` per pixel, the primary
  airframe always 1 (`core/capture/labels.py`); the gate takes id 1.
- **Albedo pass.** `FLIGHTSIM_CAPTURE_PASSES=albedo` (the `capture_passes`
  setting's developer override) makes each camera write
  `frame_NNNN_albedo.png`, 16-bit linear base colour. Without it the gate
  still runs and says the albedo was not measured.
- **Paths.** `--reference-round/--candidate-round/--scene` reads
  `docs\visual\round_<N>\summary.json` for the scene's `run_id` and takes
  `runs\webapp\<run_id>\frames\<first camera>\frame_NNNN.png`,
  `_mask.png`, `_albedo.png` and `render.json`.

Exit 0 is PASS, 1 FAIL, 2 VOID (a VOID is not a pass). VOID when: a file is
missing; the two rounds' pinned spec hashes differ; the candidate's
`render.json` has no `night_pbr` record or the reference's has one; the
aircraft is pixel-identical in both frames; fewer than 400 aircraft pixels;
both aircraft under mean luma 2.

Clauses:

- `median_delta >= 0.0`: median luma (0-255) of the aircraft pixels,
  candidate minus reference. The aircraft did not get darker.
- `candidate_mean_luma >= 2.0` (Gate 6's night floor).
- crushed share (aircraft pixels at luma <= 1) did not rise.
- `albedo_changed_outside_fraction <= 0.001`: aircraft pixels whose base
  colour differs between the two albedo passes (the ones the night branch
  touched) and lies outside linear [0.023, 0.9]. Glass, tyres, lights and
  markings are the same in both renders, so they are not counted; their
  share is reported as `albedo_outside_fraction_whole_aircraft` and not
  gated.

Known limits of the gate as written: the zero tolerance on `median_delta`
assumes the two renders are deterministic apart from the material, which is
unmeasured; the luma is taken from the raw frame, not the beauty-post one;
components of the airframe with their own `int_id` are left out unless
passed with `--aircraft-id`.

`background_mean_abs_change` is reported, not gated: it should be near 0
because only the airframe's material changed.

Also record from the same two runs, since the gate does not cover them:
device-lost count, frame time, and peak process memory, per tier, climbing
0 to 3 only while the previous tier finished clean.

## Not done, and why

- No per-airframe UV bake (soot cones, object-space weathering): the
  candidates for that were not fetched or licence-checked here.
- The bake's groove at 512 is 1.05 cm wide, three times the true 0.35 cm;
  depth is scaled so the wall slope holds. Whether that reads as a panel
  line or a stripe at tier 0 is for the frame to say.
- Glass and rubber are untouched; they have no procedural cost to remove.
