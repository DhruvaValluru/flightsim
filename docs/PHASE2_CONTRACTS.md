# Phase 2 contracts — the shapes every package shares

*Working document for the Phase 2 build (branch `phase2`). One place for
every cross-package shape: file formats, spec and manifest versions, the
refusal names, the campaign and trace files, the tool schema, the message
catalogue. A package implements against this page; a change to a shape
is a change to this page first. Where the brainstorm
(`docs/PHASE2_BRAINSTORM.md`) decided a shape, this page states it
concretely; where the code on this branch already had one (the Phase 10
tree), this page keeps it and says so.*

*Status column: **kept** (existed on the branch, unchanged), **extended**
(existed, gains keys), **new**.*

---

## 0. Version bumps — one each, for the whole phase

| Document | Was | Now | First field that forces it |
|---|---|---|---|
| `spec_version` (`core/scenario/spec.py`) | 7 | **8** | `scene.terrain_source` (package A), `taxonomy` (B), `traffic` (B), the policy leaves of `randomization` (F), `cameras[].exposure` (Look) |
| `manifest_version` (`core/capture/manifest.py`) | 5 | **6** | `objects[]` (B) and the per-object label record (C) |
| `mesh_manifest.json` `version` (`assets_pipeline/convert.py`) | 1 | **2** | `mesh_origin_actor_cm` (A — done) |
| `render.json` (commandlet) | additive | additive | `drawn` (A — done), `labels_v2`, `render_settings`, `look_applied` |
| `capture_manifest.v5.schema.json` | v5 | **v6 published**, v5 still validates older manifests | — |

A version-7 spec dict refuses by name (`spec.version`) exactly as every
earlier bump did; the committed examples are regenerated at 8. A
version-5 manifest still reads; its Phase 2 checks report NOT RUN.

---

## 1. The per-frame ground-truth bundle (packages B, C, D; Look lane)

Written by the render commandlet under `frames/<camera_id>/`, one set per
delivered frame, all from the SAME camera pose in the SAME tick. The
beauty image may use any anti-aliasing and every visual effect; the label
passes use **none** (rule §3.3 of the brainstorm: `r.AntiAliasingMethod
0`, no temporal history, screen percentage 100, show flags off for fog,
atmosphere, bloom, motion blur, DOF, lens flare, translucency).

| File | Format | Content | Status |
|---|---|---|---|
| `frame_NNNN.png` | sRGB 8-bit RGB(A) | beauty (training image) | kept |
| `frame_NNNN_linear.exr` | half-float, optional (`-linear`) | linear beauty | kept |
| `frame_NNNN_id.png` | **16-bit grey PNG** | one integer per pixel = the object's `int_id`; 0 = background/unlabelled; NO other values | new (replaces `_mask.png` aircraft=1) |
| `frame_NNNN_class.png` | 8-bit grey PNG | `class_id` per pixel (0 sky/none, then the taxonomy's ids) | kept, ids from the taxonomy |
| `frame_NNNN_depth.f32` | raw little-endian float32, row-major, `width*height` values, metres, +inf for sky | metric depth from the AA-free depth capture | new |
| `frame_NNNN_depth.png` | 16-bit grey, `metres = value * depth_scale_m`, saturating | the viewer-friendly depth, kept for old consumers | kept |
| `frame_NNNN_alone_<int_id>.png` | 16-bit grey PNG | the ID pass rendered with ONLY that object visible (its unoccluded footprint) — one per labelled object | new (generalises the Phase 10 aircraft-alone depth pass) |
| `frame_NNNN_sensor.png` | 8-bit sRGB | the seeded sensor post-pass output (Python) | kept |
| `render.json` | JSON | per-frame records incl. `labels` (below), `drawn`, `render_settings`, `look_applied` | extended |

**Why raw float32 and not EXR for depth.** OpenEXR is not a dependency
of this repository and must not become one for the verifier to run on
every machine (`docs/PHASE10_REPORT.md`, P10-3). A raw float array needs
no library on either side and loses nothing; the export writers convert
it to EXR or 16-bit PNG for consumers that want those, and the dataset
card says which. The format is the contract, not the commandlet.

**`render.json` per-frame `labels` object** (the verifier reads this;
nothing else is inferred from file names):

```json
"labels": {
  "id_png": "frame_0001_id.png",
  "class_png": "frame_0001_class.png",
  "depth_f32": "frame_0001_depth.f32",
  "depth_png": "frame_0001_depth.png",
  "depth_scale_m": 0.1,
  "width": 1280, "height": 720,
  "anti_aliasing": "none",
  "objects": [
    {"int_id": 1, "pixels": 48211, "pixels_alone": 51002,
     "alone_png": "frame_0001_alone_1.png", "visible_fraction": 0.945,
     "occluded_by": [2], "depth_min_m": 412.3, "depth_median_m": 421.7}
  ]
}
```

`visible_fraction = pixels / pixels_alone` (geometric only). Atmospheric
transmittance is analytic and lives in the Python label record (below),
never folded into `visible_fraction`.

**`render.json` root additions:** `drawn` (done, package A),
`render_settings` (every rendering console variable the commandlet set or
read: AA method per pass, Lumen, VSM, Nanite, screen percentage, exposure
mode and EV100), `look_applied` (the weather/sky parameters actually
applied, §5).

---

## 2. Identity and the taxonomy (package B)

### 2.1 Spec: `taxonomy` (spec 8, optional, provenance like every field)

```yaml
taxonomy:
  classes:            # ordered; class_id = position + 1; 0 is reserved (sky/none)
    value: [aircraft, terrain, building, vegetation, water, cloud]
    source: default
    from: the documented class list
```

`cloud` is a class in the visibility record only (volumetrics write no
ID). A dataset's categories come from this list, never from what happened
to be in the scene.

### 2.2 Spec: `traffic` (spec 8, optional) — the second aircraft

```yaml
traffic:
- aircraft: {value: A320, source: user, from: "an A320 crossing"}
  track:    {value: crossing, source: user, from: "crossing"}   # formation | crossing | overtaking
  range_m:  {value: 400.0, source: default, from: documented traffic default}
  livery:   {value: default, source: default, from: ...}
```

A scripted actor flown along a pre-solved `PoseTrack` (the camera
machinery applied to an actor); no second FDM. Its mesh must be imported
like the primary's (`aircraft.mesh` refusal otherwise).

### 2.3 Object ids

* `id` — stable string: `aircraft:<fdm>:<n>` (n = 0 primary, 1.. traffic
  in spec order), `terrain`, `building:<n>`, `vegetation:<n>`. Composed in
  Python (`core/capture/objects.py`, new) from the spec; the engine never
  invents one.
* `int_id` — small integer assigned in composition order starting at 1;
  the same spec composes the same list, so it is stable across frames,
  cameras and runs of one spec. The card carries the list; the commandlet
  sets each labelled component's Custom Depth Stencil to `int_id` and
  refuses (`annotation.identity`) a scene needing more than 255.
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

---

## 3. Boxes, depth, occlusion — the per-object label record (package C)

Manifest 6, per frame, `labels.objects[]` (Python-computed; the existing
`labels` block for the primary airframe — `bbox_2d`, `bbox_2d_unclipped`,
`truncation`, `in_frame`, `bbox_3d`, keypoints, horizon — is kept and its
airframe entry is the first element here):

```json
{"id": "aircraft:B747:0", "int_id": 1, "class_id": 1,
 "bbox_projected": [u0, v0, u1, v1],          // from the airframe hull through K,P (kept)
 "bbox_unclipped": [u0, v0, u1, v1],          // may leave the frame (kept)
 "bbox_tight": [u0, v0, u1, v1] | null,       // from the ID mask; null when no pixels
 "fraction_in_frame": 0.0..1.0,
 "visible_fraction": 0.0..1.0 | null,
 "occluded_by": ["aircraft:A320:1"],
 "atmospheric_transmittance": 0.0..1.0,       // Koschmieder along the CG ray: exp(-3.912 * range_km / visibility_km)
 "depth_projected_m": 421.4,                  // CG depth through the manifest
 "depth_min_m": 412.3, "depth_median_m": 421.7,   // from the depth image under the mask
 "bbox_3d": {…},                               // kept: centre, extents, axes, corners (camera coords, documented order)
 "not_claimed": ["subpixel_mask_accuracy_beyond_range_m: 8000", "objects_under_px: 12"]}
```

Tolerances (stated once, in `core/capture/labels.py`, imported by the
verifier as NUMBERS only, never as code):

| Quantity | Tolerance |
|---|---|
| tight box vs projected hull box | IoU ≥ 0.8 for objects ≥ 64 px extent; ≥ 0.5 for 16–64 px; not claimed under 16 px |
| mask centroid vs projected CG | ≤ 2 % of the projected span |
| mask extent vs projected hull | ≤ 5 % of the projected hull |
| depth under mask vs projected CG depth | ≤ 1 % + 2 m, growing with the airframe's length |
| visible fraction vs scripted occlusion | ≤ 3 % of the analytic overlap |

---

## 4. Verifier checks and refusal names (package D)

Each check: named, tolerance stated, NOT RUN without its evidence, a
mutation guard in `scripts/mutation_check.sh`, a visual sheet from
`tests/visual/annotation_sheets.py` under `build/visual/`.

| Check (verify.py) | Evidence | FAIL name | Sheet |
|---|---|---|---|
| `drawn_airframe` (done) | `render.json.drawn` | `aircraft.placeholder_drawn` | — |
| `mask_integers_only` | histogram of `_id.png` vs `objects[].int_id` | `annotation.mask_blend` | offending pixels highlighted |
| `mask_vs_geometry` | ID-mask centroid/extent vs projected CG/hull | `annotation.mask_offset` | mask edge + hull + CG cross |
| `box_vs_mask` | tight vs projected box IoU | `annotation.box_mismatch` | both boxes |
| `depth_vs_geometry` | depth under mask vs projected depth | `annotation.depth_range` | heatmap + predicted |
| `visibility_vs_scene` | alone-pass vs full-pass; occluders exist in `objects` | `annotation.visibility` | side by side |
| `identity_stable` | same `id`→`int_id` across frames, cameras, runs of one spec | `annotation.identity` | id strip |
| `label_files` (kept) | every declared file exists | `annotation.files` | — |

Mutations that must fail (the visual test applies each and asserts):
shift the mesh origin by 3 m; swap two ids; blur the ID image; scale depth
by 1.02; hide the occluder in the full pass; FOV off by 1°.

The verifier does not import the producer (`labels.py` numbers only).

---

## 5. Randomization policy and the look coupling (package F)

### 5.1 Provenance

`Source.SAMPLED = "sampled"` joins `user > inferred > model > derived >
default` (between `inferred` and `model`: a sampled field is as fixed as
a user field once drawn — never re-planned). `detail = {policy, distribution,
seed, draw_index}`.

### 5.2 Policy schema (spec 8 `randomization.policy`, optional; the existing
`randomization` keys — day of year, hour, sun floor, fog, jitter, livery —
are kept as leaves of the same block)

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
`beta`, `weibull`, `poisson`, `uniform_dates`, with `clip` and `gated_by`.
Every leaf maps to an existing typed field (or one added in this bump);
draws go through `validate()`; a refused draw is recorded as
`{draw_index, refusal_name, sampled_values}` and re-drawn up to
`max_attempts` (20) before the slot is `randomization.infeasible`.

### 5.3 Prompt vocabulary (`core/nl/compiler.py`, `llm_compiler.py`
`RESPONSE_SCHEMA["randomization"]`, import-time assert against the policy
leaves)

| Phrase | Policy |
|---|---|
| "varied weather" | cloud_cover, visibility_km, precipitation defaults |
| "different times of day" / "dawn and dusk only" | hour_local uniform / bimodal |
| "across the Rockies" / "over the Alps" | location choice restricted to that range |
| "mixed traffic" | traffic_count |
| "random viewpoints" | cameras block |
| "varied lighting" | hour_local + weather_date |
| anything else asking to vary | refused `randomization.vocabulary`, sentence quoted |

### 5.4 Look coupling — `core/scene/weather_visuals.py` (new, one table)

| Spec value | Engine parameter (card `look` block, commandlet flag) |
|---|---|
| `visibility_km` | fog extinction β = 3.912/V → `-fog-density`, atmosphere aerosol `-aerosol` |
| `cloud_cover`, `cloud_base_m`, `cloud_top_m` (per layer, from Open-Meteo/ERA5 for `weather_date`) | `-cloud-cover=`, `-cloud-base=`, `-cloud-thickness=`, cloud shadows on |
| `precipitation` | `-precip=none|rain|snow`, `-wet=0..1` (surface wetness), visibility floor |
| `hour_local`, `weather_date`, lat/lon | `-sun-elev/-sun-azim` (exists), `-moon`, `-stars` |
| `wind_speed_kt`, direction | `-cloud-drift=` |

Each row is recorded in `render.json.look_applied` and measured once from
pixels (Gate 6 pattern) in `experiments/gate6_visual.py` clauses.

### 5.5 Realised distribution

`campaign_report.json` histograms every sampled field over frames that
exported, beside the requested distribution, with `coverage` = fraction of
policy bins holding ≥ k frames.

---

## 6. Campaign files (package G)

```
campaigns/<id>/
  campaign.json      prompt, answers, compiled spec digest, policy, images_target, seed,
                     state: planned|running|paused|failed|done|cancelled, workers,
                     disk_budget_bytes, created_utc, format, tier (LLM tier used)
  ledger.jsonl       one line per case, append-only:
                     {index, case_id, seed, status: sampled|refused|running|rendered|
                      verified|failed, refusals: [names], frames, yield, run_dir,
                      simulation_digest, bundle_digest, started_utc, finished_utc, reason}
  control.json       {"request": "pause"|"resume"|"cancel"} written by the UI/CLI; polled by workers
  trace.jsonl        the agent's tool calls (§7)
  report.json        yield, coverage, realised distributions, refusals by name, timing
  runs/<case_id>/    ordinary run directories (capture manifest, frames, verification.json)
```

* Per-case seed: `numpy.random.SeedSequence([index, campaign_seed])`;
  draw order fixed by index; workers pull by index → same scenarios and
  bundle digests at any worker count (measured by the 1-vs-4 test).
* Disk: budget from a measured sample render × items, refused by name
  (`storage.budget_exceeded`) before starting and re-checked per batch.
* A campaign that cannot reach its target ends `failed` with `reason`
  (`campaign.target_unreachable`), never `done` at a lower count.
* CLI: `python -m flightsim.campaign "<prompt>" --images N --out DIR
  [--workers W] [--seed S] [--format coco] [--resume] [--pause|--cancel]`.

---

## 7. The tool layer and authority limits (package H)

`core/agent/tools.py` — typed functions with JSON schemas (served over MCP
by `core/agent/mcp_server.py` when the optional dependency is present;
callable directly by the tests and the controller without a model):

```
compile(prompt, answers?)             -> {spec, questions, refusals}
plan_campaign(spec, words, images)    -> {policy, estimate}
sample(campaign_id, n)                -> {cases, refused}
run(case_id, validation_token)        -> {run_id, status}
render(run_id, validation_token)      -> {frames, drawn}
verify(run_id)                        -> {checks, verdict}
export(campaign_id, format)           -> {dataset_path, card}
inspect(run_id, frame?)               -> {overlay_png, records}
report(campaign_id)                   -> {yield, coverage, refusals}
```

Authority, enforced in `core/agent/policy.py` (deterministic, no model):

| Rule | Refusal |
|---|---|
| no write to a field whose source is `user` or `inferred` | `authority.stated_field` |
| `run`/`render`/`export` need a `validation_token` minted by `validate()` for that spec digest | `authority.validation_token` |
| a spec carrying a refusal is denied for `run` with the catalogue sentence | `authority.refusal_is_not_a_run` |
| budgets: max tool calls, max re-samples per slot, max wall time | `authority.budget` |

`trace.jsonl`: one line per call `{t, tool, input, output, reason, policy}`.
The controller loop (`core/agent/controller.py`) plans from the request,
calls tools, reads results, re-samples only system-chosen fields, and
escalates in catalogue language. A scripted rogue agent in the tests tries
each violation and is denied.

---

## 8. The message catalogue and the interface (package I)

* `core/messages/catalog.yaml`: every `Violation` name and every
  progress state → `{sentence, hint?}` with `{param}` placeholders; the
  rule name is kept beside the sentence. `core/messages/__init__.py
  render(name, **params)`.
* A test asserts every constraint name in the codebase (every
  `Violation("...")` first argument and every `"refused": "..."` /
  `constraint` literal) has an entry, and every entry has a live name.
* Endpoints (FastAPI, `webapp/server.py`):
  `POST /generate/plan` (prompt → questions or plan preview),
  `POST /generate/preview` (one sample run with overlays),
  `POST /generate/start`, `POST /generate/{id}/pause|resume|cancel`,
  `GET /generate/{id}` (progress from the ledger, catalogue sentences),
  `GET /generate/{id}/frames` (gallery), `GET /generate/{id}/download?format=`.
* Page: `webapp/static/generate.html` — one flow, six states (ask,
  clarify, preview, generate, review, download), server-sent events for
  progress, plain language by default with the rule name under a
  disclosure. The expert page stays at `/` and every screen names its
  command (`docs/COMMANDS.md`, generated from the tool schema).

---

## 9. Render command flags — one builder (package A, closes the two-path drift)

`core/render/flags.py: render_flags(card, frames, *, scene, mesh, look,
cameras, labels=True, linear=False, deterministic=True, void=False,
width, height, fps)` returns the commandlet argument list used by BOTH
`flightsim/capture.py` and `webapp/runs.py`. A test compiles one spec and
asserts the two callers produce the same flag set, including `-mesh=`.

---

## 10. Look lane settings (owner decisions stated, measured switches)

| Setting | Where | Default this phase |
|---|---|---|
| Engine | `ue/FlightSim.uproject` `EngineAssociation`, every script/doc that says 5.5 | **5.7** (re-vendor JSBSim for 5.7, re-run `check_bridge_api.sh`, re-measure Gate 6 on Windows) |
| Lumen GI + reflections | `ue/Config/DefaultEngine.ini` | on (software) |
| Virtual shadow maps | same | on |
| Nanite for imported meshes | import step | on, re-tested with the label passes |
| Volumetric clouds | `FlightSimVisualScene.cpp`, driven by §5.4 | on when the card carries a cloud layer |
| Beauty AA | commandlet | TSR; label passes none |
| Exposure | commandlet | EV100 from `cameras[].exposure {aperture_f, shutter_s, iso}` (spec 8; defaults per preset); manual bias kept as the override |
| Terrain posting | `FlightSimVisualScene.cpp` | tiled procedural sections at native posting (no 701-vertex cap); Landscape import path is the next step |

Every switch is recorded in `render.json.render_settings` and has a Gate 6
clause.

---

## 11. New refusal names introduced this phase (all in the catalogue)

`spec.version` (kept), `scene.terrain` (a `terrain_source` the machine
cannot honour), `annotation.mask_blend`, `annotation.mask_offset`,
`annotation.box_mismatch`, `annotation.depth_range`,
`annotation.visibility`, `annotation.identity`, `annotation.files`,
`aircraft.placeholder_drawn`, `randomization.vocabulary`,
`randomization.infeasible`, `storage.budget_exceeded`,
`campaign.target_unreachable`, `authority.stated_field`,
`authority.validation_token`, `authority.refusal_is_not_a_run`,
`authority.budget`, `export.unverified` (the existing refusal, named).

---

## 12. Spec 8 — the whole delta in one list

| Section | Field | Type | Default | Package |
|---|---|---|---|---|
| `scene` | `terrain_source` | `auto` \| `flat` \| `synthesised` \| `baked` | `auto` (today's behaviour) | A (the mountain example says `synthesised`) |
| `taxonomy` | `classes` | list of class names | the documented list | B |
| `traffic[]` | `aircraft`, `track`, `range_m`, `livery` | as §2.2 | `[]` | B |
| `randomization` | `policy.*` | as §5.2 | absent (no sampling) | F |
| `cameras[]` | `exposure.aperture_f`, `exposure.shutter_s`, `exposure.iso` | numbers | preset defaults (f/8, 1/500 s, ISO 100 daylight) | Look |

Everything else is unchanged; the digest of a spec that states none of
these is unchanged by construction (absent blocks are canonical).
