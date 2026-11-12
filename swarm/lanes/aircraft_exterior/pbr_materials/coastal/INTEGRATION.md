# aircraft_exterior.pbr_materials.coastal -- integration

VISUAL-ONLY (beauty renders). Nothing here may reach a `-quality=measure`
render or a label. STATUS: UNMEASURED. Written and source-tested on the Mac;
no shader was compiled and no frame rendered. Nothing below is claimed to
look better until the Windows gate at the end has run.

## What the lane holds

| File | What |
|---|---|
| `bake_coastal_pbr.py` | Mac bake + the Python twin of the shader maths (`weather()`) |
| `baked/T_AcCoastal_DetailN_512.png` | tier 0 detail normal (oil-canning + orange peel), DirectX green-down |
| `baked/T_AcCoastal_Mask_512.png` | tier 0 packed linear mask: R salt film, G roughness breakup, B grime streaks along +U |
| `baked/coastal_pbr_manifest.json` | parameters, tier table, sha256s, albedo report |
| `coastal_weathering.ush` | the SM5 block (2 texture reads at tier 0) |
| `measure_gate.py` | the pixel gate, for the laptop |

Higher tiers are not shipped (size). Bake them on the Mac when the stress
ladder asks: `.venv/bin/python swarm/lanes/aircraft_exterior/pbr_materials/coastal/bake_coastal_pbr.py --tiers 1,2,3`.

## Tiers (VRAM figures are ESTIMATES: block size x 4/3 mip chain)

| Tier | Textures | Reads | Est. VRAM | Notes |
|---|---|---|---|---|
| 0 | 512 BC5 normal + 512 BC1 mask | 2 | 0.5 MB | UV0 x DetailTiling; pass `DetailFadeEndCm = 0` (no fade maths) |
| 1 | 1024 + 1024 BC1 | 2 | 2.0 MB | distance fade of the detail normal on |
| 2 | 2048 BC5 + 2048 BC7 | 4 | 10.7 MB | each map read at two scales to hide tiling (not written yet: tier 0 block called twice) |
| 3 | 4096 BC5 + 2048 BC7 | 6 | 26.7 MB | object-space two-plane projection, 8x aniso (not written yet) |

Tier 0 is designed to be the stable one (two reads, no loops, no derivatives,
no extra pass, 0.1 % of the 491 MB pool). It is not known to be stable: that
is for the laptop to say.

## Proposed changes to shared files (integrator; this lane edited none)

1. **`scripts/aircraft_look.py`** -- add to `CLASS_SCALARS["paint"]` and
   `["bare_metal"]` the scalars in `COASTAL_SCALARS` (bake_coastal_pbr.py),
   with **`CoastalWeathering` defaulting to 0.0** so every existing scene is
   unchanged, and bump `LOOK_GENERATION`. Add vector `SaltAlbedo`
   = (1.0, 1.0, 1.0, 1.0) (database row "Salt") to `CLASS_VECTORS`, and
   `"Salt"` to `materials_used` in `assets/looks/physically_based/PIN.json`.
2. **`scripts/ue_aircraft_master_materials.py`** -- in `M_AircraftPaint` and
   the bare-metal master: two `TextureSampleParameter2D` nodes
   (`CoastalDetailN`, sampler type Normal; `CoastalMask`, sampler type Linear
   Color / Masks, default the engine white texture) and the
   `coastal_weathering.ush` block between the existing base colour /
   roughness results and the material outputs. Blend its `NormalTS` with the
   panel-line normal (BlendAngleCorrectedNormals, or add XY and renormalise
   at tier 0). The block must come AFTER the existing `AlbedoMax` clamp input
   and its own clamp keeps `AlbedoMin..AlbedoMax`.
   If the master's `RoughnessBreakup` / grime terms are currently computed
   with per-pixel Noise nodes, mask G / B can replace them at tier 0 (cheaper
   on the iGPU). I did not read the master's graph closely enough to say
   they are; check before swapping.
3. **`scripts/ue_import_aircraft.py`** (or wherever textures are imported) --
   import `baked/*.png` to `/Game/FlightSim/Aircraft/Coastal/`:
   DetailN as `TC_Normalmap`, sRGB off, **Flip Green Channel OFF** (already
   DirectX); Mask as `TC_Masks` (tier 0-1: `TC_Default` with sRGB off gives
   BC1), sRGB off; both tiling/wrap, LOD group World, mips on.
4. **Scenario wiring** -- the coastal scenario card sets
   `CoastalWeathering = 1` and the `CLASS_OVERRIDES` (paint / bare_metal
   `GrimeAmount 0.2`, `PanelDarkening 0.12`). Where that card lives is the
   integrator's call; I found no "coastal" card under `core/scenario`.
5. **Fallback if clear coat is too heavy on the iGPU** (untested idea, not
   tier 0 by default): Default Lit paint with
   `Roughness = lerp(Roughness, CoatRoughness, ClearCoat)`.

## The dark-aircraft guard (what is checked on the Mac, at source level)

`tests/test_swarm_aircraft_exterior_pbr_materials_coastal.py` checks, on the
baked mask and the Python twin: albedo always within the calibrated range
[0.023 (database tyre rubber), 0.9 (`AlbedoMax`)]; no texel loses more than
15 % of its base albedo (actual worst case 10 %); mean albedo of an 18 % grey
base moves by a factor 1.029 (band 0.97-1.08), a 0.05 dark livery by 1.152
(salt lightens it; never darker on average), a 0.9 white by 0.990. These are
parameter-space numbers, not pixels.

## Proposed look parameters for the coastal scenario (UNCALIBRATED proposals)

No shared coastal parameter file existed when this lane ran, so these are
proposals for the scenario's other lanes to converge on, not agreed values:
sun elevation 12 deg, colour temperature 4300 K, sea-haze visibility 15 km,
exposure left to the existing auto-exposure (0 EV bias), water albedo 0.06.
The material side only depends on: low sun (hence `RoughnessMin 0.08`) and
salt air (hence the film).

## The Windows gate (UNMEASURED; cannot run until change 6 below is merged)

**Change 6 (integrator), the switch the gate needs.** `CoastalWeathering`
exists today only in this lane's `.ush` and its Python twin; nothing under
`ue/` or `scripts/` knows the name, so no command can currently render the
reference and the candidate differently. Add, with changes 1-2:

- `scripts/aircraft_look.py`: read `FLIGHTSIM_COASTAL_WEATHERING` (`0` or
  `1`; unset = `0`) and use it as the `CoastalWeathering` scalar of the
  `paint` and `bare_metal` classes, any other value refused by name.
- The value must reach the material instances of THAT render. I did not
  establish whether the look instances are rebuilt per render or cached
  (`ue_aircraft_master_materials.py` has `FLIGHTSIM_REBUILD_MATERIALS`); if
  cached, the switch must also invalidate them. This is the open risk.

The one command, on the laptop, in the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File swarm\lanes\aircraft_exterior\pbr_materials\coastal\run_gate.ps1
```

`run_gate.ps1` (read it; it is short):

1. REFUSES (exit 3) if `scripts\aircraft_look.py` does not contain
   `FLIGHTSIM_COASTAL_WEATHERING`, i.e. change 6 is not merged. Today it
   refuses.
2. Sets `FLIGHTSIM_COASTAL_WEATHERING=0`, renders step `coastal_pbr_ref`
   shot `a`; sets it to `1`, renders step `coastal_pbr_t0` shot `a`. Each
   step's old `a.png` / `a_mask.png` is deleted first so a failed render
   cannot leave a stale frame to be measured.
3. Runs `measure_gate.py` on the files the contact sheet itself writes:
   `runs\visual\<step>\a.png` (the beauty frame) and
   `runs\visual\coastal_pbr_ref\a_mask.png` (the ID image). These names
   are read from `experiments/visual_contact_sheet.py` (it copies the run's
   first frame to `<shot>.png` and its label mask to `<shot>_mask.png`);
   no path is guessed or string-replaced. A missing `a_mask.png` is a
   refusal (RENDER_RUNBOOK.md section 10), not a fallback.

The statistics cover only pixels whose ID is `1`, the primary airframe
(`core/capture/labels.py`: 0 = background, 1 = airframe, terrain and other
objects their own ids). If the frame's labels list airframe components with
their own int_ids, pass them: `-Ids "1,5,6"`.

Shot `a` (chase cam, real terrain, golden hour) is the nearest existing shot
to "coastal, low sun"; pass `-Shot <key>` once the coastal card has one.

Exit codes: 0 PASS (`detail_ratio >= 1.10`, `luma_ratio` in [0.97, 1.08],
`dark_share_delta <= 0.01`, `clip_share_delta <= 0.005`); 1 FAIL; 2 REFUSED
by the measurement (too few airframe pixels, size mismatch, pixel-identical
pair); 3 REFUSED by the script (switch not merged, render failed, frame or
mask missing). A device-lost crash in step 2 is a FAIL of tier 0.

What is and is not known:

- Not known: whether the two renders will differ at all, by how much, and
  whether the thresholds are sensible. The Mac test of `measure_gate.py`
  feeds it synthetic images and proves only its arithmetic and its
  refusals. It is no evidence about real frames.
- Two renders of one scene are not identical under rain and temporal AA, so
  an unwired switch most likely reads as `detail_ratio` near 1.0 and a FAIL.
  If it FAILS, check `mean_abs_diff` and the two PNGs by eye before
  blaming the look.
- `run_gate.ps1` itself has never been executed (no PowerShell on the Mac).
