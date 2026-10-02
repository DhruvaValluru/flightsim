# Phase 2 brainstorm — building it to the 2026 bar

*A working document, not a plan of record. Written against the Windows
Phase 1 branch (`master` at `e73aee8`, "Windows deploy + Win64 UE host;
Camera Phase 1") and the Phase 2 Implementation Plan ("Annotation,
Randomization and the Non-Technical Path"). The brief for this document
was: for every work package, what is the best technology in the world
today, what would it take to bring this simulator to that standard, and
where the plan repeats a Phase 1 item, treat the repetition as a verdict
that the current implementation is not good enough.*

*Date: 2026-09-24. Where a version number or a licence term is cited it
was checked by web search on that date; the sources are listed in the
final section. Everything about the codebase was read from the branch.*

---

## 0. The thesis in one page

**The plan is right about ordering and wrong about ambition.** Its
ordering argument — correct labels before pretty pixels — is the one
thing this repository has always got right, and nothing below weakens it.
But the plan's "what already exists" table describes code that is **not
on this branch**, its render path is a 2021-era offscreen capture that
cannot produce a mask without aliasing, and its world is a vertex-coloured
procedural mesh with a decade-old 10 m satellite drape and GPL-licensed
FlightGear meshes. A dataset produced from that world would be correctly
labelled pictures of something that does not look like the real sky.
To "represent the technology of now" Phase 2 has to do both jobs at
once: make the labels provably right *and* rebuild the picture-making
half on the engine features that exist in 2026.

The way to do both without the second eating the first is to split the
work into two lanes that share one contract:

* **Lane 1 — Truth.** Identity, masks, boxes, depth, visibility,
  verification, export, campaigns, the agent, the interface (plan
  packages A–I). Every artefact here is checked by an independent
  Python reimplementation and refused by name when wrong. This lane
  never depends on how pretty the frame is.
* **Lane 2 — Look.** Terrain, imagery, land cover, vegetation, sky,
  clouds, weather, water, airframes, liveries, lighting, lens and
  sensor. This lane may only ship a change that leaves Lane 1's checks
  green, and every change is measured from pixels the way Gate 6 is.

The shared contract is the **per-frame ground-truth bundle**: for every
captured frame, the engine emits the beauty image *and* an object-ID
image, a metric depth image, and per-object visibility fractions, all
from the same camera pose the manifest records. Lane 2 can change
anything about the beauty image; it may not change the ID and depth
images except through geometry, and Lane 1 grades those images
independently. That is the same "the thing that produces a number may
not be the thing that verifies it" rule the repository already lives by,
applied to pixels.

What the 2026 bar looks like, concretely:

| Aspect | The bar (who sets it) | This branch today |
|---|---|---|
| Ground-truth passes | Per-object ID, depth, normals, motion vectors, occlusion ratio, tight/loose 2-D boxes, 3-D boxes, all from the renderer's own buffers and written as EXR/PNG per frame (NVIDIA Omniverse Replicator; Unreal Movie Render Graph render layers) | One LDR RGBA8 `SceneCapture2D`, no label passes |
| World | Streamed photogrammetry or 3-D tiles, Nanite landscape, land-cover-driven materials, PCG vegetation (MSFS 2024; Cesium for Unreal; UE 5.6+) | Procedural mesh with a calibrated vertex palette or a 2016 10 m Sentinel-2 drape |
| Sky and weather | Physically based sky, volumetric cloud layers driven by real cloud data, precipitation, wet surfaces, cloud shadows (MSFS 2024 live weather; UE Sky Atmosphere + Volumetric Cloud; Ultra Dynamic Sky) | Sky Atmosphere, one sun, exponential height fog, no clouds |
| Airframes | Licence-clean high-poly PBR models with Substrate materials and swappable liveries (Fab / commercial digital twins) | FlightGear `.ac` meshes, GPL-2.0, flat colours |
| Lighting | Lumen global illumination, virtual shadow maps, MegaLights (production-ready in UE 5.8) | Dynamic cascaded shadow maps, no GI |
| Camera | Physically based exposure, lens distortion, sensor noise, motion blur, DLSS/TSR for the beauty pass and *no* AA for label passes | Manual exposure bias, no lens model, no sensor model |
| Randomization | Typed randomizer graphs over every scene parameter, with seeds recorded per frame and the realised distribution reported (Replicator; Kubric; Infinigen) | Nothing on this branch; the plan's block lives elsewhere |
| Export | COCO, YOLO, VOC, KITTI, WebDataset, Parquet/HF with a dataset card, round-tripped through the format's own reader | Nothing on this branch |
| Non-technical path | One prompt, clarifying questions, plan preview, live progress, download | A review table that speaks the spec's vocabulary |

The rest of this document works through how to get there, package by
package, with what is honest about the starting point first.

---

## 1. What the Windows Phase 1 branch actually contains

This is the inventory the plan's "What already exists, honestly" table
should have been checked against. It matters because several of the
plan's assumptions do not hold on this branch.

### 1.1 The plan's Phase 10 code is not here

The plan says instance masks, 16-bit depth, occlusion, keypoints, 2-D and
3-D boxes, COCO/KITTI/WebDataset export, a batch runner with a ledger,
a randomization block and a seeded sensor post-pass are "written and
rendering" with some checks failing. **None of that exists on `master`
or on this branch.** A search across every `.py`, `.cpp`, `.h`, `.html`
and `.md` for `coco`, `kitti`, `webdataset`, `instance_mask`,
`mask_containment`, `depth_range`, `keypoints_in_box`, `label_geometry`,
`sensor_files`, `ledger` and `livery` finds only unrelated hits (the
JSBSim headers, the interactive-mode HUD, a "ledger" of substeps). The
only remote branches are `master` and this one. So either the students'
work sits on a branch or fork that was never pushed here, or the plan
was written against a different tree. Either way, **the first act of
Phase 2 is to locate that code, diff it against this branch, and decide
whether to merge it or to rebuild each piece to the standard below.**
This document assumes the honest case — that each piece is rebuilt on
this branch to the 2026 bar — and notes where the students' draft, if it
turns up, could shorten the path.

What *is* here, and is the real head start:

| Capability | Where | State |
|---|---|---|
| Provenanced typed spec, `SPEC_VERSION` 6, sources `user > inferred > model > derived > default`, `set()`/`plan()` front door, canonical digest | `core/scenario/spec.py`, `core/scenario/fields.py` | Solid; this is the spine everything below hangs on |
| Cameras as spec elements, deterministic pose solver, capture schedules, `capture_manifest.json` with full recoverable geometry per frame | `core/scenario/camera.py`, `core/capture/` | Complete, verified, mutation-guarded |
| Independent verifier with checks that are shown to fail on corruption | `core/capture/verify.py`, `flightsim/verify.py` | Complete; the pattern Phase 2 extends |
| Named refusals on a single `Violation` surface (`camera.terrain_clearance`, `camera.scene_bounds`, `camera.hazard_intersection`, `terrain.clearance`, `ue.platform`, `aircraft.mesh`, `aircraft.mesh_import`, `ffmpeg.missing` …) | `core/scenario/validate.py`, `core/capture/validate.py`, `webapp/runs.py` | Complete; the message catalogue in package I is a layer over this |
| Seed derivation: one experiment seed, one `SeedSequence` stream per subsystem (`turbulence`, `gust`, `terrain`, `sensor_noise`, `dispersion`), JSBSim's `INT_MAX` saturation measured and avoided | `core/experiments/seeds.py` | Exactly the discipline package F needs; extend the subsystem list (the `sensor_noise` stream is declared and nothing consumes it) |
| Factorial / one-at-a-time sweeps with content-derived case ids, crash-safe JSONL append log, resume, degenerate-replicate detection | `core/experiments/sweep.py` | The batch runner package G should grow from, not replace |
| The showcase matrix: 144 clips, serial `UnrealEditor-Cmd` renders, resumable, refusals recorded | `experiments/showcase_matrix.py` | A campaign-shaped precedent, but serial and bespoke |
| Prompt → spec: deterministic parser plus an LLM tier with a strict `RESPONSE_SCHEMA` (`fields`, `notes`, `questions`, `cameras`), one round of at most three clarifying questions, an import-time assert tying the schema to the spec's field list | `core/nl/compiler.py`, `core/nl/llm_compiler.py`, `core/nl/providers.py` | The pattern package F's vocabulary and package I's questions extend |
| Web app: FastAPI, one 42 KB vanilla-JS `index.html`, 2 s polling (the telemetry WebSocket exists and the page does not use it), per-field provenance colours, camera pickers, effect report. **The app's render flow maps only camera 0 to `-camera=`/`-chase=` flags, never passes the `cameras` block into the card, never writes `capture_manifest.json`, and raises "no render pass" for `ground` and `explicit` presets** | `webapp/server.py`, `webapp/runs.py`, `webapp/static/index.html` | Working and honest, and nowhere near a product surface; the CLI and the app are already two render paths |
| Render host: UE 5.5, `FlightSimBridge` plugin, `FlightSimRender` commandlet, one `USceneCaptureComponent2D` into an `RTF_RGBA8_SRGB` render target, `SCS_FinalColorLDR`, FOV hard-coded at 55°, `ReadPixels` to PNG per frame, two warm-up captures discarded, a blank-frame check, `render.json` with per-frame telemetry and four projected `landmarks` (the only world-to-pixel projection in C++), manual exposure, fixed 120 Hz tick | `ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp` | Works, deterministic, and structurally unable to emit a clean mask |
| Visual scene: one movable directional light (intensity 8, atmosphere sun), Sky Atmosphere, Exponential Height Fog, Sky Light, 6-cascade dynamic CSM out to 20 km, no Lumen, no Nanite, no VSM, no clouds | `FlightSimVisualScene.cpp` | Gate 6's four measured clauses pass; nothing beyond them |
| Terrain: GLO-30 bakes → `UProceduralMeshComponent` **capped at 701 vertices per side, i.e. 60 m posting** in georeferenced mode, with a probe-calibrated vertex palette or the EOX Sentinel-2 cloudless **2016** drape (CC-BY-SA 4.0; later years refused as NC) via `M_TerrainImagery`; a 30 m heightfield collision grid for physics; a `core/terrain/landscape.py` Landscape exporter with the Z-scale worked out, **used only by Gate 4, never by the render path** | `FlightSimVisualScene.cpp`, `core/terrain/` | Honest scenery, not a world |
| Airframes: FlightGear `.ac` → per-part OBJ → Interchange import with Nanite forced off; c172p, A320 (GPL-2.0), B747; DHC6 and p51d refused over licensing; control surfaces animated through hinge components | `assets_pipeline/`, `scripts/ue_import_aircraft.py` | Real geometry, wrong licence family for a distributed dataset, and no PBR |
| Georeferencing: `GeoReferencing` plugin, round planet, origin at the spec ground point, projected local frame shared by every position-coupled block | `FlightSimScenarioWorld.cpp` | Correct and the reason labels can carry lat/lon later |
| Windows: vendored Win64 JSBSim build, `build_ue.ps1`, `ue_preflight.ps1`, `render_ue_scenario.ps1` with `-RenderOffScreen -AllowCommandletRendering`, one-paste deploy | `scripts/*.ps1` | Wired; **Gate 6 has not been measured on Windows**, so no render claim exists there yet |

### 1.2 The Phase 1 offset: the mechanism, from the code

The plan's blocking item is that the rendered airframe sits 25–30 m ahead
of the manifest's aircraft position. The placement code explains it.

`FlightSimScenarioWorld.cpp` places the aircraft actor so that the
JSBSim **centre of gravity** lands on the commanded geographic point:

```
Origin = TargetCentreOfGravity - Attitude.RotateVector(Movement->CGLocalPosition)
```

and the vendored plugin moves the actor the same way every tick
(`JSBSimMovementComponent.cpp`, `EngineLocation = CGWorldPosition -
CGOffsetWorld`). `CGLocalPosition` is measured from the JSBSim
**structural-frame origin** — the aircraft's datum, +X aft, inches — so
the actor origin *is* the structural datum. The plugin has a documented
knob for exactly this, `StructuralFrameOrigin` ("to manually guess the
offset between the 3D model and the internal logical model"), and the
bridge never sets it, so it stays at zero. The plugin also computes the
JSBSim visual reference point (`VRPLocalPosition`) and no bridge code
reads it.

The mesh is then attached to the actor root with no offset
(`FlightSimRenderCommandlet.cpp`, `BodyComponent->SetupAttachment(Root)`),
and the converter (`assets_pipeline/acmodel.py`) maps FlightGear's model
frame to the actor frame by negating X about the model's own origin,
applying per-part offsets but no top-level model offset and no VRP
alignment. FlightGear models are modelled about their own reference
point, not the JSBSim datum. The numbers from the pinned JSBSim files:

| Airframe | CG x-station (structural) | Where the FlightGear model origin sits |
|---|---|---|
| B747 | 1327 in = **33.7 m** | ≈ 28–30 m aft of the nose (from the hinge lines in `B747.json`: elevator 34.9 m, rudder 33.0 m, outboard aileron 12.9–17.1 m) |
| A320 | 672 in = 17.1 m | near the nose (hstab part offset 34.15 m) — roughly aligned |
| c172p | 41 in = 1.0 m | near the datum — within a metre |

So the B747 — the default airframe (`core/nl/compiler.py`) — is drawn
about 30 m forward of where the FDM's CG sits, which is what the label
records (`core/capture/poses.py` builds the aircraft track from the
telemetry's lat/lon/alt, the CG). The measured "25–30 m along its own
axis" is the 747 case. Two more consequences follow from the same
origin confusion and explain the other Phase 1 symptoms:

* **The UE preset cameras aim at the actor origin**
  (`FlightSimCameraDirector.cpp`, `Target->GetActorTransform().
  GetLocation()`), while the Python pose solver aims at the CG. On the
  747 the two aim points differ by 33.7 m. The cockpit symptom (label
  says out of frame, mask holds 434k aircraft pixels) is this, plus a
  second mismatch: Python's cockpit preset applies an unscaled
  (−6, −0.5, 1.6) m offset from the CG, C++ span-scales the shoulder
  offset with a 1.3 m floor and applies it from the actor origin.
* **The spec's intrinsics never reach the engine.** The capture's FOV is
  hard-coded at 55° (`Capture->FOVAngle = bVisual ? 55.0f : 24.0f`) and
  `focal_length_mm` is ignored even in consume-poses mode. The default
  35 mm on a 36 mm sensor is 54.4°, so the manifest's fx of 1244 px
  disagrees with the engine's ≈1229 px at 1280 px width — a 1.2 %
  scale error on every projected label, invisible on a placeholder and
  fatal for a box-vs-mask IoU gate.

The fix belongs in the asset manifest and the plugin's own knob, not in
a magic number: the converter reads the FDM's VRP and the model XML's
offsets, writes `vrp_actor_cm` and `model_origin_actor_cm` into
`mesh_manifest.json`; the bridge sets `StructuralFrameOrigin` from it
(or attaches the body at that relative location, one or the other,
stated); every camera in C++ aims at the CG the plugin already exposes;
and the capture takes its FOV from the card's focal length and sensor
width. The regression check the plan asks for (ID-mask centroid and
extent versus the projected CG and hull, per frame, stated tolerance)
then closes all three, and a mutation that shifts the attach point by
3 m or the FOV by 1° must fail it.

A thirty-minute diagnostic that settles the offset before any code
changes: spawn a 1 m emissive sphere at `TargetCentreOfGravity` and
another at the actor origin, render one frame, project both through the
manifest's camera. If the projected CG lands on the first sphere and
the mesh's nose sits near the second, the mechanism is confirmed and
the placeholder boxes (built about the origin, "tail 30 m aft") were
simply hiding it.

### 1.3 Why the current render path cannot produce a correct mask

Three structural reasons, each of which decides a design choice in
section 3:

1. **One capture, one buffer.** The commandlet reads back a single
   `SCS_FinalColorLDR` target. Everything a label needs — which object
   owns a pixel, how far away it is, whether cloud hides it — has been
   composited away by the time that buffer exists.
2. **Anti-aliasing bleeds.** Any temporal or spatial AA blends object
   edges into their background. A mask derived by colour-keying a
   beauty frame is wrong along every edge, and edges are where a
   detector learns.
3. **Fog and clouds are not occluders.** Volumetrics attenuate; they do
   not write depth. A "visibility fraction" through haze cannot come
   from a depth test; it needs a separate transmittance measure.

None of these is fixed by "adding a mask pass" to the current loop. The
label passes need their own captures, rendered with AA off and
volumetrics either disabled or measured separately, from the same pose,
in the same tick.

---

## 2. Work package A — Phase 1 corrections, and what each one teaches

Every item in A is a symptom of the same three gaps: no ground-truth
passes, a mesh frame that was never tied to the FDM frame, and checks
that ran on the wrong platform. Fix them as a set.

| Plan item | Root cause (from the code) | Fix | The check that would have caught it |
|---|---|---|---|
| Airframe 25–30 m ahead of the label | Mesh attached at the actor origin (= JSBSim structural datum); model built about its VRP (§1.2) | `vrp_actor_cm` in the mesh manifest, applied as the body's relative location; recorded in `render.json` | `mask_vs_geometry`: engine ID-mask centroid and extents vs the CG and the airframe's known length projected through the manifest, per frame, tolerance = 2 % of the projected span |
| `--render` never passes `-mesh=` | On this branch `flightsim/capture.py` has no `--render` at all (its arguments are `spec`, `--out`, `--terrain`, `--max-previews`, `--card`); rendering happens only through `webapp/runs.py:_render` or the `render_ue_scenario` scripts, and the app maps only camera 0 to flags and never writes `capture_manifest.json`. The plan's symptom belongs to the missing tree; the disease here is two render paths | One `core/render/command.py` builder (card + every camera + `-mesh=` + the label passes) shared by the CLI, the app, the campaign runner and the tests; the app's render flow writes the same `capture_manifest.json` the CLI does | A test that the CLI's and the app's argument lists are byte-identical for the same spec and both carry `-mesh=` for any airframe with a config |
| Camera intrinsics never applied; presets aim at the actor origin (§1.2) | `Capture->FOVAngle` hard-coded; `CameraDirector` aims at `GetActorTransform().GetLocation()` | FOV from the card's focal length and sensor width; aim at the CG the plugin exposes; one cockpit offset rule shared by Python and C++ (the Python one, consumed verbatim) | `render.json` records the applied FOV and aim point; verify compares them to the manifest to 0.1° and 0.1 m |
| `proximity` trigger implemented but refused | `core/capture/schedule.py` has it, `TRIGGER_KINDS` omits it | Add it to the vocabulary or delete the code | The examples test |
| LLM system prompt still says "three keys" | `core/nl/llm_compiler.py` prompt text predates the `cameras` key | Generate that sentence from the schema | Import-time assert, like the field list |
| Manifest records the mesh sha256 even when the placeholder drew | The commandlet echoes the manifest's hash; nothing records what was drawn | `render.json` gains `drawn: {kind: mesh|placeholder, asset_sha256, triangle_count}` written from the loaded `UStaticMesh`, and the Python manifest copies *that* | Verify refuses a run whose `drawn.kind != mesh` unless the spec says `placeholder_ok` |
| Cockpit preset looks from outside and below | Same offset as row 1 | Same fix | Same check, plus the existing "aimed camera must contain the aircraft" verifier clause with the ID mask as the evidence |
| `pull back` trips `pose_matches_spec` (172.1 m vs 166 m) | The move word's documented distance and the tolerance were written independently | Decide the contract: the move word is the contract, the tolerance is derived from it (5 % of the commanded distance, minimum 2 m) | The example spec that uses `pull back` is in the suite |
| Preflight false alarm (`vswhere -latest` without `-products *`) | Build Tools installs are not "products" to vswhere by default | `-products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64` | A preflight unit test with a recorded `vswhere` transcript from a Build-Tools-only machine |
| `cameras_mountain_refusal.yaml` does not refuse as documented | Needs `--synth-terrain`, stated only in a comment | Put the terrain in the spec (`terrain: control_ridge`), never in a flag | `tests/test_camera_cli.py` runs every `examples/*.yaml` and asserts the header's stated outcome |
| 3000 m over 413 m terrain refuses at −89.5 m AGL | Two projected frames disagree: the clearance scan samples the raster in one CRS and the track in another, or the "altitude" compared is AGL against MSL | Reproduce with `experiments/agl_parity.py`-style probe; the fix is whichever frame conversion is wrong, then a unit test with that exact spec | A property test: for any track with `alt > max(raster) + margin`, clearance is positive |
| Two missing example specs | Never written | `examples/cameras_event_trigger.yaml` (n_z threshold), `examples/cameras_hazard_refusal.yaml` (camera through the tornado core) | The same examples test as above |

The generalisable lesson: **every example is a test and every check runs
on the platform that produces the frames**. Gate 6 has never been
measured on Windows. Phase 2's first Windows milestone is a green
`gate6_visual.py` on the target machine, before any annotation work is
believed there.

---

## 3. The ground-truth bundle — the one design decision that carries B, C and D

### 3.1 What the best tools emit per frame

Omniverse Replicator's annotator set is the de facto reference: RGB,
semantic segmentation, instance segmentation (by object and by
primitive), tight and loose 2-D boxes, 3-D boxes, distance to camera,
distance to image plane, normals, motion vectors, pointcloud, skeleton
keypoints, and an **occlusion ratio** per instance. Unreal's Movie
Render Graph render layers cover a similar set (beauty, object ID /
Cryptomatte, depth, world normal, motion vector) as multilayer EXR.
Kubric writes the same family from Blender. Every serious pipeline
writes these from the renderer's own buffers, aliasing-free, in one
pass with the beauty image.

### 3.2 Two ways to get there in Unreal, and the recommendation

**Option A — extend the commandlet with multiple `SceneCapture2D`
passes.** Keep the fixed-tick loop the gates measure. Per frame, capture
in this order from the same transform:

1. Beauty: `SCS_FinalColorHDR` into an `RTF_RGBA16f` target (linear,
   tonemapped in Python or by a second LDR capture), TSR or DLSS on.
2. Object ID: a second capture whose post-process material outputs
   the **Custom Stencil** value as a flat integer (every labelled
   component has `bRenderCustomDepth` on with its stencil set from the
   card's object list; Landscape components and foliage instances
   support the custom-depth pass too, which is what Cosys-AirSim's
   proxy-mesh approach cannot do — it explicitly leaves landscape,
   foliage and decals unsegmented). The stencil is 8-bit, so 255 ids
   per frame: far more than the handful of labelled aircraft plus
   class codes for terrain, buildings and vegetation this dataset
   needs; the card refuses a scene that would need more. `ShowFlags`
   disable AA, fog, atmosphere, bloom, motion blur and translucency
   for this capture; read back at full resolution as integers, never
   through an sRGB or compressed path (Cosys's "request uncompressed
   image" rule exists because of exactly this).
3. Depth: `SCS_SceneDepth` into an `RTF_R32f` target, same show flags;
   write as 32-bit float EXR (or 16-bit PNG in millimetres with a
   recorded scale — pick EXR; KITTI-style 16-bit PNG is a lossy choice
   the 2026 tools no longer make).
4. Visibility: a **second ID capture with every occluder hidden** (only
   the labelled object visible, `bRenderInMainPass` toggled or a
   per-capture `ShowOnlyComponents` list). Visible fraction = pixels
   with the object's ID in pass 2 ÷ pixels in pass 4. Truncation is
   handled by a wider virtual sensor (render pass 4 at 1.5× FOV, or
   compute the unclipped projected box from the mesh's convex hull in
   Python).
5. Atmospheric visibility: sample the Sky Atmosphere and height fog
   transmittance along the ray to the object's centroid (the engine
   exposes the fog parameters the spec set; the extinction is
   analytic). Report it as a separate `atmospheric_transmittance`,
   never folded into the geometric visibility fraction.

Cost: four to five captures per frame instead of one. At 1280×720 on an
RTX-class card that is still tens of frames per second, and the render
is not the campaign bottleneck (the FDM flight and disk are).

**Option B — move frame production to Movie Render Graph.** MRG gives
the render layers (beauty, **Object IDs stored per the Cryptomatte
spec**, world depth, motion vectors, normals) as multilayer EXR,
temporal sub-sampling, per-layer choice of deferred or path-traced
renderer, and Epic maintains it. Cryptomatte is the one route that
keeps anti-aliasing and motion-blur coverage *correct*: an edge pixel
carries ranked id/coverage pairs instead of a blended value, so a
consumer decodes weights rather than guessing. It runs in `-game` mode
from the command line (`-MoviePipelineConfig=` or a Python host
executor, `-RenderOffscreen -Unattended` work), not inside a
commandlet. The costs: the fixed-tick loop the gates measure and the
JSBSim substep accumulator would have to be reproduced under MRG's own
time control (temporal samples tick the engine, spatial samples do
not — so temporal = 1, spatial > 1 is the repeatable setting); a known
MRG bug writes the Cryptomatte layer without its manifest metadata in
some graph setups; and every Phase 1 render calibration would be
re-measured.

**Recommendation: Option A for Phase 2, with the bundle's file format
chosen so Option B can replace the producer later without changing a
consumer.** The stencil route gives hard integer masks, which is what
COCO/YOLO/VOC consume and what the verifier can grade without decoding;
Cryptomatte's soft coverage matters only if sub-pixel mask accuracy is
ever *claimed*, which `not_claimed` says it is not. The format is the
contract, not the commandlet. Write per
frame: `frame_%06d.png` (beauty, sRGB 8-bit for training),
`frame_%06d.beauty.exr` (optional linear half-float), `frame_%06d.id.png`
(16-bit, one integer per instance, 0 = background),
`frame_%06d.depth.exr` (32-bit float metres), and one
`frame_%06d.json` with the per-object records (§3.4). MRG's Cryptomatte
and depth layers convert to exactly that.

### 3.3 Aliasing, the rule

Label passes render with **no anti-aliasing, no temporal history, no
screen-percentage scaling** (`r.AntiAliasingMethod 0`,
`r.TemporalAA.Upsampling 0`, `r.ScreenPercentage 100`, show flags for
fog/atmosphere/bloom/motion blur/DOF/lens flare/translucency off), at
the exact pixel resolution of the beauty pass. Every open-source UE
generator learned this the hard way: EasySynth's README says to use
FXAA at most because everything else produces "jagged or bled edges",
and a community thread on `SceneCaptureComponent2D` segmentation shows
the interpolation artefacts. The beauty pass is free to use TSR or
DLSS (the DLSS 4.5 plugin covers UE 5.4–5.7, with a 5.8 build listed).
The verifier checks that the ID image contains only integers from the
frame's declared instance list — a single blended value fails the
frame.

### 3.4 Identity (package B)

* `ObjectId` is assigned in Python when the scene is composed, not in
  the engine: a stable string (`aircraft:A320:0`, `aircraft:c172p:1`,
  `terrain`, `building:0017`), hashed to a 16-bit integer for the ID
  image with collisions refused at composition time. The spec carries a
  `taxonomy` block (class list with ids and names, source-attributed
  like every other field) and the manifest carries `objects: [{id, class,
  instance, mesh_sha256, licence, labelled: true|false, in_scene:
  true|false}]`. A missing label is thereby distinguishable from a
  missing object, which the plan asks for.
* The engine reads the object list from the card and sets each
  component's custom primitive data to the integer id. It never invents
  an id.
* A second aircraft is a **scripted traffic actor**: a second mesh flown
  along a pre-solved track (the same `PoseTrack` machinery the cameras
  use, applied to an actor), with its own id and class. No second FDM in
  this phase, exactly as the plan allows. Formation, crossing and
  overtaking tracks are the three that produce object–object occlusion.
* Clouds and terrain carry ids too (`cloud` as a class only in the
  visibility record, never as a mask, since volumetrics write no ID).
* A **path-traced reference frame** is a cheap extra check the engine
  now offers: the Path Tracer has been production-ready since 5.5 and
  Epic names it as a reference for the atmosphere and volumetric
  clouds. One path-traced frame per campaign, graded against the
  raster beauty frame with the same ID mask, catches a raster-only
  artefact (light leaking, shadow acne on the airframe) that no label
  check would.

### 3.5 Boxes, depth, occlusion (package C)

* 2-D tight box from the ID mask; 2-D projected box from the airframe's
  convex hull in the manifest frame; both recorded; the frame fails when
  the IoU between them is below a stated threshold (0.8 at ≥ 64 px
  extent, relaxed by a stated schedule for smaller objects).
* Truncation: `box_clipped`, `box_unclipped` (from the hull, may leave
  the frame), `fraction_in_frame`.
* Occlusion: `visible_fraction` (geometric, from the two ID passes),
  `occluded_by: [ids]` (the ids found in pass 2 inside the pass 4
  footprint), `atmospheric_transmittance` (analytic).
* Depth: per-object `depth_min`, `depth_median` from the depth image
  under the mask; checked against the manifest's projected CG depth
  with a tolerance that grows with range and the airframe's length.
* 3-D box: the airframe's axis-aligned extent in body axes (from the
  mesh, once, in the asset manifest) plus the CG position and the
  attitude quaternion in camera coordinates — reconstructible from
  `capture_manifest.json` alone, KITTI/nuScenes convention stated.
* **What is not claimed** is a field, not a paragraph: per frame,
  `not_claimed: ["subpixel_mask_accuracy_beyond_range_m: 8000",
  "objects_under_px: 12"]`, and the dataset card aggregates it.

### 3.6 Quality gates (package D)

The existing verifier grows one check per artefact, each with a named
failure, a stated tolerance, a mutation guard and a **visual test**:

| Check | Independent evidence | Named failure | Visual test writes |
|---|---|---|---|
| `mask.integers_only` | ID image histogram vs declared ids | `annotation.mask_blend` | the offending pixels highlighted |
| `mask.vs_geometry` | ID-mask centroid/extent vs projected CG and hull | `annotation.mask_offset` | overlay: mask edge, hull outline, CG cross |
| `box.vs_mask` | tight box vs projected hull box, IoU | `annotation.box_mismatch` | both boxes drawn |
| `depth.vs_geometry` | depth under mask vs projected depth | `annotation.depth_range` | depth heatmap with predicted value |
| `visibility.vs_scene` | second-pass footprint vs first-pass count; occluders listed exist in the scene | `annotation.visibility` | pass 2 and pass 4 side by side |
| `identity.stable` | same object id for the same spec object across frames, cameras, runs | `annotation.identity` | id timeline strip |
| `drawn.is_mesh` | `render.json.drawn.kind` | `aircraft.placeholder_drawn` | contact sheet with the drawn kind stamped |

`tests/visual/annotation_sheets.py` stands the tool up on a 20-frame
run and writes `build/visual/*.png`. Mutations that must fail:
shift the mesh attach by 3 m; swap two ids; blur the ID image; scale
depth by 1.02; hide the occluder in pass 2.

The verifier still does not import the producer. The projection code it
uses is the one in `core/capture/verify.py` today; the hull projection
is new Python over the asset manifest's vertex bounds.

---

## 4. Export (package E)

Keep it boring and reference-checked.

* Writers: COCO (instances + `segmentation` as RLE via `pycocotools`),
  YOLO (`labels/*.txt` normalised xywh + `data.yaml` class list, the
  Ultralytics layout), Pascal VOC (per-image XML with `truncated`,
  `occluded`, `difficult` derived from the visibility record), KITTI
  (2-D + 3-D with `truncated`, `occluded` 0–3, `alpha`), WebDataset
  (tar shards with `.png`, `.id.png`, `.depth.exr`, `.json` per sample),
  and **Parquet + a Hugging Face `dataset_infos`/Croissant card** as the
  modern interchange, since that is what 2026 training stacks load
  first.
* Round-trip tests load each export with the format's own reader
  (`pycocotools.COCO`, `ultralytics.data`, `torchvision.datasets.
  VOCDetection`, a minimal KITTI reader, `webdataset.WebDataset`,
  `datasets.load_dataset`) and assert counts, categories, box
  coordinates to the pixel and mask areas to 1 %.
* Splits: digest-based on `simulation_digest`, so every frame of one
  flight lands in one split; the policy and seed go in the card.
* The card: counts, class balance, realised condition histograms
  (§5.5), per-run spec digest + seed + verification status,
  `not_claimed`, licences of every asset drawn (the airframe licence
  question in §9 decides whether the card can even be published).
* Refusal by name for any run without a green `verification.json`, as
  planned.

---

## 5. Randomization from the prompt (package F)

### 5.1 The model to copy

Replicator's randomizer graph and Kubric's "worker" scripts share one
idea: randomization is a **typed distribution over named parameters,
sampled from a seeded generator, with the sampled value recorded next to
the parameter**. Infinigen goes further and randomizes the *generators*
(terrain, weather, vegetation) not just their parameters. The plan's
"sampling policy over the typed fields that already exist" is the same
idea, and the spec's provenance system is already built for it: add
`Source.SAMPLED` with `detail = {policy, distribution, seed, draw_index}`
and `PLANNABLE_SOURCES` gains nothing (a sampled field is as fixed as a
user field once drawn).

### 5.2 The policy schema

```yaml
campaign:
  images: 5000
  seed: 20260924
  policy:
    location:      {choice: [rockies, alps, cascades, flint_hills], weights: [3,3,2,1]}
    weather_date:  {uniform_dates: ["2024-01-01", "2024-12-31"]}   # drives ERA5 wind + cloud/visibility
    hour_local:    {uniform: [5.5, 20.0]}
    sun_elevation_min_deg: 2
    visibility_km: {lognormal: {median: 25, sigma: 0.6}, clip: [1, 80]}
    cloud_cover:   {beta: [2, 2]}                                  # 0..1 low-layer cover
    precipitation: {choice: [none, rain, snow], weights: [7, 2, 1], gated_by: cloud_cover > 0.6}
    wind_speed_kt: {weibull: {k: 2.0, lambda: 12}}
    turbulence:    {choice: [none, light, moderate, severe], weights: [4,3,2,1]}
    surface:       {choice: [grassland, desert, forest, city, ocean]}
    aircraft:      {choice: [A320, B747, c172p, dhc6]}
    livery:        {choice: [white, airline_a, airline_b, bare_metal]}
    traffic:       {count: {poisson: 0.7}, max: 2}
    cameras:
      preset:       {choice: [chase, tower, wingman, ground]}
      focal_length_mm: {loguniform: [24, 400]}
      offset_jitter_m: {normal: {sigma: 5}}
```

Every leaf maps to an existing typed field or to a new one added with
validation. Draws go through `validate()`; refusals are recorded as
`{draw_index, refusal_name, sampled_values}` and re-drawn with a stated
maximum (say 20 attempts per slot) before the campaign reports the slot
infeasible. The "quietly discards half its draws" failure is then a
number in the campaign report.

### 5.3 The prompt vocabulary

Extend `RESPONSE_SCHEMA` with a bounded `randomization` block (mirroring
how `cameras` was added in Camera Phase 1, import-time assert against
the policy's field list). Documented phrases: "varied weather" →
`cloud_cover`, `visibility_km`, `precipitation` distributions;
"different times of day" → `hour_local` uniform; "across the Rockies" →
`location` choice restricted to the curated set in that range; "mixed
traffic" → `traffic.count`; "random viewpoints" → the camera block;
"dawn and dusk only" → `hour_local` bimodal. Anything else is refused by
name (`randomization.vocabulary`) with the sentence quoted, exactly as
today's surfaces are.

### 5.4 Visuals coupled to the same values

The plan's one visual item — cloud, precipitation, visibility, time of
day driven by the values the physics uses — is where Lane 2 meets Lane 1
in this phase. The coupling is a **table, in one module** (`core/scene/
weather_visuals.py`), from spec values to engine parameters:

* `visibility_km` → fog extinction (Koschmieder: β = 3.912 / V) → both
  the height fog density and the Sky Atmosphere aerosol term; the
  extinction Gate 6 measures from pixels becomes the check.
* `cloud_cover`, `cloud_base_m`, `cloud_top_m` (ERA5 low/mid/high
  layers from Open-Meteo, already fetched for wind) → Volumetric Cloud
  layer altitude, thickness and coverage; cloud shadows on.
* `precipitation` → Niagara rain/snow system density; wet-surface
  roughness/specular on terrain and airframe materials; visibility
  floor.
* `hour_local`, `weather_date`, `latitude`, `longitude` → sun azimuth
  and elevation (already computed), moon and stars at night.
* `wind_speed_kt` → cloud drift, tree/grass sway amplitude, sea state
  (Beaufort) where the surface is ocean.

Each row is a claim measured from pixels once (the Gate 6 pattern) and
recorded in the manifest as the visual parameters actually used.

### 5.5 Realised distribution, measured

The campaign report histograms every sampled field over the frames that
actually exported (not the draws), states the requested distribution
beside it, and computes a coverage score (fraction of policy bins with
at least *k* frames). "Varied" is then a number with a picture.

---

## 6. Campaign execution at scale (package G)

* **Campaign as a first-class object**: `campaigns/<id>/campaign.json`
  (prompt, compiled policy, target, seed, state machine
  `planned|running|paused|failed|done|cancelled`, worker count, disk
  budget), a JSONL ledger with one line per run (case id, seed, status,
  frame count, annotation yield, refusal names), and a `trace.jsonl`
  for the agent (§7). Grow it from `core/experiments/sweep.py`: the
  content-derived case id and the append-only log are already right.
* **Determinism independent of worker count**: per-run seeds are
  derived from `SeedSequence([draw_index, campaign_seed])` — NumPy's
  own documented recommendation ("place the varying IDs before the
  unvarying root seed") and exactly what `core/experiments/seeds.py`
  already does for subsystems; the draw order is fixed by index, never
  by completion order; workers pull cases by index from a queue. Kubric
  persists its seed into the scene metadata and Infinigen names each
  scene directory by seed; do both. The test the plan asks for — same
  campaign, 1 worker and 4 workers, identical scenario set and identical
  frame digests — is then a property of the design, and it is still
  measured.
* **Parallel engine instances on one Windows GPU**: several
  `UnrealEditor-Cmd -run=FlightSimRender` processes can share a card —
  a September 2026 UE data-pipeline paper reports that one process
  rarely saturates a GPU (asset loading, shader compilation and I/O
  dominate) and that concurrency is tuned empirically against memory.
  No verified per-instance VRAM figure exists for a scene like this
  one, so it is measured: the throughput curve at 1, 2 and 4 workers
  on the target card, VRAM and RAM per process recorded, the knee
  chosen and written into the campaign defaults. The DDC is shared
  (leave the local DDC warm once, or set a shared path). Gotcha 9 (one
  editor at a time) was about DDC and GPU contention on a Mac and is
  re-measured, not inherited. `-deterministic` (fixed timestep and
  seed) is worth adding to the argument list even though the commandlet
  already fixes the tick, so the engine's own random streams are pinned
  too.
* **Orchestration**: the honest choice for a Python project that must
  run on one Windows box is `asyncio` plus a `ProcessPoolExecutor`
  with the `spawn` start method, a queue and a ledger — not a cluster
  scheduler. The 2026 facts that decide it: Celery has not supported
  Windows since 4.x; Ray 2.58 calls its Windows support "Beta" (single
  node, more memory, slower); RQ 2.12 works on Windows only through its
  `SpawnWorker`; Temporal (Python SDK 1.33) is the right tool if
  durable multi-day pause/resume across crashes matters more than
  simplicity; Prefect and Dagster are merging under the Prefect name
  from August 2026 and are heavy for one box. Start with the pool;
  keep the ledger one JSON per task so Temporal or Ray can adopt it
  later without a format change.
* **Unattended**: `-unattended -nopause -nosplash -NoSound
  -RenderOffScreen -AllowCommandletRendering -stdout
  -FullStdOutLogOutput` (already used; never `-nullrhi`, which
  produces empty captures that report success), plus a watchdog that
  kills a renderer that stops writing frames for N minutes and
  re-queues the case with a recorded reason. Windows Error Reporting
  dialogs are suppressed by registry policy (`DontShowUI`) on the
  render box.
* **Disk**: a 1280×720 bundle (PNG beauty ~1 MB, 16-bit ID PNG ~50 KB,
  float depth EXR ~1.5 MB, JSON ~5 KB) is ~2.5 MB per camera frame;
  5000 frames ≈ 12.5 GB. Budget per campaign from a measured sample
  render (items × bytes per item against `shutil.disk_usage`), shown
  in the plan preview, re-checked per batch, and refused by name
  (`storage.budget_exceeded`) rather than discovered at 90 % full.
  Retention after export follows Infinigen's `--cleanup big_files`
  idea: keep the bundle and the ledger, drop intermediates.
* **Progress and yield** are computed from the ledger, not from a
  counter in memory, so a restarted server reports the truth (gotcha
  23 fixed by design).

---

## 7. The agentic controller (package H)

### 7.1 Tools, not prose

Expose the pipeline as **typed tools** with JSON schemas, served over
the Model Context Protocol so any 2026 agent runtime (the Claude Agent
SDK, OpenAI's Agents SDK, LangGraph, Pydantic AI) can drive the same
surface and the tests can drive it without a model:

```
compile(prompt, answers?) -> {spec, questions, refusals}
plan_campaign(spec, policy_words, images) -> {policy, estimate}
sample(campaign_id, n) -> {cases, refused}
run(case_id) -> {run_id, status}
render(run_id) -> {frames, drawn}
verify(run_id) -> {checks, verdict}
export(campaign_id, format) -> {dataset_path, card}
inspect(run_id, frame?) -> {overlay_png, records}
report(campaign_id) -> {yield, coverage, refusals}
```

### 7.2 Authority limits enforced in code

The controller is a loop with a budget and a policy check on every call,
not a prompt that asks nicely:

* **Stated fields are immutable.** Every tool that takes a spec takes
  it with provenance; the tool layer refuses any write to a field whose
  source is `user` or `inferred` (`authority.stated_field`).
* **Validation cannot be bypassed.** There is no tool that runs an
  unvalidated spec; `run()` calls `validate()` itself.
* **A refusal is not a run.** The tool layer returns refusals as
  structured data; the only way past one is a new `sample()` or a
  `plan()` on a system-chosen field, both logged.
* **Budgets**: max tool calls, max re-samples per slot, max wall time;
  exceeding one ends the loop with a plain-language escalation.

Implement the limits twice, deliberately: as a **deterministic policy
function** inside the tool layer (so no runtime can lose them) *and*
as the runtime's own pre-tool hook (so the model sees the refusal as a
typed error and re-plans instead of failing silently). Concretely:

1. `compile`/`plan_campaign` reject — or rewrite back — any input that
   changes a field whose provenance is `user` or `inferred`.
2. `run`, `render` and `export` require a `validation_token` minted by
   `validate()` for that exact spec digest; there is no way to obtain
   one without validating.
3. A spec carrying a named refusal is denied for `run` with the
   refusal's catalogue sentence as the reason string.

Every 2026 runtime has a hook for this, and they differ in one way that
matters: in the Claude Agent SDK the `PreToolUse` hook runs *before*
every other permission step and its deny holds even in bypass modes,
and its `updatedInput` can restore a user-stated field the model tried
to move; Pydantic AI's `requires_approval` / `ApprovalRequired` and
deferred-tool results give the same shape provider-independently, with
AG-UI streaming to the browser built in; the OpenAI Agents SDK has
`needs_approval` and tool guardrails; Google ADK's plugin ordering has
an open issue where one plugin can bypass later governance plugins —
which is the argument for rule 1–3 living in the tools. MCP tool
annotations (`readOnlyHint`, `idempotentHint`) are metadata, not
enforcement; `run(campaign_id, index, spec_digest)` is made idempotent
by keying its outputs on those three. Test each limit with a scripted
adversarial agent that tries to violate it, and log every denial.

### 7.3 Trace beside the dataset

`trace.jsonl`: one line per tool call with inputs, outputs, the model's
stated reason, and the policy check result; OpenTelemetry spans if the
project ever wants Langfuse or another viewer. The dataset card links
the trace. That is the audit the plan asks for.

### 7.4 Which runtime

For one campaign loop with stated authority, the choice matters less
than the tool layer, and the tool layer is the same for all of them.
Given that `core/nl/providers.py` already serves five tiers, the
provider-agnostic harness is **Pydantic AI** (typed tools, approval
predicates, deferred pause/resume, AG-UI events to the UI), with the
**Claude Agent SDK** as the alternative if the Anthropic tier is
primary (its hook ordering is the strongest guarantee available, and
its `AskUserQuestion` contract — at most four questions, two to four
options each with a label and description, a free-text "Other" — is a
ready-made schema for package I's clarifying questions; run it with
`tools=[]` and a strict MCP config so only the pipeline's tools
exist). LangGraph only if durable multi-day checkpointing is needed.
Two housekeeping facts from the research: the Anthropic Python SDK is
at 1.8 and the repository pins 0.121, and structured outputs are now
GA there (`output_config.format`, `strict: true` on tools) while the
newest models reject forced `tool_choice` — the compiler's pinned
default model id and its call shape should be re-checked against the
current lineup before Gate 8.1 is re-run. Local tiers stay the
zero-cost path: Ollama now takes a JSON schema as `format` and applies
it in one pass on thinking models, and the 2026 small-model picks for
schema extraction on a consumer GPU are Qwen3.5 4B/9B, Gemma 4 E4B/12B,
Phi-4-mini and Mistral Small 3.2; wrap the call in Instructor for
Pydantic validation and one retry. Record which model drove a campaign
in the card, as Gate 8.1 records the tier it measured.

---

## 8. The non-technical interface (package I)

### 8.1 The flow, and the fact that it is a product

One page, six states, each with one plain sentence at the top:

1. **Ask** — the prompt box, a few example prompts, the active tier
   named.
2. **Clarify** — at most three questions, answered by buttons or a
   sentence; each answer becomes a `user`-sourced field, as today.
3. **Preview** — "Here is what will be generated": a plain-language
   paragraph (airframes, places, conditions, viewpoints, count,
   format), the refusals in words with the rule name under a
   disclosure, and **one rendered sample frame with mask and box
   drawn**, produced by a real short run so the user sees the actual
   look before spending hours.
4. **Generate** — progress in human terms from the ledger: images so
   far, what is varying (live histograms), what was refused and why,
   estimated time from the measured per-frame cost.
5. **Review** — a gallery of frames with overlays, the realised
   distribution, the verification summary as ticks.
6. **Download** — format picker, the card shown, one button.

### 8.2 The message catalogue

Every refusal name and every progress state maps to a human sentence in
one catalogue (`core/messages/catalog.yaml`), with the rule name kept
underneath; a test asserts every `Violation` name in the codebase has a
catalogue entry and every entry has a live name (the same import-time
assert pattern). Unicode MessageFormat 2.0 is stable (CLDR 47 / ICU 77,
2025) and is the right template syntax for plurals and units ("The
camera would sit 89 m below the ground at that spot"; "3 of 5 draws
were refused"); Python's Fluent runtime has not shipped since 2023, so
a small MF2-style renderer over YAML, server-side, is the pragmatic
choice. The same catalogue feeds the agent's reason strings, so a
refusal reads identically in the UI, the CLI and the trace.

### 8.3 Stack

The current single HTML file is honest but not the surface a
non-technical user, or a reviewer of "the technology of now", should
meet. Two defensible choices:

* **Stay Python-native, upgrade in place**: FastAPI + HTMX + Alpine.js
  with server-sent events for progress. Smallest change, no build step,
  and the expert path stays identical. The page can look modern with a
  real design system (Tailwind via CDN, a dark theme, a proper gallery).
* **A real front end**: React 19 / Next.js with shadcn/ui and Tailwind,
  talking to the same FastAPI endpoints, with a WebSocket for progress
  and a canvas overlay viewer for masks and boxes. More work, and it is
  what every product in this space (Roboflow, Scale Nucleus, Voxel51's
  FiftyOne App) ships.

Recommendation: HTMX 2 + server-sent events (`sse-starlette`) now,
because package I's real work is the catalogue, the preview and the
campaign object, not the framework; keep the API clean enough that a
React front end is a later add. If the owner wants the 2026 product
look from the start, the mainstream combination for a Python backend
is FastAPI + Vite/React 19 + Tailwind v4 + shadcn/ui with assistant-ui
or CopilotKit speaking the AG-UI event protocol over SSE, which
Pydantic AI emits natively — that is how the plan preview, the
clarifying questions and the live progress become one stream. NiceGUI
can mount inside the existing FastAPI app for a middle path; Gradio and
Streamlit are demo tools, not product surfaces. For the review gallery,
embed FiftyOne (1.22, September 2026) rather than write one; for
overlays on a single frame, Konva on a canvas is enough. Pixel
Streaming 2 can put a live engine view in the browser for the preview
step, but its infrastructure branches list UE 5.5 as unsupported and
5.6 as end-of-life, which is one more input to the engine-version
decision in §9.8.

### 8.4 The expert path stays

Every screen names its command; `docs/COMMANDS.md` is generated from
the same tool schema the agent uses, so the three surfaces (UI, CLI,
agent) cannot drift.

---

## 9. The look — bringing the world to the 2026 bar

The plan defers photorealism to Phase 5. The brief for this document
overrides that: the simulator has to look like a current-generation
game, and every repeated Phase 1 item is a verdict that the current
version is not good enough. So this section treats the look as Lane 2
work that starts now, subject to one rule: **a Lane 2 change may not
touch an ID or depth pass except through geometry, and it ships with a
pixel measurement.** Licences are stated for everything, because a
dataset that cannot be distributed is not a dataset.

### 9.1 Terrain and imagery: real places, open data, no 60 m cap

**What the best do.** MSFS 2024 streams terrain, textures, meshes and
photogrammetry on demand from more than two petabytes of Bing Maps and
photogrammetry data, with a 50 cm "countryside" mesh being bought
continent by continent; that is the reference look, and it is built on
commercial imagery under terms that forbid exactly the offline,
machine-interpretation use a dataset generator is. Cesium for
Unreal gives the same streamed look inside UE — and Cesium ion's terms
forbid storing or redistributing its output for offline use, Google
Photorealistic 3D Tiles forbid "image analysis, machine interpretation,
object detection, offline uses", and Mapbox and Bing tiles forbid
tracing, extraction and offline storage. **None of those can be the
source of a distributable dataset**, however good they look. Cesium
ion's Community tier also excludes funded research, as `VALIDITY.md`
§5 already records.

**The licence-clean stack** (each item verified 2026-09-24; links in
§14):

| Layer | Source | Resolution | Licence | Note |
|---|---|---|---|---|
| Elevation, global | Copernicus DEM GLO-30 on AWS (already used) | 30 m | free, attribution | vertical RMSE ≈1.7 m; better than NASADEM |
| Elevation, US | USGS 3DEP 1 m DEM and lidar point clouds | 1 m | public domain | the real answer for US sites: ridgelines, cut slopes, buildings as bumps |
| Elevation, CH / NL / JP | swissALTI3D, AHN5/6, GSI 5 m | 0.5–5 m | open (CH/NL OGD, CC0) | for Alpine scenes the Matterhorn bake could be sub-metre |
| Imagery, global | Copernicus Data Space quarterly cloudless Sentinel-2 mosaics (full archive processed 2026-03) | 10 m | free, attribution | replaces the 2016 EOX layer with a current, seasonal one; the NC problem with EOX 2018+ goes away |
| Imagery, US | NAIP | 30–60 cm | public domain with attribution | the difference between "a green blur" and "a field with tractor lines" under a chase camera |
| Land cover | ESA WorldCover 2021 or Esri/IO annual LULC 2017–2025 | 10 m | CC BY 4.0 | drives materials and vegetation, and becomes a label class |
| Buildings | Microsoft Global ML Building Footprints (with heights) / Overture buildings filtered to CC-BY sources | vector | CDLA-Permissive 2.0 / CC BY | extruded boxes with heights, the 9.4 city plan made real |
| Roads | OpenStreetMap | vector | ODbL | usable, but the *extracted* road database is a derivative and must be offered under ODbL if the dataset is public; keep it optional |

**Getting it into the engine.** The branch already has
`core/terrain/landscape.py` with the 16-bit height encoding and the
Z-scale rule worked out and verified by Gate 4; it was never wired to
the render path. Wire it:

1. **Bake → UE Landscape**, not a procedural mesh. Import at native
   posting (30 m global, 1 m where 3DEP exists, tiled through World
   Partition for anything over 8129×8129). This removes the
   701-vertex cap and lets virtual shadow maps replace the six-cascade
   CSM. Nanite Landscape is still marked Experimental on Epic's
   roadmap through 5.7 (with displacement bugs reported in 5.6/5.7 and
   its 5.8 status unverified), so it is a toggle measured on the target
   machine, not an assumption; the classic Landscape path is the
   default.
2. **Imagery as a Streaming Virtual Texture**: the orthomosaic tiles
   imported as a UDIM set into one SVT, so a 20 km NAIP scene is a
   multi-GB texture that streams instead of one 8K PNG. A Runtime
   Virtual Texture on top carries decals (roads, runway markings) and
   the wet-surface layer.
3. **Land cover → landscape layers → PCG biomes**: rasterise WorldCover
   classes into weightmaps; the terrain material blends per-class
   surfaces (Quixel's unrestricted free-for-Unreal offer ended at the
   close of 2024; **Megaplants stay free** under the Fab Standard
   licence and other Megascans are priced individually or by
   subscription — and every listing is checked for the NoAI tag, §9.4),
   and PCG Biome Core (production-ready framework since 5.7) spawns
   trees, shrubs and grass from the same weights, so "forest" in the
   spec is a forest on screen. Nanite Foliage in 5.7 is Experimental
   and the 5.8 Procedural Vegetation Editor is Experimental: both worth
   a probe render, neither a bet.
4. **Buildings** extruded from footprints with heights, instanced,
   given a simple façade material set from land cover (city vs
   suburb), and — because they are geometry — they get ids and enter
   the collision mesh exactly as the Phase 9.4 plan intended.
5. **Provenance carries through**: every raster and vector tile is
   sha256'd into the bake sidecar as GLO-30 is today; the render
   manifest lists them; the dataset card credits them. That is already
   the discipline; it just gains rows.

The imagery-on-geometry verification from Phase 7
(`experiments/imagery_drape.py`, landmark projection through the camera
of record) becomes a standing check on every new bake.

**What to say no to.** Cesium World Terrain and Google 3D Tiles for
anything that is exported; commercial 30 cm imagery (Vantor, Planet)
unless a derivative-works licence is bought; Mapbox-fed plugins
(Landscaping's Mapbox extension) for the same reason. Cesium for Unreal
with *local* tilesets from open data is fine, and is the path if the
project ever wants a whole-planet streamed scene; it needs UE 5.6+.

### 9.2 Sky, clouds and weather: the same numbers the physics uses

**What the best do.** MSFS 2024 renders live weather from a meteoblue
grid with 60 vertical layers per cell, blended with METARs near
airports, as volumetric cumuliform and stratiform layers with cloud
shadows and precipitation. X-Plane 12 ray-marches volumetric clouds from
NOAA GRIB blended with METARs and, since 12.2, shadows clouds on each
other. The look people mean by "realistic sky" is multi-layer volumetric
cloud driven by real data, lit by a physically based atmosphere.

**What the branch has.** The Hillaire Sky Atmosphere (the same model
Epic ships; the branch already sets real Earth radii and
multiscattering), an exponential height fog, one sun. No clouds.

**The build.** Two tiers, chosen by licence appetite:

* **Native first** (no third-party licence, deterministic, fully
  scriptable from C++): UE's Volumetric Cloud component — material-
  driven ray marching, per-layer bottom altitude and thickness, cloud
  shadows on the directional light. Drive it from the spec:
  `cloud_cover_low/mid/high`, `cloud_base_m` per layer from Open-Meteo
  (which already serves the branch's ERA5 wind and exposes cloud cover
  by layer), or from METARs via aviationweather.gov for the
  present-day case. Two layers cover most weather; a third for cirrus
  is a 2-D layer.
* **Ultra Dynamic Sky + Ultra Dynamic Weather** (Fab, paid, UE
  5.5–5.8; v9.7 in Aug 2026 reportedly added unlimited extra cloud
  layers — version seen only on mirrors) or **Sky Creator** (UE
  4.26–5.7, multi-layer volumetrics, rain, screen raindrops, snow,
  mist) if the owner wants the fastest route to a game-quality sky
  with weather transitions and precipitation already built. UDS
  simulates the real sun, moon and stars from latitude, longitude,
  time zone and a north yaw, which lines up with the spec's
  georeferencing for free; UDW exposes material wetness, snow and dust
  coverage as 0–1 material functions for props and landscape, which
  is the wet-surface coupling below without writing it. Either is
  driven the same way — from the spec's values — and neither writes to
  the ID or depth pass.

Either tier is measured, not admired:

| Spec value | Engine parameter | Pixel measurement |
|---|---|---|
| `visibility_km` | fog extinction β = 3.912 / V (Koschmieder) into height fog and the atmosphere's aerosol | Gate 6's extinction clause, re-run with V as the variable |
| `cloud_cover_*`, `cloud_base_m` | Volumetric Cloud layer altitude, thickness, coverage | a ray from the camera hits cloud at base ± 200 m in a cloud-only depth render; cover fraction from a nadir render |
| `precipitation` | Niagara rain/snow (UDS/Sky Creator ship theirs); wet-surface roughness/specular via the RVT layer; visibility floor | rain-on/off null test on road/runway specular |
| `hour_local`, date, lat/lon | sun elevation and azimuth (exists), moon, stars, night exposure | the existing exposure-does-not-breathe clause at −12° sun |
| `wind_speed_kt`, direction | cloud advection, foliage sway, sea state | cloud motion vector direction over 10 frames |
| thunderstorm word (Phase 9.2) | dark anvil layer, lightning flashes, rain | the frame-45 luminance histogram shifts as the Phase 9 storm look records |

Data sources for the present day: Open-Meteo (cloud layers, winds at
10/80/120/180 m and pressure levels), ERA5 (CC-BY, hourly, 1940–), NOAA
HRRR (3 km hourly, open, US), METAR/TAF JSON (aviationweather.gov, 1-min
updates, 15-day history). The spec's `weather_date` plus location
resolves to one coherent set of numbers that drives the wind field,
the turbulence word, the clouds and the visibility together — the
plan's "low visibility draw looks like one in the image as well as in
the wind field", made literal.

### 9.3 Water

For ocean and lake scenes (the `ocean` surface class exists and renders
a flat slab today): the UE Water plugin's Gerstner ocean is adequate and
free, with the caveat that the plugin is still marked Experimental in
5.5–5.8 ("use caution when shipping"); Oceanology (Fab, FFT + Gerstner,
breaking waves) or Fluid Flux (shallow-water shorelines) if the look
matters. Sea state from wind via
Pierson–Moskowitz (Hs ≈ 2.14×10⁻² U₁₉.₅²) so a 25 kt draw has 3 m seas,
recorded in the card and measured once from a nadir frame's wave
spectrum.

### 9.4 Airframes and liveries: the licence is the design constraint

**What the branch has.** FlightGear `.ac` models (c172p, A320, B747,
DHC6) under GPL-2.0, flat colours, Nanite off, no PBR. They fly the
right FDM (the §1.4 pairing rule is enforced) and they look like 2008.

**The problem.** GPL meshes in the asset pipeline of a proprietary
dataset generator are a contamination risk, and a published dataset
whose card must credit a GPL mesh invites questions no one wants.
Separately, the Fab Standard Licence has a "NoAI" tag whose holders
prohibit generative-AI dataset use of tagged content, and Epic's EULA
restricts using Licensed Technology as generative-AI training input;
whether a *computer-vision* training dataset falls under either is not
settled. **Every airframe the dataset draws needs a licence read for
this specific use** before it enters `assets/aircraft_config/`, and the
config's `license` block should gain `ml_dataset_use: permitted |
unclear | forbidden` as a field the export refuses on.

**Sources with a clear answer:**

* NASA 3D Resources (free under NASA media guidelines; several
  airframes and the NASA fleet).
* OpenVSP Airshow models (per-model public-domain or CC BY-SA).
* Sketchfab CC0 / CC-BY aircraft (filter by tag; the CC-BY attribution
  goes in the card).
* Fab models *without* the NoAI tag, licence read and recorded
  (Personal and Professional tiers grant the same rights including
  commercial use; the Epic EULA's generative-AI clause is the open
  question).
* **Not TurboSquid by default**: its licence says imagery "may NOT be
  used in machine learning programs without prior authorization" —
  authorization has to be obtained in writing and filed beside the
  licence. CGTrader's terms were not verifiable this session; treat
  the same way until read.
* Commissioned models with an explicit machine-learning-use clause,
  for the two or three hero airframes the dataset leans on. The
  purchase or commission record goes beside the licence file exactly
  as the pinned commit does today.

**Quality bar.** A 2026 airliner mesh for a chase camera is 200k–1M
triangles with 4K PBR sets (base colour, normal, roughness, metallic,
AO, plus a dirt/grime mask), separated control surfaces, gear, flaps
and spinning fans. Import through Interchange with Nanite **on**
(gotcha 5's "Nanite off" was because the scene capture drew the coarse
fallback; that has to be re-tested with the label passes, and if it
still bites, Nanite stays off for airframes only — they are small on
screen).

**Materials.** Substrate is the 2026 material model in UE; for an
airframe it buys a proper clear-coat over paint with metallic flake and
a separate roughness for the coat, which is what makes a fuselage read
as painted aluminium under a low sun. A livery is a **material-layer
parameter set** (base paint colour, decal texture, registration text,
dirt amount) on the same mesh, so the policy's `livery` draw is a
material instance swap, not an asset swap, and the ID mask is untouched
by definition.

**The second aircraft** (traffic, package B) is the same asset class
driven along a pre-solved track. Formation, crossing and overtaking
tracks give the three occlusion geometries the visibility check needs.

### 9.5 Neural and hybrid realism, used honestly

* **3D Gaussian Splatting backgrounds**: splat plugins for UE
  (XV3DGS, Apache-2.0; Volinga, paid, relightable 4DGS as of Aug 2026;
  PostShot, free plugin, UE 5.4–5.7) render captured scenes at
  photographic fidelity. For this project they are a *background* tool
  — an airport apron, a mountain village — captured from open imagery
  or the instructor's own photos. Splats write depth but not a
  meaningful object id, so they are `terrain`-class background only,
  and their licence is that of the photos.
* **Sim-to-real translation**: NVIDIA Cosmos Transfer (2.5, Apache-2
  code, open-model-licence weights; Cosmos 3 launched June 2026)
  re-renders a synthetic frame conditioned on its depth, segmentation
  and edges. It is the closest thing to a "make it look real" button
  and it is how several vendors close the domain gap. The rule here:
  it is an **export variant**, produced after verification, and the
  labels are re-verified against the translated frame (mask-vs-
  geometry on the translated image's own edges), because
  diffusion-based translation is known to move geometry unless
  constrained. The card states which frames are translated and with
  what model.

Both are Phase 2 experiments with a pixel measurement, not Phase 2
dependencies.

### 9.6 Lighting and materials: what the engine already does that the branch turns off

**What the branch has.** No rendering settings at all in
`DefaultEngine.ini` (engine defaults), one directional light with
six-cascade dynamic shadow maps out to 20 km, a real-time sky light,
no global illumination, Nanite forced off at import. `VALIDITY.md`
§2.13 records the reason: "VSM wants Nanite and a runtime procedural
mesh is not Nanite". Once the terrain is a Landscape (§9.1) that
reason is gone.

**The 2026 stack and its maturity, as of 5.7 / 5.8:**

| Feature | Status | What it buys this project |
|---|---|---|
| Lumen (software or hardware ray-traced GI and reflections) | production since 5.1; **Lumen Lite** in 5.8 is up to 2× faster than the high-quality preset | valleys lit by sky and bounce instead of a flat ambient term; the Gate 6 "peaks shadow the valley" clause becomes a GI clause |
| Virtual Shadow Maps | production | the cloud-shadow and airframe-ground-shadow clauses at 30 m posting without cascade seams |
| Nanite for static meshes | production | high-poly airframes and buildings at no LOD cost; gotcha 5's Interchange note re-tested |
| Substrate materials | **production-ready in 5.7** | clear-coat paint on airframes, wet-surface layering on terrain |
| MegaLights | beta in 5.7, **production-ready in 5.8** | many shadowed lights — airport aprons, city night scenes — affordable; not needed for daylight aerial frames |
| PCG framework | production-ready in 5.7 | §9.1 vegetation and structures |
| Path Tracer | production since 5.5, named as the reference for atmosphere and clouds | the one-frame-per-campaign reference render in §3.4 |
| Sparse Volume Textures / Heterogeneous Volumes | experimental | true 3-D cloud fields from NWP data later; not now |
| DLSS 4.5 plugin (Super Resolution, Ray Reconstruction, DLAA) | 5.4–5.7, 5.8 build listed | beauty pass only; never on a label pass |
| TSR | built-in default upscaler | same rule |

**The build.** Turn on, in `DefaultEngine.ini`, with each setting
recorded in `render.json`: Lumen GI and reflections (software first;
hardware RT when the target card allows), VSM, Nanite on the Landscape
(experimental toggle, measured) and on imported meshes, Substrate.
Re-run `gate6_visual.py`: its four clauses are the regression test
that the new lighting did not break the old measurements, and each
new feature gets one clause of its own (§12). The sky light stays
real-time-captured so the sky atmosphere's colour reaches the ground
bounce; the manual exposure survives as EV100 (§9.7).

**What not to do:** enable everything at once and admire it. Every
switch is a probe render against a control, exactly as the vertex
palette was calibrated in Phase 6B (gotcha 6), because half of these
features change the luminance the existing clauses were tuned on.


### 9.7 Camera and sensor: from "a viewport" to "a camera"

**What the branch has.** A `SceneCapture2D` at a hard-coded FOV with a
manual exposure bias chosen per scene by probe render (gotcha 7). No
lens, no sensor.

**What the best do.** Anyverse runs a spectral path tracer into an ISP
stage; Parallel Domain models the camera as a sensor; Rendered.ai
routes through DIRSIG for thermal. Inside UE the pieces exist:

* **Intrinsics from the spec** (the §1.2 fix): FOV from focal length
  and sensor width; principal point at centre unless stated.
* **Lens distortion**: UE's Camera Calibration plugin stores a
  Brown–Conrady model (K1, K2, P1, P2, K3) in a Lens File and applies
  it as a post-process; UE 5.8's DynamicLens adds focal/focus/f-stop-
  driven distortion, image circle, vignette and bokeh from measured
  grids. The label passes are rendered **undistorted** and the
  distortion is applied to the beauty image *and* to the ID/depth
  images by the same warp in Python (or the verifier undistorts the
  beauty image before grading); the manifest records the coefficients
  so a consumer can do either. That keeps the projection in
  `capture_manifest.json` a pinhole and the checks simple.
* **Physical exposure**: EV100 = log₂(N²/t · 100/ISO) with "extend
  default luminance range" on; the spec's `camera.exposure` becomes
  aperture, shutter and ISO with sensible defaults per preset, and the
  manual bias the branch tunes by hand becomes a computed number. The
  Gate 6 "exposure does not breathe" clause still applies; auto-
  exposure remains the negative control.
* **Motion blur and rolling shutter**: motion blur from the engine
  (velocity-based) on the beauty pass only; rolling shutter has no
  native UE support and is a Python post-pass over the velocity
  buffer if a consumer ever needs it — recorded as not modelled until
  then.
* **Sensor noise as the seeded post-pass the plan describes**: a
  Poisson shot + Gaussian read model with an optional Bayer→demosaic
  stage (the standard "camera pipeline" formulation), consuming the
  `sensor_noise` seed stream that `core/experiments/seeds.py` has
  declared since Phase 7 and nothing has used. It runs after
  verification on the beauty image only, is recorded in the card with
  its parameters and seed, and — like Cosmos in §9.5 — never touches
  the ID or depth images. This is the post-pass the plan says reports
  NOT RUN; on this branch it does not exist, so it is built to that
  contract from the start.
* **EO/IR**: still not claimed (`VALIDITY.md` §2.5). A thermal look
  without radiometry is a lie with a colour map; if it is ever wanted,
  the honest tools are DIRSIG (via Rendered.ai) or MuSES, both
  commercial, both a phase of their own.

### 9.8 The engine version is a decision, and 5.5 is the wrong answer

Everything above assumes an engine newer than the 5.5 the branch pins.
The facts as of 2026-09-24:

| Need | Minimum UE | Note |
|---|---|---|
| Nanite Landscape (experimental toggle, measured) | 5.6+ | still Experimental on Epic's roadmap through 5.7; 5.8 status unverified; 5.8 (June 2026) adds experimental Mesh Terrain |
| Nanite Foliage (dense forests) | 5.7 | Experimental in 5.7 |
| PCG Biome Core | 5.6 | |
| Cesium for Unreal (if used with local tilesets) | 5.6 | v2.29 dropped 5.5 |
| Ultra Dynamic Sky | 5.5–5.8 | v9.7 Aug 2026 |
| Sky Creator | ≤ 5.7 | 1.41.3 |
| Pixel Streaming 2 infrastructure | 5.7 supported, 5.8 current | 5.5 unsupported, 5.6 end-of-life |
| Cosys-AirSim (for reference reading) | 5.8 | v3.5.0 |
| Substrate, MegaLights, Lumen, VSM maturity | see §9.6 | |
| JSBSim plugin (vendored, MIT, four local patches) | "5.0–5.6 stated" | measured on 5.5; the vendor script pins it — a 5.7 build has to be re-measured for the three patched upstream bugs |

**Recommendation: move to UE 5.7.** It is ten months old, every
third-party piece above supports it, and 5.8 is three months old with
its headline terrain feature still experimental. The cost is real and
bounded: rebuild the vendored JSBSim plugin on Windows for 5.7
(`vendor_ue_plugin.ps1` already does this per version), re-run
`check_bridge_api.sh` for the three patched upstream bugs, re-measure
Gate 6 on the target machine (which has to happen on Windows anyway),
and re-probe the two gotchas that were engine-version-sensitive (async
asset compilation in commandlets, Interchange Nanite at import). Do it
in week 1, before any Lane 2 asset lands, so nothing is calibrated
twice.

---

## 10. What the field does that this plan should copy or beat

A short benchmark against the systems that define "state of the art"
in synthetic data in 2026, so each Phase 2 package can say what it
matches and where it goes further.

### 10.1 NVIDIA Omniverse Replicator / Isaac Sim (the reference)

Isaac Sim 6.0 went GA in June 2026 and 6.1 shipped in September; it is
open source on GitHub since 5.0. Its Replicator layer is the reference
design for everything in packages B–G:

* **Annotators**: `rgb`, `distance_to_image_plane` (float depth),
  `semantic_segmentation`, `instance_segmentation`,
  `bounding_box_2d_tight`, `bounding_box_2d_loose`, `bounding_box_3d`,
  `camera_params`, `occlusion` (visibility ratio per instance),
  `normals`, `pointcloud`, `motion_vectors`. The bundle in §3.2 is this
  list, minus normals and motion vectors for now.
* **Writers**: `BasicWriter`, `KittiWriter`, `CocoWriter`, a
  `CosmosWriter` that emits the depth/segmentation/edge sequences Cosmos
  Transfer consumes, and a documented custom-writer path.
* **The KITTI writer's label policy is a floor to beat**: it estimates
  occlusion from the tight/loose box *area ratio* and writes truncation
  as 0.0 because it cannot compute it. The two-pass visibility in
  §3.2 and the unclipped hull box in §3.5 are strictly better, and the
  card should say so.
* **Randomization**: a graph of registered randomizers fired by
  triggers; 6.0 moved to a functional API and added camera-placement
  randomization with an intrinsics/extrinsics/FOV *coverage
  visualization* — the same idea as §5.5's realised-distribution report,
  which this plan already had.
* **Seeds**: `rep.set_global_seed` plus a NumPy generator; NVIDIA does
  not claim bit-identical renders across GPUs, and neither should this
  project (the "reproducible within tolerance" claim in `VALIDITY.md`
  §3 is the right one; what *is* bit-identical is the scenario set and
  the label geometry).
* **Sim-to-real**: Cosmos Transfer conditioned on depth and
  segmentation, gated by Cosmos Evaluator (hallucination and object-
  correspondence checks). §9.5 adopts the pattern with the labels
  re-verified on this side.
* **Scale**: OSMO (Apache-2.0, Kubernetes) and the Physical AI Data
  Factory blueprint. Overkill for one Windows box; the ledger format in
  §6 is kept one-JSON-per-task so it could feed such a thing later.

### 10.2 Unity Perception

Discontinued (README says so; last release 2022). Not a benchmark any
more.

### 10.3 Open-source generators worth stealing from

* **Kubric** (Google): the seed contract is exemplary — `--seed`,
  random if absent, persisted into the scene metadata; the scene is the
  unit of seeding so parallelism only changes scheduling. §6 does the
  same with `SeedSequence([draw_index, campaign_seed])`, which is also
  NumPy's own documented recommendation ("place the varying IDs before
  the unvarying root seed").
* **Infinigen** (Princeton): one seed per scene directory, SLURM
  fan-out via submitit, and `--cleanup big_files` for retention — the
  disk policy §6 asks for, seen in the wild. Infinigen also randomizes
  the *generators* (terrain, weather, vegetation), which is the
  Phase 5 ambition this document pulls partway forward in §9.
* **BlenderProc 2**: depth via ray tracing, COCO and BOP writers, env-
  var seed; no release since October 2024 — a warning about what
  happens to generators that are not products.
* **Cosys-AirSim** (the maintained AirSim fork, v3.5.0 for UE 5.8,
  September 2026): instance segmentation through proxy meshing without
  an engine fork, multi-layer annotation, a "Lighting" image type. It
  is the closest existing UE aerial generator and its segmentation
  approach is worth reading before writing §3.2's ID pass. AirSim,
  Project AirSim and Colosseum are all archived.

### 10.4 Commercial vendors, and the one most like this project

* **Bifrost AI** (satellite and aerial): "pixel-perfect labels and
  scenario metadata"; their published RarePlanes result came from
  *widening the camera-angle randomization range* after finding misses
  at extreme off-nadir angles — the exact loop packages F, G and H
  describe (measure yield per condition bin, adjust the policy, re-run).
* **Rendered.ai**: graph-configured channels, an aerial object-
  detection channel, a channel that inserts 3-D models into real
  satellite imagery (a cheap hybrid worth noting for runway scenes),
  and DIRSIG for thermal — the EO/IR path `VALIDITY.md` §2.5 says does
  not exist here.
* **Parallel Domain**: full label stack plus Cosmos Transfer variants
  of one reconstructed scene, "additive" to the deterministic sim.
* **Duality AI Falcon**: GIS-based aerial environments and a YOLOv8
  tutorial — the "download and it loads in Ultralytics" bar of §12.
* Datagen ceased operations; Synthesis AI was acquired; AI.Reverie
  went to Meta. The survivors all converged on the same shape:
  procedural 3-D for ground truth, a physically based sensor model, a
  generative post-pass for appearance, a verifier gating outputs.

### 10.5 Aerial datasets and papers to calibrate against

LAA3D (Nov 2025; real + synthetic low-altitude aircraft with 6-DoF
poses; synthetic pretraining transfers), the IEEE 2025 air-to-air
detection set (AirSim/UE, nine UAV models, on Kaggle), "Synthetic Data
for Robust Runway Detection" (Oct 2025), LARD, AeroRunway (X-Plane),
SynthAirDrone (April 2026; a four-criterion plausibility score — sky
overlap, lighting consistency, size plausibility, edge continuity —
that §12 borrows the spirit of), AVOIDDS, SkyScenes, RarePlanes. Any
of the public ones with a compatible licence is a candidate for the
200-frame real evaluation set in §13.

### 10.6 Domain randomization: what 2026 says about "varied"

The recent literature is blunt: uniform randomization "offers no
guarantee of distributional coverage" and yields task-irrelevant
samples; physically based lighting randomization matters most for
out-of-distribution transfer; and appearance diversity now comes from
a label-preserving generative pass, with geometry and labels from the
renderer. Coverage is measured, not asserted: per-parameter histograms
of realised draws, per-bin object counts (altitude, off-nadir angle,
sun elevation, weather, object pixel size), and an embedding-space
diversity score such as the Vendi score. §5.5 and the card adopt
exactly this.

### 10.7 Formats and tooling, 2026 versions

* COCO via `pycocotools` 2.0.11; YOLO layout per Ultralytics (YOLO26,
  January 2026, now covers detect, instance and semantic segmentation,
  depth, pose and OBB — the depth head is a reason to export depth
  EXRs in the YOLO tree too); VOC through `torchvision`; KITTI
  truncation float + occlusion 0–3; nuScenes visibility bins 0–40 /
  40–60 / 60–80 / 80–100 as a sensible discretisation of
  `visible_fraction` for the card.
* WebDataset ~1 GB shards; LeRobot v3 chunked Parquet as the streaming
  pattern; **Croissant 1.1** metadata (served by Hugging Face; used by
  most NeurIPS 2025 dataset papers) and the HF dataset card template
  as the card's machine-readable twin.
* **FiftyOne 1.22** for review: mistakenness scoring for label errors,
  native 2-D/3-D label editing, YOLO26 in the zoo. Embedding its app
  in the review screen is the fastest route to a best-in-class gallery.
* The label-quality checks no open tool ships by default — mask-vs-box
  consistency, a tiny-object policy, truncation from the unclipped
  box — are the ones package D builds. That is the gap this project
  fills, and the card should name it.

---

## 11. Sequencing — eight weeks, two lanes, one contract

The plan's ordering argument is kept: nothing in Lane 2 lands before the
Lane 1 gate it depends on is green. But Lane 2 starts on day one,
because asset licensing, terrain streaming and the sky are long-lead
items and none of them touches a label.

| Week | Lane 1 — Truth | Lane 2 — Look | Gate |
|---|---|---|---|
| 1 | Locate or declare absent the students' Phase 10 tree; Windows Gate 6 measured; offset diagnostic; `vrp_actor_cm` + `StructuralFrameOrigin` fix; intrinsics applied; one render command builder | Airframe licensing decision (§9); order or fetch the first licence-clean airliner and GA model; enable Lumen/VSM/Nanite in `DefaultEngine.ini` and re-measure Gate 6 | **A closed**: mask-vs-geometry check passes on all five presets |
| 2 | ID + depth + visibility passes in the commandlet, AA-free; the bundle format; `objects` in the manifest; second aircraft as a scripted actor | Landscape import path (`landscape.py` → UE Landscape, Nanite toggle measured) at 30 m, SVT imagery drape, first PCG vegetation layer from land cover | **B closed**: integer-only ID masks, stable ids across frames, cameras, runs |
| 3 | Boxes, truncation, occlusion, 3-D boxes; every D check with mutation guard and visual sheet | Volumetric clouds + Sky Atmosphere aerosol driven from the spec's visibility and ERA5 cloud layers; cloud shadows | **C + D closed**: `verify` refuses a shifted, blurred, swapped or scaled bundle |
| 4 | Export writers + round-trip tests + card; Parquet/HF | Precipitation, wet surfaces, sea state; physically based camera (exposure from EV, lens distortion, noise) with the sensor stream finally consumed | **E closed**: three formats read back by their own readers |
| 5 | `Source.SAMPLED`, policy schema, prompt vocabulary, re-sample with recorded refusals, realised-distribution report | Liveries (decal/material-layer swap) sampled by the policy; time-of-day and date drive sun, moon, stars | **F closed**: "varied" is a histogram |
| 6 | Campaign object, ledger, worker pool, watchdog, disk budget; 1-vs-4-worker determinism test | Throughput curve at 1/2/4 renderers on the target GPU; DLSS/TSR on the beauty pass | **G closed**: 5,000 frames unattended overnight, identical digests at two worker counts |
| 7 | Typed tool layer over MCP, controller loop, authority limits with adversarial tests, trace | Sim-to-real spot check: 200 synthetic frames vs 200 real aerial frames, FID/KID and a detector trained on synthetic, tested on real (small, honest, labelled as a smoke test not the Phase 5 study) | **H closed**: a scripted rogue agent cannot move a stated field or run a refusal |
| 8 | Message catalogue, preview run with overlays, progress from the ledger, gallery, download; the demonstration document | Final look pass measured from pixels: extinction, cloud shadow presence, wet-surface specular, night exposure — each a Gate 6-style clause | **I closed**: a non-technical tester completes the instructor's script without help |

Two people can run the lanes in parallel; one person runs them
interleaved with Lane 2 items pulled forward only when a Lane 1 gate is
waiting on a render.

## 12. What "perfect" means, so it can be measured

"Ultra-realistic and perfect" is not a feeling; it is the following
list, every line of which is a number produced by a script that can
fail. This is the exit bar this document proposes for Phase 2 on top of
the plan's four criteria.

**Labels**

* ID masks contain only declared integers on 100 % of frames.
* Mask centroid within 2 % of projected span of the projected CG, and
  mask extent within 5 % of the projected hull, on every preset and
  every airframe, at every range up to the stated `not_claimed` limit.
* Tight-box vs hull-box IoU ≥ 0.8 for objects ≥ 64 px; policy stated
  below that.
* Depth under the mask within 1 % + 2 m of the projected CG depth.
* Visibility fraction reproduces a scripted occlusion (one aircraft
  passing behind another) to within 3 % of the analytic overlap.
* Every check has a mutation guard that fires and a visual sheet in
  `build/visual/`.
* Identical scenario set and identical bundle digests at 1 and 4
  workers.

**Look** (each measured from pixels, Gate 6 style; thresholds set by a
first calibration run and then frozen)

* Range-based extinction tracks the spec's visibility: the measured
  contrast ratio at 10 km vs 30 km matches Koschmieder within 15 %.
* Cloud layers appear at the ERA5 base altitude ± 200 m (measured by a
  ray from the camera through the cloud base on the ID/depth passes of
  a cloud-only render).
* Cloud shadows: a shadows-on/off null test darkens ≥ N px of terrain
  under a scripted cloud.
* Wet-surface specular: a rain-on/off null test raises the peak
  luminance of the runway/road band by a stated factor.
* Night: manual exposure holds the sky band within 8/255 across a
  roll sweep at sun elevation −12°.
* Terrain posting ≤ 30 m in view (no 60 m cap), VSM on, no visible
  LOD popping across a 20 s chase clip (frame-to-frame edge delta below
  a threshold on the ID pass).
* Airframe: PBR materials with a measured specular highlight on the
  fuselage in the sun-glint geometry; a livery swap changes ≥ 30 % of
  fuselage pixels and 0 % of ID-mask pixels.
* The sim-to-real smoke test: a detector trained on 5,000 synthetic
  frames reaches a stated AP on 200 real labelled aerial frames, and the
  number is published whatever it is.

**Product**

* One prompt, ≤ 3 questions, a preview with a real overlay, live
  progress, a download that loads in Ultralytics and `pycocotools`
  without edits.
* Every message on the default path is in the catalogue; a test proves
  the catalogue and the `Violation` names are in step.
* The agent's trace explains every decision in one sentence each.

## 13. Decisions only the owner can make

1. **Airframe licences.** FlightGear models are GPL-2.0. A dataset that
   distributes rendered images of a GPL mesh is not clearly a derived
   work of the mesh, but the *project* that ships the mesh in its asset
   pipeline is on much firmer ground with CC-BY / Fab Standard / bought
   licences. Decide: keep GPL meshes for internal runs only and license
   clean ones for anything published, or replace outright.
2. **World data terms.** Google Photorealistic 3D Tiles and most
   commercial imagery tiles forbid offline caching and derived datasets;
   Copernicus Sentinel-2 mosaics and open land cover are clean at 10 m,
   NAIP is clean at 30–60 cm in the US, and 3DEP lidar is clean at 1 m.
   Decide whether the target is "real places, open data, 10 m globally
   and sub-metre where national data exists" or "photogrammetry look,
   commercial terms, no redistribution".
3. **Cesium ion tier.** The Community tier excludes funded research;
   Commercial is a monthly cost. Decide whether Cesium is in scope at
   all or whether the in-house Landscape path is the one to invest in.
4. **The students' Phase 10 tree.** Find it or declare it gone. Merging
   unreviewed code that fails its own checks is a week; rebuilding to
   the bundle contract is two to three, and the result is the same set
   of checks either way.
5. **Hardware.** One Windows box with a 24–32 GB GPU and a fast NVMe
   runs everything here; a second box halves campaign wall time. Decide
   the budget before week 6, because the throughput curve is measured
   there.
6. **The sim-to-real smoke test.** It needs ~200 real, labelled aerial
   frames with a licence that allows evaluation. Decide the source
   (a public aircraft-detection set, or the instructor's own captures)
   in week 1 so it exists by week 7.

---

## 14. Sources

Verified by web search on 2026-09-24 unless marked. Where a vendor page
was unreachable from the research sandbox, the claim rests on a search
result quoting that page or a GitHub mirror and is marked *(snippet)*.

**Unreal Engine versions and features**

* UE 5.8 released 2026-06-17; MegaLights production-ready, Lumen Lite, Procedural Vegetation Editor and Mesh Terrain experimental — https://www.unrealengine.com/news/unreal-engine-5-8-is-now-available ; https://www.cgchannel.com/2026/06/see-5-key-features-for-cg-artists-in-unreal-engine-5-8/ ; https://www.guru3d.com/story/unreal-engine-58-debuts-lumen-lite-and-productionready-megalights/ *(snippet)*
* UE 5.7 (Nov 2025): Substrate and PCG production-ready, MegaLights beta, Nanite Foliage experimental — https://www.unrealengine.com/news/unreal-engine-5-7-is-now-available ; https://tomlooman.com/unreal-engine-5-7-performance-highlights/ ; https://www.cgchannel.com/2025/11/unreal-engine-5-7-five-key-features-for-cg-artists/ *(snippet)*
* UE 5.5: Path Tracer production-ready, reference for atmosphere and volumetric clouds — https://dev.epicgames.com/documentation/unreal-engine/unreal-engine-5-5-release-notes *(snippet)*
* Nanite Landscape experimental on the public roadmap; 5.6/5.7 displacement bug reports — https://portal.productboard.com/epicgames/1-unreal-engine-public-roadmap/c/1176-nanite-landscape ; https://forums.unrealengine.com/t/nanite-landscape-displacement-not-working-ue-5-6-5-7/2686600 ; https://forums.unrealengine.com/t/ue-5-6-landscape-nanite-build-lots-of-bugs-and-problems/2545165
* Water plugin experimental 5.5–5.8 — https://dev.epicgames.com/documentation/unreal-engine/API/PluginIndex/Water *(snippet)*
* Landscape technical limits (16-bit heights, 8129×8129) — https://dev.epicgames.com/documentation/en-us/unreal-engine/landscape-technical-guide-in-unreal-engine
* Streaming and Runtime Virtual Texturing — https://dev.epicgames.com/documentation/en-us/unreal-engine/streaming-virtual-texturing-in-unreal-engine ; https://dev.epicgames.com/documentation/en-us/unreal-engine/runtime-virtual-texturing-in-unreal-engine
* PCG Biome Core — https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-pcg-biome-core-and-sample-plugins-overview-guide-in-unreal-engine
* Volumetric Cloud component — https://dev.epicgames.com/documentation/en-us/unreal-engine/volumetric-cloud-component-in-unreal-engine
* Sky Atmosphere (Hillaire 2020) — https://onlinelibrary.wiley.com/doi/abs/10.1111/cgf.14050 ; https://github.com/sebh/UnrealEngineSkyAtmosphere
* DLSS 4 / 4.5 plugin for UE — https://www.techpowerup.com/338625/nvidia-launches-dlss-4-plugin-for-unreal-engine-5-6 ; https://developer.nvidia.com/rtx/dlss *(snippet)*
* Pixel Streaming 2 infrastructure branches (5.8 current, 5.7 supported, 5.6 EOL, 5.5 unsupported) — https://github.com/EpicGames/PixelStreamingInfrastructure
* Camera Calibration plugin (Brown–Conrady lens files) and DynamicLens — https://dev.epicgames.com/documentation/unreal-engine/camera-lens-calibration-overview ; https://github.com/Dylanyz/DynamicLens
* Physical exposure (EV100) — https://dev.epicgames.com/documentation/en-us/unreal-engine/auto-exposure-in-unreal-engine ; https://www.magnopus.com/blog/lighting-in-unreal-with-photography-principles
* Interchange import formats — https://dev.epicgames.com/documentation/unreal-engine/importing-assets-using-interchange-in-unreal-engine *(snippet)*

**Ground-truth capture in UE**

* MRQ/MRG additional render passes: Object IDs stored per the Cryptomatte spec, world depth, motion vectors — https://dev.epicgames.com/documentation/en-us/unreal-engine/cinematic-render-passes-in-unreal-engine ; https://dev.epicgames.com/community/learning/tutorials/238l/unreal-engine-render-objectids-with-movie-render-graph
* MRG transition guide (temporal vs spatial samples, per-layer renderer) — https://dev.epicgames.com/documentation/unreal-engine/transitioning-to-the-movie-render-graph-from-movie-render-queue-in-unreal-engine
* MRG Object ID manifest-metadata bug — https://forums.unrealengine.com/t/object-id-cryptomatte-bug-in-movie-render-graph/2523030
* Cryptomatte — https://github.com/Psyop/Cryptomatte
* Custom stencil segmentation examples — https://www.mathworks.com/help/driving/ug/apply-labels-to-unreal-scene-elements-for-semantic-segmentation-and-object-detection.html ; https://github.com/rapyuta-robotics/RapyutaSimulationPlugins/pull/359
* SceneCapture segmentation edge artefacts — https://forums.unrealengine.com/t/image-segmentation/444268
* EasySynth (FXAA-at-most rule) — https://github.com/ydrive/EasySynth
* Cosys-AirSim (instance segmentation limits, uncompressed images, image types) — https://github.com/Cosys-Lab/Cosys-AirSim/blob/main/docs/instance_segmentation.md ; https://github.com/Cosys-Lab/Cosys-AirSim/blob/main/docs/image_apis.md ; https://github.com/Cosys-Lab/Cosys-AirSim/blob/main/CHANGELOG.md
* UnrealCV — https://github.com/unrealcv/unrealcv ; NVIDIA NDDS (dormant, UE 4.2x) — https://github.com/NVIDIA/Dataset_Synthesizer
* Colosseum archived 2026-07-11 — https://github.com/CodexLabsLLC/Colosseum ; Project AirSim continuation — https://github.com/iamaisim/ProjectAirSim
* Kubric per-instance visibility — https://github.com/google-research/kubric/blob/main/challenges/movi/README.md
* MRQ command-line rendering, Python host executor — https://dev.epicgames.com/documentation/en-us/unreal-engine/using-command-line-rendering-with-move-render-queue-in-unreal-engine ; https://github.com/leixingyu/unrealRenderFarm/blob/master/requestWorker.py
* `-nullrhi` yields empty captures — https://github.com/carla-simulator/carla/blob/dev/Docs/adv_rendering_options.md
* `-deterministic` flag — https://gpuopen.com/learn/unreal-engine-performance-guide/ *(snippet)*
* Multiple UE processes per GPU (Sept 2026 pipeline paper) — https://arxiv.org/pdf/2609.03557 *(snippet)*

**Synthetic-data platforms and research**

* Isaac Sim 6.0 GA (2026-06-08), 6.1, Replicator functional API — https://github.com/isaac-sim/IsaacSim/discussions/538 ; https://github.com/isaac-sim/IsaacSim/discussions/655 ; https://github.com/isaac-sim/IsaacSim/releases
* Replicator annotators and writers — https://github.com/isaac-sim/IsaacSim/blob/main/skills/data-collection-sim/SKILL.md ; https://docs.omniverse.nvidia.com/extensions/latest/ext_replicator/custom_writer.html
* KITTI writer occlusion/truncation policy — https://docs.omniverse.nvidia.com/py/replicator/1.5.1/source/extensions/omni.replicator.core/docs/API.html *(snippet)*
* Cosmos Transfer 2.5 and Cosmos 3 — https://github.com/nvidia-cosmos/cosmos-transfer2.5 ; https://www.hpcwire.com/aiwire/2026/06/01/nvidia-launches-cosmos-3-the-open-frontier-foundation-model-for-physical-ai/ ; Cosmos Evaluator — https://github.com/nvidia-cosmos/cosmos-evaluator
* OSMO — https://github.com/NVIDIA/OSMO
* Unity Perception discontinued — https://github.com/Unity-Technologies/com.unity.perception
* BlenderProc 2 — https://github.com/DLR-RM/BlenderProc/releases ; Kubric — https://github.com/google-research/kubric ; Infinigen — https://github.com/princeton-vl/infinigen ; https://arxiv.org/abs/2406.11824
* Bifrost AI RarePlanes result — https://www.bifrost.ai/blog/geospatial-benchmark *(snippet)* ; NTT DATA PoC — https://www.nttdata.com/global/en/insights/focus/2025/055
* Rendered.ai aerial and SatRGB channels — https://rendered.ai/generate-synthetic-data-for-aerial-object-detection-with-rendered-ai/ *(snippet)*
* Parallel Domain + Cosmos Transfer — https://paralleldomain.com/parallel-domain-and-nvidia-cosmos-transfer-additional-scene-variation/ *(snippet)*
* Duality AI Falcon — https://www.businesswire.com/news/home/20250410838504/en/
* Aerial datasets: LAA3D — https://arxiv.org/html/2511.19057 ; air-to-air detection — https://ieeexplore.ieee.org/abstract/document/11163828/ ; runway detection — https://arxiv.org/abs/2510.20349 ; LARD — https://arxiv.org/abs/2304.09938 ; SynthAirDrone — https://www.mdpi.com/2504-446X/10/4/306 ; AVOIDDS — https://arxiv.org/abs/2306.11203 ; SkyScenes — https://arxiv.org/pdf/2312.06719 ; RarePlanes — https://ar5iv.labs.arxiv.org/html/2006.02963
* Domain randomization: structured DR — https://arxiv.org/html/1810.10093v1 ; lighting matters most — https://arxiv.org/pdf/2210.12682 ; semantically guided DR (Sept 2026) — https://arxiv.org/html/2609.26505 ; Vendi score — https://www.emergentmind.com/papers/2210.02410 ; "Measure Dataset Diversity" — https://arxiv.org/pdf/2407.08188
* Formats: pycocotools — https://pypi.org/project/pycocotools/ ; Ultralytics detect format and YOLO26 — https://raw.githubusercontent.com/ultralytics/ultralytics/main/docs/en/datasets/detect/index.md ; https://www.ultralytics.com/news/ultralytics-redefines-state-of-the-art-vision-ai-with-yolo26 ; VOC via torchvision — https://docs.pytorch.org/vision/main/generated/torchvision.datasets.VOCDetection.html ; KITTI fields — https://docs.cvat.ai/docs/dataset_management/formats/format-kitti/ ; nuScenes visibility bins — https://github.com/nutonomy/nuscenes-devkit/blob/master/docs/schema_nuscenes.md ; WebDataset — https://github.com/webdataset/webdataset ; Croissant — https://github.com/mlcommons/croissant ; HF dataset card — https://github.com/huggingface/datasets/blob/main/templates/README_guide.md
* FiftyOne 1.22 — https://pypi.org/project/fiftyone/ ; https://docs.voxel51.com/tutorials/detection_mistakes.html
* NumPy parallel seeding guidance — https://github.com/numpy/numpy/blob/main/doc/source/reference/random/parallel.rst

**World data and licences**

* Copernicus DEM on AWS — https://copernicus-dem-30m.s3.amazonaws.com/readme.html ; https://registry.opendata.aws/copernicus-dem/ ; accuracy — https://www.mdpi.com/2072-4292/15/10/2509
* USGS 3DEP — https://registry.opendata.aws/usgs-lidar/ ; swisstopo OGD — https://www.swisstopo.admin.ch/en/free-geodata-ogd ; AHN — https://zenodo.org/records/22201281
* Copernicus Data Space quarterly cloudless mosaics — https://dataspace.copernicus.eu/news/2026-3-16-clear-skies-zero-clouds-weve-processed-full-sentinel-archive-seamless-monthly-s1-and ; Sentinel licence — https://www.copernicus.eu/en/access-data/copyright-and-licences
* EOX cloudless licences (2016 vs later) — https://eox.at/2025/03/sentinel-2-cloudless-2024/
* NAIP — https://github.com/awslabs/open-data-registry/blob/main/datasets/naip.yaml
* Google Map Tiles policies (no ML, no offline) — https://developers.google.com/maps/documentation/tile/policies ; https://cloud.google.com/maps-platform/terms/maps-service-terms ; Cesium's Google terms — https://cesium.com/legal/terms-for-google/
* Mapbox Product Terms (Oct 2025) — https://cdn.prod.website-files.com/609ed46055e27a02ffc0749b/68dddd2815cb3d82685f0096_Mapbox%20Product%20Terms%20(October%201,%202025).pdf ; Bing Maps shutdown/terms — https://blogs.bing.com/maps/2025-06/Bing-Maps-for-Enterprise-Basic-Account-shutdown-June-30,2025
* Cesium ion terms (no offline storage), archives/exports — https://cesium.com/legal/terms-of-service/ ; https://cesium.com/learn/ion/cesium-ion-archives-and-exports/ ; Cesium for Unreal changelog (5.5 dropped in 2.29) — https://github.com/CesiumGS/cesium-unreal/blob/main/CHANGES.md
* ESA WorldCover — https://github.com/awslabs/open-data-registry/blob/main/datasets/esa-worldcover-vito.yaml ; Esri/IO LULC — https://www.esri.com/about/newsroom/arcnews/latest-land-cover-data-release-shows-more-change-over-time
* OSM ODbL FAQ — https://osmfoundation.org/wiki/Licence/Licence_and_Legal_FAQ ; Overture — https://github.com/awslabs/open-data-registry/blob/main/datasets/overture.yaml ; Microsoft building footprints — https://github.com/microsoft/GlobalMLBuildingFootprints/blob/main/README.md
* Quixel/Megascans on Fab (Megaplants free) — https://quixel.com/news/quixel-on-fab-new-megascans-and-megaplants *(snippet)*
* Ultra Dynamic Sky / Weather (real sun-moon-stars, wetness functions) — https://github.com/kevinpbuckley/unreal-engine-skills/blob/master/skills/ultra-dynamic-sky/ue-uds-simulation/SKILL.md ; listing — https://www.fab.com/listings/84fda27a-c79f-49c9-8458-82401fb37cfb
* Sky Creator — https://dmkarpukhin.com/sky-creator/
* MSFS 2024 weather and streaming — https://business.meteoblue.com/articles/microsoft-flight-simulator-partnership-meteoblue ; https://msfsaddons.com/2024/09/19/microsoft-flight-simulator-2024-fully-detailed-a-comprehensive-look-at-the-next-gen-sim/ *(snippet)* ; X-Plane 12 clouds — https://flyawaysimulation.com/news/4997/
* Open-Meteo upper air — https://openmeteo.substack.com/p/upper-air-weather-forecasts-via-api ; ERA5 — https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=overview ; HRRR — https://github.com/awslabs/open-data-registry/blob/main/datasets/noaa-hrrr-pds.yaml ; METAR API — https://aviationweather.gov/data/api/
* Koschmieder visibility–extinction — https://arxiv.org/pdf/1908.10335
* Pierson–Moskowitz sea state — https://www.sciencedirect.com/topics/engineering/pierson-moskowitz-spectrum
* JSBSim releases (1.3.1, 2026-05-17) and licensing discussion — https://github.com/JSBSim-Team/jsbsim/releases ; https://github.com/JSBSim-Team/jsbsim/discussions/631 ; FlightGear aircraft GPL — https://wiki.flightgear.org/FGAddon
* Aircraft asset licences: NASA 3D Resources — https://www.nasa.gov/3d-resources/ ; OpenVSP Airshow — https://airshow.openvsp.org/ ; Sketchfab CC guidelines — https://sketchfab.com/developers/download-api/guidelines ; Fab EULA and NoAI — https://www.fab.com/eula?lang=en ; https://forums.unrealengine.com/t/new-eula-ai-restriction/2068913 ; TurboSquid ML clause — https://www.turbosquid.com/licensing *(snippet)*
* Sensor noise models — https://arxiv.org/pdf/1904.08825 ; https://arxiv.org/html/2512.15905
* 3DGS in UE: XV3DGS — https://github.com/xverse-engine/XV3DGS-UEPlugin ; Volinga — https://www.cgchannel.com/2026/08/volinga-plugin-pro-lets-you-relight-4dgs-data-inside-unreal-engine/ ; plugin support table — https://radiancefields.com/3d-gaussian-splatting-engine-support
* Label alignment under diffusion translation — https://arxiv.org/html/2505.16360 ; https://arxiv.org/pdf/2602.09476

**Agent runtimes, LLM tiers, UI, orchestration**

* Claude API structured outputs (GA) and MCP connector — https://platform.claude.com/docs/en/build-with-claude/structured-outputs ; https://platform.claude.com/docs/en/agents-and-tools/mcp-connector ; Python SDK — https://pypi.org/project/anthropic/
* Claude Agent SDK: custom tools, permissions order, hooks, user input, sessions — https://code.claude.com/docs/en/agent-sdk/custom-tools ; https://code.claude.com/docs/en/agent-sdk/permissions ; https://code.claude.com/docs/en/agent-sdk/hooks ; https://code.claude.com/docs/en/agent-sdk/user-input ; https://code.claude.com/docs/en/agent-sdk/python
* Auto-mode classifier design — https://www.anthropic.com/engineering/claude-code-auto-mode ; evals for agents — https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents ; building effective agents — https://www.anthropic.com/engineering/building-effective-agents ; writing tools for agents — https://www.anthropic.com/engineering/writing-tools-for-agents
* Pydantic AI deferred tools / approvals — https://github.com/pydantic/pydantic-ai/blob/main/docs/deferred-tools.md ; OpenAI Agents SDK human-in-the-loop — https://github.com/openai/openai-agents-python/blob/main/docs/human_in_the_loop.md ; Google ADK plugin ordering issue — https://github.com/google/adk-python/issues/4910 ; LangGraph interrupts — https://docs.langchain.com/oss/python/langgraph/interrupts *(snippet)*
* OpenTelemetry GenAI agent spans — https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md ; OpenInference Claude Agent SDK instrumentation — https://github.com/Arize-ai/openinference/tree/main/python/instrumentation/openinference-instrumentation-claude-agent-sdk
* Least privilege for agents (Microsoft, 2026-07-16) — https://www.microsoft.com/en-us/security/blog/2026/07/16/least-privilege-for-ai-agents-identity-access-and-tool-binding/
* Local models and constrained decoding: Qwen3.5 — https://github.com/QwenLM/Qwen3.5 ; Ollama API `format` schema — https://github.com/ollama/ollama/blob/main/docs/api.md ; vLLM no native Windows — https://github.com/vllm-project/vllm/blob/main/docs/getting_started/installation/gpu.md ; XGrammar — https://github.com/mlc-ai/xgrammar ; llguidance — https://github.com/guidance-ai/llguidance ; Outlines — https://github.com/dottxt-ai/outlines ; Instructor — https://github.com/567-labs/instructor
* UI: AG-UI protocol — https://github.com/ag-ui-protocol/ag-ui ; CopilotKit — https://github.com/CopilotKit/CopilotKit ; assistant-ui — https://github.com/assistant-ui/assistant-ui ; Vercel AI SDK 6 — https://github.com/vercel/ai/releases/tag/ai%406.0.0 ; sse-starlette — https://pypi.org/project/sse-starlette/ ; htmx 2 — https://github.com/bigskysoftware/htmx/releases/tag/v2.0.0 ; Tailwind v4 — https://github.com/tailwindlabs/tailwindcss/releases/tag/v4.0.0 ; shadcn/ui — https://ui.shadcn.com/docs/tailwind-v4 ; NiceGUI in FastAPI — https://github.com/zauberzeug/nicegui/blob/main/examples/fastapi/main.py ; Konva — https://github.com/konvajs/konva
* MessageFormat 2.0 — https://github.com/unicode-org/message-format-wg ; Python Fluent runtime (stale) — https://pypi.org/project/fluent.runtime/
* Orchestration on Windows: Ray beta — https://github.com/ray-project/ray/blob/master/doc/source/ray-overview/installation.md ; Celery no Windows — https://github.com/celery/celery/blob/main/docs/faq.rst ; RQ SpawnWorker — https://github.com/rq/rq/blob/master/docs/docs/workers.md ; Temporal Python SDK — https://github.com/temporalio/sdk-python ; Prefect — https://github.com/PrefectHQ/prefect ; Dagster joining Prefect — https://dagster.io/prefect *(snippet)*
