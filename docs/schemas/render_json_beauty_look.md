# render.json: the beauty look's record (visual overhaul)

Owner: verifier-tooling lane. Read by `core/capture/beauty_look.py` and
graded by `look_record` and `look_label_alignment` in
`core/capture/verify.py`. The render host writes these keys into each
camera's `frames/<camera>/render.json`, beside the keys it already writes.

**Who writes them (integration, 2026-11-09).** The render commandlet writes
all five root keys on every `-quality=beauty` and `-quality=pathtrace`
render, and none on `-quality=measure`:

| key | written by | filled from |
|---|---|---|
| `beauty_look` | `FFlightSimBeautyLook::Record` (look-dev) | the `-beauty-look=` sidecar and what was read back; absent without a sidecar |
| `pixel_moving_effects` | `RenderWriteLookContract` (FlightSimRenderCommandlet.cpp) | the beauty capture's show flags and post-process settings read back after every lane ran, and `aircraft_look.heat_haze` |
| `beauty_samples` | `RenderWriteLookContract` | `render_settings.beauty_path.accumulation.captures_per_frame` (still samples), the TSR history constants, `-pathtrace-spp`, the engine motion blur's shutter |
| `beauty_only_actors` | `RenderWriteLookContract` | `VisualScene.BeautyOnlyActors` (the weather, weather-look, rain, starfield and world fair-cumulus actors appended to it), `AircraftFX.BeautyOnlyActors`, and the world's volumetric cloud owners (hidden by the Cloud show flag) as `{"name", "source", "hidden_by"}` objects |
| `cloud_occlusion` | `FFlightSimWorldBeauty::CloudOcclusionRecord` (world), then `RenderMergeMeasuredCover` (commandlet) | the per-frame slab model (`basis` `"modelled"`), replaced on a beauty raster render by the measured cover (`basis` `"measured"`, below) when it ran |

The commandlet writes one `pixel_moving_effects` entry for each of
`motion_blur`, `depth_of_field`, `heat_haze`, `path_tracer_filter`,
`chromatic_aberration`, `lens_distortion`, `lens_drops` and
`windshield_rain`, with `on` measured off the capture
(`core/capture/beauty_look.py COMMANDLET_EFFECTS`). The last two are the
rain blendables (`M_LensDrops`, `M_WindshieldRain`) found by base
material in the beauty's `WeightedBlendables`; both refract the scene,
and their `max_displacement_px` is a bound by construction. None carries a
transform or a measured displacement yet, so a beauty render with any of
them on is graded beauty-not-label-aligned until
`experiments/look_label_check.py` measures it. That is the rule working:
labelled sets come from `-quality=measure`. `tests/test_render_json_contract.py`
checks the commandlet source against these tables.

**Every key here is optional.** A render.json written before them stays
valid: `look_record` grades only the quality (`scene.render_quality`, on
every render.json since V0) and `look_label_alignment` reports NOT RUN.
Neither ever fails on a key's absence.

## The rule this record exists for

Labels must match pixels. Masks, class, depth and boxes come from label
captures of the same frame as the beauty, and those captures never see
the look. An effect that only changes a pixel's colour (exposure, tone
map, grade, bloom, grain, vignette, depth of field on an in-focus
subject) leaves every label true. An effect that changes **where** a pixel
lands (lens distortion, chromatic aberration, heat-haze refraction, heavy
motion blur, panini projection, overscan, upscaling or resampling) moves
the subject off its mask. Such an effect is beauty-only, and either:

1. a **transform** that maps the labels onto the beauty is recorded, or
2. its **measured** displacement is within the mask gate's tolerance
   (`LOOK_ALIGNMENT_TOL_PX` = `MASK_TOL_PX_MESH` = 2.0 px), or
3. the bundle fails `look_label_alignment` as
   `look.beauty_not_label_aligned`, and the dataset export refuses it.

An uncalibrated displacement estimate is not evidence of alignment, however
small it is.

## Keys

### `scene.render_quality` (string; existing key, new value)

`measure` | `beauty` | `pathtrace`. Root `quality` is read as an alias
when `scene` lacks it. Any other value fails as `look.quality`.

On `measure`, which is the path Gate 6 passed on, nothing may change:
`beauty_look` must be absent, empty or `{"applied": false}`, no
pixel-moving effect may be on, and `beauty_samples.temporal`,
`beauty_samples.spatial`, `beauty_samples.still_samples` and
`render_settings.beauty_path.accumulation.captures_per_frame` must each be
1 (the commandlet captures a measure frame once and never supersamples
it). Otherwise the run fails as `look.measure_altered`. The host's record
(`FFlightSimBeautyLook::Record`: `sidecar`, `plan`, `applied`) counts as
a look applied when `applied` is a non-empty object or `sidecar` names a
file.

### `beauty_look` (object)

The look-dev lane's record of the look applied. The verifier does not grade
its contents. It only searches them, through every nested object, for
the keys that move pixels:

| key(s) | effect name |
|---|---|
| `motion_blur`, `motion_blur_amount` | `motion_blur` |
| `lens_distortion` | `lens_distortion` |
| `chromatic_aberration`, `scene_fringe_intensity` | `chromatic_aberration` |
| `heat_haze`, `refraction` | `heat_haze` |
| `panini`, `panini_d` | `panini` |
| `overscan`, `overscan_fraction` | `overscan` |
| `upscale`, `upscaling`, `screen_percentage` | `upscale` |
| `temporal_accumulation` | `temporal_accumulation` |
| `MotionBlurAmount` (the C++ record's spelling) | `motion_blur` |
| `SceneFringeIntensity` (the C++ record's spelling) | `chromatic_aberration` |
| `PaniniD`, `ScreenPercentage` (UE spellings) | `panini`, `upscale` |

`MotionBlurMax` is not a switch (it caps the smear and draws nothing while
`MotionBlurAmount` is 0). When the record carries the host's non-empty
`applied` echo, its `plan` subtree (the request, and descriptive rows such
as `plan.pixel_effects.motion_blur`) is not searched: `applied` is what
was set on the capture.

A key counts as on when its value is `true`, a non-zero number, a word
other than off/none/false/0, or an object whose `on`, `enabled` or
`applied` is true, or whose `amount`, `intensity`, `strength`, `scale`,
`k1`, `fraction` or `max_displacement_px` is non-zero.
`screen_percentage` / `ScreenPercentage` is on away from 0 (the engine default) and 100. A key
that is on and has no entry in `pixel_moving_effects` fails as
`look.pixel_moving_unrecorded`. `motion_blur` and `temporal_accumulation`
answer for each other. The on/off words are matched without regard to case.

The commandlet's own measurement is read too, on every bundle whatever
its age: `render_settings.beauty_show_flags.motion_blur` (written today,
FlightSimRenderCommandlet.cpp) `true` counts as `motion_blur` on. UE 5.7
turns motion blur off on every scene capture, so `true` means it was
turned on. On a measure render it fails as `look.measure_altered`; on a
beauty render it must be listed in `pixel_moving_effects`.

Optional `beauty_look.camera.fov_deg` (or `beauty_look.fov_deg`) is the
beauty camera's horizontal field of view. It must equal the pose solver's,
2 atan(width / 2 fx) from the capture manifest, within
`APPLIED_FOV_TOL_DEG` (0.1 deg). The commandlet writes a per-frame
`frame_records[].beauty_fov_deg` (the beauty capture's `FOVAngle`, beauty
and pathtrace only), which overrides it; without either, the look-dev
record's `beauty_look.applied.camera.fov_deg_unchanged` is compared. The
PASS text claims the field of view only when a comparison ran.

### `pixel_moving_effects` (list)

```json
[{"name": "lens_distortion", "on": true,
  "transform": {"kind": "brown_conrady", "k1": -0.021, "k2": 0.0, "p1": 0.0, "p2": 0.0},
  "max_displacement_px": null, "displacement_basis": "uncalibrated"},
 {"name": "motion_blur", "on": true, "transform": null,
  "max_displacement_px": 0.8, "displacement_basis": "measured"}]
```

- `name` (required). A bare string entry means `{"name": s, "on": true}`
  with nothing else recorded.
- `on` defaults to true, because the effect was listed. Entries that are
  off are not graded.
- `transform`: an object with a non-empty `kind` and finite numbers. It is
  the mapping from label pixels to beauty pixels.
- `max_displacement_px` with `displacement_basis`. Only `"measured"`
  counts. `experiments/look_label_check.py` is the measurement.

### `beauty_samples` (object)

`spatial`, `temporal` and `path_tracer_spp` must each be a whole number of
at least 1, and `shutter_s` a time of at least 0. A malformed value fails
as `look.record`. A `pathtrace` render must state its samples per pixel:
`beauty_samples.path_tracer_spp` or the render path's
`render_settings.beauty_path.path_tracer.samples_per_pixel` (the same
`PathTraceSpp`; two that disagree fail as `look.record`).
Temporal samples greater than 1 over a non-zero shutter make motion blur
by accumulation, so `temporal_accumulation` or `motion_blur` must be
listed. (The S4 per-frame `accumulation` of `-accumulate=K` is a separate
record, graded by `engine_accumulation`.)

### `beauty_only_actors` (list) and `cloud_occlusion` (object)

`beauty_only_actors` names the actors in `VisualScene.BeautyOnlyActors`
(FlightSimRenderCommandlet.cpp / FlightSimVisualScene.cpp), which are
hidden from every label capture. When the list is non-empty,
`cloud_occlusion.policy` must be one of the values below, or the run
fails as `look.record`:

- `labels_unoccluded`: the mask shows the subject where a beauty-only
  cloud or contrail may cover it. This is aligned only with a `"measured"`
  `subject_occluded_fraction` at or below `VISIBILITY_TOL_FRACTION`
  (0.03). With no number, or an unmeasured one, the run is
  beauty-not-label-aligned.
- `kept_clear`: the visual scene keeps beauty-only volumes out of the
  camera-to-subject cone by construction, so the mask has nothing to
  miss.
- `none_in_frame`: no beauty-only actor projects into the frame.

The world lane's per-frame rows, `look_applied.world_beauty.frames[]`
(FlightSimClouds.cpp), are graded too: a frame with
`cloud_occludes_aircraft` true, or with `cloud_occlusion_complete` false
(a drawn cloud outside the slab model, so "not flagged" is only a lower
bound), makes the run beauty-not-label-aligned unless `cloud_occlusion`
carries a `"measured"` covered fraction, which supersedes the model.

**The measured cover (2026-11-11).** On a `-quality=beauty` raster render
with `-labels` (never on measure or pathtrace), the commandlet measures
the covered fraction itself (`FlightSimRenderCommandlet.cpp`, constants at
`RenderCoverCaptureDivisor`). For each sampled delivered frame it takes two
extra captures at half the output size (`capture_px`) from the beauty's
camera, pose and field of view: one as the beauty draws, one with every
`beauty_only_actors` entry hidden (`HiddenActors`) and the Cloud show flag
off. Both come from their own capture component: lens-free, no TSR, no
persistent view state, manual exposure, no post blendables. The beauty
capture's hidden list and temporal history are never touched, and the
captures run after the frame's readback, so the beauty frame is unaffected.
Inside the subject's label mask (the primary `int_id` in
`frame_NNNN_mask.png`; a capture pixel counts when at least 3/4 of its
2x2 block is the subject), a pixel is covered when its sRGB luma differs
between the two captures by more than 10 % of the brighter one and by
more than 3 codes. The frame's fraction is covered pixels / mask pixels.
Every delivered frame is sampled up to 64, then at a fixed stride. A
frame whose mask shows no subject pixel is measured as 0. The fraction is
an upper bound: a hidden cloud's shadow and reflection on the subject also
count as covered. The thresholds are UNCALIBRATED (stated, not tuned).

When every sampled frame was measured, the policy stays
`labels_unoccluded` and the record carries:

| key | meaning |
|---|---|
| `subject_occluded_fraction` | the max over the sampled frames |
| `basis` | `"measured"` |
| `method` | the rule above, in words |
| `threshold` | `{"relative_luma": 0.10, "luma_floor_codes": 3, "mask_block_share": 0.75, "basis": ...}` |
| `capture_px` | `[width, height]` of the two captures |
| `frames_measured`, `frames_delivered`, `sample` | how many frames, out of how many, at what stride |
| `measured_frames` | per frame: `frame`, `subject_label_pixels`, `mask_pixels`, `changed_pixels`, `fraction` (or `not_measured` with the reason) |
| `modelled_fraction`, `modelled_basis`, `modelled_method` | the world lane's numbers it replaced (`modelled_fraction` null when the model had none) |

When it did not run (`-measure-cover=off` on the command line or in
`FLIGHTSIM_RENDER_SWITCHES`, no `-labels`, no subject, an engine-metered
exposure, pathtrace) or a sampled frame could not be measured, the
modelled fraction (or null) stands, `basis` gains `"; cover not measured:
<why>"`, and `measured_cover` holds the reason. The verifier's rule is
unchanged: only `basis == "measured"` at or below the tolerance is aligned.

Decision (verifier-tooling, 2026-11-09): a cloud in front of the
aircraft in the beauty and absent from the mask is a label error, not a
look. It is either kept out of the cone, measured under the visibility
gate, or the bundle is refused. The amodal masks (S2) already carry the
"behind something" case for real occluders. Beauty-only actors are not
real occluders, because the physics and the labels never see them.

### `render_settings.label_show_flags` (object, beauty and pathtrace)

The label capture's own show flags, read back by the commandlet after
registration: anti-aliasing, temporal AA, motion blur, depth of field,
bloom, lens flares, grain, vignette, local exposure, colour fringe, lens
distortion, refraction, path tracing, eye adaptation, translucency, cloud
and fog. Any `true` fails `look_label_alignment` (the labels saw the look).

Why it exists (integration, 2026-11-09): UE 5.7 `USceneCaptureComponent::
OnRegister` calls `UpdateShowFlags()`, which resets `ShowFlags` to the
class default and re-applies only `ShowFlagSettings`. Flags set before
`RegisterComponent()` were lost, which is the `"DEFECT: label capture
anti-aliasing show flag is on"` in `tests/fixtures/engine_bundle_min`
(a pre-overhaul render). The beauty's TSR, lens and path-tracing flags were
lost the same way. On beauty and pathtrace the commandlet now pins every
flag through `ShowFlagSettings` (`RenderPinShowFlags`). Measure renders keep
the registration Gate 6 passed on, so their labels are unchanged and the
recorded defect still stands there. Changing that is the owner's call.

### per frame (`frame_records[]`)

- `beauty_window_s`: `[t0, t1]`, the beauty's exposure or accumulation
  window. It must contain the record's `t`, the labels' instant.
- Every file-valued entry of `labels` (`.png`, `.f32`, `.exr`, `.json`,
  `.bin`, `.npy`) must carry this frame's stem (`frame_0000_...`).

Either key on a frame record makes `look_label_alignment` grade that
camera even without a root look record.

## Failure names (core/messages/catalog.yaml)

`look.quality`, `look.measure_altered`, `look.pixel_moving_unrecorded`,
`look.record`, `look.beauty_not_label_aligned`. The check names are
`check.look_record` and `check.look_label_alignment`.
