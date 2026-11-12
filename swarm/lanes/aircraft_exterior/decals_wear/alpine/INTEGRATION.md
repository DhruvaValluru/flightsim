# aircraft_exterior.decals_wear.alpine: integration

VISUAL ONLY. Shading only: no vertex moves, no opacity, so labels, masks and
depth are unchanged and `render.json` needs no `pixel_moving_effects` entry.

Status: everything render-side is UNMEASURED. The Mac ran the generator and
the code-level test only. Nothing here has been compiled by Unreal or drawn.

## What is in this lane

| File | Role |
| --- | --- |
| `bake_decals_wear.py` | Mac generator: mask, normal, soot LUT, stencil atlas, `bake_manifest.json` with sha256 and the `wear` constants |
| `alpine_wear.ush` | SM5 functions the master material's custom nodes call |
| `tiers.json` | tier table (estimates) and the scenario's shared look parameters |
| `pixel_gate.py` | Windows gate: detail gain and dark-aircraft guard on the albedo pass |
| `run_gate.cmd` | Windows wrapper: refuses if the switch is not integrated, renders off and tier, runs the gate |
| `PROVENANCE.json` | nothing fetched; candidates considered and why not |

Bake: `.venv/bin/python swarm/lanes/aircraft_exterior/decals_wear/alpine/bake_decals_wear.py --tier 0`
(writes `out/tier0/`, git-ignored).

## Proposed changes to shared files (not made here)

1. **Asset import** (`scripts/ue_create_materials.py` or a sibling): import
   `out/tier<N>/T_AlpineWear_*.png` to `/Game/FlightSim/Wear/`.
   Mask: sRGB off, `TC_Masks` forced to BC1 (`CompressionNoAlpha`), wrap.
   Normal: `TC_Normalmap` (BC5), wrap. Soot and Decals: `TC_Grayscale`/BC4,
   clamp. All with full mips, `NeverStream` off, LOD group `Vehicle`.
   Unreal compresses on import; the Mac does not ship BC blocks.

2. **Master material** (the airframe paint/metal masters the wet layer
   already edits): add static switch `AlpineWearTier` (-1 = off, 0..3) and a
   custom node including `alpine_wear.ush`. Order: master base colour ->
   `AlpineWearBaseColor` -> the wet layer's `lerp(albedo, albedo^2, ...)`.
   Wear is a property of the paint; wetness goes on top of it. Inputs:
   object-space position (cm) and normal, as the wet rivulets use. Scalars
   and vectors: every key of `PARAMS` in `bake_decals_wear.py`, same names,
   defaults from there.

3. **Look manifest**: copy `bake_manifest.json["wear"]` into each look
   manifest as group `wear` with its UNCALIBRATED stamp, as `wet` is.

4. **Switch** (does not exist yet: `FLIGHTSIM_AIRCRAFT_WEAR` is read nowhere
   in the repo). One vocabulary, five values: `off`, `tier0`, `tier1`,
   `tier2`, `tier3`. Anything else, including a value with a trailing space,
   refuses by name. Default `off` until the gate below has passed on the
   laptop; this lane does not claim tier 0 should be the default.
   - `core/render/flags.py`: read the variable where the render flags are
     built and emit `-aircraft-wear=<value>`.
   - Commandlet: map the value to the `AlpineWearTier` static switch
     (`off` = -1) and write the value it actually applied to `render.json`
     as `"aircraft_wear": "<value>"` (beside the other look values). If the
     master has no wear node or the textures are missing, write `"off"`.
   - `pixel_gate.py` reads that key from both runs and exits 3 (not
     measured) unless the reference states `off` and the candidate states
     the tier asked for. This is what stops a missing switch from reading as
     a wear failure.

5. **Frost**: `FrostAmount` stays 0 unless the card has an icing schedule
   (`core/scenario/card.py`, `card.icing_schedule`); then set it per step to
   the schedule's eta. Without that hook the frost code path is dead, which
   is the intended default: no icing conditions, no rime.

6. **Anchors (tier >= 1)**: soot and stencils need per-airframe object-space
   anchors that this lane cannot know: exhaust exit position, lateral axis
   and plume length (cm); per stencil a box centre, two axes, size (cm) and
   atlas row (0 NO STEP, 1 NO PUSH, 2 LIFT HERE, 3 static-port ring). Put
   them beside the airframe's config. Until an airframe has anchors, hold it
   at tier 0. No registration mark is generated: one must come from the
   scenario, not from this lane.

7. **Snow albedo**: `core/scene/hero_lighting.py GROUND_ALBEDO_RGB` has no
   snow row; alpine falls to rock/scree 0.18. `tiers.json` proposes 0.80 for
   snow cover. This lane only uses it to cap frost brightness, but the belly
   bounce over a snowfield is that table's business.

## Dark-aircraft guard

`AlpineWearBaseColor` ends with
`max(A, Albedo * lerp(WearFloorRatio, SootFloorRatio, Dark))`, so outside the
soot plume and stencil ink the base colour never falls below 72 % of the
paint, and the result is clamped to [0.04, 0.90] unless the paint itself is
outside it. The numpy mirror, run over the baked tier-0 mask at full
placement weight, is tested to keep the tile's mean luminance at or above
90 % of the paint. That is arithmetic on the Mac, not a rendered result.

Not covered: the wet layer squares the albedo on top of this. Worn and
soaked paint together is darker than either alone; the Windows gate below
should be repeated on a rain scene before any tier becomes the default there.

## Not delivered

Panel lines, rivet rows and per-panel tone (need the mesh's UVs or a 3D
re-base onto the real airframe), registration marks, slush spray behind the
wheels, BC-compressed files, any measurement of cost or appearance.

## UNMEASURED and BLOCKED: the Windows gate

The gate cannot be run today. It needs items 1-4 above; item 4's switch is
proposed, not present. No frame has been rendered and the gate has never read
a real capture. On the laptop, from the repo root, after integration:

```
swarm\lanes\aircraft_exterior\decals_wear\alpine\run_gate.cmd <alpine spec.yaml> tier0
```

`run_gate.cmd` checks that `core\render\flags.py` reads the switch, then
renders the spec twice with `--passes albedo` (`off`, then the tier) into
`runs\alpine_wear_ref` and `runs\alpine_wear_<tier>`, then runs
`pixel_gate.py --reference ... --candidate ... --expect <tier>`. It sets the
variable as `set "FLIGHTSIM_AIRCRAFT_WEAR=off"`: the quotes keep a trailing
space out of the value.

| Exit | Meaning |
| --- | --- |
| 0 | pass |
| 1 | wear was drawn and broke a threshold: a wear failure |
| 2 | frames missing or unpaired |
| 3 | not measured: `render.json` does not state `aircraft_wear` as expected, or no albedo pixel moved in any frame |
| 4 | blocked: the switch is not in the checkout; nothing was rendered |
| 5 | a capture run failed |

Only 0 and 1 are results about the wear. Pass is every frame meeting
`detail_gain >= 1.25`, `beauty_ratio >= 0.90`, `dark_fraction <= 0.03`,
`albedo_p99 <= 0.90`, `0.002 <= changed_fraction <= 0.35`.

Still assumed, to be checked on the first real run: the beauty frame is the
albedo file name without `_albedo` (`--beauty-suffix` changes that); the two
runs are otherwise pixel-identical (same seed, no temporal noise on the
albedo pass); and the thresholds themselves, which were chosen on synthetic
frames. Device loss, frame time and real VRAM per tier are for the stress
ladder; this lane claims none.
