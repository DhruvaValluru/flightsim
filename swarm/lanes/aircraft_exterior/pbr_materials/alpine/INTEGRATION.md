# aircraft_exterior.pbr_materials.alpine: integration notes

VISUAL-ONLY. Nothing here is wired in, and nothing here has been rendered. Every
visual and cost statement is UNMEASURED until the commands at the bottom run on
the Windows laptop. Written and source-tested on the Mac.

## What the lane holds

| file | role |
|---|---|
| `alpine_pbr_look.py` | constants, tier table, shared look parameters, Python twin of the shader (stdlib only) |
| `bake_alpine_pbr.py` | the offline bake (numpy + Pillow, fixed seed, tiles exactly) |
| `shaders/alpine_detail.hlsl` | `AlpineUV`, `AlpineDetail`, `AlpineNormal` custom-node bodies, D3D11 / SM5 |
| `out/tier0/T_AlpineDetail_256.png` | the baked tier 0 texture (163 KB PNG) |
| `out/bake_manifest.json`, `out/render_tiers.json` | hashes, UE import settings, render-side description |
| `measure_gate.py` | the pixel gate (runs on the laptop) |
| `tests/test_swarm_aircraft_exterior_pbr_materials_alpine.py` | source-level checks |

Tiers 1-3 are not committed (they are deterministic): bake them on the Mac with
`.venv/bin/python swarm/lanes/aircraft_exterior/pbr_materials/alpine/bake_alpine_pbr.py --tier all`
and copy `out/` across. Do not bake on the laptop.

## Why it is shaped this way

- Round 23 (docs/visual/PROBE_LOG.md) traced the dark airframes to shading
  normals, not to the masters' colour maths. So tier 0 never touches the normal:
  one texture, one sample, Default Lit. The normal map starts at tier 1, its
  stored tilt is under 6 degrees and its z stays above 0.98.
- The albedo contract is fixed in code: the lane multiplies a base colour by no
  less than 0.792 (`MAX_DARKENING`), clamps `GrimeAmount` in the shader, keeps
  paint inside 0.03-0.90 linear, and frost can only brighten.
- Wear, decals, rivets and soot are other lanes' subjects (decals_wear, the
  existing exhaust soot). The G channel here is a faint flow-aligned grime
  only; decals_wear wins where both apply.

## Proposed changes to shared files (not made)

1. `scripts/ue_aircraft_master_materials.py`, paint and bare_metal masters:
   - texture parameters `AlpineDetailMap` (default: a 1x1 texel 0.5, 0, 0, 1 so
     the layer is the identity apart from the albedo clamp) and, behind a static
     switch `AlpineNormalOn`, `AlpineNormalMap` (sampler type Linear Color, not
     Normal: the stored slopes carry a gain of 6).
   - scalars `AlbedoModAmount`, `FrostAmount`, `FrostOpacity`,
     `AlpineNormalAmount`; `GrimeAmount` and `RoughnessBreakup` already exist.
   - insert `AlpineDetail()` after the master's own AlbedoMax and before the wet
     layer graft; feed `LocalPosition` (cm) and the local vertex normal to
     `AlpineUV()`. Sample with `SampleGrad` on the picked plane's gradients.
   - tier 0 builds the paint master as Default Lit (no clear coat lobe); tiers
     1-3 keep Clear Coat. This is a second static permutation, not a parameter.
   - bump `LOOK_GENERATION`.
2. `scripts/aircraft_look.py`: a scenario overlay that applies
   `alpine_pbr_look.ALPINE_SCALARS` on top of `CLASS_SCALARS` when the card's
   region is alpine, written into `look_manifest.json`; a new host word
   `-aircraft-alpine-pbr=off|tier0|tier1|tier2|tier3`, default `off` until the
   gate passes on the laptop, and a probe word `noalpine` for bisecting.
3. `ue/.../FlightSimAircraftFX.cpp` `ApplyMaterials`: set the two texture
   parameters and the static tier on the look instances, beauty only. A
   `-quality=measure` or `-labels` render must build none of it.
4. `scripts/ue_create_materials.py` (or the import step it calls): import the
   PNGs with the settings in `out/bake_manifest.json` `ue_import` (sRGB off;
   TC_Masks / TC_Normalmap; Wrap).
5. Lighting lane, not a file change here: the sky light's lower hemisphere must
   carry the snow bounce (`ground_albedo` 0.80). With no dynamic GI on this
   machine that term is the whole underside of the airframe; a black lower
   hemisphere would reproduce the dark aircraft whatever the material does.

## Tiers (ESTIMATES; none is claimed sustained)

| tier | maps | samples | shading | est. texture memory |
|---|---|---|---|---|
| 0 | 256 detail | 1 | Default Lit, mesh normal | 0.08 MB |
| 1 | 512 detail + normal | 2 | Clear Coat | 0.67 MB |
| 2 | 1024 detail + normal | 4 (side/top blend) | Clear Coat | 2.67 MB |
| 3 | 2048 detail + normal | 4 | Clear Coat + `r.ClearCoatNormal 1` | 10.67 MB |

Basis: 8 bits per pixel block compression times 4/3 for mips. Shader cost,
frame time and stability are unknown.

## UNMEASURED, and the Windows commands that would measure it

Prerequisite: an integrator has made changes 1-4. Then, in PowerShell from the
repo root (`$py = ".\.venv\Scripts\python.exe"`):

1. Render the same alpine card twice, labelled, beauty, same seed. The card is
   the repo's existing "A-4 over the matterhorn" scenario
   (`scripts/run_test_scenarios.py`); the runs go to
   `runs\swarm\alpine_pbr\flat` (host words `-aircraft-materials=on
   -aircraft-probe=flat`) and `runs\swarm\alpine_pbr\tier0` (host words
   `-aircraft-materials=on -aircraft-alpine-pbr=tier0`). The second host word
   does not exist until change 2 lands, so no exact render line can be given
   honestly today.
2. Gate:
   `& $py swarm\lanes\aircraft_exterior\pbr_materials\alpine\measure_gate.py --reference runs\swarm\alpine_pbr\flat\frames --candidate runs\swarm\alpine_pbr\tier0\frames --out runs\swarm\alpine_pbr\gate_tier0.json`
   Pass: on every frame, airframe-mask mean luma ratio in 0.85-1.15, share of
   mask pixels under 24/255 no more than the reference's + 0.02, Laplacian
   variance ratio at least 1.10.
3. Repeat step 1-2 per tier for the stress ladder; a device loss at a tier is
   the finding for that tier.

Not measured by anything here: whether the frost reads as rime or as noise,
whether the projection switch shows a seam on the fuselage shoulder, BC5
banding of the oil-canning in reflections, import time on the laptop, and
every look number (all UNCALIBRATED).
