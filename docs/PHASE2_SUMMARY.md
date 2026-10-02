# Phase 2 -- what was implemented, how to run it, what remains

The short deliverable document for Phase 2 (annotation, randomisation and
the non-technical path). The long record, package by package, is
`docs/PHASE2_REPORT.md`; this page is the instructor's entry point.

Status line, honestly: every work package A-I is implemented in code and
held by tests that run without an engine (the suite, plus 770 mutation
guards). The annotation gates have been run on ONE real Windows render
(UE 5.7.4, D3D11, A-4 over the Matterhorn), and two of them failed there:
`mask_integers_only` (ids 44-49 no object owns) and `mask_vs_geometry` (an
empty aircraft alone pass). The capture path has since been hardened and
instrumented for exactly those (below); the exit criterion "annotations
correct and proven so on every camera" is NOT met until a re-render passes.

## How to run it (Windows, engine present)

From the repo folder in PowerShell (`.\.venv\Scripts\python.exe` is
`python` below):

```powershell
# the non-technical path: nothing below the browser
python -m uvicorn webapp.server:app --port 8008
#   open http://127.0.0.1:8008/generate.html, type e.g.
#   "500 images of airliners over mountains in varied weather and
#    lighting, chase and tower views, COCO format", press Generate,
#   watch, read the card, download

# the same campaign from the command line
python -m flightsim.campaign "..." --out campaigns/demo --render
python -m flightsim.export campaigns/demo/runs --out datasets/demo --format coco,yolo,voc

# the checks
python -m flightsim.verify campaigns/demo/runs/<case>   # geometry AND annotation gates
python -m pytest tests/test_annotation_gates.py tests/test_annotation_passes.py tests/test_dataset_boxes.py -q
python tests/visual/annotation_sheets.py <run_dir> --out build/visual   # pictures to look at
python scripts/label_diagnose.py <run_dir>    # what the mask images hold, in text
```

Every page screen names its command in the "expert path" footer;
`docs/COMMANDS.md` maps every agent tool to its CLI and page equivalent.

## What was implemented, per work package

* **A -- Phase 1 corrections.** The 25-30 m airframe offset: the mesh was
  hung at the flight model's datum while the model is built about its own
  origin; the origin is now measured from the vertices (mesh manifest 3).
  `--render` passes `-mesh=` or refuses. What the engine drew (mesh or
  placeholder) is recorded in `verification.json` (`drawn_airframe`), and
  a placeholder never carries the mesh's hash. "pull back" is graded
  against the keyframed offset. Preflight's vswhere sees Build Tools. The
  mountain refusal example refuses with no flag. The -89.5 m AGL bug (a
  synthesised ridge substituted under a staged datum) is fixed. The
  event-trigger and hazard-refusal examples ship.
* **B -- identity and masks.** Stable class/instance ids per object
  (aircraft, terrain, building/vegetation aggregates), the taxonomy in
  spec and manifest, per-frame ID images from the custom stencil, scripted
  second aircraft (`examples/traffic.yaml`), in-scene vs labelled per object.
* **C -- boxes, depth, occlusion.** Boxes are taken from the mask (the
  projected box kept beside it, and `box_vs_mask` fails a disagreement);
  clipped and unclipped boxes with `truncation` and `fraction_in_frame`;
  visibility from per-aircraft alone passes; float32 and 16-bit depth; a
  3-D box and orientation in camera coordinates; a `not_claimed` record.
* **D -- quality gates.** Seven annotation checks in the verifier with
  stated tolerances and named failures; a FAIL, or a NOT RUN on a run that
  has engine labels, refuses export. The grader imports no producer code
  (enforced by an AST test and a fresh-interpreter test). Every verdict is
  bound to the manifest bytes it graded. Mutation guards for every gate,
  including a 3 m airframe shift; a visual sheet for every gate.
* **E -- export.** COCO, KITTI, WebDataset, YOLO and Pascal VOC, chosen on
  the page and recorded in the card; read back by pycocotools, the
  `webdataset` package's own reader and an XML parser (YOLO and KITTI by
  line readers); digest-based splits with policy and seed; a card with
  counts, class balance, conditions, per-run spec/seed/verdict and box
  source, shown on the page before download; labels-only downloads say so.
* **F -- randomisation from the prompt.** A policy over location, weather,
  wind, turbulence, surface, airframe, traffic count and camera placement
  and lens; prompt words ("varied weather", "random viewpoints", "mixed
  traffic"...) extracted with attribution and refused by name when
  inexpressible; refused draws re-drawn and counted; every drawn value
  recorded `sampled` with policy, seed and draw index, on the ledger too;
  a sampled traffic count becomes scripted aircraft; the realised
  distribution is reported.
* **G -- campaigns.** Create, watch, pause, resume, cancel; a worker pool,
  disk budget and fsynced ledger; headless; identical scenarios and
  digests at 1, 2 and 4 workers; a campaign below target ends
  `target_unreachable` with the reason. A prompt's "500 images" is the
  dataset size, spread over many varied scenarios.
* **H -- agent.** Eleven typed tools (compile, validate, plan, sample, run,
  render, verify, export, inspect, report, bake); a controller that reads
  each result and re-draws only system-chosen fields, bakes a named place
  it lacks, and escalates by name; authority limits enforced and tested;
  `trace.jsonl` beside the campaign.
* **I -- the page.** `generate.html`: prompt, plain-language question,
  plan and estimate, one sample case, Generate, progress with time left,
  the card, download in the chosen format. Rule names only under
  "details".

## What remains

1. **Real-render proof of the annotations (blocking for exit).** On the
   owner's machine re-render a labelled run, then run `flightsim.verify`,
   `annotation_sheets.py` and `label_diagnose.py` on it. Label captures now
   pin unit exposure (eye adaptation off, manual exposure) -- the most
   likely cause of the stray ids -- and the commandlet logs
   `labels.diagnostic` lines for stray ids and an empty alone pass. If the
   gates still fail, those lines say where.
2. **A rendered campaign at scale**, at 1 and 2+ workers, exported to three
   formats and loaded elsewhere. Every campaign test so far is headless.
3. **Not claimed / out of scope:** per-instance buildings and vegetation
   (one aggregate id each), cloud and fog occlusion measured from pixels
   (analytic only), YOLO/KITTI read by the official tools (line readers
   here), "across the Rockies" (no bake yet), rain drawn (recorded only),
   the cockpit preset confirmed on a render. Photorealism is Phase 5.
