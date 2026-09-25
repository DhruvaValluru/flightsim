# Phase 2 contracts — the shapes every package shares

*Working document for the Phase 2 build (branch `claude/relaxed-cori-gccjvx`,
the clone the brainstorm calls `phase2`). One place for every cross-package
shape: file formats, spec and manifest versions, the refusal names, the
campaign and trace files, the tool schema, the message catalogue. A
package implements against this page; a change to a shape is a change to
this page first. Where the brainstorm (`docs/PHASE2_BRAINSTORM.md`) decided
a shape, this page states it concretely; where the code on this branch
already had one (the Phase 10 tree), this page keeps it and says so.*

*This revision was checked line by line against the subsystem maps and
the critique (2026-09-25, HEAD 40fbfe3). Every place the first draft
invented a name the code already had, the code's name now stands; every
place the draft's design was not implementable as written, the simplest
honest alternative stands and the reason is on the page. §13 lists each
change with its evidence.*

*Status column: **kept** (existed on the branch, unchanged), **extended**
(existed, gains keys), **new**.*

---

## 0. Version bumps — one each, for the whole phase

| Document | Was | Now | First field that forces it |
|---|---|---|---|
| `spec_version` (`core/scenario/spec.py` L56) | 7 | **8** | `scene.terrain_source` (package A), `taxonomy` (B), `traffic` (B), `randomization.policy` (F), `cameras[].exposure` (Look) |
| `manifest_version` (`core/capture/manifest.py` L181, `SUPPORTED_MANIFEST_VERSIONS` L186) | 5, reads (3, 4, 5) | **6**, reads (3, 4, 5, 6) | `objects[]` (B) and `labels.objects[]` per frame (C) |
| `mesh_manifest.json` `version` (`assets_pipeline/convert.py` `MESH_MANIFEST_VERSION` L86) | 2 (eb5c71d: VRP-based origin) | **3** (origin measured from vertices, §0.1) | `mesh_origin_basis = "measured from vertices"`, `mesh_extent_actor_m` |
| `render.json` (commandlet) | additive | additive | `drawn` (done, eb5c71d), `labels.id`/`labels.objects[]`, `render_settings`, `look_applied`, `applied_*` on every frame |
| `docs/schemas/capture_manifest.v5.schema.json` | v5 only | **v6 published**, v5 kept | — |

**How a spec bump is done (the mechanics, as every earlier bump did it).**
`ScenarioSpec.from_dict` refuses any other version with
`ValueError("spec_version 7 is not supported by this build (expects 8).
Refusing to guess at the schema.")` — a `ValueError`, not a `Violation`;
there is no `spec.version` constraint name in the code today (spec.py
L260-265; tests match the sentence: `tests/test_scenario_spec.py` L86,
`test_camera_spec.py` L60, `test_camera_profile.py` L199-210). The bump
touches: `SPEC_VERSION` and the comment block at spec.py L30-55 (one dated
line per version, kept); every `examples/*.yaml` (all eight say
`spec_version: 7` today and are regenerated at 8, not hand-edited);
the three version tests above (and the stale docstring at
test_scenario_spec.py L57-58, which still says 6); `core/nl/compiler.py`
`compile_prompt` defaults for each new field; `core/nl/llm_compiler.py`
`FIELD_VALUE_SCHEMAS` (import-time assert against `FIELD_ORDER`, L251-253);
`core/scenario/card.py` projection; `docs/PHASE2_BRAINSTORM.md` L105
(says 6). Every digest changes with the version field, by design.
The catalogue (§8) keys the refusal sentence under the NEW name
`spec.version`; the code keeps raising `ValueError`.

**How a manifest bump is done.** `MANIFEST_VERSION`, the `SUPPORTED`
tuple, `docs/schemas/capture_manifest.v6.schema.json` (the validator
refuses keywords outside `core/capture/schema.py` `SUPPORTED_KEYWORDS`
L32-36 — no `oneOf`, no `format`), `tests/test_capture_schema.py`,
`tests/test_camera_labels.py` L343-354, the mutation guard for manifest
versions in `scripts/mutation_check.sh`, `SIDECAR_CONTEXT_KEYS`
(manifest.py L566, gains `objects`), and `webapp/static/index.html` L1186
which hard-codes the v5 schema link (frames.html L268 builds it from
`payload.manifest_version` and needs nothing). A version-5 manifest still
reads; `verify_json_schema` reports NOT RUN for a supported older version
with no published schema (verify.py L2182+), and every Phase 2 check
reports NOT RUN on it. `read_capture_manifest` refuses other versions with
`ValueError`, surfaced as the `manifest_version` FAIL check (verify.py
L2302).

**How the mesh manifest bump is done.** `assets_pipeline/importer.py`
`stale_manifest_reason` (L122-145) already treats `version <
MESH_MANIFEST_VERSION` as stale and `ensure_model`/`scripts/import_aircraft.py`
re-convert (40fbfe3); bumping to 3 is what makes every VRP-based
version-2 manifest on the Windows box re-convert. `core/capture/verify.py`
`DRAWN_MESH_MIN_MANIFEST_VERSION` (L1718) goes to 3 and `drawn_airframe`
also grades `drawn.origin_basis` (§4). The pins in
`tests/test_aircraft_assets.py` L311-323 (`-1327 * 2.54`) and L343-345
(`"VRP" in mesh_origin_basis`) are rewritten to the measured rule.

### 0.1 The mesh origin rule — measured from vertices, not a VRP convention

Contract decision (critique `offset_root_cause`). The FlightGear meshes
were built for their OWN repositories' FDMs (FGMEMBERS/747-400's own
`747-400.xml` has VRP (1263, 0, 0) in; the staged `B747.xml` has VRP = CG
= (1327, 0, −24) in), so "the model origin is the staged FDM's VRP"
(eb5c71d, `MESH_ORIGIN_BASIS` convert.py L88-97) is the wrong FDM for two
of three airframes. Measured with the repository's own reader
(`assets_pipeline.acmodel.parse_ac` + `world_vertices` + `ac_to_ue`) on
the pinned `.ac` files, in the UE actor frame (+X forward) about the
model origin:

| Airframe | forward extreme (nose) | aft extreme (tail) | x-span | `labels.dimensions_m.length` |
|---|---|---|---|---|
| B747 (`747-400_fuselage.ac`, 2529 verts) | **+29.80 m** | −41.14 m | 70.94 m | 70.66 m (0.4 %) |
| A320 (`res/fuselage.ac`, 10312 verts) | **−2.53 m** (origin is AHEAD of the nose) | −40.09 m | 37.57 m | 37.57 m (0 %) |
| c172p (`c172-common.ac`, 27791 verts) | **+2.14 m** | −6.09 m | 8.23 m | 8.28 m (0.6 %) |

The rule, written into `assets_pipeline/convert.py` (replacing
`fdm_vrp_actor_cm` as the source of the number; the VRP stays recorded
as `vrp_actor_cm`, informational):

* `mesh_origin_actor_cm.x` aligns the mesh's forward extreme with the
  airframe labels' **nose keypoint**, converted structural → actor by
  `(−x, y, z)` in inches × 2.54 (the plugin's `StructuralToActorMatrix`
  about its zero origin, `JSBSimMovementComponent.cpp` L754-764; the
  keypoint comes from `core/capture/airframe.py` `load_airframe`, which
  reads it as `fdm_contact` or `structural_in`): `x = nose_actor_cm.x −
  100 · nose_extreme_m`. B747: nose `structural_in [0, 0, −24]` (basis
  `estimate`) → `x = 0 − 2980 = −2980 cm` (eb5c71d wrote −3370.6: 3.9 m
  aft of its label). A320: `NOSE_TIP` contact at structural x = 0 → `x =
  0 − (−253) = +253 cm` (eb5c71d: −1679, a 19.3 m error). c172p:
  `NOSE_SKID` at x = −37.7 in → `x = 95.8 − 214 = −118 cm` (eb5c71d: −108,
  within 0.1 m).
* `mesh_origin_actor_cm.z` aligns the mesh's **lowest gear vertex** with
  the FDM's main-gear contact z (`LEFT_MLG`/`RIGHT_MLG` for B747 and
  A320, `LEFT_MAIN`/`RIGHT_MAIN` for c172p, structural → actor as above)
  where gear parts are identifiable in the model (the 747's
  `747-400_gear.ac` objects are; where they are not, the VRP z is used
  and the manifest says so).
* `mesh_origin_actor_cm.y = 0`.
* `mesh_origin_basis = "measured from vertices"`; the manifest also
  records `mesh_extent_actor_m: {x: [min, max], y: [min, max], z: [min,
  max]}`, `origin_anchor: {x: "nose keypoint <basis>", z: "main-gear
  contact" | "vrp"}`, and the vertex counts, so the number is never
  separated from the measurement that produced it.
* Refusal **`aircraft.mesh_extent`** (a `ConvertError` with that
  constraint, exit 2 on `scripts/import_aircraft.py`) when the mesh
  x-span disagrees with `labels.dimensions_m.length` by more than 5 %:
  the mesh is then not the airframe the labels describe, and the
  config's `model_origin_offset_m` cannot fix it.
* `model_origin_offset_m` (config, default 0) is kept as the documented
  per-airframe correction on top of the measured origin, exactly as
  convert.py L174-184 reads it today.

Consequence for the verifier: `drawn_airframe` (§4) fails a mesh drawn
with `origin_basis` other than `"measured from vertices"` or a manifest
version below 3, and `mask_vs_geometry` is the pixel check that would
have caught the residuals (a 3 m mutation barely catches the B747's 3.9 m
and would miss nothing on the A320's 19.3 m — which is why the basis is
graded by name as well).

---

## 1. The per-frame ground-truth bundle (packages B, C, D; Look lane)

Written by the render commandlet under `frames/<camera_id>/`, one set per
delivered frame, all from the SAME camera pose in the SAME tick. Frame
names are `frame_%04d` (manifest.py L375-383; the brainstorm's `%06d` is
not used anywhere and is not adopted). The beauty image may use any
anti-aliasing and every visual effect; the label passes use **none**
(rule §3.3 of the brainstorm: `r.AntiAliasingMethod 0`, no temporal
history, screen percentage 100, show flags off for fog, atmosphere,
bloom, motion blur, DOF, lens flare, translucency; each label
`USceneCaptureComponent2D` carries its own `ShowFlags` and
`bAlwaysPersistRenderingState = false` — today the depth captures inherit
engine defaults, commandlet L1742-1768, and their edge behaviour was
never measured).

| File | Format | Content | Status |
|---|---|---|---|
| `frame_NNNN.png` | sRGB 8-bit RGBA (alpha forced 255; `SCS_FinalColorLDR` → `RTF_RGBA8_SRGB`, commandlet L1103-1108) | beauty (training image) | kept |
| `frame_NNNN_linear.exr` | float32 RGBA of `SCS_FinalColorHDR`, optional (`-linear`) | linear beauty | kept |
| `frame_NNNN_mask.png` | **8-bit grey PNG**, one integer per pixel = the object's `int_id`; 0 = background/unlabelled; NO other values | the ID image, from the Custom Stencil pass (§2.3). Today it is the aircraft-alone depth-agreement silhouette with the single value 1; the primary aircraft is composed first so its `int_id` is 1 and every existing reader (`verify.AIRCRAFT_INSTANCE_ID = 1`, L1511; `frames.html` legend) stays true on single-aircraft runs | kept name, extended semantics |
| `frame_NNNN_class.png` | 8-bit grey PNG | `class_id` per pixel (0 sky/none, then the taxonomy's ids) — today 0 sky / 1 aircraft / 2 terrain-or-other | kept, ids from the taxonomy |
| `frame_NNNN_depth.f32` | raw little-endian float32, row-major, `width*height` values, metres, `+inf` for sky (the engine reads back `SCS_SceneDepth` as float centimetres already, L1711-1723; written with `FFileHelper::SaveArrayToFile`) | metric depth from the AA-free depth capture | new |
| `frame_NNNN_depth.png` | 16-bit grey, `metres = value * depth_scale_m` (0.1), saturating at `depth_saturation_m` (6553.5; geometry beyond 50 km counts as sky) | the viewer-friendly depth, kept for old consumers | kept |
| `frame_NNNN_alone_<int_id>.png` | 8-bit grey PNG | the ID pass rendered with ONLY that object visible (its unoccluded footprint) — one per labelled object of class `aircraft` (scene objects — terrain, buildings — get no alone pass, `pixels_alone: null`) | new (generalises the aircraft-alone `ShowOnlyActors` depth pass, L1265) |
| `frame_NNNN_sensor.png` | 8-bit sRGB | the seeded sensor post-pass output (Python, `core/capture/profile.py`) | kept |
| `render.json` | JSON, ASCII only | root + `frame_records[]` (`frames` is an INTEGER count — read the array through `verify._render_frame_records`) | extended |

**Why raw float32 and not EXR for depth.** OpenEXR is not a dependency of
this repository (`requirements.txt`) and must not become one for the
verifier to run on every machine: `core/capture/profile.py` L521-539
already falls back from the `-linear` EXR to inverting the 8-bit sRGB PNG
because `import OpenEXR` fails. A raw float array needs no library on
either side (`numpy.fromfile`) and loses nothing; the export writers
convert it to EXR or 16-bit PNG for consumers that want those, and the
dataset card says which. The format is the contract, not the commandlet.

**Why 8-bit and not 16-bit for the ID image.** The Custom Depth Stencil is
8 bits wide, so a scene is refused (`annotation.identity`, §2.3) beyond
255 ids anyway; an 8-bit grey PNG is what the commandlet's grey writer
(L187-196, `ERGBFormat::Gray`, any bit depth) produces today for
`_mask.png`, and `verify._read_gray_png` (Pillow → numpy) reads either.
A 16-bit file would promise a range the producer cannot fill.

**`render.json` per-frame `labels` object** — the existing keys are kept
verbatim (commandlet L1860-1873; `_engine_label_records` reads
`mask`/`class_mask`/`depth`, verify.py L1644-1665); the new keys are added
beside them. The verifier reads this record; nothing is inferred from
file names.

```json
"labels": {
  "mask": "frame_0001_mask.png",                 // kept: now the ID image
  "class_mask": "frame_0001_class.png",          // kept
  "depth": "frame_0001_depth.png",               // kept
  "depth_scale_m": 0.1, "depth_saturation_m": 6553.5,   // kept
  "silhouette_pixels": 51002, "visible_pixels": 48211,  // kept: the PRIMARY's alone-pass and ID-pass counts
  "occlusion_fraction": 0.055,                   // kept: 1 - visible/silhouette (L1867), i.e. 1 - visible_fraction of the primary
  "classes": "0 sky, 1 aircraft, 2 terrain",     // kept key; the string is generated from the taxonomy
  "method": "custom-stencil ID pass, AA off; alone pass per aircraft",   // kept key, new text
  "depth_f32": "frame_0001_depth.f32",           // new
  "anti_aliasing": "none",                       // new: what the label captures ran with
  "objects": [                                   // new
    {"int_id": 1, "pixels": 48211, "pixels_alone": 51002,
     "alone_png": "frame_0001_alone_1.png", "visible_fraction": 0.945,
     "occluded_by": [2], "depth_min_m": 412.3, "depth_median_m": 421.7},
    {"int_id": 2, "pixels": 610044, "pixels_alone": null,
     "alone_png": null, "visible_fraction": null,
     "occluded_by": [], "depth_min_m": 1.2, "depth_median_m": 2210.0}
  ]
}
```

`visible_fraction = pixels / pixels_alone` (geometric only) — the same
quantity the commandlet already writes as `1 − occlusion_fraction` for the
primary, now per object and from ID passes rather than a 5 cm depth
agreement. Atmospheric transmittance is analytic and lives in the Python
label record (§3), never folded into `visible_fraction`.

**As landed (package C, commandlet, UNCOMPILED here):** the per-frame
`labels` object also carries `id_source` (`"card objects[]"`, or the
Phase 10 default pair when the card has none -- stated, never silent),
`unlabelled_geometry_pixels` (geometry with no stencil: id 0, class 0)
and `non_integer_id_pixels` (readback floats that were not whole
numbers: an AA-free pass gives 0; anything else is a measurement the
verifier grades). `occluded_by` in render.json is a list of INTEGER
ids (the Python record resolves them to strings). The root gains
`objects[]` (the ids this pass wrote) and `traffic[]` (each traffic mesh
drawn: `mesh_airframe`, `fdm`, `license`, `manifest_version`,
`origin_basis`, `track`, `range_m`). The ID pass needs the post-process
material `/Game/FlightSim/M_CustomStencilID`; absent, `-labels` refuses
by name rather than writing an ID image from anything else.

**`render.json` root additions:** `drawn` (done, eb5c71d, commandlet
L2123-2150: `{kind: "mesh" | "placeholder", mesh_origin_actor_cm: [x, y,
z] | null, manifest_version: int | null, origin_basis: str, triangles?:
int}`), `render_settings` (every rendering console variable the
commandlet set or read, by its `r.` name, via
`IConsoleManager::Get().FindConsoleVariable()` — AA method per pass,
Lumen, VSM, Nanite, screen percentage, exposure mode and EV100, RHI and
shader model), `look_applied` (the weather/sky parameters actually
applied, §5.4). The root `camera_preset` is hard-coded `"LaggedChase"`
today (L2068) — fixed to the real preset (`scene.camera_preset` is the
truthful one). The per-frame `applied_focal_length_mm`,
`applied_sensor_width_mm`, `applied_fov_deg`, `applied_width_px`,
`applied_height_px` (L2024-2031) are written on EVERY frame, not only when
the card carried landmarks, so the verifier can project without
guessing.

---

## 2. Identity and the taxonomy (package B)

### 2.1 Spec: `taxonomy` (spec 8, optional, provenance like every field)

The spec's sections today are `aircraft`, `initial`, `environment`, `run`
(+ `cameras`, `randomization`); `taxonomy`, `traffic` and `scene` (§12)
are NEW top-level blocks. They are serialised like `randomization`, not
like `cameras`: an absent block is canonical and omitted from `to_dict`,
so the digest of a spec that states none of them is unchanged by
construction. `ScenarioSpec.from_dict` tolerates unknown top-level keys
(spec.py L266-273), which is exactly why the version must bump: a v7
reader would silently drop them.

```yaml
taxonomy:
  classes:            # ordered; class_id = position + 1; 0 is reserved (sky/none)
    value: [aircraft, terrain, building, vegetation, water, cloud]
    source: default
    from: the documented class list
```

`cloud` is a class in the visibility record only (volumetrics write no
ID). A dataset's categories come from this list, never from what happened
to be in the scene (today `export_coco` makes one category per airframe
name, export.py L311-316).

### 2.2 Spec: `traffic` (spec 8, optional) — the second aircraft

```yaml
traffic:
- aircraft: {value: A320, source: user, from: "an A320 crossing"}
  track:    {value: crossing, source: user, from: "crossing"}   # formation | crossing | overtaking
  range_m:  {value: 400.0, source: default, from: documented traffic default}
  livery:   {value: default, source: default, from: ...}
```

A scripted actor flown along a pre-solved `PoseTrack` (`core/capture/poses.py`
L298, the camera machinery applied to an actor, carried on the card as
`traffic[].poses` in the same block shape as `cameras[].poses`); no second
FDM. `FFlightSimScenarioWorld::Populate` (L938-1020) holds exactly one
aircraft today and is generalised to one FDM actor plus N scripted mesh
actors. Its mesh must be imported like the primary's — the existing
refusal `aircraft.mesh` (`webapp/runs.py` `refuse_placeholder_mesh`
L795-878, `flightsim/capture.py` L196-232) applies to every traffic
airframe, and the commandlet's own mesh/FDM pairing refusal (L269-290)
is per actor.

### 2.3 Object ids

* `id` — stable string: `aircraft:<fdm>:<n>` (n = 0 primary, 1.. traffic
  in spec order), `terrain`, `building:<n>`, `vegetation:<n>`. Composed in
  Python (`core/capture/objects.py`, new) from the spec; the engine never
  invents one.
* `int_id` — small integer assigned in composition order starting at 1
  (the primary aircraft is always first, so `int_id = 1` keeps every
  Phase 10 reader true); the same spec composes the same list, so it is
  stable across frames, cameras and runs of one spec. The card carries
  the list (`objects[]`, read by `FFlightSimScenarioWorld::ReadCard`); the
  commandlet sets each labelled component's
  `SetRenderCustomDepth(true)` + `SetCustomDepthStencilValue(int_id)`
  (both `UPrimitiveComponent` API, 5.5 and 5.7) and refuses
  (`annotation.identity`) a scene needing more than 255. This requires
  `r.CustomDepth=3` under `[/Script/Engine.RendererSettings]` in
  `ue/Config/DefaultEngine.ini`, which today carries NO renderer settings
  at all (25 lines), and a post-process material (built by
  `scripts/ue_create_materials.py`, like `M_VertexColor`) emitting
  `SceneTexture:CustomStencil` into the ID capture.
* `class_id` — from the taxonomy (position + 1).

### 2.4 Manifest 6: `objects[]` and `label_conventions`

```json
"objects": [
  {"id": "aircraft:B747:0", "int_id": 1, "class": "aircraft", "class_id": 1,
   "instance": 0, "role": "primary", "mesh_sha256": "…", "licence": "GPL-2.0",
   "in_scene": true, "labelled": true},
  {"id": "terrain", "int_id": 2, "class": "terrain", "class_id": 2,
   "instance": 0, "role": "scene", "mesh_sha256": null, "licence": null,
   "in_scene": true, "labelled": true}
]
```

A missing label is thereby distinguishable from a missing object.
`label_conventions` (labels.py `conventions()` L384-405) gains `id_mask`,
`alone_pass`, `depth_f32` and `visible_fraction` sentences; the existing
`camera_frame`, `body_frame`, `bbox_2d`, `truncation`,
`keypoint_in_frame`, `corner_order`, `horizon`, `projection_matrix`
sentences are kept. `objects` joins `SIDECAR_CONTEXT_KEYS` so every
`frame_NNNN.json` sidecar carries it.

**As landed (packages B + C, `core/capture/objects.py`, manifest 6) --
three shape additions this page left open, stated so the other packages
implement against what exists:**

* Two more top-level manifest keys beside `objects[]`: `taxonomy` (the
  spec's ordered class list, so a reader resolves `class_id` without
  the spec) and `traffic[]` (one block per scripted aircraft: `id`,
  `int_id`, `aircraft`, `track`, `range_m`, `livery`, `spec`,
  `track_digest`, its cited `airframe` in the same shape as the
  top-level `airframe`, and `attitude_basis`). Both join
  `SIDECAR_CONTEXT_KEYS`. `simulation_digest` drops `taxonomy` (§12);
  `traffic` stays in it (a second aircraft is in the scene the pixels
  show).
* The run card carries the same three blocks: `objects[]` verbatim,
  `taxonomy` (a list of names) and `traffic[]` (§2.2's block plus
  `mesh_manifest` -- the imported manifest path or null -- and
  `cg_actor_cm`, the airframe's CG in the UE actor frame, `(-x, y, z)
  * 2.54` of `cg_structural_in`, so the host places the mesh actor's
  origin at `CG - R * cg` exactly as it places the FDM actor). Absent
  blocks are absent: a card of a spec with no traffic is byte-identical
  in every key it had.
* `label_conventions` also gains `objects`, `bbox_2d_tight` and
  `bbox_2d_hull` sentences.

---

## 3. Boxes, depth, occlusion — the per-object label record (package C)

Manifest 6, per frame, `labels.objects[]` (Python-computed). The existing
`labels` keys for the primary airframe are kept exactly as the v5 schema
requires them — `bbox_2d`, `bbox_2d_unclipped`, `truncation`, `in_frame`,
`bbox_3d_camera`, `keypoints`, `horizon` (labels.py `bbox_labels`
L170-223, `keypoint_labels` L227-244; schema `$defs/frame_record/
properties/labels.required`) — and the primary's entry is the first
element of `objects[]`, with the same key names:

```json
{"id": "aircraft:B747:0", "int_id": 1, "class_id": 1,
 "bbox_2d": [u0, v0, u1, v1],                 // kept: the OVERALL extents box (nose-to-tail x span x height), clipped
 "bbox_2d_unclipped": [u0, v0, u1, v1] | null, // kept: may leave the frame; null when a corner is behind the camera
 "truncation": 0.0..1.0 | null,               // kept: 1 - clipped area / unclipped area
 "in_frame": true,                            // kept
 "bbox_2d_tight": [u0, v0, u1, v1] | null,    // new: from the ID mask; null when no pixels
 "bbox_2d_hull": [u0, v0, u1, v1] | null,     // new: the mesh extent (mesh_manifest v3 mesh_extent_actor_m) projected; the box mask_vs_geometry grades against
 "visible_fraction": 0.0..1.0 | null,         // new: copied from render.json labels.objects[]
 "occluded_by": ["aircraft:A320:1"],          // new: int_ids resolved to ids through objects[]
 "atmospheric_transmittance": 0.0..1.0,       // new: exp(-beta * range_m) along the CG ray; beta = fog_density (1/m, the existing randomisation unit) or 3.912 / (1000 * visibility_km) when the policy states visibility
 "depth_projected_m": 421.4,                  // new: CG depth through the manifest (bbox_3d_camera.cg_m[2])
 "depth_min_m": 412.3, "depth_median_m": 421.7,   // new: from the depth image under the mask
 "bbox_3d_camera": {…},                       // kept: centre_m, extents_m [forward, right, down], body_axes_in_camera, corners_m (order: for x in (aft, fwd), for y in (left, right), for z in (top, bottom)), cg_m
 "keypoints": {…}, "horizon": {…},            // kept (primary only)
 "not_claimed": ["subpixel_mask_accuracy_beyond_range_m: 8000", "objects_under_px: 12"]}
```

The draft's `fraction_in_frame` is dropped: it is `1 − truncation` by the
existing definition.

**As landed (package C, `labels.object_label_record` /
`attach_engine_labels`):** every entry has the SAME key set (a scene
object -- the terrain -- carries `null` for `bbox_2d`,
`bbox_2d_unclipped`, `truncation`, `in_frame`, `bbox_2d_hull`,
`atmospheric_transmittance`, `depth_projected_m`, `bbox_3d_camera`, `{}`
for `keypoints`; `horizon` is `null` on every non-primary entry), plus
one more key, `basis`: `{bbox_2d_hull, atmospheric_transmittance,
engine}` -- the sentence behind each derived value. Before a render
`basis.engine` is the no-bundle sentence and the five engine-derived
keys are null; `attach_engine_labels(run_dir)` (a post-render Python
step, numpy over the ID image, the alone pngs and the depth `.f32`)
fills them in place in the manifest and every sidecar and sets
`basis.engine` to `{files, pixels, pixels_alone, method}`. `keypoints`
are carried for every aircraft object (from its own airframe), not only
the primary; `labels_sensor.objects[]` carries every non-primary
aircraft's sensor mapping. The ID image (`_mask.png`) holds every
`int_id`, so on a single-aircraft run its terrain pixels are `2`;
`AIRCRAFT_INSTANCE_ID = 1` readers are unaffected. KITTI `occluded` (export.py L389-392, always 3 today
because no producer writes `engine_labels`) is derived from
`visible_fraction` (≥ 0.95 → 0, ≥ 0.5 → 1, else 2; null → 3).

Tolerances are stated once, as `#:`-documented module constants in
`core/capture/verify.py` beside the existing `MASK_CONTAINMENT_MIN` /
`DEPTH_RANGE_SLACK_M` block (L1497-1511) — NOT in `labels.py`: the
verifier does not import the producer (module docstring L1-40; the two
existing exceptions, `verify_projection_matrix` and
`verify_sensor_undistortion`, are not to be extended). `labels.py` may
import the numbers from `verify.py` if it needs them for `not_claimed`.

| Quantity | Tolerance |
|---|---|
| tight box vs projected hull box | IoU ≥ 0.8 for objects ≥ 64 px extent; ≥ 0.5 for 16–64 px; not claimed under 16 px |
| mask centroid vs projected CG | ≤ 2 % of the projected span |
| mask extent vs projected hull | ≤ 5 % of the projected hull |
| depth under mask vs projected CG depth | ≤ 1 % + 2 m, growing with the airframe's length |
| visible fraction vs scripted occlusion | ≤ 3 % of the analytic overlap |

---

## 4. Verifier checks and refusal names (package D)

Each check: a `Check(name, status, detail)` with status in `PASS` /
`FAIL` / `NOT RUN` (verify.py L75-89; names are flat snake_case like every
existing check), NOT RUN without its evidence (never a pass on a
tautology), a mutation guard in `scripts/mutation_check.sh`, a visual
sheet from `tests/visual/annotation_sheets.py` (new directory) under
`build/visual/`. `Check.to_dict()` gains one optional key, `failure`: the
catalogue name below, present only on FAIL (readers — `index.html`
L1250-1262, `export.py` L492-494, `batch.py` L270-274 — read by key and
tolerate it). Today the FAIL name lives only in the detail text.

| Check (verify.py) | Evidence | `failure` name | Sheet | Status |
|---|---|---|---|---|
| `drawn_airframe` (done, L1743; between `keypoints_in_box` and `label_files` in `verify_run`) | `render.json.drawn` | `aircraft.placeholder_drawn`; also FAIL on `manifest_version < 3` or `origin_basis != "measured from vertices"` | contact sheet with the drawn kind stamped | extended |
| `mask_integers_only` | histogram of `_mask.png` vs `objects[].int_id` | `annotation.mask_blend` | offending pixels highlighted | new |
| `mask_vs_geometry` | ID-mask centroid/extent vs projected CG/hull, through the verifier's own `_body_point_enu` + `project_point` | `annotation.mask_offset` | mask edge + hull + CG cross | new — the check that exposes the offset |
| `box_vs_mask` | tight vs projected hull box IoU | `annotation.box_mismatch` | both boxes | new (supersedes `mask_containment`, which is kept per-object for v5 runs) |
| `depth_vs_geometry` | `depth_min`/`depth_median` under the mask vs projected CG depth | `annotation.depth_range` | heatmap + predicted | new (supersedes `depth_range`, kept for v5 runs) |
| `visibility_vs_scene` | alone-pass vs ID-pass counts; every id in `occluded_by` exists in `objects` | `annotation.visibility` | side by side | new |
| `identity_stable` | same `id`→`int_id` across frames, cameras, runs of one spec | `annotation.identity` | id strip | new |
| `applied_intrinsics` | `render.json` `applied_focal_length_mm` / `applied_fov_deg` / `applied_width_px` / `applied_height_px` vs the record's `focal_length_mm`, `width_px`, `height_px` (0.1° of FOV) | `annotation.intrinsics` | — | new (these keys are read by no check today) |
| `label_files` (kept, L1672) | every declared file exists | `annotation.files` | — | extended for the new files |

Mutations that must fail (the visual test applies each and asserts):
shift the mesh origin by 3 m; swap two ids; blur the ID image; scale depth
by 1.02; hide the occluder in the full pass; FOV off by 1°. Every new
`mutate` entry uses a multi-line, file-unique old-string: `mutate()` does
`str.replace(old, new, 1)`, and the 12-space `if gap > tol:` guard at
script L1026-1029 silently disables the 16-space clause at verify.py L557
instead of the chase clause at L603 (critique; fix that entry first).

The verifier does not import the producer. `verify_run`'s check order is
the order in `verification.json` and on the page; the new checks are
appended after `depth_range` and before `sensor_undistortion`.
`VerificationReport.ok` is True with every check NOT RUN (an unrendered
run exports); a format that ships masks refuses in `export.load_run`
(`export.unverified_labels`, new) when `mask_integers_only` or
`mask_vs_geometry` is NOT RUN — the verifier itself never turns NOT RUN
into FAIL.

**Contract decision (b): `pose_matches_spec` keeps its tolerance.** A
chase/wingman camera is graded at each record's `t_s` against the
KEYFRAMED offset interpolated from the spec's `moves` by the verifier's
own `_keyframed_scalar` (verify.py L452, L474-646; commit 7118a0c "a
keyframed move is the station a chase camera is graded against"), with
`tol = max(50.0, 1.5 * |offset|)` metres in the heading-only frame
(L596) — the keyframes are the contract, and the lag (`POSITION_LAG_S`
0.45 s on a linear goal) is what the 50 m floor and the 1.5× factor
absorb. The brainstorm's "5 % of commanded distance, min 2 m" is NOT
adopted: a 2 m floor would fail every lagged camera at airliner speed.
`tests/test_camera_verify.py` L214-266 reproduces the Phase 1 172.1 m vs
166.0 m failure by monkeypatching `_keyframed_scalar` and stays.

---

## 5. Randomization policy and the look coupling (package F)

### 5.1 Provenance

`Source.SAMPLED = "sampled"` joins the enum at `core/scenario/fields.py`
L28-41 (`user > inferred > model > derived > default`; SAMPLED sits
between `inferred` and `model`: a sampled field is as fixed as a user
field once drawn — never re-planned). Today the sampler writes draws as
`Source.DERIVED` (randomization.py L161-164). The plannable rule is
hand-copied in FOUR places and every copy must exclude SAMPLED:
`spec.py` L220-225, `camera.py` L214-220, `randomization.py` `PLANNABLE`
L83, `webapp/runs.py` `PLANNABLE_SOURCES` L465. `detail = {policy,
distribution, seed, draw_index}` (detail keys are flat siblings in the
serialised Quantity and digest-relevant, fields.py L106-107).

Fix first: `Violation.render()` crashes (`ValueError: Unknown format code
'g' for object of type 'str'`) whenever `validate_randomization` passes a
string `limit`/`actual` (validate.py L274-277, L285-289, L302-304;
re-confirmed on HEAD). Every refused draw is rendered, so numeric limits
(or None) with the range in the message come before any policy work.

### 5.2 Policy schema (spec 8 `randomization.policy`, optional)

The existing block is kept as leaves of the same mapping. Its 20 keys are
exactly (`RandomizationSpec.FIELD_ORDER`, randomization.py L126-134):
ranges `enabled`, `seed`, `year`, `day_of_year_min`, `day_of_year_max`,
`hour_utc_min`, `hour_utc_max`, `sun_elevation_min_deg`,
`fog_density_min`, `fog_density_max`, `camera_jitter_m`,
`camera_jitter_deg`, `camera_focal_jitter`; sampled `day_of_year`,
`hour_utc`, `sun_elevation_deg`, `sun_azimuth_deg`, `exposure_bias`,
`fog_density`, `livery`. `from_dict` refuses unknown keys (L191-195) and
`is_default()` compares against `defaulted()`, so `policy` is a new,
defaulted key of that block (absent block still omitted from `to_dict`,
spec.py L252-253 — old digests unchanged). The card/manifest block
(`card_block`, L476-507) keeps its keys — `seed`, `year`, `day_of_year`,
`hour_utc`, `sun_elevation_deg`, `sun_azimuth_deg` (compass),
`engine_sun_azimuth_deg` (`= (90 − compass) % 360`, the commandlet's
`-sun-azim`), `exposure_bias`, `fog_density`, `livery`, `solar_source`,
`camera_jitter` — and gains one entry per sampled policy leaf.

```yaml
randomization:
  seed: {value: 20260924, source: user, from: "seed 20260924"}
  policy:
    location:       {choice: [rockies, alps, cascades, flint_hills], weights: [3,3,2,1]}
    weather_date:   {uniform_dates: ["2024-01-01", "2024-12-31"]}
    hour_local:     {uniform: [5.5, 20.0]}
    sun_elevation_min_deg: 2
    visibility_km:  {lognormal: {median: 25, sigma: 0.6}, clip: [1, 80]}
    cloud_cover:    {beta: [2, 2]}
    precipitation:  {choice: [none, rain, snow], weights: [7,2,1], gated_by: "cloud_cover > 0.6"}
    wind_speed_kt:  {weibull: {k: 2.0, lambda: 12}}
    turbulence:     {choice: [none, light, moderate, severe], weights: [4,3,2,1]}
    surface:        {choice: [grassland, desert, forest, city, ocean]}
    aircraft:       {choice: [A320, B747, c172p]}
    livery:         {choice: [default]}
    traffic_count:  {poisson: 0.7, max: 2}
    cameras:
      preset:          {choice: [chase, tower, wingman, ground]}
      focal_length_mm: {loguniform: [24, 400]}
      offset_jitter_m: {normal: {sigma: 5}}
```

Distributions: `choice`, `uniform`, `loguniform`, `normal`, `lognormal`,
`beta`, `weibull`, `poisson`, `uniform_dates`, with `clip` and `gated_by`
(today only uniform / log-uniform / choice exist, L309-450). Every leaf
maps to an existing typed field (`environment.wind_speed`, `turbulence`,
`surface`, `weather_date`, `aircraft.aircraft`, `cameras[].preset` /
`focal_length_mm`, the jitter fields) or one added in this bump
(`visibility_km`, `cloud_cover`, `cloud_base_m`, `precipitation`,
`hour_local`, `location`, `traffic_count`). `location` draws from
`core/terrain/glo30.py` `LOCATIONS` keys; a name with no bake in that range
is refused (`randomization.location`, new). Draws go through `validate()`;
a refused draw is recorded as `{draw_index, refusal_name, sampled_values}`
and re-drawn up to `max_attempts` (20) before the slot is
`randomization.infeasible`. Seeds: per draw
`numpy.random.SeedSequence([draw_index, campaign_seed])` (§6); the block's
own `derive_block_seed` sha256 stream (L241-246) stays for the Phase 10
leaves so `examples/randomized.yaml` samples identically.

### 5.3 Prompt vocabulary

`core/nl/compiler.py` has NO randomization phrases today (probe: "varied
weather … random viewpoints" compiles to an all-default spec with empty
notes); a `RANDOMIZATION_WORDS` table beside `CAMERA_VIEW_WORDS` (L316) and
an `_randomization(text)` extractor after `_cameras` (L632-637) are new.
`core/nl/llm_compiler.py`: `RANDOMIZATION_FIELD_VALUE_SCHEMAS` with an
import-time assert against the policy leaves (mirror L275-279), a bounded
`randomization` key in `RESPONSE_SCHEMA` (L304-345; `response_shape_sentence`
then says five keys by itself), and the LITERAL key set in `_parse_payload`
L611-613 edited (it does not read `RESPONSE_TOP_LEVEL_KEYS`).

| Phrase | Policy |
|---|---|
| "varied weather" | cloud_cover, visibility_km, precipitation defaults |
| "different times of day" / "dawn and dusk only" | hour_local uniform / bimodal |
| "across the Rockies" / "over the Alps" | location choice restricted to that range (refused `randomization.location` until a bake in that range exists in `LOCATIONS`) |
| "mixed traffic" | traffic_count |
| "random viewpoints" | cameras block |
| "varied lighting" | hour_local + weather_date |
| anything else asking to vary | refused `randomization.vocabulary`, sentence quoted |

### 5.4 Look coupling — `core/scene/weather_visuals.py` (new, one table)

The draft's nine new commandlet flags are replaced by ONE card block: the
engine consumes what the CARD carries (`FFlightSimScenarioWorld::ReadCard`,
L86-544, already reads `randomization.livery`), and a render pass should
read one record, not a flag list rebuilt by thirteen callers (§9). The
four existing flags (`-sun-elev=`, `-sun-azim=`, `-fog-density=`,
`-exposure-bias=`, commandlet L656-676; set from `render_look`) stay for
back-compatibility and are overridden by `card.look` when present.

| Spec value | `card.look` key | Engine parameter |
|---|---|---|
| `visibility_km` | `fog_extinction_per_m` (β = 3.912 / (1000 · V)), `aerosol` | `UExponentialHeightFogComponent::FogDensity` (today `-fog-density`, default 0.0025), `USkyAtmosphereComponent` Mie scattering scale |
| `cloud_cover`, `cloud_base_m`, `cloud_top_m` (per layer; from Open-Meteo/ERA5 for `weather_date`, the fetch `core/environment/era5.py` already makes for wind) | `clouds: [{cover, base_m, top_m}]` | `UVolumetricCloudComponent` layer bottom altitude / thickness, coverage through the cloud material; cloud shadows on |
| `precipitation` | `precipitation`, `wetness` (0..1) | visibility floor and a `Wetness` scalar on the terrain and airframe materials (roughness/specular). Particles are NOT drawn this phase: no Niagara rain/snow asset exists in `ue/Content`, and building one is a Look-lane item with its own Gate 6 clause — `not_claimed: ["precipitation_particles"]` |
| `hour_local`, `weather_date`, lat/lon | `sun_elevation_deg`, `sun_azimuth_deg` (compass), `engine_sun_azimuth_deg` | the existing `SunLight` rotation (`FRotator(-elev, azim+180, 0)`). Night sky: sun below the horizon only; moon and stars are `not_claimed` (no asset, no API in the scene builder) |
| `wind_speed_kt`, direction | `cloud_drift_mps` | `UVolumetricCloudComponent` material wind offset per tick |
| `cameras[].exposure` (§10) | `ev100` | manual exposure `AEM_Manual` with `CameraShutterSpeed` / `CameraISO` / `DepthOfFieldFstop` (replaces `AutoExposureBias`, `FFlightSimVisualScene::ApplyManualExposure` L571-584) |

Each row is recorded in `render.json.look_applied` and measured once from
pixels (Gate 6 pattern) in `experiments/gate6_visual.py` clauses.

### 5.5 Realised distribution

`campaigns/<id>/report.json` histograms every sampled field over frames
that exported, beside the requested distribution, with `coverage` =
fraction of policy bins holding ≥ k frames. Source of truth per run: the
manifest's `randomization` block (already copied into every manifest and
sidecar, manifest.py L545-548) plus `conditions`.

### 5.6 As landed (package F) -- the shape decisions this page left open, and three departures

Stated here so the campaign (G), the tools (H), the page (I) and the
Look lane implement against what exists.

* **`Source.SAMPLED` joins `core/scenario/fields.py`** (not `spec.py`:
  the enum lives in fields.py, §5.1 was right). It is absent from all
  four plannable rules and from `fields.PLANNABLE_SOURCES` by
  construction (they list members, not exclusions). **Only policy draws
  are `sampled`**; the seven Phase 10 leaves stay `derived` with their
  sha256 streams, so `examples/randomized.yaml` samples to the same
  bytes and digest (pinned).
* **The block's spec-8 leaves are per-field absent-canonical**:
  `visibility_km`, `cloud_cover`, `cloud_base_m`, `precipitation`,
  `hour_local`, `location`, `traffic_count` and the draw record
  `policy_draws` are optional on read and omitted from `to_dict()` while
  at their placeholder, so a Phase 10 block keeps its 20 keys, its bytes
  and its digest. `policy` stays on `ScenarioSpec.randomization_policy`
  as stage 1 put it (file shape unchanged).
* **Leaves** (`randomization.POLICY_LEAVES`, the one table the LLM schema
  is generated from and asserted against): the §5.2 list plus
  `wind_direction_deg`; `cloud_top_m` is NOT a leaf (derived in the look
  table as base + a stated thickness; Open-Meteo serves no base or top
  and `era5.py` was not extended -- the wind request does not return
  cloud layers, and adding variables to it is an unmeasured network
  change). `hour_local` admits `choice` over named windows (`dawn 5.5-8`,
  `morning`, `midday`, `afternoon`, `dusk 17-20`, local mean time by
  longitude) -- how "dawn and dusk only" is expressed in the nine forms.
  `location` choices are bake keys OR range names (`LOCATION_RANGES`:
  alps, sierra_nevada, himalayas, colorado_plateau, great_plains, japan,
  rockies, cascades); a range with no bake refuses `randomization.location`.
  `traffic_count` is recorded on the block; it does NOT instantiate
  `traffic[]` entries (an entry needs an airframe, B's shape).
* **Seeds**: `SeedSequence(entropy=[draw_index, campaign_seed],
  spawn_key=(attempt, stable_hash(leaf)))`, PCG64, one stream per leaf
  and attempt; the campaign seed is the block's own seed; the recorded
  `seed` detail is the folded integer (1..MAX_SEED).
* **The refusal record** is `{draw_index, attempt, refusal_name, message,
  sampled_values}` (two keys more than §5.2), kept on the block's
  `policy_draws` field (`{draw_index, attempts, max_attempts, refused,
  seed_derivation, campaign_seed}`) and in the card; an exhausted slot's
  `RandomizationError("randomization.infeasible")` carries the same list
  in `.detail["refusals"]` and the spec is left exactly as given.
* **Stated fields**: a top-level leaf over a user/inferred-stated target
  refuses `randomization.policy` by name (a draw never moves a stated
  value); inside the `cameras` group a stated camera field is skipped
  with a note, the Phase 10 jitter's rule, so a named view keeps its
  view while its lens still varies. A drawn `location` moves
  latitude/longitude/terrain_elevation; a DEFAULTED altitude keeps its
  height above the ground the draw moved (a recorded plan).
* **The vocabulary refusal** is raised by the sampler from a record the
  compiler writes (`randomization_policy.detail["unmapped"]`, the quoted
  sentences), not by `compile_prompt` itself: that is how it reaches the
  page's verdict, `/run`, the capture command and a batch through the
  existing wrappers without a new surface. The LLM tier's parser refuses
  leaf shapes by name (`compile.rejected`); an EMPTY model block falls
  back to the deterministic vocabulary (the control).
* **The look block lands at `card.randomization.look`**, not `card.look`:
  `card.py` is not F's file and the engine already reads the card's
  `randomization` object (`ReadCard`, livery). Lifting it to `card.look`
  is one line in `write_run_card` for the Look lane. The card block also
  gains `policy` (the requested distribution, for §5.5) beside the
  per-leaf entries and `policy_draws`.
* **`realised_distribution(runs, policy=None, k=1, bins=8)`** reads each
  run's `capture_manifest.json` (`randomization` + `frames`); numeric
  leaves bin over the REQUESTED support (clip / uniform bounds / [0,1]
  for beta) else the observed range; `coverage` per leaf and overall
  (mean over leaves with a requested distribution). The picture is
  `python -m core.scene.realised_plot`.

---

## 6. Campaign files (package G) and export layouts (package E)

### 6.1 The campaign directory — grown from `core/dataset/batch.py`

The batch runner exists (P10-6): `flightsim.batch <matrix.yaml> --out DIR
[--workers N] [--no-resume] [--dry-run]`, `DIR/batch.json`,
`DIR/ledger.jsonl`, `DIR/<run_id>/` with `run_id = spec.digest()[:16]`
taken AFTER `sample_randomization` (batch.py L214-225, mutation-guarded).
The campaign keeps every existing ledger key and adds to it; a campaign
directory is a batch directory that also carries `campaign.json`.

```
campaigns/<id>/
  campaign.json      prompt, answers, compiled spec digest, policy, images_target, seed,
                     state: planned|running|paused|failed|done|cancelled, workers,
                     disk_budget_bytes, created_utc, format, tier (LLM tier used),
                     git (commit, branch, dirty, dirty_files -- as batch.json)
  ledger.jsonl       one line per case, append-only (ResultLog, flushed per line,
                     tolerant of a truncated last line; keyed on case_id):
                     KEPT from batch.py run_case: run_id, case_id (== run_id), spec_digest,
                       seed, run_dir, command, capture_exit, wall_seconds, ok,
                       verified, verification {ok, passed, failed, not_run}, error
                     NEW: index, status: sampled|refused|running|rendered|verified|failed,
                       refusals: [names], frames, yield, simulation_digest, output_digest,
                       solve_source, bundle_digest (sha256 over render.json
                       frame_records[].sha256, repro.engine_digests), started_utc,
                       finished_utc, reason
  control.json       {"request": "pause"|"resume"|"cancel"} written by the UI/CLI; polled by workers between cases
  trace.jsonl        the agent's tool calls (§7)
  report.json        yield, coverage, realised distributions, refusals by name, timing
  runs/<case_id>/    ordinary run directories (spec.yaml, capture.log, capture_manifest.json,
                     frames/, verification.json -- exactly what run_case leaves today)
```

* Rows are appended in COMPLETION order today (as_completed, batch.py
  L364-365), so two ledgers at different worker counts differ line for
  line; the 1-vs-4 test compares the row SET keyed on `case_id` and the
  per-case `bundle_digest`. Workers pull cases by `index` from a queue
  (replacing submit-all, L361-363); a refused draw is a ledger row with
  `status: refused` (today a sampler refusal aborts `build_cases`
  entirely, L220-224).
* Per-case seed: `numpy.random.SeedSequence([index, campaign_seed])`
  (the matrix's literal `seeds` list stays for `flightsim.batch`).
* Resume keeps batch semantics: a row with `ok: true` is skipped whether
  or not verified (a failed verification is a finding, not a retry); a
  failed capture is retried and appends a NEW line (L319-323).
* `capture_command` (L236-248) gains `terrain`/`synth_terrain` in
  `CAPTURE_OPTIONS` (L63-64) so a mountain case can run at all, and
  forwards `-deterministic` (accepted by the commandlet, passed by no
  caller today).
* Disk: budget from a measured sample render × items against
  `shutil.disk_usage`, refused by name (`storage.budget_exceeded`) before
  starting and re-checked per batch; `verification.json` is written
  atomically (tmp + `os.replace`; `write_verification` uses
  `Path.write_text` today, L2359).
* A campaign that cannot reach its target ends `failed` with `reason`
  (`campaign.target_unreachable`), never `done` at a lower count.
* CLI: `python -m flightsim.campaign "<prompt>" --images N --out DIR
  [--workers W] [--seed S] [--format coco] [--resume] [--pause|--cancel]`
  (new; `flightsim.batch` stays).

### 6.2 Export layouts (package E) — kept, extended

`core/dataset/export.py` `FORMATS = ("coco", "kitti", "webdataset",
"yolo", "voc")` (landed, package E);
`flightsim.export RUNS... --out DIR --format F[,F...] [--split 0.8,0.1,0.1]
[--split-seed 0] [--image ideal|sensor] [--labels-only] [--shard-size 1000]`
(one format writes into `DIR` as before; a comma list writes
`DIR/<format>/` each, with ONE card at `DIR`; the card records `formats`
and `layout`);
`load_run` refuses `export.unverified` (no `verification.json`) and
`export.verification_failed` (any FAIL); the runs of one export must
carry one class list -- a run naming a taxonomy beside one that does not,
or two different lists, refuses `export.taxonomy` (landed, package E:
the class list is the manifests' `taxonomy` / `objects[]` when present,
else the sorted airframe names as Phase 10 wrote COCO categories); splits by `simulation_digest`
(drops prompt, notes, cameras AND randomization — two runs differing only
in look land in one split, by design); sample key
`<run>_<camera_id>_<index:04d>`. Kept layouts:

* COCO: `images/<split>/<key>.png`, `annotations/instances_{train,val,test}.json`
  (all three always written); categories today one per airframe with the
  seven `KEYPOINT_NAMES`; **extended**: categories from the taxonomy, one
  annotation per `objects[]` entry, `segmentation` as uncompressed RLE
  computed in Python from `_mask.png` (no `pycocotools` in
  `requirements.txt`; it is an optional round-trip test dependency only).
* KITTI: `<split>/image_2/`, `label_2/` (15 fields; `occluded` from
  `visible_fraction`, §3, instead of the constant 3), `calib/`
  (P0..P3, R0_rect, Tr_*).
* WebDataset: `<split>/shard-NNNNNN.tar`, members `<key>.png` then
  `<key>.json` (sidecar + `export: {labels, split}`); **extended** with
  `<key>.mask.png`, `<key>.class.png`, `<key>.depth.f32`; image members
  written from bytes with `mtime=0`/`uid=0` so with-pixels shards are
  byte-reproducible (today `tar.add(path)` leaks the source mtime).
* **New** writers over the same `Sample`: YOLO (`images/<split>/`,
  `labels/<split>/<key>.txt` normalised `class cx cy w h` from the
  clipped `bbox_2d`, 0-based class index in taxonomy order, `data.yaml`
  with `path`/`train`/`val`/`test`/`names`), Pascal VOC -- **as landed
  (package E)**: the devkit layout at ONE root, `JPEGImages/<key>.png`,
  `Annotations/<key>.xml`, `ImageSets/Main/{train,val,test}.txt` (the
  draft's `<split>/JPEGImages` is not what `torchvision`/the devkit read;
  the split lives in the ImageSets lists), `bndbox` 1-based inclusive
  integers covering the float box (`floor+1 .. ceil`), `truncated` =
  `fraction_in_frame < 1` when a record carries that key else
  `truncation > 0`, `occluded` = `visible_fraction < 0.9` (the plan's
  threshold; 0 when no visibility was recorded, stated in the card),
  `difficult` = the clipped box's longer side under the not-claimed
  pixel threshold (the record's `objects_under_px: N`, else
  `NOT_CLAIMED_EXTENT_PX = 16`). The reader keys on the PRESENCE of
  `labels.objects[]`, not the manifest version; a mask on disk that
  `mask_integers_only` / `mask_vs_geometry` did not PASS refuses
  `export.unverified_labels` for `coco` and `webdataset` only (the
  formats that ship it); a run with no mask on disk is unaffected.
* Card: `dataset.json` + `DATASET_CARD.md` (`dataset_card` L469-529)
  gain class balance, the realised histograms (§5.5), per-asset licences
  from `objects[]`, `render.json` `drawn`/`render_settings`/`look_applied`
  provenance, and `not_claimed` aggregated per frame; `label_conventions`
  is taken from `runs[0]` today (L521) and becomes per-manifest-version.

---

## 7. The tool layer and authority limits (package H)

`core/agent/tools.py` (new; no `core/agent` exists) — typed functions
with JSON schemas (served over MCP by `core/agent/mcp_server.py` when the
optional `mcp` package is present — it is not in `requirements.txt` and
must not become required; callable directly by the tests and the
controller without a model):

```
compile(prompt, answers?)             -> {spec, questions, refusals}   # core.nl.llm_compiler.compile_prompt_llm / compiler.compile_prompt, then the planners now sequenced only in webapp/server.py compile_endpoint L242-280 (moved to a core-level compile-and-plan function)
plan_campaign(spec, words, images)    -> {policy, estimate}
sample(campaign_id, n)                -> {cases, refused}
run(case_id, validation_token)        -> {run_id, status}              # core.dataset.batch.run_case
render(run_id, validation_token)      -> {frames, drawn}
verify(run_id)                        -> {checks, verdict}             # verify_run(run_dir).to_dict(); NOT RUN is not a verdict
export(campaign_id, format)           -> {dataset_path, card}          # core.dataset.export.export
inspect(run_id, frame?)               -> {overlay_png, records}
report(campaign_id)                   -> {yield, coverage, refusals}
```

Authority, enforced in `core/agent/policy.py` (deterministic, no model):

| Rule | Refusal |
|---|---|
| no write to a field whose source is `user`, `inferred` or `sampled` — the tool layer exposes `plan()` (which already refuses those, spec.py L220-225) and never `set()` (which forces `user`, L174-197) | `authority.stated_field` |
| `run`/`render`/`export` need a `validation_token` minted by `validate()` for that spec digest (`ValidationReport.spec_digest`, validate.py L64-96) | `authority.validation_token` |
| a spec carrying a refusal is denied for `run` with the catalogue sentence | `authority.refusal_is_not_a_run` |
| budgets: max tool calls, max re-samples per slot, max wall time | `authority.budget` |

`trace.jsonl`: one line per call `{t, tool, input, output, reason, policy}`.
The controller loop (`core/agent/controller.py`) plans from the request,
calls tools, reads results, re-samples only system-chosen fields, and
escalates in catalogue language. It never writes `capture_manifest.json`
(only `build_capture_manifest` may) or `verification.json` (only
`write_verification`), and never alters `solve_source`. A scripted rogue
agent in the tests tries each violation and is denied.

---

## 8. The message catalogue and the interface (package I)

* `core/messages/catalog.yaml` (new; no `core/messages` exists): every
  refusal name and every progress state → `{sentence, hint?}` with
  `{param}` placeholders; the rule name is kept beside the sentence.
  `core/messages/__init__.py render(name, **params)`. The names it must
  cover are the ones the code emits today (§11 lists them) plus this
  phase's; the shapes they arrive in are three: the `Violation` dict
  `{constraint, message, actual, limit, unit}` (validate.py L38-53;
  `webapp/runs.py` emits the same five keys as a plain dict), the
  `.constraint` attribute of `RandomizationError`, `PoseSolveError`,
  `ScheduleError`, `AirframeLabelError`, `HostFlightError`, `CaptureError`,
  `BatchError`, `ExportError`, `AircraftAssetError`, `ConvertError`, and
  the `ValueError` sentences (`spec_version`, `manifest_version`,
  `LLMCompileError` "the language model's response was rejected: …").
* **Landed (package I part 1, `core/messages/`).** `explain(violation |
  refusal dict | error | name) -> {"sentence", "hint", "rule"}` beside
  `render(name, **params)`. Placeholders are `{param}` and the plural
  form `{param:one|many}`, chosen by the numeric value of `param`; the
  parameters are the refusal's own five fields plus three derived ones,
  `shortfall` (limit − actual), `excess` (actual − limit) and `count`
  (violations in a report). An absent placeholder renders as nothing and
  never raises; an unknown name renders as the raw name with the
  technical message as the hint, and the coverage test forbids that path
  for every name the code emits. The catalogue also keys `check.<name>`
  for every `Check("<name>")` in `verify.py` (the sentence beside the
  tick), `verdict.{pass,fail,not_run}`, and the progress states
  `progress.campaign.<state>` (§6.1 `campaign.json`),
  `progress.case.<status>` (the ledger) and `progress.page.<state>` (the
  six page states). The bare names the CLIs and the web app print today
  (`trim`, `validation`, `weather`) are kept as spelled.
  `tests/test_messages.py` lists every not-yet-emitted name in
  `ALLOWED_FUTURE` with its package; the package that lands a name
  removes it there in the same commit.
* A test asserts every constraint name in the codebase (every
  `Violation("...")` first argument, every `constraint=`/`"constraint":`
  literal, every `*Error("...")` constraint) has an entry, and every
  entry has a live name.
* Endpoints (FastAPI, `webapp/server.py`). **Kept**: `POST /compile`
  (`{prompt, compiler, questions?, answers?, prior_spec?, clip_seconds?}`
  → `{needs_clarification, questions, spec, validation, …}`), `POST
  /cameras`, `POST /run`, `POST /bake`, `GET /status`, `GET /runs/{id}`
  and the artefact routes (`clip.mp4`, `telemetry.json`, `card.json`,
  `effect.json`, `provenance.json`, `capture_manifest.json`,
  `verify.json`, `images`, `cameras/{cid}/manifest.json`,
  `cameras/{cid}/frames.zip`, `clips/{cid}.mp4`,
  `{frames|overlays|previews}/{cid}/{name}`), `GET /schemas/{name}`,
  `WS /telemetry` (unused by either page). **New**: `POST /generate/plan`
  (wraps the `/compile` clarification protocol: prompt → questions or
  plan preview), `POST /generate/preview` (one sample run with overlays),
  `POST /generate/start`, `POST /generate/{id}/pause|resume|cancel`
  (writes `control.json`), `GET /generate/{id}` (progress from the
  ledger, catalogue sentences), `GET /generate/{id}/events` (server-sent
  events through `StreamingResponse` — no `sse-starlette` dependency),
  `GET /generate/{id}/frames` (gallery), `GET /generate/{id}/download?format=`.
  The image route's name regex (`server.py` L604, `.png|.json` only) admits
  `.f32`; the two verdict files (`verify.json` `{ok, checks, overlays}`
  and `verification.json` `{ok, passed, failed, not_run, checks}`) are
  unified on `verification.json`.
* Page: `webapp/static/generate.html` — one flow, six states (ask,
  clarify, preview, generate, review, download), server-sent events for
  progress, plain language by default with the rule name under a
  disclosure. The expert page stays at `/` and every screen names its
  command (`docs/COMMANDS.md`, generated from the tool schema).

---

## 9. Render command flags — one builder (package A, closes the drift)

`core/render/command.py` (new; the name the brainstorm and three maps
use): `render_command(card, frames, *, scene, mesh, look, cameras,
labels=True, linear=False, deterministic=True, void=False, width, height,
fps)` returns the commandlet argument list used by BOTH
`flightsim/capture.py` (L520-560) and `webapp/runs.py` (`_render`
L1548-1600, `_fly_host` L1752-1766); the experiments (`gate6_visual.py`,
`gate10_render_repro.py`, `showcase_matrix.py`, … — thirteen builders in
all) migrate next. It also owns the placeholder refusal: today
`flightsim/capture.py` L196-200 imports `webapp.runs.refuse_placeholder_mesh`
and `assets_pipeline.importer.is_imported` (the CLI depending on the web
layer), which moves into the builder. A test compiles one spec and
asserts the two callers produce the same flag set, including `-mesh=`
(both pass it today: capture.py L560, runs.py L1588-1589) and
`-deterministic` (neither passes it today). The byte-identity pin for
camera-less specs (`tests/test_camera_spec.py` L155-175) is retired with
the legacy `-camera=`/`-chase=` path or re-pinned to the builder's output —
one of the two, stated in the commit. The flags that exist today
(commandlet L559-682, L857-984): `-scenario= -frames= -fps= -width=
-height= -Visual -shot= -NoShadows -HideAircraft -labels -linear
-deterministic -AutoExposure -terrain= -seconds= -telemetry= -mesh=
-GeorefTerrain -sun-elev= -sun-azim= -sun-elev-end= -sun-azim-end=
-fog-density= -imagery= -exposure-bias= -chase=x:y:z -NoOrographic
-camera= -wingman-abeam= -camera-index= -probe-*`; the wrapper
`scripts/render_ue_scenario.ps1` adds `-camera-index=N` and
`-telemetry=<cam>/host_telemetry.json` per camera pass and forwards the
rest. No new flags are added this phase (§5.4 moves look onto the card).

### 9.1 As landed (package A, last item) -- the name, the signature and four stated departures

* **The module is `core/render/flags.py`, the function `render_flags`**
  (the orchestrator's name for this item; the brainstorm's
  `core/render/command.py` / `render_command` does not exist and nothing
  imports it). Signature: `render_flags(card, frames, *, scene, mesh,
  look, camera_flags, labels=True, linear=False, deterministic=True,
  void=False, width, height, fps, telemetry=None, extra=())` -- `cameras`
  became `camera_flags` (the `(inline, trailing)` pair
  `webapp.runs.camera_render_flags` already produces, for the legacy
  preset path only), and `telemetry` / `extra` were added because the
  web app's per-camera loop (`webapp/capture.py`, not this package's
  file) hands `-camera-index=N -labels` and the per-camera telemetry
  path in through them. `for_wrapper(flags)` strips what
  `render_ue_scenario.ps1` writes itself (`-scenario= -frames=
  -camera-index= -telemetry=` and the launcher tokens).
* **The launcher tokens are part of the list**, at the position the web
  app has always put them (mid-list), because the camera-less argument
  list is pinned byte-identical by `tests/test_camera_spec.py` and the
  commandlet's parser is order-blind. The wrapper strips them.
* **The CLI now passes the web app's default look when the
  randomisation block is off** (`DEFAULT_LOOK` = noon, clear; pinned
  equal to `showcase_matrix.TIME_OF_DAY["noon"]` + `VISIBILITY["clear"]`)
  plus `-shot=showcase -fps= -width= -height=` and `-deterministic`.
  Before, the CLI passed no look and the commandlet's own defaults lit
  the frames. Two callers cannot produce one flag set unless one moves;
  the web app's list is the pinned one. `-width/-height/-fps` are inert
  on every card with a cameras block (the commandlet takes the size
  from the card's camera and records `applied_width_px`), stated in the
  module docstring as not claimed.
* **The web app's per-camera (consume-poses) pass no longer carries
  `-chase=`/`-camera=chase`**: the test that drives both paths caught
  them as the one difference. By reading of the commandlet they were
  inert there (the pose comes from the card, "replacing the chase
  settle-in placement"; the default preset word is already `chase`);
  not measured on Windows. The legacy single pass and the solve pass
  keep them.
* **The placeholder refusal did NOT move into the builder** (this page
  said it would): `flightsim/capture.py` still imports
  `webapp.runs.refuse_placeholder_mesh`, outside the block this item
  owned. The builder forwards `mesh` verbatim and checks no filesystem;
  the callers vouch for the path. Open item, stated in the report.

---

## 10. Look lane settings (owner decisions stated, measured switches)

| Setting | Where | Default this phase |
|---|---|---|
| Engine | `ue/FlightSim.uproject` L3 `EngineAssociation`; `ue/Source/FlightSim.Target.cs` + `FlightSimEditor.Target.cs` L9 `IncludeOrderVersion`; `scripts/build_ue.{ps1,sh}`, `ue_preflight.{ps1,sh}` (L38-57, L76-92), `setup.{ps1,sh}`, `deploy_windows.ps1`, `vendor_ue_plugin.ps1`, `check_bridge_api.sh`, `render_ue_scenario.sh`, `run_ue_scenario.sh`; `core/util/platform.py` (refusal text and default install paths); `tests/test_platform.py`, `tests/test_powershell_scripts.py` | **5.7** (re-vendor JSBSim for 5.7 via `vendor_ue_plugin.ps1` — `VENDORED.json` upstream e07a7d8 + patches, `.uplugin` declares no `EngineVersion`; re-run `check_bridge_api.sh`; re-check the 5.7 API list in the ue-render map §8; re-measure Gate 6 and Gate 10-R on Windows) |
| Renderer settings | `ue/Config/DefaultEngine.ini` `[/Script/Engine.RendererSettings]` — the file has NONE today | `r.CustomDepth=3` (required by §2.3), `r.DynamicGlobalIlluminationMethod=1`, `r.ReflectionMethod=1`, `r.GenerateMeshDistanceFields=1`, `r.Shadow.Virtual.Enable=1`, `r.AntiAliasingMethod` pinned (label captures override per capture), `r.DefaultFeature.AutoExposure.ExtendDefaultLuminanceRange=1`; `[/Script/WindowsTargetPlatform.WindowsTargetSettings]` DX12 + SM6 (VSM/Nanite/Lumen need SM6). Each recorded in `render.json.render_settings` |
| Lumen GI + reflections | above | on (software) |
| Virtual shadow maps | above | on for static/Landscape geometry; the terrain is a Movable `UProceduralMeshComponent` today (VALIDITY §2.13 records CSM-not-VSM for that reason), so VSM applies to it only once the terrain row below lands |
| Nanite for imported meshes | `scripts/ue_import_aircraft.py` L49-57 (`build_nanite=False`) | **off** — measured: the scene capture drew the coarse Nanite fallback (3563 of 24471 tris) and Nanite must be disabled at import, not after; `FlightSimVisualScene.cpp` L109 "No Nanite in a procedural-mesh scene". Re-testing on 5.7 is a Look-lane experiment, not a default |
| Volumetric clouds | `FlightSimVisualScene.cpp` `Build`, driven by §5.4 `card.look.clouds` | on when the card carries a cloud layer |
| Beauty AA | commandlet, per capture `ShowFlags` | TSR; label passes none (§1) |
| Exposure | commandlet / `ApplyManualExposure` | EV100 from `cameras[].exposure {aperture_f, shutter_s, iso}` (spec 8; defaults per preset); `-exposure-bias` (`AutoExposureBias`, default 11.0) kept as the override |
| Terrain posting | `FlightSimVisualScene.cpp` `BuildGeoreferencedTerrain` L391-569, `MaxVerticesPerSideGeoreferenced = 701` (L46) | tiled procedural sections at native 30 m posting (no 701-vertex cap); a Landscape import path (`core/terrain/landscape.py` exporter exists, unused by the render path) is the next step |

Every switch is recorded in `render.json.render_settings` and has a Gate 6
clause.

---

## 11. Refusal names — existing and new (all in the catalogue)

**Existing on the branch (kept, exact spellings from the code).**
`Violation.constraint` in `core/scenario/validate.py`: `aircraft.exists`,
`altitude.terrain_clearance`, `airspeed.stall_margin`,
`airspeed.approach_speed`, `run.duration`, `run.rate`,
`environment.wind_speed`, `environment.wind_direction`,
`environment.surface`, `environment.weather_event`,
`envelope.trim_feasible`, `randomization.enabled`, `randomization.year`,
`randomization.<field>` (each range/jitter field by name),
`randomization.sun_elevation_min_deg`. In `core/capture/validate.py`:
`camera.identifier`, `camera.preset`, `camera.profile`,
`camera.intrinsics`, `camera.schedule`, `camera.moves`,
`camera.terrain_clearance`, `camera.scene_bounds`,
`camera.hazard_intersection`. Error `.constraint`s: `camera.poses`,
`camera.labels`, `capture.host_flight`, `randomization.livery`,
`randomization.time_of_day`, `randomization.unsampled`, `camera.render`,
`camera.track`, `camera.multi_render`, `ffmpeg.missing`, `ue.platform`,
`aircraft.mesh`, `aircraft.mesh_import`, `terrain.unbaked`,
`terrain.clearance`, `weather.not_a_place`, `weather.unavailable`,
`batch.{matrix,base,factors,seeds,design,workers,capture}`,
`export.{runs,unverified,verification_failed,image,sensor_labels,
missing_frames,empty,split,shard_size,format,arguments,taxonomy}`
(`export.taxonomy` landed with package E: the runs of one export
disagree on the class list). Named
`ValueError`s (no constraint string today, catalogued under the new
names): `spec.version`, `manifest.version`. The un-named
`LLMCompileError`s are catalogued as `compile.rejected` (the "response
was rejected" sentence) and `compile.unavailable` (no provider, no SDK).

**New this phase.** `scene.terrain` (a `terrain_source` the machine
cannot honour: `baked` with no whole bake stated or given, or a CLI flag
that contradicts the stated source), `scene.terrain_source` (a value
outside the four), `taxonomy.classes` (empty, non-string or repeated
class names), `traffic.count` (more than two entries), `traffic.aircraft`
(not a configured airframe: no `assets/aircraft_config/<name>.json`),
`traffic.track`, `traffic.range_m`, `randomization.policy` (a leaf not
of a §5.2 form -- shape only; the semantic refusals below are F's),
`camera.exposure` (a non-positive aperture, shutter or ISO) -- all
landed with the spec-8 bump (package A);
`aircraft.mesh_extent` (§0.1), `annotation.mask_blend`,
`annotation.mask_offset`, `annotation.box_mismatch`,
`annotation.depth_range`, `annotation.visibility`, `annotation.identity`,
`annotation.intrinsics`, `annotation.files`, `aircraft.placeholder_drawn`
(the `drawn_airframe` check's FAIL, today only in its detail text),
`randomization.vocabulary`, `randomization.location`,
`randomization.infeasible`, `storage.budget_exceeded`,
`campaign.target_unreachable`, `export.unverified_labels`,
`authority.stated_field`, `authority.validation_token`,
`authority.refusal_is_not_a_run`, `authority.budget`.

---

## 12. Spec 8 — the whole delta in one list

| Section | Field | Type | Default | Package |
|---|---|---|---|---|
| `scene` (new section) | `terrain_source` | `auto` \| `flat` \| `synthesised` \| `baked` | `auto` (today's behaviour: the webapp's `pick_scene`; the CLI's `--terrain <stem>` = `baked`, `--synth-terrain` = `synthesised`) | A (`examples/cameras_mountain_refusal.yaml` says `synthesised` and drops its `--synth-terrain` note) |
| `scene` | `terrain` | bake stem (as `--terrain`), required when `baked` | absent | A |
| `taxonomy` | `classes` | list of class names | the documented list | B |
| `traffic[]` | `aircraft`, `track`, `range_m`, `livery` | as §2.2 | `[]` | B |
| `randomization` | `policy.*` | as §5.2 | absent (no sampling) | F |
| `randomization` | `visibility_km`, `cloud_cover`, `cloud_base_m`, `precipitation`, `hour_local`, `location`, `traffic_count` | sampled leaves (like `fog_density`) | defaulted placeholders | F |
| `cameras[]` | `exposure.aperture_f`, `exposure.shutter_s`, `exposure.iso` | numbers | preset defaults (f/8, 1/500 s, ISO 100 daylight) | Look |

Everything else is unchanged; the digest of a spec that states none of
these is unchanged by construction (absent blocks are canonical), and
`simulation_digest` (manifest.py L213-233) keeps dropping `cameras` and
`randomization` and additionally drops `taxonomy`.

**As landed (package A, the bump commit) -- three shape decisions the
table above left open, stated here so the other packages implement
against what exists:**

* `cameras[].exposure` is ALSO absent-canonical: a camera whose triple is
  the preset's documented default (`ExposureSpec.is_default(preset)`)
  serialises exactly as it did at 7 (no `exposure` key); a stated or
  planned triple appears as a nested block `{aperture_f, shutter_s, iso}`
  of Quantities (units `f-number`, `s`, `ISO`). Addressed as
  `cameras[i].exposure.<field>`. `EXPOSURE_DEFAULTS` in `camera.py` is
  keyed per preset with one daylight triple for all of them today
  (§12's f/8, 1/500 s, ISO 100).
* `randomization.policy` is one provenanced Quantity whose VALUE is the
  §5.2 mapping (`{value: {...}, source, from}` under
  `randomization.policy`), carried on `ScenarioSpec.randomization_policy`
  rather than inside `RandomizationSpec` (whose 20-field reader is
  untouched); package F may move the attribute inside the block without
  changing the file shape. A `randomization` block that holds only
  `policy` leaves the ranges at their defaults. Validation is
  structural only (`core/scenario/validate.py` `policy_problems`):
  fixed scalars are admitted at the top level only; inside a group
  every member is a distribution leaf or a group.
* `scene`, `taxonomy` and `traffic[]` live in `core/scenario/blocks.py`
  (`SceneSpec`, `TaxonomySpec`, `TrafficSpec`, each a
  `ProvenancedBlock` with the spec's set()/plan() doctrine; the
  plannable rule they read is `fields.PLANNABLE_SOURCES`). `traffic` is
  omitted when empty; `MAX_TRAFFIC = 2`; the default track is
  `crossing`, range 400 m, livery `default`; a traffic entry's
  `aircraft` is `user`-sourced by construction (it has no documented
  default). `scene.terrain` is a Quantity whose value is `None` when
  absent (the block is omitted whole when defaulted).

---

## 13. Corrections from the map

Each change this revision made to the draft (15e0bc9), with the evidence.

1. **`spec.version` is not a refusal name.** `ScenarioSpec.from_dict`
   raises `ValueError("spec_version … is not supported by this build
   (expects 7)")` (spec.py L260-265; tests match the sentence). §0 now
   states the mechanics (the comment block, the eight examples regenerated
   at 8, the three version tests, `FIELD_VALUE_SCHEMAS`, `card.py`) and
   §11 lists `spec.version` / `manifest.version` as catalogue names for
   `ValueError`s, not as existing constraints.
2. **Manifest bump mechanics** added (`SUPPORTED_MANIFEST_VERSIONS`,
   schema keyword restriction `schema.py` L32-36, `SIDECAR_CONTEXT_KEYS`,
   the hard-coded v5 link at `index.html` L1186, the tests and guard) —
   capture-labels map gotcha on adding a version; verifier map
   `json_schema` NOT RUN behaviour.
3. **Mesh manifest 2 → 3, origin measured from vertices** (§0.1): the
   critique's `offset_root_cause` (B747 +29.80/−41.14 m, A320
   −2.53/−40.09, c172p +2.14/−6.09 in the actor frame; eb5c71d's VRP rule
   wrong by 3.9 m on the B747 and 19.3 m on the A320); the stale rule in
   `importer.stale_manifest_reason` re-converts by version; the pins in
   `tests/test_aircraft_assets.py` L311-323 / L343-345 are named as the
   ones to rewrite. New refusal `aircraft.mesh_extent`.
4. **`render.json` keys corrected to the code's.** Per-frame `labels`
   today: `mask`, `class_mask`, `depth`, `depth_scale_m`,
   `depth_saturation_m`, `silhouette_pixels`, `visible_pixels`,
   `occlusion_fraction` (= 1 − visible/silhouette, commandlet L1867),
   `classes`, `method` (L1860-1873); files `_mask.png`, `_class.png`,
   `_depth.png`, `_linear.exr` (L1842-1844, L1892). The draft's `id_png` /
   `class_png` / `depth_png` / `frame_NNNN_id.png` are gone: the ID image
   keeps the `_mask.png` name and `mask` key, with `int_id` values (the
   primary is 1, so `AIRCRAFT_INSTANCE_ID = 1` stays true). `drawn` keys
   are the committed ones (L2123-2150). `frames` is an integer count;
   `frame_records` is the array.
5. **ID image 8-bit, not 16-bit** — the stencil is 8-bit and the
   commandlet's grey writer (L187-196) is what exists; §1 says why.
6. **Depth stays raw float32** — evidence strengthened: `profile.py`
   L521-539 already falls back because `OpenEXR` is not installed;
   `requirements.txt` confirms.
7. **`applied_*` intrinsics on every frame** and the root `camera_preset`
   lie (L2068) — ue-render map known_defects; new `applied_intrinsics`
   check because no Python check reads those keys (verifier map).
8. **Label record names are the code's**: `bbox_2d`, `bbox_2d_unclipped`,
   `truncation`, `in_frame`, `bbox_3d_camera`, `keypoints`, `horizon`
   (schema `labels.required`); `bbox_2d` is the OVERALL extents box, not
   a hull (labels.py `conventions()`), so the hull box is a new field
   from the mesh extent; `fraction_in_frame` dropped as `1 − truncation`;
   KITTI `occluded` derivation replaces the dead `engine_labels` read
   (export.py L389).
9. **Tolerances live in `verify.py`, not `labels.py`** — the verifier's
   independence rule (module docstring; the two existing producer imports
   are not to be extended).
10. **Check names flat, `drawn_airframe` already exists** (verify.py
    L1743, 26 checks in `verify_run`); `Check.to_dict` gains an optional
    `failure` key because today the FAIL name is only detail text;
    mutation-guard uniqueness rule from the L557/L603 aliasing (critique).
11. **Decision (b) recorded in §4**: `pose_matches_spec` keeps
    `max(50, 1.5 × |keyframed offset|)` (verify.py L596, commit 7118a0c);
    the brainstorm's 5 %/2 m contract is explicitly not adopted.
12. **Randomization block keys** listed exactly (20 `FIELD_ORDER` names,
    `SAMPLED`, `card_block` keys incl. `engine_sun_azimuth_deg`); the four
    hand-copied plannable rules named; draws are `DERIVED` today; the
    `Violation.render()` str-limit crash is the first task; the
    `_parse_payload` literal key set (llm_compiler.py L611-613); the
    compiler has no randomization vocabulary (nl-compiler probe);
    `randomization.location` added because `LOCATIONS` has no Rockies bake.
13. **Look flags replaced by `card.look`** — the engine reads the card
    (`ReadCard` L86-544); the draft's `-aerosol`, `-cloud-*`, `-precip=`,
    `-wet=`, `-moon`, `-stars`, `-cloud-drift=` did not exist and would
    have deepened the thirteen-builder drift. Precipitation particles,
    moon and stars are `not_claimed` (no assets; no scene-builder API).
14. **Campaign ledger extends the batch ledger** (`run_case` row keys,
    batch.py L269-293; `batch.json` keys; completion-order rows; resume
    semantics; `run_id` after sampling; `CAPTURE_OPTIONS` lacks terrain;
    `-deterministic` passed by nobody; `write_verification` not atomic).
15. **Export layouts stated from the code** (§6.2: `FORMATS`, COCO/KITTI/
    WebDataset trees, `load_run` refusals, split key, sample key;
    `pycocotools` not a dependency; WebDataset mtime leak).
16. **Tool layer**: the planners are sequenced only in `webapp/server.py`
    (nl-compiler map G); `set()` forces `user` so the tools expose `plan()`
    only; `mcp` optional; `validation_token` from `ValidationReport.spec_digest`.
17. **Endpoints**: the existing route list (server.py L170-815) is kept
    and named; `/generate/*` are new; SSE via `StreamingResponse` (no new
    dependency); the `.f32` extension in the image-route regex; the two
    verdict files unified.
18. **Builder named `core/render/command.py`** (brainstorm + three maps),
    thirteen builders counted (webapp map), the CLI's import of
    `webapp.runs.refuse_placeholder_mesh` (critique) moves into it, the
    existing flag list stated, `-mesh=` already passed by both callers
    (critique: capture.py L560, runs.py L1588).
19. **Look defaults corrected**: Nanite **off** (measured fallback,
    `ue_import_aircraft.py` L49-57; `FlightSimVisualScene.cpp` L109); VSM
    conditional on the terrain path (Movable procedural mesh); the
    `DefaultEngine.ini` has no renderer settings and `r.CustomDepth=3` is
    required; the 5.7 pin list from the ue-render and scripts maps;
    `MaxVerticesPerSideGeoreferenced = 701`.
20. **§11 rewritten from the code's constraint literals** (grep of
    `Violation(`, `constraint=`, `"constraint":`, `*Error("…")`);
    `export.unverified` and `export.verification_failed` exist;
    `aircraft.mesh` / `aircraft.mesh_import` exist.
21. **§12**: `scene` is a new SECTION (sections today: aircraft, initial,
    environment, run) and `from_dict` tolerates unknown top-level keys —
    the reason the bump is not optional; `scene.terrain` (bake stem)
    added because `terrain_source: baked` alone names no bake.
22. **Frame names `frame_%04d`** (manifest.py L375-383); the brainstorm's
    `%06d` is not used.
23. **`traffic` needs `Populate` generalised** (one aircraft today,
    `FlightSimScenarioWorld.cpp` L938-1020) and the per-actor mesh
    refusals — ue-render map B.

**Not settled from the code (owner or measurement needed):** the B747
nose keypoint is an `estimate` at the structural datum (B747.json); if the
type's nose tip sits 2.66 m aft of the datum (critique alternative:
aligning the mesh nose gear at +22.4 m with `NOSE_LG` 10.06 m aft), the
label, not the mesh, is what is off — §0.1's rule aligns to the labelled
nose as stated and the residual is a Phase 2 measurement
(`mask_vs_geometry` on the first Windows render). The main-gear z anchor
is stated per airframe only where gear objects are identifiable in the
`.ac` (confirmed for the 747's `747-400_gear.ac`; A320 and c172p to be
confirmed at conversion). The 5.7 API re-checks (ue-render map §8) are
listed, not done.
