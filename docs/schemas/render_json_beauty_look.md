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
| `cloud_occlusion` | `FFlightSimWorldBeauty::CloudOcclusionRecord` (world) | the per-frame slab model; `basis` is `"modelled"`, never `"measured"` |

The commandlet writes one `pixel_moving_effects` entry for each of
`motion_blur`, `depth_of_field`, `heat_haze`, `path_tracer_filter`,
`chromatic_aberration` and `lens_distortion`, with `on` measured off the
capture (`core/capture/beauty_look.py COMMANDLET_EFFECTS`). None carries a
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
pixel-moving effect may be on, and `beauty_samples.temporal` must be 1.
Otherwise the run fails as `look.measure_altered`.

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

A key counts as on when its value is `true`, a non-zero number, a word
other than off/none/false/0, or an object whose `on`, `enabled` or
`applied` is true, or whose `amount`, `intensity`, `strength`, `scale`,
`k1`, `fraction` or `max_displacement_px` is non-zero.
`screen_percentage` is on away from 0 (the engine default) and 100. A key
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
`APPLIED_FOV_TOL_DEG` (0.1 deg). A per-frame `beauty_fov_deg` overrides it.

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
as `look.record`. A `pathtrace` render must state `path_tracer_spp`.
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

Decision (verifier-tooling, 2026-11-09): a cloud in front of the
aircraft in the beauty and absent from the mask is a label error, not a
look. It is either kept out of the cone, measured under the visibility
gate, or the bundle is refused. The amodal masks (S2) already carry the
"behind something" case for real occluders. Beauty-only actors are not
real occluders, because the physics and the labels never see them.

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
