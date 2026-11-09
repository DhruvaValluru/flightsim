# Visual overhaul probe log

Each lane keeps its own `## <lane>` section, so merges stay trivial. Every
entry is either code that has not been rendered yet (session flightsim-83,
2026-11-09, Mac, code only) or a number a probe render on the render
machine has set. The shared record is ruflo memory, namespace `visual`, key
`visual-overhaul/<lane>/<topic>`. The render machine reads this repo copy.

## verifier-tooling

Session flightsim-83, 2026-11-09. Code only: nothing here has been
rendered. Schema: `docs/schemas/render_json_beauty_look.md`.

### What was built

- `core/capture/beauty_look.py` (new) reads the render.json keys
  `scene.render_quality` (measure|beauty|pathtrace), `beauty_look`,
  `pixel_moving_effects`, `beauty_samples`, `beauty_only_actors`,
  `cloud_occlusion` and the per-frame `beauty_window_s`.
- `core/capture/verify.py` gets two new checks, run by `flightsim.verify`
  and by every batch and campaign verify:
  - `look_record` checks quality, that measure is left alone, the sample
    counts, the occlusion decision, and that every pixel-moving key is
    listed.
  - `look_label_alignment` checks the transform or measured displacement
    of each pixel-moving effect, a cloud over the subject, the FOV against
    the pose solver, and that labels come from the same frame and instant.

  On failure the run is refused by name: `look.quality`,
  `look.measure_altered`, `look.pixel_moving_unrecorded`, `look.record`,
  `look.beauty_not_label_aligned`. These have catalogue entries in
  `core/messages/catalog.yaml`. Old bundles stay valid: their look checks
  are PASS (quality only) or NOT RUN, never FAIL.
- `experiments/look_label_check.py` (new) measures the mask-edge offset
  against the luminance-gradient silhouette in a measure bundle and a
  beauty bundle of the same card and frame. It includes a self-validation
  control (a 3 px shift must be recovered, or the result is VOID).
  Unit-tested on synthetic pictures in `tests/test_look_label_check.py`.

### Decisions

- A pixel-moving effect is label-aligned only with a recorded transform,
  or with a **measured** displacement of at most `LOOK_ALIGNMENT_TOL_PX` =
  `MASK_TOL_PX_MESH` = 2.0 px. That is the gate tolerance, not a new
  constant. An uncalibrated displacement is not evidence. Anything else
  fails as `look.beauty_not_label_aligned` and export refuses it.
- A beauty-only cloud or contrail in front of the subject is a label error.
  The `cloud_occlusion.policy` options:
  - `kept_clear` (by construction)
  - `none_in_frame`
  - `labels_unoccluded`, which needs a **measured**
    `subject_occluded_fraction` of at most `VISIBILITY_TOL_FRACTION` =
    0.03. Otherwise the bundle is refused.
- On measure, the look must be absent or `{"applied": false}`, with no
  pixel-moving effect and `beauty_samples.temporal` = 1. Otherwise it
  fails as `look.measure_altered`.
- The beauty FOV must equal the pose solver's (2 atan(w/2fx)) within
  `APPLIED_FOV_TOL_DEG` = 0.1 deg. This is the existing applied_intrinsics
  tolerance.
- Not treated as pixel-moving: depth of field, bloom, grain, vignette,
  tonemapping and the colour grade. These change values, not positions.
  Depth of field on an out-of-focus subject would spread its edge.
  `look_label_check` reads that as edge distance, not offset.

### UNCALIBRATED constants (experiments/look_label_check.py)

Each is set by a probe render on the render machine:

| constant | value now | the probe render that sets it |
|---|---|---|
| `SEARCH_RADIUS_PX` | 6 | The beauty chase frame with the look-dev lens distortion on. The largest recorded corner displacement must fit inside it. |
| `EDGE_PERCENTILE` | 80 | The measure chase frame. Its p90 edge distance should sit near 1 px. |
| `CONTROL_SHIFT_PX` | 3 | The measure chase frame. The control must recover the shift. |
| `CONTROL_SLACK_PX` | 1.0 | The same probe. Widen it only if the measure control is VOID on a picture known to be aligned. |

### Engine symbols

None added. This lane wrote no C++, so `scripts/check_bridge_api.sh` is
unchanged.

### Hooks other lanes must write (render host, render-path / look-dev)

The commandlet does not write the new keys yet. Until it does,
`look_label_alignment` is NOT RUN on every bundle. When a lane turns a
pixel-moving effect on, it must write `pixel_moving_effects`. When it
writes `VisualScene.BeautyOnlyActors` names into render.json, it must also
write `cloud_occlusion`. The verify gate does not ask for anything beyond
those two.

### Render-machine commands

Render the same card twice from the web app on Windows, so the masks
come from the labelled path:

```powershell
$env:FLIGHTSIM_RENDER_QUALITY = "measure"; .\.venv\Scripts\python.exe -m uvicorn webapp.server:app --port 8008   # capture card X -> runs\webapp\<measure_id>, stop the server
$env:FLIGHTSIM_RENDER_QUALITY = "beauty";  .\.venv\Scripts\python.exe -m uvicorn webapp.server:app --port 8008   # capture the SAME card X -> runs\webapp\<beauty_id>
.venv\Scripts\python -m flightsim.verify runs\webapp\<beauty_id>
.venv\Scripts\python -m experiments.look_label_check --measure runs\webapp\<measure_id> --beauty runs\webapp\<beauty_id> --camera chase --out runs\visual\look_label_check.json
```

`look_label_check` exits 0 for ALIGNED, 1 for NOT ALIGNED and 2 for VOID.
Record each run's offsets here, and in ruflo under
`visual-overhaul/verifier-tooling/probe-<date>`, before changing any
constant above.
