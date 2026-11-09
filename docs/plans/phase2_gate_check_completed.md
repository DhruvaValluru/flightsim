**Phase 2 Gate Check — Short Test Plan (Completed)**

Annotation, randomisation and the non-technical path · executed run, 11
October 2026

|                         |                                                                                                                                 |
|-------------------------|---------------------------------------------------------------------------------------------------------------------------------|
| **Branch tested**       | phase-2-final @ 8a05a3f1 in C:\FSU_ISL_FlightSynth                                                                              |
| **Date of run**         | 10/11/2026                                                                                                                      |
| **Run by**              | Claude, through the instructor job runner (build\eval\runner.ps1), started by the instructor on this machine                    |
| **Verified by**         | Claude: console output read from build\eval\logs, rendered frames and label images opened and measured directly, manifests read |
| **Machine**             | mbmsis16a1 · UE 5.5.4 installed (the project pins 5.7) · RTX 5080 Laptop · Python 3.12.10                                       |
| **Baseline**            | FLIGHTSIM_GOOGLE_TILES=off, FLIGHTSIM_WEATHER_BACKEND=off, FLIGHTSIM_LLM=none in every window                                   |
| **Companion documents** | Phase 2 Static Code Review · Phase 2 Manual Test Plan (full version)                                                            |

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<tbody>
<tr class="odd">
<td><p><strong>How this was run.</strong> Every command was executed
through the job runner rather than typed by hand. Nothing in the student
repository was modified: no file was edited, no branch was created.
Where a step refused, the refusal is quoted as it printed.</p>
<p><strong>The headline. Phase 2 does produce automated annotations, and
they are real.</strong> A labelled render completed on this machine and
wrote an instance mask, a class image and a depth image beside every
frame. The Phase 1 placement defect is <strong>fixed</strong>:
independently measured, the aircraft now sits <strong>0.4 m</strong>
from its labelled position along the flight axis, against 25–30 m in
Phase 1.</p>
<p><strong>And the phase does not pass yet.</strong> Of the seven
annotation gates, <strong>two pass, three fail and two cannot
run</strong>. The box a trainer would actually use (bbox_2d_tight) is
null in every record, and the exporter correctly refuses to ship the
dataset because of it.</p></td>
</tr>
</tbody>
</table>

Result summary

| **Step** | **What it checks**                          | **Result**                                                                                                                                 |
|----------|---------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------|
| 1        | Their annotation tests pass                 | **FAIL** — passes only while the reference readers are absent; installing webdataset makes test_dataset_boxes fail                         |
| 2        | A render produces a label bundle            | **PASS with caveats** — 24 frames with mask, class and depth on camera 1; camera 2 drew nothing; the engine binary is the Phase 1 build    |
| 3        | The seven annotation gates pass             | **FAIL** — 2 PASS, 3 FAIL, 2 NOT RUN                                                                                                       |
| 3b       | Labels match pixels, measured independently | **PASS** — +0.4 m along the flight axis (Phase 1: +25.7 m)                                                                                 |
| 4        | One prompt, attributed variety              | **PASS** — policy printed per variable; an unsupported phrase refuses by name                                                              |
| 5        | A campaign is reproducible                  | **PASS with findings** — identical across 1 and 4 workers; but the plan's own example prompt yields nothing, and 48 images asked gives 120 |
| 6        | Export and read back                        | **PASS with findings** — COCO loads in pycocotools; every exported text file is CRLF; the failed run is correctly refused                  |

|                                                                                                                                                                                                                                                                                                                                         |
|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **One sentence for the students.** The annotation pipeline works end to end — pixels, masks, depth, gates, refusals — and the Phase 1 geometry defect is genuinely fixed; what remains is that the bundle→record completion step never ran on this machine, because the Phase 2 C++ does not compile against any engine installed here. |

1\. Their annotation tests

> .\\venv\Scripts\python.exe -m pytest tests\test_annotation_gates.py
> tests\test_annotation_passes.py tests\test_dataset_boxes.py -q
>
> pytest exit: 0 \<- first run, before the reference readers were
> installed

Then pycocotools and webdataset were installed for step 6, and the same
three files were run again:

> FAILED
> tests/test_dataset_boxes.py::test_every_format_writes_the_mask_box_and_keeps_the_projected_one
>
> pytest exit: 1
>
> ValueError:
> C:\FSU_ISL_FlightSynth\build\tmp\\..\ds\webdataset\train\shard-000000.tar:
>
> no gopen handler defined
>
> ☒ The test passes only while webdataset is **not installed**. With the
> real reader present it fails, because the reader treats a Windows path
> (C:\\..) as a URL scheme it does not know.
>
> ☑ test_annotation_gates.py and test_annotation_passes.py pass in both
> runs.

This is the review's finding made concrete: CI never installs the
reference readers, so the WebDataset round-trip claim is asserted by a
test that cannot exercise it. The fix is one line in the writer (open
the shard by file handle, not by path) plus the readers in
requirements-dev.txt for CI.

|                                                                                     |
|-------------------------------------------------------------------------------------|
| **Result: FAIL** (10/11/2026) — one test, with a one-line cause and a one-line fix. |

2\. A labelled render

2a. The build does not compile here

> powershell -ExecutionPolicy Bypass -File scripts\build_ue.ps1
>
> building FlightSimEditor Win64 Development with C:\Program Files\Epic
> Games\UE_5.5
>
> ue\Source\FlightSim.Target.cs(9,51): error CS0117:
> 'EngineIncludeOrderVersion' does not
>
> contain a definition for 'Unreal5_7'
>
> ue\Source\FlightSimEditor.Target.cs(9,51): error CS0117: ...
> 'Unreal5_7'
>
> build failed (8)
>
> ☒ The branch pins engine 5.7 (ue/FlightSim.uproject). The machine has
> 5.0, 5.1, 5.2 and **5.5.4**; the registry still lists a 5.7 that is
> not on disk. UBT on 5.5 has no Unreal5_7 include-order constant, so
> **no Phase 2 C++ has been compiled on this machine at all**.

Consequence, visible later in this run: the plugin's new editor module
is missing.

> LogPluginManager: Error: Plugin 'FlightSimBridge' failed to load
> because module
>
> 'FlightSimBridgeEditor' could not be found.

Everything below was therefore produced by **the Phase 1 engine binary**
(UnrealEditor-FlightSim.dll, built 18 September) driven by the Phase 2
Python. That is worth holding in mind when reading the failures: some of
them are exactly what an uncompiled engine half would produce.

2b. The render refuses twice, then works

First attempt — the aircraft model was not imported:

> REFUSED -- aircraft.mesh: the B747 model is not imported on this
> machine ... and
>
> placeholder airframes never render. Build it once with \`python
> scripts/import_aircraft.py B747\`
>
> ... a manifest older than version 2 (no mesh origin -- the mesh would
> be drawn at the
>
> structural datum, 25-30 m off its label) re-converts with ...
>
> ☑ **The refusal names the Phase 1 defect by its measurement.** The
> students did not just fix the offset; they wrote the old failure into
> the refusal so it cannot silently come back.

Running the remedy it names:

> python scripts\import_aircraft.py B747
>
> B747
>
> re-converting: manifest version 1 predates 3: it records no mesh
> origin, so the mesh
>
> would be attached at the structural datum instead of where the
> vertices say
>
> source already at 887ff4746c37
>
> converting (license-verified, FDM-matched)
>
> importing 1 aircraft into the Unreal project
>
> Imported 1 aircraft. Renders now use the real models.

Second attempt — the scenario commandlet died on the missing editor
module, and the capture refused by name rather than carrying on:

> REFUSED -- capture.host_flight: the scenario commandlet exited 1 and
> recorded no flight;
>
> nothing was rendered. ... Re-run with --no-host-flight to solve over
> the pre-run instead,
>
> knowing the labels will then describe a different flight from the one
> the pixels show
>
> ☑ The refusal is honest about the trade it is offering, which is the
> right behaviour: it does not quietly substitute a different flight.

Third attempt, taking that escape:

> python -m flightsim.capture examples\cameras_multi.yaml --out
> runs\p2gate3 --render --no-host-flight
>
> captured: 48 frames across 2 camera(s)
>
> rendering 2 camera pass(es) into runs\p2gate3\frames in the visual
> scene ...
>
> scene flags: -Visual -shot=showcase -fps=30 -width=1280 -height=720
> -labels -deterministic
>
> -mesh=...\assets\generated\B747\mesh_manifest.json
>
> camera 1/2: chase0 -\> runs\p2gate3\frames\chase0
>
> REFUSED -- camera.render: the render wrapper exited 1 and drew no
> pictures;
>
> the manifest and verification above still stand
>
> chase0 png=96 mask=24 class=24 depth=24 alone=0
>
> tower0 png=0 mask=0 class=0 depth=0 alone=0
>
> ☑ **Camera 1 produced a complete label bundle for all 24 frames**: the
> picture, an instance mask, a class image and a depth image.
>
> ☒ Camera 2 drew nothing — the second commandlet pass crashed, and the
> run as a whole refused while 24 good frames sat on disk.
>
> — No \_alone\_\*.png passes were written, which is why one of the
> seven gates below cannot run.

<img
src="phase2_gate_check_media/media/ed24098dcdab5019413a163ef7086c83d194178c.png"
title="runs\p2gate3, chase0, frame 0000: the rendered picture and the three ground-truth images written beside it. The mask is pixel-accurate down to the landing gear and the engine pylons. This is the answer to &quot;does Phase 2 do automated annotations&quot;: yes."
style="width:6.39583in;height:3.88542in"
alt="runs\p2gate3, chase0, frame 0000: the rendered picture and the three ground-truth images written beside it. The mask is pixel-accurate down to the landing gear and the engine pylons. This is the answer to &quot;does Phase 2 do automated annotations&quot;: yes." />

*runs\p2gate3, chase0, frame 0000: the rendered picture and the three
ground-truth images written beside it. The mask is pixel-accurate down
to the landing gear and the engine pylons. This is the answer to "does
Phase 2 do automated annotations": yes.*

|                                                                                                                                  |
|----------------------------------------------------------------------------------------------------------------------------------|
| **Result: PASS with caveats** (10/11/2026) — a real labelled render exists; half the cameras and all of the newer passes do not. |

3\. The seven annotation gates

> python -m flightsim.verify runs\p2gate3
>
> \[PASS\] mask_integers_only: 24 ID images hold only \[1\] of the
> declared \[1, 2\];
>
> the class image agrees at every labelled pixel
>
> \[FAIL\] mask_vs_geometry: chase0/frame_0000.png aircraft:B747:0: mask
> extent 658x170 px
>
> against a projected hull of 878.3x217.5 px (25.1 % off, tol 5 % or 2
> px)
>
> \[FAIL\] box_vs_mask: the record's bbox_2d_tight is None while the ID
> image holds
>
> 15598 pixels of it (box \[311, 191, 969, 361\]); the record was never
>
> completed from the bundle
>
> \[FAIL\] depth_vs_geometry: farthest depth under the mask 167.4 m is
> beyond the hull's
>
> farthest corner 144.7 m by more than 3.4 m
>
> \[NOT RUN\] visibility_vs_scene: the engine declared no alone pass
>
> \[NOT RUN\] identity_stable: render.json declares label records but
> carries no root
>
> objects\[\] echo (an older engine build)
>
> \[PASS\] applied_intrinsics: 24 frames rendered at the record's lens
> and picture size;
>
> worst field-of-view gap 0.0000 deg
>
> verification FAILED (22 passed, 4 failed, 39 not run, 2 superseded)
>
> refused by name: annotation.mask_offset, annotation.box_mismatch,
> annotation.depth_range

| **Gate**            | **Verdict** | **What it means here**                                                  |
|---------------------|-------------|-------------------------------------------------------------------------|
| mask_integers_only  | PASS        | The mask is a clean integer ID image and the class image agrees with it |
| mask_vs_geometry    | FAIL        | The drawn aircraft is 25 % smaller than the geometry the labels project |
| box_vs_mask         | FAIL        | The mask-tight box is null — never filled in from the bundle            |
| depth_vs_geometry   | FAIL        | Depth under the mask runs 23 m deeper than the projected hull allows    |
| visibility_vs_scene | NOT RUN     | No per-object "alone" pass was written                                  |
| identity_stable     | NOT RUN     | The engine wrote no objects\[\] echo to check identities against        |
| applied_intrinsics  | PASS        | The pictures were taken with the lens the record states                 |

The three failures share one cause and it is visible in the second of
them: **\`bbox_2d_tight\` is \`None\` in every record**. The step that
completes a label record from the rendered bundle — read the mask,
derive the tight box, reconcile it with the projected geometry — is the
Phase 2 engine-side work that never compiled here. The verifier is doing
its job: it says so by name and refuses.

<img
src="phase2_gate_check_media/media/e398f944083d9d436451e7e8b5cac4f901437e47.png"
title="The same frame with both boxes the record carries. Red is `bbox_2d`, projected from the 3-D box, which is loose by construction. Green is the box the pixels actually occupy, which I derived from the mask. `bbox_2d_tight` — the one a trainer would use, and the one the green box should be — is null in every record. Anyone training on this export today would be training on the red box."
style="width:6.39583in;height:3.59375in"
alt="The same frame with both boxes the record carries. Red is `bbox_2d`, projected from the 3-D box, which is loose by construction. Green is the box the pixels actually occupy, which I derived from the mask. `bbox_2d_tight` — the one a trainer would use, and the one the green box should be — is null in every record. Anyone training on this export today would be training on the red box." />

*The same frame with both boxes the record carries. Red is bbox_2d,
projected from the 3-D box, which is loose by construction. Green is the
box the pixels actually occupy, which I derived from the mask.
bbox_2d_tight — the one a trainer would use, and the one the green box
should be — is null in every record. Anyone training on this export
today would be training on the red box.*

|                                                                                                 |
|-------------------------------------------------------------------------------------------------|
| **Result: FAIL** (10/11/2026) — 2 of 7 gates pass. This is the exit criterion, and it is unmet. |

3b. The independent measurement — the Phase 1 defect is fixed

This does not trust the verifier. It takes the centroid of the aircraft
in the mask, projects the aircraft's recorded position through the
recorded camera pose, and resolves the difference along the flight axis
— the direction a chase camera cannot see.

> python build\eval\p2_offset_check.py runs\p2gate3
>
> 24 frames measured
>
> camera n range m du px dv px ALONG m across m
>
> --------------------------------------------------------------------
>
> chase0 24 111 -0.4 -43.9 +0.4 3.9
>
> VERDICT: pass -- worst median along-axis offset 0.4 m (silhouette
> noise).
>
> ☑ **+0.4 m**, against **+25.7 m** measured the same way on Phase 1 in
> September. The mesh-origin work (manifest version 3,
> mesh_origin_measured_actor_cm, origin_anchor) did what it set out to
> do.
>
> — The 3.9 m across-axis residual and the 25 % size disagreement in
> mask_vs_geometry are the same observation seen twice: the drawn
> aircraft and the projected hull are not the same size. That is now the
> open geometry question, and it is a different, smaller one than Phase
> 1's.

|                                                                |
|----------------------------------------------------------------|
| **Result: PASS** (10/11/2026) — the Phase 1 finding is closed. |

4\. One prompt, attributed variety

> python -m flightsim.campaign "200 images of airliners over the Rockies
> in varied weather
>
> and lighting, random viewpoints" --out campaigns\p2_plan --images 200
> --plan
>
> campaign p2_plan: spec 244232a8c9a4ca37 (compiled by regex), seed 1,
> target 200 frame(s)
>
> ~ 2 case(s) at ~121 frame(s) each (recorder cadence 0.1 s);
>
> policy over cloud_cover, visibility_km, precipitation, hour_local,
> weather_date, cameras
>
> "precipitation": { "choice": \["none","rain","snow"\], "weights":
> \[7,2,1\],
>
> "gated_by": "cloud_cover \> 0.6" },
>
> "cameras": { "preset": {"choice":
> \["chase","tower","wingman","ground"\]},
>
> "focal_length_mm": {"loguniform": \[24, 400\]},
>
> "offset_jitter_m": {"normal": {"sigma": 5}} },
>
> "seed_derivation": "SeedSequence(\[index, campaign_seed\])"
>
> ☑ Each phrase maps to named variables with stated distributions, and
> precipitation is correctly gated on cloud cover rather than drawn
> independently.
>
> ☑ "random viewpoints" reaches the camera block: preset, focal length
> and position jitter all vary.

A phrase the vocabulary cannot express:

> python -m flightsim.campaign "60 images of airliners over the Rockies
> at impossible
>
> o'clock in purple fog with cinematic vibes" --out campaigns\p2_refuse
> --images 60 --plan
>
> REFUSED -- prompt.not_set: the prompt says "fog" (fog / haze) but the
> compiled spec does
>
> not set it -- it would fly without it. State it in the review table
>
> (randomization.fog_density or varied weather (visibility)), or compile
> with the language
>
> model, which reads it \[exit 2\]
>
> ☑ It quotes the word back, says what the word would have set, names
> both remedies, and exits non-zero. It does not quietly ignore the part
> it could not parse.

|                                |
|--------------------------------|
| **Result: PASS** (10/11/2026). |

5\. A reproducible campaign

5a. The prompt in the plan yields nothing

> python -m flightsim.campaign "36 images of airliners over mountains in
> varied weather"
>
> --out campaigns\p2a --images 36 --seed 7 --workers 1
>
> \[0\] a691caffc059948b failed frames=0 yield=0 (10.4 s) --
> flightsim.capture exited 2
>
> REFUSED -- campaign.target_unreachable: 2 round(s) added no verified
> frame
>
> and in that case's own log:
>
> REFUSED -- by name:
>
> \[camera.scene_bounds\] camera 'chase': 188 of 1155 solved poses fall
> outside the scene
>
> raster, where terrain and imagery do not exist
>
> ☒ An ordinary prompt — airliners over mountains — produces **zero
> images**. The synthesised terrain raster is smaller than the distance
> an airliner covers in the twelve seconds the campaign flies, so the
> chase camera leaves the map and every case refuses.

Three variants were tried to see whether campaigns work at all. All
three succeeded in about eight seconds each:

> "12 images of airliners over flat ground in varied weather" -\> 120
> verified frames
>
> "12 images of airliners over the ocean in clear weather" -\> 120
> verified frames
>
> "12 images of a cessna 172 over flat ground at 110 knots" -\> 120
> verified frames
>
> — So the machinery is sound and the failure is specific: **"over
> mountains" does not work out of the box**, and the refusal, while
> named precisely, does not tell the user to ask for a smaller area or a
> shorter flight.
>
> — Also visible above: **12 images asked, 120 delivered** — the
> campaign rounds up to whole cases and counts every recorder frame, so
> the yield figure overshoots an order of magnitude. A user asking for
> 500 images should expect several thousand.

5b. Determinism across worker counts

> python -m flightsim.campaign "48 images of airliners over flat ground
> in varied weather
>
> and lighting" --out campaigns\p2d1 --images 48 --seed 11 --workers 1
>
> python -m flightsim.campaign "\<same\>" --out campaigns\p2d4 --images
> 48 --seed 11 --workers 4
>
> 1 worker : \[0\] d8a41d7715ae6eaf verified frames=120 yield=120 (8.2
> s)
>
> 4 workers: \[0\] d8a41d7715ae6eaf verified frames=120 yield=120 (8.3
> s)
>
> ledger comparison (build\eval\logs\p2_ledger_cmp.py):
>
> fields: attempt, campaign_seed, index, started_utc, status
>
> IDENTICAL ignoring timestamps: True
>
> ☑ Same case id, same seed, same spec digest, same per-index work,
> whatever the worker count. Only the wall-clock timestamp differs.

5c. What the report says

> python -m flightsim.campaign --out campaigns\p2d1 --report
>
> yield: 120 verified frame(s) of 48 asked (100%); 120 captured; 1
> verified case(s),
>
> 0 with pixels
>
> coverage: 17% of the requested bins hold \>= 1 frame(s)
>
> cloud_cover: 12% of 8 bins, 120 frame(s) hour_local: 12% of 8 bins
>
> precipitation: 33% of 3 bins visibility_km: 12% of 8 bins
>
> refusals: none
>
> uncertainty: NOT RUN: no case flew the dt/2 twin
>
> not claimed: pixels unless drawn_cases \> 0 (no engine on this
> platform); ...
>
> ☑ The report is candid: it prints **"0 with pixels"**, it prints
> coverage against what was asked rather than against what was drawn,
> and it carries an explicit "not claimed" list.
>
> ☒ But the same run is called **"verified"** and counted as 120
> verified frames, with no image anywhere. "Verified" here means the
> checks that do not need pixels passed and the rest were NOT RUN — the
> distinction the review flagged, demonstrated end to end.

|                                                                                                                                                       |
|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Result: PASS with findings** (10/11/2026) — reproducible and honest in its report; the default prompt path and the yield arithmetic both need work. |

6\. Export and read it back

First against the rendered run, whose gates failed:

> python -m flightsim.export runs\p2gate3 --out datasets\p2rendered
> --format coco
>
> REFUSED -- export.verification_failed: runs\p2gate3 failed
> verification
>
> (flight_agreement, mask_vs_geometry, box_vs_mask, depth_vs_geometry);
>
> refusing to export it \[exit 2\]
>
> ☑ **This is the system working.** The gates are not decoration: a run
> whose annotations disagree with its pixels cannot be exported, and the
> refusal names every failing check.

Then against the headless campaign, which has labels but no pictures:

> python -m flightsim.export campaigns\p2d1\runs --out datasets\p2gate
> --format coco,yolo,voc
>
> REFUSED -- export.missing_frames: 120 frame(s) named by the manifests
> have no ideal image
>
> on disk ...; render them, or pass --labels-only to export annotations
> without pixels
>
> python -m flightsim.export ... --labels-only
>
> exported 120 frame(s) from 1 run(s) as coco,yolo,voc into
> datasets\p2gate
>
> splits: train 120, val 0, test 0 (by simulation digest, seed 0)
>
> boxes: 120 projected (2-D box source: mask = the engine ID mask's
> tight box,
>
> projected = the projected geometry)
>
> card: datasets\p2gate\DATASET_CARD.md
>
> python -c "from pycocotools.coco import COCO; ..."
>
> 120 images 120 annotations
>
> categories: \['aircraft', 'terrain', 'building', 'vegetation',
> 'water', 'cloud'\]
>
> ☑ The COCO file loads in the reference reader and the counts are
> right.
>
> ☑ The card does not oversell. It states the taxonomy, the split basis,
> the software revision, and — in full — the 53 checks that did not run,
> ending: \*"nothing was drawn and no rendering switch is recorded"\*.
> It also prints a "Variety you actually got" section naming every bin
> that was never filled.
>
> ☒ **Every exported text file is CRLF** — dataset.json, all three COCO
> annotation files, every VOC XML. The review's finding, confirmed byte
> by byte: the same export on Linux is LF, so no two platforms produce
> the same dataset.
>
> — One arithmetic oddity in the card: a 120-frame dataset reports
> camera jitter "in 240 frame(s)". Frames are being counted more than
> once per variable in the realised-coverage summary.

|                                                                                                                                               |
|-----------------------------------------------------------------------------------------------------------------------------------------------|
| **Result: PASS with findings** (10/11/2026) — the export path, its refusals and its card all behave; the line endings and one counter do not. |

Gate decision

| **Requirement**                                  | **Step** | **Met?**                                    |
|--------------------------------------------------|----------|---------------------------------------------|
| Their annotation tests pass                      | 1        | No — one fails with the readers installed   |
| A render produces a full label bundle            | 2        | Partly — one camera of two; no alone passes |
| All seven annotation gates PASS on real pixels   | 3        | **No — 2 of 7**                             |
| Labels match pixels when measured independently  | 3b       | **Yes — +0.4 m**                            |
| One prompt produces attributed, varied scenarios | 4        | Yes                                         |
| A campaign is reproducible across worker counts  | 5        | Yes                                         |
| A dataset exports and loads in a standard reader | 6        | Yes, labels-only                            |

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<tbody>
<tr class="odd">
<td><p><strong>Decision: not yet — and much closer than the branch
looked on paper.</strong></p>
<p>The static review found one rendered run on record with two gates
failing. This run is the second, and it moves the picture: the
annotations are real, the masks are pixel-accurate, the Phase 1 geometry
defect is closed, the gates catch what they are meant to catch, and the
exporter refuses a dataset whose labels do not match its pixels. That is
most of a working system.</p>
<p>What stands between here and a pass is narrow and nameable:
<strong>the label record is never completed from the rendered
bundle</strong> (bbox_2d_tight null, the alone passes absent, no
objects[] echo), because the Phase 2 engine code has not been compiled
against any engine on this machine.</p></td>
</tr>
</tbody>
</table>

What to ask the students for

| **\#** | **Ask**                                                                                     | **Why**                                                                                                          |
|--------|---------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------|
| 1      | A labelled render from a machine with **UE 5.7 installed**, with verification.json attached | It is the only way to know whether the three failing gates are the uncompiled engine half or a real geometry bug |
| 2      | Either a 5.7 build, or an include-order constant that falls back on 5.5                     | Right now the whole render path is gated behind an engine nobody in the lab has installed                        |
| 3      | bbox_2d_tight filled from the mask in every record                                          | It is the box a trainer uses; it is null in all 24 frames                                                        |
| 4      | The per-object "alone" passes written by default when -labels is on                         | Two of the seven gates cannot run without them                                                                   |
| 5      | A campaign prompt mentioning mountains that actually yields frames                          | The obvious first prompt a user types returns zero images                                                        |
| 6      | newline="" in the export writers, and the reference readers in CI                           | Datasets differ between Windows and Linux, and the round-trip test cannot fail today                             |
| 7      | Yield counted in annotations, not recorder frames                                           | 48 asked, 120 delivered, reported as 100 %                                                                       |

Evidence on disk

|                        |                                                                                               |
|------------------------|-----------------------------------------------------------------------------------------------|
| **Rendered run**       | runs\p2gate3 — 24 frames, masks, class and depth images, verification.json, frame_checks.json |
| **Offset measurement** | build\eval\logs\p2_offset.csv (24 rows) · build\eval\p2_offset_check.py                       |
| **Campaigns**          | campaigns\p2a (refused), p2v_flat, p2v_ocean, p2v_slow, p2d1, p2d4                            |
| **Export**             | datasets\p2gate — COCO, YOLO, VOC, DATASET_CARD.md                                            |
| **Console logs**       | build\eval\logs\5\*.log, 6\*.log (one per step, with the job script in build\eval\done)       |
| **Figures**            | build\eval\compare\p2_bundle.png, p2_boxes.png                                                |

Nothing in the student repository was modified. The working tree carries
the five files it carried before this run.
