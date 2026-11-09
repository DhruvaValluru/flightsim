**Phase 2 — Static Code Review**

Annotation, randomisation and the non-technical path · branch
phase-2-final

|                         |                                                                                                                     |
|-------------------------|---------------------------------------------------------------------------------------------------------------------|
| **Repository / branch** | DhruvaValluru/flightsim · phase-2-final @ **8a05a3f1** (276 commits, 16,325 files changed since the Phase 1 branch) |
| **Reviewed**            | 11 October 2026                                                                                                     |
| **Method**              | Full source read (1,174 tracked text files) + the shipped test suite executed on Windows. No render was attempted.  |
| **Working copy**        | C:\FSU_ISL_FlightSynth (Windows, UE 5.5 installed; the branch now pins UE 5.7)                                      |
| **Companion documents** | Phase 2 Implementation Plan · Phase 1 Initial Run Report · Phase 1 Gate Check (Completed)                           |

1\. Summary

**All nine Phase 2 work packages are implemented**, and several are
better engineered than the plan asked for. The randomisation policy, the
campaign runner, the message catalogue and the export card are strong,
carefully provenanced work. The students' own documentation is unusually
honest: docs/PHASE2_SUMMARY.md opens by stating that the phase's exit
criterion is **not** met.

Three things dominate the assessment. First, **the exit criterion is
open and the branch cannot currently close it**: one real Windows render
has ever been made, two of the seven annotation gates failed on it,
every C++ change since is uncompiled, and the engine target moved from
5.5 to 5.7 with nothing re-measured. Second, **about 44,000 lines —
roughly the size of Phase 2 itself — implement work nobody asked for**,
including two items that are explicitly out of scope and now sit in the
default render path. Third, **the shipped test suite fails on Windows**:
12 failures and 2 errors, almost all from one portability defect they
have already fixed twice elsewhere.

| **Area**                       | **Assessment**                                                                                                                                                                                       |
|--------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Packages A–I                   | All implemented. B, C, E, F, G strong; D's independence claim is weaker than stated; H is a deterministic loop, correctly described as such; I is real but makes one false claim in its own UI copy. |
| Shipped tests (Windows)        | 3,387 tests, **12 failures + 2 errors**, 25 skipped, 20.9 min. Four of five failure families are one bug.                                                                                            |
| Phase 1 carry-over (package A) | All ten items addressed in code. The aircraft-offset fix is plausible and well explained, but unproven: it needs a render.                                                                           |
| Exit criterion                 | **Not met**, and the students say so. Annotation correctness is proven only against synthetically painted test bundles.                                                                              |
| Out-of-scope work              | ~44,000 lines, ~43% of the tests, most of the new C++. High craft, wrong phase; two items carry real risk.                                                                                           |
| Overall                        | Substantial, honest and ambitious work that has not yet demonstrated the one thing the phase was defined by.                                                                                         |

2\. Method

- The branch was fetched into the existing Windows working copy and
  every tracked text file was read (1,174 files; ~100k lines of Python,
  ~64k lines of tests, ~23k lines of C++).

- The shipped test suite was run on Windows with the project's own
  setup.ps1 environment (Python 3.12).

- **No render was attempted.** No Unreal build, no campaign, no dataset
  export. Everything below is reading plus the suite result; the manual
  test plan that accompanies this document is what exercises the engine.

- Four independent passes were made over the code — annotations and
  gates, export/randomisation/campaign, agent and interface, and
  out-of-scope inventory — and their findings cross-checked against the
  students' own reports.

|                                                                                                                                                                                                                                                                      |
|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Where this document says a thing is "claimed", the claim is in the students' documentation or in the shipped UI text, and the finding is that the code does something different. Where it says "unproven", the code looks right and no machine has yet confirmed it. |

3\. The shipped test suite, on Windows

python -m pytest on the branch: **3,387 tests, 12 failures, 2 errors, 25
skipped, 20.9 minutes**. The skips are legitimate (no C++ compiler for
source-parity tests, no EGM2008 grid, no pycocotools, Windows symlink
privilege, no Phase 9 bakes).

| **Failure family**                                  | **Count** | **Cause**                                                                                                                                                                                                                                                               |
|-----------------------------------------------------|-----------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| test_radiometry (5) + test_sensing_block (2 errors) | 7         | The CIE V(λ) and ASTM G173 tables fail their own sha256 sidecars: assets/cie/\*\* and assets/illuminants/\*\* are **not** marked -text in .gitattributes, so a Windows checkout rewrites their line endings. The whole sensing/radiometry path refuses on this machine. |
| test_camera_profile                                 | 1         | Same cause: assets/camera_profiles/\*.json digests are pinned but the files are not protected.                                                                                                                                                                          |
| test_derive_injections                              | 1         | Same family: a pinned template hash does not survive the checkout.                                                                                                                                                                                                      |
| test_dataset_formats (frozen writer)                | 1         | Exported JSON differs by \r\n vs \n. The export writers use write_text with no newline="", so **every COCO / KITTI / YOLO / VOC / card file is CRLF on Windows and LF on Linux**.                                                                                       |
| test_xplane                                         | 1         | Path built with the OS separator where the format requires / (+40+000\\46+007.png).                                                                                                                                                                                     |
| test_licence                                        | 1         | A refusal name differs from the expected one (aircraft.licence_dataset vs asset.licence) — environment-dependent, worth a look.                                                                                                                                         |
| test_camera_verify_corruption                       | 1         | A placeholder/mesh rule assertion fails on a machine that has the real B747 imported. Touches package A, so it should be understood rather than waved off.                                                                                                              |

|                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **The headline finding of the suite run.** .gitattributes already carries a comment saying exactly this failure was measured on a Windows runner and fixed for four asset directories. Two more directories with the same contract were missed, and the exported-dataset line endings were never considered at all. The fix is three lines of .gitattributes plus newline="" on the writers — but until it lands, the sensing path does not load on Windows and datasets are not byte-identical across platforms. |

4\. What was built, package by package

A — Phase 1 corrections

All ten carry-over items are addressed in code. Verified by reading:

| **Carry-over item**                            | **State on this branch**                                                                                                                                                                                                                |
|------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 25–30 m airframe offset                        | Diagnosed as the mesh hung at the flight model's datum while the model is built about its own origin; the origin is now **measured from the vertices** (mesh manifest v3). Plausible and well explained. **Unproven without a render.** |
| --render never passed -mesh=                   | Now passes it or refuses (flightsim/capture.py, refuse_placeholder_mesh).                                                                                                                                                               |
| Manifest recorded a mesh the engine never drew | The engine now reports what it drew; drawn_airframe is a verifier check and a placeholder never carries the mesh hash.                                                                                                                  |
| Cockpit preset not a forward view              | Cockpit remains the one roll-inheriting preset; the offset fix is the claimed cure. **Unproven.**                                                                                                                                       |
| pull back tripped pose_matches_spec            | Now graded against the keyframed offset.                                                                                                                                                                                                |
| Preflight false "C++ workload missing"         | Fixed: vswhere -latest -products \*.                                                                                                                                                                                                    |
| Mountain refusal needed an undocumented flag   | Fixed: scene.terrain_source: synthesised in the spec; --synth-terrain is now an alias.                                                                                                                                                  |
| −89.5 m AGL web refusal                        | Fixed: a synthesised ridge was substituted under a staged datum.                                                                                                                                                                        |
| No event-trigger example                       | examples/cameras_event_trigger.yaml ships.                                                                                                                                                                                              |
| No hazard/scene-bounds refusal example         | examples/cameras_hazard_refusal.yaml ships.                                                                                                                                                                                             |

B — Object identity and masks

- One composition point for identity (core/capture/objects.py): stable
  string ids, composition-order integers 1–255, hard refusals for \>255
  ids and duplicates, class_id from a spec-carried taxonomy, and a
  three-way presence model (absent / in scene but unlabelled / unknown).
  Schema-required in manifest v7.

- Traffic is real end to end: examples/traffic.yaml, scripted tracks
  with digests, per-frame traffic_states, one label record per aircraft.

- **The documentation is now wrong about how masks are made.**
  objects.py, labels.conventions() and the contracts page all say the ID
  image is the Custom Depth Stencil. Since 2026-10-06 the commandlet
  instead takes one show-only scene-depth capture per id and awards a
  pixel to the id whose depth matches — identity is \*reconstructed by
  depth comparison\*, not read. Two artefacts of the abandoned route
  survive, including a material whose absence still refuses the render
  although nothing uses it.

C — Boxes, depth, occlusion

- Per object and per frame: clipped and unclipped 2-D boxes, truncation
  and fraction_in_frame computed as complementary ratios so they cannot
  disagree, a mask-tight box, a mesh-hull box, an amodal box, a full 3-D
  box in camera coordinates with the KITTI terms, world placement,
  keypoints, horizon, depth min/median, visible_fraction, occluded_by
  and occluded_pixels_by.

- Depth ships as float32 (+inf sky) and as a 16-bit PNG. Atmospheric
  transmittance is kept deliberately separate from geometric occlusion.

- 3-D boxes are reconstructible from the manifest alone, and a test
  rebuilds the eight corners from centre + extents + axes and reprojects
  them.

D — Annotation quality gates

- Seven annotation gates plus label_geometry, keypoints_in_box,
  label_files and drawn_airframe, each with stated tolerances and
  catalogue names; export refuses on FAIL and on a NOT RUN gate where
  engine labels exist.

- 38 mutation guards on the annotation block, each target verified
  unique, with a suite-level lint that fails if a refactor orphans one.

- **The independence claim is not enforced by its own tests.** The AST
  test scans only direct imports of verify.py against a hand-written
  list that omits core.capture.manifest; the fresh-interpreter test
  deliberately avoids verify_run. Measured: calling verify_run loads
  seven of the seventeen banned producer modules. The independence is
  real in substance — no grading check consumes a producer-computed
  value — but a future import would sail through both tests.

- **The sharp gate is blind along the line of sight.**
  mask_vs_geometry's 2 % centre clause is the only real placement check;
  on a chase-only run (the documented default) a 3 m along-axis shift
  passes every gate, because the depth backstop's tolerance is 1 % of
  range + 2 m — 3.1 m at the default 110 m chase station. Their own test
  for the 3 m shift passes only because it names a **wingman** frame as
  the first offender.

- box_vs_mask's IoU floors tolerate roughly 11 % of span of pure
  translation at 0.8 and 33 % at 0.5, so it is a sanity check, not a
  placement check.

E — Dataset export

- Five writers — COCO, KITTI, WebDataset, YOLO, Pascal VOC — with the
  awkward conventions handled correctly and the reasons written in code
  (YOLO's deliberately absent path key; VOC's 1-based inclusive boxes;
  byte-reproducible tars).

- Six named, pre-write refusals including manifest-digest staleness and
  an annotation-gate gate; nothing is written before they fire.

- A genuinely informative card: per-run verification detail, per-asset
  licence verdicts, box-provenance counts, requested-versus-realised
  variety in numbers and sentences, and a not_claimed list computed from
  the data.

- **CI never installs the reference readers.** pycocotools and
  webdataset are in requirements-dev.txt; the workflow installs only
  requirements.txt, so the three tests that use a real third-party
  reader skip on every CI run, silently. The headline "round-tripped
  through the format's own reader" claim is never exercised by
  automation.

- **The verification gate is advisory.** Writing {"ok": true} into a
  run's verification.json defeats all four export refusals. Disclosed in
  the card as verification_bound_to_manifest: false, but that is
  disclosure, not a control.

F — Randomisation from the prompt

- Nineteen policy leaves plus a camera group: location, weather date,
  hour, visibility, cloud cover and base, precipitation, wind speed and
  direction, turbulence, surface, aircraft, livery, traffic count, fuel,
  payload, icing, and per-camera preset / focal length / offset jitter.
  Nine distribution forms, gates, circular wrapping with the wrap
  recorded.

- A drawn value is as immovable as a stated one: SAMPLED is deliberately
  absent from the plannable set, enforced structurally and tested.

- Refused draws are **counted, recorded with their values, and
  re-drawn**, with policy \*defects\* correctly distinguished from
  unlucky draws, and the spec restored byte-identical on refusal.

- The prompt vocabulary is the sampler's own table, asserted at import
  from both compilers, with conjunction expansion and a
  randomization.vocabulary refusal that quotes the sentence back on
  three surfaces.

- Realised-versus-requested coverage is computed over the frames that
  actually shipped, with honest support declarations and plain-language
  narrowness warnings.

G — Campaign execution at scale

- Full state machine (planned/running/paused/failed/done/cancelled) with
  an explicit transition table; a spawn process pool; an append-only
  fsynced ledger that is the only source of truth; a measured disk
  budget; and an output-based watchdog that kills the process tree.

- **Determinism across worker counts is measured, not asserted**: the
  same campaign at 1 vs 2 and 1 vs 4 spawned workers is compared on
  per-case seeds, sampled values, manifest spec_digest /
  simulation_digest / output_digest, and the whole ledger. This is the
  strongest single piece of evidence on the branch. It proves headless
  determinism; pixel determinism is untested, and they say so.

- A campaign never reports done below target; it fails by name with the
  constraints its draws hit.

- **Yield counts frames, not annotations.** A run of 96 frames in which
  the aircraft left the picture in 40 counts 96 toward the target, and a
  campaign can report 100 % of target without reporting how many images
  carry a label. Worse, a run whose annotation gates were all NOT RUN is
  counted as "verified" by the batch, the campaign and the web page.

H — Agentic controller

- Eleven typed tools with schemas generated from the Python signatures,
  each a thin call into existing library code, with one chokepoint no
  other path bypasses.

- Authority is enforced in code, not prose: a provenance-comparing
  stated-field rule, an independently recomputed validation token, a
  refusal-keyed run block and four budgets — exercised by a scripted
  "rogue agent" performing ten distinct violations, and backed by six
  live mutation guards.

- The loop is deterministic with data-driven branching (continue /
  narrow / escalate), and the module says so plainly rather than
  dressing it up as an agent runtime. The narrow outcome — count met,
  variety not, dataset still exported, explicitly refusing to raise the
  image count "because the count is the person's" — is thoughtful
  design.

- **The LLM tier is broken for answer rounds**: compile omits
  questions=, which the LLM compiler refuses outright, so every --tier
  llm --answer … silently degrades to the offline parser.
  Tools(tier="llm") has no test at all.

- The trace is beside the dataset, not bound to it: not in the download
  zip, not referenced by the card, and a non-named exception leaves no
  trace line.

I — The non-technical interface

- A six-state guided page (generate.html): ask → clarify → preview →
  generate → review → download, with a live campaign table, SSE
  progress, pause/resume/cancel, a gallery, the card in plain words
  before download, and the zip.

- **The message catalogue is the best single piece of work in the
  phase.** 399 entries; a source-scanning test that covers Python
  \*and\* the uncompiled C++, expands dynamic names by reading their
  defining sources, and fails if a name is uncovered or dead. Measured
  here: 340 emitted names, zero uncovered, zero dead. A server
  middleware re-words any 4xx that names a rule, so a raw constraint id
  cannot reach the page.

- Estimates and progress are measured rather than asserted: the preview
  really flies one case through the campaign's own worker, and an
  unmeasured projection is None with a stated basis.

- **The page claims masks and boxes it never draws.** The UI text says
  "the rendered frame with the mask and box drawn on it", but the only
  overlay writer on that path draws a horizon, landmark circles and
  crosses, a body glyph and crosshair stubs — no mask, no box rectangle.
  The module that does draw boxes is not written by the runner the page
  uses and is not in the page's image list. On every machine, the
  pictures the user sees carry no mask and no box.

- Spec vocabulary leaks on the default path: histogram titles and
  drawn-value lines print leaf names with underscores swapped for spaces
  ("hour local", "sun elevation deg"), while a correct plain-label table
  exists and is used only in the card.

- The page's default compiler tier is llm, and with no key and no
  configuration that resolves to the students' hosted relay — so a bare
  clone sends the user's prompt to a third-party service by default.

5\. Gaps against the Phase 2 intent

Ranked by what they cost the phase.

| **\#** | **Gap**                                                                                                                                                                                   | **Why it matters**                                                                                                           |
|--------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------|
| 1      | **The exit criterion is not met.** Annotations are correct only against painted test bundles. One real render exists; mask_integers_only and mask_vs_geometry failed on it.               | This is the phase. Everything else is preparation for it.                                                                    |
| 2      | **Nothing on the branch has been compiled or rendered since that one run**, and the engine target moved 5.5 → 5.7 with Gate 6, exposure and vertex-palette calibrations all taken on 5.5. | The first 5.7 render is a probe, not a dataset. Ten new C++ subsystems are in front of it.                                   |
| 3      | **"NOT RUN" counts as verified** in the batch, the campaign and the page. A headless campaign reports verified frames with zero annotation grading.                                       | The one number a non-technical user reads can be made entirely of ungraded runs.                                             |
| 4      | **The placement gate is blind along the camera axis** and loose below ~70 px of span; the default is a single chase camera.                                                               | This is the exact class of defect Phase 1 shipped. Catching it still depends on the user asking for a second, off-axis view. |
| 5      | **Campaign yield is frames, not annotations.**                                                                                                                                            | "Annotation yield against the request" was an explicit plan item; it is not reported.                                        |
| 6      | **The export verification gate trusts a JSON file** anyone can write.                                                                                                                     | The refusal is advisory, not a control.                                                                                      |
| 7      | **The reference-reader round trip is never run by CI.**                                                                                                                                   | The strongest external-validity claim in package E is untested by automation.                                                |
| 8      | **The page promises masks and boxes on its pictures and draws neither.**                                                                                                                  | A non-technical user judges annotation quality by looking. There is nothing to look at.                                      |
| 9      | **The agent's LLM tier cannot do an answer round**, untested.                                                                                                                             | The page defaults to that tier; the agent CLI silently degrades.                                                             |
| 10     | **Windows portability defects** in pinned-digest assets, exported line endings and one path separator.                                                                                    | Windows is the render platform. Their own suite proves it.                                                                   |

6\. Additions beyond Phase 2

Roughly **44,000 lines of Python, about 43 % of the 3,387 tests, and
most of the new C++** implement work outside packages A–I. Nearly all of
it is documented, provenanced, mutation-guarded and candid about what is
unverified. In aggregate it is a second project of Phase 2's size,
landed on the Phase 2 branch.

| **Addition**                                                                                                                                                      | **Size**                        | **Original phase**            | **Assessment**                                                                                                                                |
|-------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------|-------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| Record framework: per-variable provenance, read-back, null tests, GUM uncertainty, requirement→test→guard traceability, Gebru datasheet, tabular export           | ~4,000 lines                    | None — new                    | Most aligned with the project's goal. Keep.                                                                                                   |
| Sensing passes: world normals, optical flow with validity, disparity, point clouds, amodal masks, stereo rig, radiometry, PSF, motion blur, exposure              | ~4,450 lines                    | Phase 5                       | Highest product value of the out-of-scope work; standard perception ground truth, each graded by an independent check.                        |
| Vertical datum / EGM96 geoid                                                                                                                                      | ~1,400 lines                    | None — new                    | Closes a measured 23–53 m absolute-height error. Small, correct, bounded.                                                                     |
| Physics layers: non-standard atmosphere, von Kármán turbulence, wind shear, gusts, icing, failures, wake, loading, limit monitoring, modal analysis, rain physics | ~10,300 lines                   | Phase 3 in effect             | Excellent engineering, wrong phase. Buys diversity the dataset cannot yet use.                                                                |
| Instrument models (IMU/GPS/pitot/magnetometer with Allan deviation)                                                                                               | ~2,300 lines                    | None — new                    | Useful for state estimation, dead weight for detection.                                                                                       |
| DIS interoperability (IEEE 1278.1 entity-state PDUs + CLI)                                                                                                        | ~2,400 lines                    | None — new                    | Textbook-clean, and of no use to an image dataset.                                                                                            |
| World: land cover, weightmaps, 3DEP, night lights, buildings, runways, moon/starfield, physical sky                                                               | ~10,000 lines + C++             | Phase 5 — explicitly excluded | Data halves tested; engine halves uncompiled and in places nothing reads the files yet.                                                       |
| Weather as a drawn thing: three overlapping render paths (look, rain particles, storm weather with synthesised thunder audio)                                     | ~5,800 Python + ~2,640 C++      | Phase 5 — excluded            | The branch itself says the overlap is unresolved. The heaviest path is **on by default** for every web run.                                   |
| Route lane: draw a flight path on a map, live feasibility checks, fly it for real                                                                                 | ~3,250 lines                    | Phase 6                       | Genuinely good, produced a real autopilot bug fix, nobody asked for it.                                                                       |
| Expert-page additions: 3-D camera placer, lens picker, conditions list, lighting panel, terrain prefetch                                                          | ~2,140 lines                    | Phase 6                       | Appear in no phase document at all.                                                                                                           |
| X-Plane 12 extraction lane: ground drape, sky tables, decompiled logic reimplemented                                                                              | ~3,000 lines + committed assets | None — new                    | See risks. Feeds the default render path.                                                                                                     |
| Google Photorealistic 3D Tiles, hardcoded on                                                                                                                      | ~414 C++ + spec rules           | Phase 5 — excluded            | See risks.                                                                                                                                    |
| A-4 Skyhawk airframe                                                                                                                                              | ~1,350 lines + assets           | Phase 5 — excluded            | Its licence is not on the dataset allow-list, so it cannot ship in a distributable dataset — and it is the airframe the one real render used. |

**Two structural consequences.** SPEC_VERSION went 8 → 9 with
**fifteen** new top-level blocks, none of them a package A–I
deliverable, plus a manifest-version and record-version bump. The
absent-canonical discipline and the frozen spec-8 examples make this
safe today, but the schema an instructor must read is now carrying
roughly three times the surface Phase 2 justified. And
core/capture/verify.py is now 8,884 lines running **69 checks**, of
which seven are the agreed annotation gates — while the export refuses
on **any** FAIL, so an out-of-scope check (grey card, land cover, night
exposure, instrument Allan deviation) can block the in-scope dataset
export.

7\. Risks to raise before the next phase

7.1 The X-Plane lane — decide this first

core/xplane/ (~3,000 lines) extracts water masks, terrain catalogues,
ground textures and sky-colour tables from a local X-Plane 12 install,
and reimplements rules read out of **decompiled** subsystem sources and
**disassembled** shader archives, both committed under
assets/logic_reports/, alongside a copy of the simulator's Resources/
tree. It is wired into the default render path: the ground texture a
georeferenced render wears and the sky lighting flags both come from it.
NOTICE.md credits the aircraft models, the Copernicus terrain and the
Poly Haven textures, and says nothing about X-Plane. In a project whose
own export gate refuses assets that fail a licence allow-list, that is
an inconsistency that could follow every dataset produced. Its 52 tests
were also landed unrun.

7.2 Mandatory Google Photorealistic 3D Tiles

Terrain renders now require Google's 3D Tiles and the Cesium plugin
unless an environment variable turns them off, and a render that cannot
draw them refuses by name. CLAUDE.md records the instruction and adds
"do not make them opt-in again". This puts a paid, keyed, rate-limited
network service in front of the one thing Phase 2 still has to prove,
and it is a reproducibility hazard for a dataset generator whose selling
point is provenance.

7.3 The engine move and the uncompiled C++

EngineAssociation is now 5.7, with a new renderer-settings block (Lumen,
VSM, Nanite, TSR, extended luminance range) that by its own comments
moves the luminance every Gate 6 clause was tuned on. Three patched
upstream bugs in the vendored JSBSim plugin were measured on 5.5, and
the plugin claims 5.0–5.6 compatibility. None of it is compiled.

7.4 Weather on by default

webapp/runs.py sends the procedural storm backend at gain 4, cinematic
style, on **every** web render. Two overlapping weather paths both draw
drops, storm clouds and lightning, and the branch says which to keep is
an open question. This has already cost an engine crash and a
black-frame debugging cycle, and it sits directly on the path the
annotation gates must be re-proved on.

7.5 Determinism and provenance at the edges

Headless determinism across worker counts is proven. Pixel determinism
is not, and the render path now includes a network tile service, a
weather backend chosen by default, and a texture source derived from a
third-party simulator.

8\. Questions for the students

- **When can a labelled render be reproduced?** What has to happen — a
  5.7 build, a Google key, a bake — before the seven gates can be run
  again, and what did the two failures on the one real render turn out
  to be?

- **What is the licensing position on the X-Plane extraction?** Which
  files are derived from the simulator, what is committed, and why is
  none of it in NOTICE.md?

- **Why are Google tiles mandatory rather than opt-in?** What is the
  fallback when there is no key, and does a dataset built with them
  carry a usable licence?

- **Why does the page say masks and boxes are drawn on the preview when
  nothing draws them?** This is the user-visible claim a non-technical
  reviewer will check first.

- **Should "NOT RUN" count as verified?** It currently does, in the
  batch, the campaign and the page.

- **Does a single chase camera satisfy the placement gate?** The 2 %
  centre clause cannot see an along-axis shift, which is the Phase 1
  defect class.

- **Which of the fifteen new spec blocks belong to Phase 2?** The schema
  is carrying substantially more than the phase justified, and the next
  reviewer inherits all of it.

- **Were the two weather paths meant to ship together, and why is the
  heavier one on by default?**

9\. What happens next

This review is reading plus the test suite. The accompanying **Phase 2
Manual Test Plan** exercises the engine: a build on 5.7, one labelled
render, the seven gates against real pixels, an independent
mask-versus-geometry measurement of my own (the Phase 1 method that
found the 25–30 m offset), a campaign at two worker counts, an export
read back with each format's own reader, and the guided page end to end.
The **short gate check** condenses that to the handful of steps that
decide whether the phase passes.

Two things to settle before that runs: whether Google tiles can be
turned off for the evaluation, and which weather backend the gates
should be proved against.
