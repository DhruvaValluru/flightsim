# Resume here

**Fresh session? Read docs/CONTEXT_SCENE_DIRECTOR_SESSION.md and
docs/CONTEXT_PHASE8B_SESSION.md first**, then this file's gotchas 1-28.

**Standing until the Windows logs are pasted back: the engine
per-camera pass, engine_parity on rendered pixels, the overlays on
rendered frames, the by-product clip's ffprobe length and the page's
frames flow are NOT YET RUN on Windows.** Do docs/CAMERA_PHASE1_REPORT.md
"Engine verification (Windows)" steps 1-7 (build; the one command,
whose expected stdout is generated from the honest engine stub with
only the engine_parity digits masked x; the two commandlet passes and
their log lines; the tree; the verifier and its failure demonstrations;
ffprobe on the clip; the overlays looked at; the page; --against) and
paste every log back; the report's "Status today" table says, per
deliverable and dated, what was measured here and what awaits. The
render choice: the CLI's `--render frames|clip|none` IS the page's
Render frames and clip / Clip only / Headless (the same three words,
core.capture.render_pass.RENDER_WORDS), default the richest the
machine supports (render_choice_default), engine options refused
`ue.platform` by name with the machine's reason, the choice recorded
in run.json / provenance.json "render".

**Camera Phase 1, docs round 1 (2026-09-05, the judge's seven ranked
gaps against bar section 7, all seven closed in priority order, four
code/doc commits plus this tally).** (1) The Windows expected-output
block (report section 2) is GENERATED: scripts/examples_expected.py
generate_frames() runs `--render frames --brief` on the honest engine
stub in a child process (`--frames-stub-run`), normalises paths, masks
only the engine_parity row's MEASURED digits as x (mask_engine), and
`--write` splices it between the frames_expected markers; measured
15.39 s wall, exit 0, 82 stdout lines, 15 model loads, 48 previews at
0.074 s/frame, 48 overlays at 0.172 s/frame, 1439 steps per pass, ten
PASS rows, "done: rendered 48 frames ...". tests/test_camera_cli.py::
test_the_documents_windows_frames_block_matches_the_stub_run
regenerates and compares it (15.3 s) and reads verify.json's counts
and every run.json key back from the run. (2) The run card's mixture
probe is routed through the console sink WHOLE (construction, run_ic,
trim, the sustain steps; stamp "FGFDMExec(B747, mixture probe)"): the
Mass Properties Report JSBSim prints at run_ic (debug level 1) no
longer lands on stdout under "nothing of JSBSim's on stdout" --
measured on `--card --render none`: 96 lines before, 82 after, 0 ANSI
escapes, the report at line 546 of jsbsim.log; pinned under capfd.
(3) Section 6c's path was `capture<FF>rames\chase0<LF>ender.json` (an
interpreted \f); fixed, and the report is pinned to carry no control
character but newline. (4) The expected tree's verify.json line said
8 checks against the ten-row table: 10/10/10 now, read back from the
stub run's file; run.json's line names every key (jsbsim_log,
previews, overlays added). (5) A dated "Status today" table at the
top of the report, per deliverable x platform, every engine cell
"NOT YET RUN -- section N" (the one Windows observation, the pre-
rewrite clip flow before 2026-09-03, is dated as such). (6) README's
capture section no longer says "Off macOS" (Windows renders after the
build, as its own table says) and quotes 0.074-0.075 s/frame from the
dated blocks (0.049 was stale); core/util/platform.py's docstring
carries ue_unavailable_reason()'s words, not "macOS-only". (7) The
standing block above, and gotchas 1-28. tests/test_camera_docs.py is
new (6 tests, 0.05 s). 11 guards under "docs round 1", each verified
firing by subset (1 + 4 + 6: 1m26, 6m43, 2.5 s). Touched test files
in full: 98 passed in 118 s. Gotchas: (a) a `\f` or `\r` typed inside
a Python string that writes Markdown is interpreted -- grep the
document for bytes below 0x20 after writing it (the test does now);
(b) the honest stub's engine_parity row is all zeros BY CONSTRUCTION
(it draws where the label says), so a generated block must mask that
cell or it prints zeros as the engine's; (c) the mutation runner
mutates docs in place too -- never edit the report while a docs guard
subset runs; (d) capsys does not see JSBSim's C++ output, capfd does.
STILL NOT YET RUN: everything in the status table's engine column.

**Camera Phase 1, page round 3 (2026-09-05, the judge's eight ranked
gaps against bar section 4, all eight closed in priority order, eight
code commits; docs/CAMERA_PHASE1_REPORT.md section 6 (fallback words,
parity captions), 6b (the dishonest pass) and the new 6c are
current).** (1) The flight path is drawn from the telemetry file the
run LISTED (telemetrySource: telemetry.json, else
capture/telemetry.json, else nothing), through the whitelist route.
(2) The page's DOM glue runs under node (tests/page_dom.js: a
60-line-DOM over index.html's own script, fetch from the TestClient's
payloads) -- poll, renderCapture, initFilesPanel, toggleOverlays,
renderSpec, editedSpecDict, startRun are executed, not regex-pinned.
(3) ONE refusal shape for the whole page (refusalWords in the
PAGE_CAPTURE block: "[constraint] message (requested X unit, limit Y
unit)"); every 409 carries constraint/message/actual/limit/unit
(server.refusal_payload, runs.platform_refusal, runs.busy_refusal;
new constraint names run.busy and editor.locked; the old keys stay).
(4) Keyframed moves carry provenance (CameraSpec.moves_source /
moves_from, set_moves(); serialised only when moves exist, so a
move-less camera's digest is unchanged); the page's keyframe rows are
inputs writing into dict.cameras[i].moves[k], the source column the
recorded word or "spec data (no recorded source)" in grey. (5)
verify.json's engine_parity data carries "frames" (per camera: index,
t_s, ok, gaps, that frame's problem sentences); /files galleries
attach it; a rejected frame is captioned "parity FAIL: <sentence>" in
red with a red outline. (6) renderSpec/provenanceNote/renderVerdict
escape everything. (7) A /files failure is said by name in the card.
(8) The headless fallback is the platform gate's sentence once. 29
guards under "page round 3" (8 for gaps 1-2, 21 for gaps 3-8), each
verified firing by subset. Full suite after the round: 818 passed, 1
skipped in 331 s. The 14 "page round 2" and the 8 earlier "page round
3" guards were re-fired to completion: 21 ok, 1 SKIP (the contact-sheet
guard's target moved when gap 5 added failedWords to galleryHtml;
repointed and re-fired: ok).
Gotchas: (a) Python 3.11's Enum raises TypeError on `"str" in Enum`
-- validate against `[s.value for s in Source]`; (b) page_dom.js
serialises innerHTML with entities kept (&ldquo; stays &ldquo;), so
assert the entity form, and page_capture returns a dict -- index
["refusals"] / ["moves"]; (c) an escaping guard is WEAK unless the
test carries the escaped character in the EXACT interpolation the
guard mutates (the scalar-value guard needed a quoted aircraft value);
(d) no prompt vocabulary produces moves, so the page's keyframe rows
show only for a spec that carried them (Known limitations); (e) the
DOM harness's setInput now reports sourceCells (every cell sharing
the input's data-src-key) beside sourceCell.

**Camera Phase 1, page round 2 (2026-09-05, the judge's seven ranked
gaps against bar section 4, six closed in priority order, six code
commits; docs/CAMERA_PHASE1_REPORT.md section 6 and the new 6b are
current).** (1) A FAILED run is terminal for the page: poll() asks
runIsTerminal (done OR failed) and draws the clip words (clipHtml:
headless / "the run FAILED before a clip was encoded -- <status line>"
/ "the by-product clip was not encoded"), the capture card (its refused
branch, now a path the live page takes; or the counts with
"(engine pass FAILED: <status line>)" right after "verified") and the
files panel with the strip -- measured on the mid-run
camera.terrain_clearance refusal (4 files, downloads ['everything'])
and on a 3-of-4 short engine pass (frames.zip = 3 PNG + render.json,
downloads frames/manifest/verification/telemetry/everything, no clip).
(2, NOT closed: needs the engine) the frames path stays "awaiting
Windows verification". (3) closure.json's window word is "capped" (the
first min(duration, 22) s) or "full duration", with spec_duration_s
beside duration_s; the page reads "the first 12 s, the same window a
clip would cover, capped at 22 s" on a headless run, "the clip's
window" only on a clip run, "of the 120 s flight" when the cap bit.
(4) On a frames run the preview contact sheet lives INSIDE the
previews' <details> ("...: 4 shown, and their contact sheet"); the
first <img> under a rendered count is a rendered frame. (5) as_dict
carries the whole event log (25 of 25 through /runs/<id>). (6) A
"verification" download class (verify.json) between manifest and
telemetry -- six classes on a frames run; the tally links
capture/verify.json and the closure heading capture/closure.json
(fileLink, built from the payload's run_id only). (7) The review table
shows each camera's keyframed MOVES (the judge called them planner
moves; a planner's change is the field's provenance note) as rows
after its fields, units from the field rows. 14 new guards under
"page round 2", each verified firing by subset. Gotchas: (a) text_of
turns "</span>;" into ") ;" -- assert the clause and the order, not
the joined string; (b) the poll() string test forbids the word
"failed" inside poll(), comments included; (c) the harness (page_
capture) now also returns terminal, clip and moves; (d) any test that
lists download classes must include "verification"; (e) gap 2 is the
only one left and it is the engine's.

**Camera Phase 1, commands round 3 (2026-09-05, the judge's seven ranked
gaps against bar sections 5 and 6, closed in priority order; four
code commits plus the tally commit; docs/CAMERA_PHASE1_REPORT.md
"How to demonstrate", "Watching each check fail" and "Known
limitations" are current).** The verifier GRADES THE POSE:
core/capture/verify.py pose_fidelity (recompute_pose_tracks solves
every camera's track again from scenario.yaml over telemetry.json in
the manifest's frame block -- the producer's solver, stated as such --
and every record's position/quaternion/Euler/focal/fx/fy/principal
point/resolution/sensor/near/far is compared at its sample, 1e-6 m,
1e-6 deg, 1e-9 quaternion, 1e-6 px, plus every block's
pose_track_digest verbatim; 0.0096 s for both cameras of cameras_multi,
digests bit-identical) and aim_fidelity (the telemetry's aircraft
through each record against the pixel the preset's promise predicts,
computed WITHOUT the solver: the AIM_LAG_S first-order lag recomputed
over the telemetry for chase/wingman/tower/ground, the centre for an
explicit camera, the body-axis cg pixel for a cockpit with the axes
compared to the telemetry attitude; 1e-6 px; honest worst 4.1e-13 px,
0.001 deg of yaw is 0.022 px and FAILS). cross_view_consistency is no
longer circular: the ray goes through the record's own label but
STARTS at the recomputed pose, and the recovered point is graded
against the telemetry's aircraft and both records' (data["mode"]
independent / records-only; records-only WHERE says "the poses are not
tested here"). The judge's seven pose corruptions (both +30 m, tower
+5 m, both yawed 3 deg consistently, tower yawed 10 deg, lens x1.5,
ids swapped) all FAIL now. Ten --corrupt kinds (pose, lens, aim added;
schedule now copies the spec's pose at the moved sample too so only
schedule_fidelity fails); --corrupt flight and quaternion fail
cross-view too (50.0 m; 18.1 m). The CLI runs 9/9 (single camera 8/8
+ cross-view skipped; manifest-only 5/5 + 4 skipped). A REFUSED
capture prints the header from the spec alone (flightsim.report.
spec_manifest + captures_words: "output -", fx from focal x width /
sensor width, "every 1 s, interval" when the flight decides the
count) before the violation; --json carries it. The request
handlers' planning (/compile, /run, /capture) is routed to
<runs root>/jsbsim.log (RunManager.planning_console; /status names it
with planning_model_loads) and the console sink is one slot PER
THREAD (core/fdm/console.py threading.local). The doc's block list is
16. Gotchas: (a) a check that is SKIPPED for a manifest-only directory
must be added to the skipped lists in tests/test_camera_verify.py
(three places) and tests/test_webapp_capture.py's tally; (b) the
doc-staleness guard target moves with the tally ("(9/9 checks; ...");
(c) the corrupt "schedule" kind must copy the POSE at the new sample
or pose_fidelity and cross-view fail it; (d) CameraSpec.defaulted()
takes no field kwargs -- set() them; (e) /status's
planning_model_loads is since process start, so a test compares
deltas; (f) 24 new guards under "commands round 3", every one
verified firing by subset (never run pytest while a subset runs);
the whole 311-guard suite was run to completion at the end of the
round (tally in the report).

**Camera Phase 1, commands round 2 (2026-09-05, the judge's eight ranked
gaps against bar sections 5 and 6, all eight closed; five commits;
docs/CAMERA_PHASE1_REPORT.md "How to demonstrate" and "Known
limitations" are current).** The verifier READS THE FLIGHT:
core/capture/verify.py flight_fidelity (every record's t_s, altitude,
attitude and pyproj-projected north/east against telemetry.json at its
sample_index, tolerances 1e-9 s / 1e-6 m / 1e-6 deg; telemetry.json's
digest = output_digest) and schedule_fidelity (the schedule recomputed
from scenario.yaml's cameras over the telemetry, instant for instant);
both SKIPPED by name when the file is not beside the manifest (a
manifest-only directory is 5/5 + 2 skipped, the CLI runs 7/7). Seven
--corrupt kinds (clock, flight, schedule added); the copy is the
SIBLING <run>_corrupt_<kind>/ or --corrupt-dir, never inside the run.
render() prints a PASS once (the table); "detail:" only for rows that
did not PASS. The flight line states the telemetry window ("telemetry
t 4.900..34.858 s (280 samples, 0.108 s apart), the clock at 4.900 s
when the record began (trim and engine start)"); --brief words
distance/proximity/event schedules from the trigger. A missing spec is
USAGE 3; the USAGE line prints once (stdout). The page run enters
<run>/jsbsim.log around the whole flow (webapp/runs.py _execute), a
direct capture_run opens capture/jsbsim.log; every routed load is
stamped "# load N: FlightDynamics(X) called from module.function".
The header states the aim reference per preset ("aim body axis" +
the cg pixel for a cockpit) and the schedule table has an "off-aim
px" column. scripts/examples_expected.py compares the doc blocks
EXACTLY on the measured platform (only "s/frame" and the engine line
masked), masked on other platforms. Gotchas: (a) tests that pinned
"[PASS] name" lines now assert the table row and "[PASS]" ABSENT;
(b) verification_rows() in the CLI tests ends the table at "detail:"
OR the first line not indented two spaces (a report with every row
PASS has no detail block); (c) the request handler's pre-flight
planning (/capture, /run) still constructs FDMs before a run exists
and prints to the server console -- stated in Known Limitations, not
routed; (d) the doc-staleness guard target is now "(7/7 checks; ...";
(e) 24 new guards under "commands round 2" (plus three round-1 guards repointed), every one verified firing
by subset (never run pytest while a subset runs).

**Camera Phase 1, commands round 1 (2026-09-05, the judge's ten ranked
gaps against bar sections 5 and 6, closed in order;
docs/CAMERA_PHASE1_REPORT.md "How to demonstrate" is current).**
flightsim/report.py is the surface both commands share: header, per-
camera schedule table (--brief), the verifier's CHECK/STATUS/MEASURED/
TOLERANCE/WHERE table (core/capture/verify.py: every Check carries
measured/tolerance/unit/where, VerificationReport.to_dict() is the ONE
source for verify.json, the page and --json), a verdict line whose
first word is the exit code's word (0 done/verified, 1 FAILED, 2
REFUSED, 3 USAGE, 4 UNEXPECTED; capture.verification moved 2 -> 1 to
match verify). SKIPPED (ok None + reason) is the fourth status: a
single camera's cross-view check, counted in neither passed nor ran.
JSBSim's C++ banner is routed at the fd level (core/fdm/console.py:
jsbsim_console(path) around the run, captured_console() around each
FGFDMExec construction in fdm.py and card.py) to <out>/jsbsim.log and
counted ("14 model loads"); the sink refuses os.devnull. verify
--corrupt {quaternion|aircraft|time|count} copies the manifest to
<run>/corrupt_<kind>/ (round 2: the SIBLING <run>_corrupt_<kind>/) and
must exit 1 with the named check FAILED.
examples/cameras_multi_cockpit.yaml is the committed alignment pair
(keep `name: cameras_multi`: the name is in the simulation digest).
scripts/examples_expected.py --write regenerates the doc's verbatim
blocks; a test compares their SHAPE (numbers, digests, camera ids
masked) with the doc's. Gotchas: (a) the `[STATUS] name: detail`
lines are pinned by tests and stay under the table as "detail:"; (b)
the sink must wrap ONLY the C++ construction -- a whole-run dup2 would
swallow our own prints; (c) the scale refusal runs BEFORE validation so
a refused run leaves no directory (the sink mkdirs lazily on the first
load); (d) never run pytest while a mutation subset runs.

**Camera Phase 1, preview round 3 (2026-09-04, the judge's eight ranked
gaps against bar section 3, closed in order, eight commits;
docs/CAMERA_PHASE1_REPORT.md "Geometry preview" is current and
SUPERSEDES rounds 1 and 2).** core/capture/preview.py: (1) contact-
sheet tiles are DRAWN FOR THE TILE (draw_preview size=(320, 180),
style="thumbnail": intrinsics scaled per axis, no text of any kind,
horizon/track/body at 2 px; info["text_drawn"] is 0 for a tile),
never Image.thumbnail() of the preview -- 6.47% geometry pixels
against 1.30%, peak 255 against 159; (2) the WEAK round-2 wrap guard
fires: a 400x225 record's 440-px position line wraps to 8 lines from
6 (480x270 does NOT wrap: 440 < 472); (3) labels are REQUESTED while
drawing and PLACED once the band, legend, compass and FOV zones are
known -- right/left/above/below, shifted outward up to 6 lines, 20 px
clearance then 3 px, the rows beside a zone the anchor lies in, a
leader when the box ends farther than gap + one line height --
"boresight" on the cross (18 px), "N" on the arrow TIP right/left
first, ring labels at min(25 deg, hfov/4) round the ring and 80 px
from the sides: 0 overlapping pairs and 0 collided over the judge's
three runs (was 136 px boresight drift, N under the arrow base, rings
on the shaft); (4) the horizon is split per column against
skyline_cull's skyline (horizon_runs): solid where the ground's top is
below it, dashed HORIZON_HIDDEN_RGB (4 on / 8 off; Pillow paints a
4-px dash as 5 pixels) where a ridge rises above it, info
horizon_visible_px / horizon_hidden_px -- 157/160 horizon pixels
through the ridge face went to 0/160; (5) overlay text carries a 2 px
black stroke and the compass a disc of the band's alpha; (6)
validated_scale(scale, resolution) refuses a non-divisor by name
("3 does not divide 1280x720 exactly (426.67x240)"), the CLI before
run_spec from spec.cameras or default_cameras (exit 2, no directory)
and the page's /run and /capture (409) via scale_refusal_for_cameras;
(7) ground_words takes the picture's counts: "(out of frame)", "(none
in frame)", per-kind "(124 of 1314 coarse + ... in view, 1190 hidden
behind ridges)" and "; north arrow: drawn (45 px, 5892 m)" / "ground
out of frame"; info["segments"] counts per kind (terrain,
terrain_fine, rings_in_frame) in frame / _visible / _hidden /
_visible_runs with hidden + visible == in frame (the old single
terrain_hidden 1202 was a cross-kind difference); (8) a second budget
test over a 97x97 relief raster (0.0915 s/frame, 0.1072 with the
sheet) and 12 overlays (0.1615 s/frame). CLI: cameras_multi 0.077
s/frame, cameras_waypoint 0.084, control_ridge with --terrain 0.090.
42 tests in tests/test_camera_preview.py; 18 new guards, each
verified firing by the scratchpad subset builder as it was added; the
whole 56-guard preview set run to completion: 53 ok, 0 WEAK, 3 SKIP whose targets round 3 had moved (repointed, re-run: ok; log in the report).
Gotchas: (a) a mutation guard's "ok" is meaningless while its test
fails on its own -- run the test alone first (an early overlay-text
assertion compared the header's tag line between preview and
overlay); (b) a loop variable named in_frame shadowed the in_frame()
helper further down draw_preview; (c) Pillow's textlength at an 8-px
font is anti-aliased: grade text pixels by brightness, not exact
colour; (d) the ridge scene's tower frames wrap the band to 125 px,
which six shifted lines cannot clear -- hence the zone candidates;
(e) the gap-6 commit body says "100 passed" for the three test files
where the run printed 93 (corrected in the gap-7 commit). NOT YET RUN:
overlays on real engine pixels (report step 5c).

**Camera Phase 1, preview round 2 (2026-09-04, the judge's nine ranked
gaps against bar section 3, closed in order; docs/CAMERA_PHASE1_REPORT.md
"Geometry preview" is current and SUPERSEDES round 1's description).**
core/capture/preview.py: (1) terrain segments drawn far to near and
HIDDEN behind nearer ground by a vectorised per-column skyline
(skyline_cull: samples sorted by column then depth, the running
minimum v before each sample, hidden when below it by more than 1 px;
sub-segments rebuilt from the visible runs); (2) the flown track is
the run's telemetry (telemetry_track: integer-stride decimation to
<= 10 Hz, the rate as the recorder's MEDIAN step, 9.23 Hz for its
13-step spacing, never the mean), past/future split at the frame's
t_s, this camera's scheduled instants as dots, the header and run.json
"track_source" say which; the CLI and webapp/capture.py pass columns
(CaptureOutcome.telemetry carries them to the overlays); (3) rings
around the camera's EXACT ground point (plan camera_north_m/east_m),
the lattice keeps its snapped origin; (4) an image-space compass
(north at -yaw, heading needle at heading - yaw, bottom-right) in
every scene, the world arrow sized by its PROJECTION (secant steps,
capped 0.3 x depth) and based on the ray 90 px below the boresight
(NORTH_ARROW_DROP_PX; terrain: marched + bisected on the raster),
labels shifted when within 20 px of another; (5) overlays at the
frame's own size for any ratio (axis_scale per axis, never resampled),
header font from the image height, lines wrapped at field separators,
band alpha <= 96; (6) header line "terrain <name> WxH @ px m, wireframe
NxN (spacing) + fine within R km; rings on the terrain" from
terrain_plan, the coarse stride now a multiple of 4 raster px
(control_ridge: 24 px = 720 m, 43x43), a fine lattice at stride/4
within 10 coarse steps, rings draped on the raster and culled with
it; (7) runner.aircraft_metrics: length = the LARGER of the stated-
station extent (eyepoint/VRP/aero RP/CG/tail arm = aero RP + 12 lh)
and arm + chord, with length_label, length_caveat and both candidates
(B747 59.6 m eyepoint to tail arm; c172p 6.3 m arm + chord) and the
picture reads "length >= 59.6 m (...; no fuselage length in JSBSim)";
(8) "frame index 5 (6 of 24)" / "#5 (6/24)"; (9) scripts/
mutation_check.sh --only <label regex> runs a named subset (baseline
and restore still run the whole suite), 21 new guards + 3 repointed
(two of round 1's whose target lines changed, one PRE-EXISTING stale
CLI guard whose record.update call had gained a key); the subset
run was stopped after 11 of 38 (all 11 fired, the 3 repointed ones
among them); round 3 ran the whole set to completion: 20 ok, 1 WEAK
("header lines wider than the image are wrapped"), the WEAK one fixed
by a test that wraps (see the round-3 entry above; the log is in the
report). Measured: 0.068 s/frame on cameras_multi (48
frames), 0.076 on cameras_waypoint, 0.053 on the control_ridge frame
(draw_preview alone; the first cut was 0.135 until the raster
sampling and header measurement were vectorised -- text measurement
was the profile's top entry). Gotchas: (a) the info key "terrain" is
the count of coarse segments IN FRAME and "terrain_visible" the count
after the cull, so round 1's "> 100" assertion stands at full
strength; (b) the recorder's samples are 13 steps apart, not 12: a
test that assumes "10 Hz" fails -- compute the words from the run's
telemetry; (c) the raster lattice column nearest east 0 sits at
-0.44 m in the synthetic fields: grade pixels on the lattice's own
columns, not at east 0; (d) the arrow at the boresight hit lands ON
the aircraft an aimed camera centres, hence the 90 px drop; (e) a
mutation run rewrites preview.py, runner.py, flightsim/capture.py and
webapp/capture.py in place -- never edit or test while one runs.
NOT YET RUN: overlays on real engine pixels (report step 5c).

**Camera Phase 1, preview round 1 (2026-09-04, the geometry preview
done properly against bar section 3; docs/CAMERA_PHASE1_REPORT.md
"Geometry preview" is the description).** core/capture/preview.py
rewritten: terrain as a depth-shaded wireframe (flat scenes: a
camera-derived lattice reaching the horizon or far_m, distance rings,
a north arrow), the horizon from the camera's pitch and roll (v = cy +
fy tan(pitch): pitched DOWN puts it ABOVE centre; roll +20 gives slope
-tan 20), the aircraft as a three-axis body + box + heading tick +
past/future track scaled from `aircraft_metrics` -- read ONCE from the
FDM by core.scenario.runner.aircraft_metrics (metrics/bw-ft span;
lh-ft + cbarw-ft as the longitudinal extent because JSBSim has no
length; sqrt(Sv-sqft) vertical) and carried through the run manifest
into the capture manifest -- boresight cross + FOV at the edges, a
four-line header. Full resolution by default (--preview-scale N / the
page's field, refused by name preview.scale otherwise); the measured
time per frame printed and in run.json "previews" (0.049 s/frame at
1280x720 on the 48-frame example; budget 0.5 s); overlays over every
rendered PNG after a frames pass (overlays/<cam>/NNNN.png, CLI and
page, stub-verified only); contact_sheets/<cam>.png. 20 tests in
tests/test_camera_preview.py + 6 CLI/page tests; 15 guards verified
firing by subset (202 guards on the branch). Suite 716 passed, 1
skipped in 166 s. Gotchas: (a) the contact sheet must NOT live under
previews/ -- tests/test_camera_cli.py counts every *.png there as a
preview, so it lives beside it; (b) preview_scale travels to
capture_run / manager.start only when it is not 1, because existing
tests stub those with their old signatures (one spelling of the
default). NOT YET RUN: overlays on real engine pixels (report step 5c).

**Camera Phase 1, frames round 3 (2026-09-04, six commits -- the
judge's ranked gaps against analysis/QUALITY_BAR_camera_phase1.md,
closed in priority order; docs/CAMERA_PHASE1_REPORT.md is current and
SUPERSEDES the round-2 tolerances below).** (1) Engine parity judges
the PIXELS: the commandlet writes its own projection of the aircraft
it drew (aircraft_px/py/visible, aircraft_bbox_px from the bounds'
corners via ProjectToPixel) and the verifier grades it against the
labelled pixel within the graded budget and against its own projection
of the drawn point within 3 px ("do not describe one lens"); a
label-window contrast clause reads the PNG (window half max(16 px,
graded budget) widened to the screen box, against a same-size window
at the farthest corner, >= 8/255 in mean or spread) so a flat frame or
a blob 40 px off fails by frame with both windows' numbers; all three
engine stubs DRAW the blob at the label (tests.test_camera_verify.
honest_frame). (2) ONE parity contract: the manifest carries rate_hz,
step_s and per-frame aircraft.speed_mps (tas_kt, else ground speed);
solve_schedule(rate_hz=) and the manifest refuse an instant off the
fixed-step grid by name; t_applied_s must EQUAL t_s to 1e-6 s (the
commandlet subtracts its clock origin, read before the first step,
recorded as clock_origin_s, and fails a step that passes an instant --
nothing is rounded to a nearest step, so "nearest" and "at or after"
never differ); render.json's step_s is CHECKED against 1/rate_hz, never
the tolerance; the drawn-aircraft budget is (1 + 0.5) steps x
speed_mps / rate_hz per frame with the arithmetic printed ("budget
2.08 m = 1.5 steps x 1.384 m/step at 166.0 m/s" on cameras_multi;
1.24 m on the synthetic 99.43 m/s track), so a one-step-late clock
fails cleanly by name and is never "within contract" on one line and
over budget on the next; ENGINE_AIRCRAFT_TOL_M is gone. (3) The CLI's
run.json carries render {choice, label, engine_available,
engine_unavailable_reason} and verify.json is written beside the
manifest in every mode (webapp.capture.verification_verdict). (4) POST
/run without the field resolves through render_choice_default(); the
page prints the server's word. (5) macOS is gated on the editor at
UE_ROOT and the built .dylib exactly like Windows (ue_available() IS
ue_unavailable_reason() is None). Suite 690 passed, 1 skipped in 107 s
(+9 tests); 187 guards (+15, one repointed), each verified firing by
subset. Gotcha: tests/test_webapp.py's clip-flow posts must state
render "clip" -- an omitted field is now the machine's default (frames
under a mocked-open gate). Gotcha: the synthetic make_columns track is
99.43 m/s through the scene frame's projection, not the 100 m/s its
degrees imply; pin measured numbers. STILL NOT YET RUN: the engine
fields (aircraft_px/py/visible/bbox, clock_origin_s, t_clock_s, the
exact-grid capture rule) are compile-safe by inspection only; the
report's Windows section carries the commands, the log lines and the
x digits to fill; the 8/255 contrast threshold is stated, not measured
on rendered pixels, and the Windows run's "lowest label window
contrast" is the first measurement of it.

**Camera Phase 1, frames round 2 (2026-09-03, six commits -- the
judge's ranked gaps against analysis/QUALITY_BAR_camera_phase1.md,
closed in priority order; docs/CAMERA_PHASE1_REPORT.md is current).**
(1) Engine parity JUDGES the aircraft the engine drew: aircraft_applied_*
within ENGINE_AIRCRAFT_TOL_M = 2.5 m of the manifest's aircraft (one
1/120 s step at 300 m/s plus the measured host residual: VALIDITY's
Gate 5 3.6e-4 m, the parity matrix's constant one-step phase of 1.24 m)
and, reprojected through the applied pose, within 3 px + fx * 2.5 m /
depth of the labelled pixel (measured on cameras_multi: 31.1-20.6 px at
the chase's 110.7-177.2 m, 4.0 px at the tower's 3074-3262 m); a record
without it FAILS the frame. A spec whose air cannot agree across hosts
(a turbulence word; the lee rotor a terrain scene attaches) is refused
render.host_parity BY NAME before editor time (POST /run 409, the flow,
the CLI exit 2) through the ONE rule core.capture.render_pass.
frames_host_parity_refusal -- Clip only keeps its visual-only label.
(2) The commandlet applies the pose AT THE SCHEDULED INSTANT and records
t_pose_s beside t_applied_s (the clock); the verifier requires t_pose_s
== t_s to 1e-6 s, so the pose contract is exact by construction and the
capture time is the only tolerance; the expected drawn-aircraft
distance on the Windows run is ~1.4 m (this example flies 322.7 kt TAS,
1.384 m per step) plus 1.4 m per step of clock offset -- the coupling
the report's Windows section now pins by number. (3) flightsim.capture
verifies in EVERY mode and prints the table before its final line; a
manifest that fails its own verification exits 2 (capture.verification);
a successful headless run says "engine absent: <reason>; frames not
rendered" and "done: ..." -- REFUSED is exit 2's word only;
UE_PLATFORM_REFUSAL speaks of frames. (4) No hidden render default: the
form's select ships DISABLED on Headless and is enabled only once
/status has said render_default (= render_choice_default(), the CLI's
rule); the page's applyRenderChoices is run verbatim under node against
the real /status payload (skipped without node; the string test pins the
source). (5) A frames pass stops after its last scheduled instant
(1439 of 1440 steps for the example) and records steps_taken/stepped_s,
said per pass and recorded as provenance render_passes (CLI: run.json).
(6) The by-product clip: black lead-in PNG listed first in the concat
playlist (no tpad), argv spelled once (clip_command) and pinned exactly
with subprocess stubbed, expected length scheduled_clip_seconds (12.992
s for the example) stated before encoding and recorded with
clip_encoded; the report's step 5b is the ffprobe measurement. (7) The
three stale guards (measured control signs, the one-sample exemption,
the rotor seed) are repointed to the code as it stands and fire;
scripts/mutation_check.sh ran END TO END: 172 guards, 170 fired in one end-to-end run (31 min; the suite green before and after), and the 2 WEAK there were BOTH pre-existing -- a fourth stale guard, 'a failed model build fails the run BY NAME', whose target string's FIRST occurrence had drifted into _capture_phase so the mutation never touched the guarded line (repointed to the unique except-branch), and 'the rotor card word travels with its pinned turbulence writes', which since Package F had no test where a rotor ACTS (tests/test_webapp.py gained test_a_rotor_that_acts_carries_its_word_and_block_on_the_card, the pre-flight stubbed to 'acts', the flow real) -- both verified firing by subset afterwards: 172 of 172 load-bearing. Suite: 681 passed, 1 skipped in 154 s (+35 tests this round, 14 new guards, 5 repointed).
Gotcha: scripts/check_bridge_api.sh reports "API surface has drifted" on
any machine without the engine install (it looks for headers under the
UE_ROOT default) -- identical on the base commit; not a C++ regression
signal here. Gotcha: node on PATH is what makes the page-JS test run;
without it the test skips and the four form guards fire through the
string-level test alone. STILL NOT YET RUN: every engine change (pose at
the scheduled instant, t_pose_s, the stop after the last instant,
steps_taken/stepped_s) is compile-safe by inspection only; the report's
Windows section has the commands, the log lines and the numbers to fill.

**Airborne physics reconstruction, phase 2 (2026-09-02 --
docs/AIRBORNE_PHASE2_REPORT.md is the full report, with the pre/post
table; analysis/ holds the audit, the research ledger the findings came
from, and the brief that was executed).** Eight packages, one commit
each, suite green after each: (A) the aircraft is trimmed IN the spec's
wind on both hosts -- FGTrim::DoTrim re-applies the zero wind IC over
atmosphere/wind-* writes, so the wind now goes into the ICs through a
fixed point on the OBSERVED vc and beta (FlightDynamics.
set_wind_initial_conditions / verify_wind_state, refusal wind.trim_state;
open-loop excursion 333 m -> 0.8 m; parity harness grades the first
sample; the C++ TrimInWind mirror is UNCOMPILED here -- verify per the
report). (B) the control-sign probe flies the engaging aircraft's own
state (the c172p engages; the p51d refuses control.signs by name).
(C) every run flies its spec closed loop headlessly and writes
capture/closure.json; a missed closure FAILS the run by name. (D)
core/performance.py measures T_trim/T_max/T_idle and a throttle-thrust
secant at the engaging state; TECS throttle gains are multiplied by the
measured thr_per_ste, a feed-forward on demanded energy rate is added,
hdot-max is capped at 0.8 Edot_max (B747 300 m step 72.7 s -> 28.7 s).
(E) core/terrain/lookahead.py raises the altitude setpoint ahead of
terrain along the projected track (90 s, half raster pitch, span
stations) or refuses terrain.lookahead when the escape climb cannot
clear it. (F) the lee rotor measured its own delivery: 0.000 m/s on
every planner-produced track (W20 route inert >= 300 m AGL; POE-1 curve
zero at ~3000 m MSL); the claimed floor is now measured at the MSL, the
provider observes atmosphere/turb-down-fps through a read-only stack
hook and acts() only at >= 0.3 m/s, and the web app drops a rotor that
did not act, stating why. (G) sideslip-to-rudder coordination from a
measured beta-per-rudder slope (turn-rate error 10% -> 1%, beta 1.16 ->
0.005 deg, Dutch roll settles faster). Fixed on the way: "over 2000 m
mountains" compiled to a 2000-MINUTE duration (gotcha: the bare "m" is
minutes only after for/during). Gotcha from the first run on the user's
machine: the closure pair must fly the CLIP's window (CLIP_SECONDS), not
the spec's full duration, and the look-ahead horizon is capped by the
time left in the run -- otherwise a 22 s clip is refused for a ridge
59 s ahead that it never reaches. Suite 635 tests (1 skipped), 131 mutation
guards, all new ones verified firing. Every number in the report comes
from experiments/airborne/*.py.

**Camera Phase 1 finished: frames, not a clip (2026-09-03, five
commits -- docs/CAMERA_PHASE1_REPORT.md "The run emits frames, not a
clip" + "Engine verification (Windows)").** The run form and the CLI
carry the SAME render choice (Render frames and clip / Clip only /
Headless; --render frames|clip|none; default = the richest the machine
supports, engine options refused ue.platform by name WITH the reason,
recorded in provenance.render). "frames" solves the capture first, puts
cameras=camera_card_blocks(...) on the card (whole flight, not the 22 s
clip cap) and runs the commandlet's consume-poses pass once per camera
(-camera-index=N, -frames=<run>/capture/frames/<id>) through the ONE
command builder core/capture/render_pass.render_command; a short pass
fails the run as render.frames; the clip is a by-product of camera 0
(frames at their instants via ffmpeg concat; UNMEASURED here, no
ffmpeg). Frames are frames/<id>/NNNN.png by manifest index. The verifier
gained engine_parity (10 cm / 0.1 deg / one fixed step / PNG size /
reprojection 3 px) with a third state, AWAITING, that never counts as
a pass; every summary says scheduled / rendered / verified. The C++
(schedule-driven capture, index naming, applied+solved per frame,
orientation parity, count contract, FOV from the card's lens) is
UNCOMPILED HERE: the report's Windows section has the literal commands,
the log lines that must appear and the expected counts; it is marked
NOT YET RUN until the user pastes the log back. Gotcha: the headless
recorder's first sample is at t = one step (0.00833 s), not 0, so the
engine's first post-step clock meets it exactly; the parity time
tolerance is ONE fixed step (the bar's words), not half. Gotcha: three
pre-existing guards (measured control signs, gate5 one-sample
exemption, rotor seed) no longer match their source text and SKIP in a
full mutation run -- found while checking guard targets, untouched
here. Suite +49 tests, +23 guards, all new ones verified firing.

**Camera Phase 1 (2026-08-31 -- docs/CAMERA_PHASE1_REPORT.md is the
full report).** The camera is a spec element now: SPEC_VERSION 6,
cameras as provenanced CameraSpec blocks (core/scenario/camera.py),
digest-relevant, editable in the review table, addressable via
set()/plan() as cameras[0].<field>; an EMPTY list drives the render
flow byte-identically to the preset build (pinned by test). New
core/capture/ package: deterministic pose solver (five UE presets
ported; only cockpit inherits roll), telemetry-only capture scheduling
(exact counts are contracts), camera.* refusals on the Violation
surface (scene-free in validate(), scene-coupled in /run and the CLI),
capture_manifest.json with full per-frame recoverable geometry, and an
independent verifier whose every check is shown to fail on corruption.
CLI: python -m flightsim.capture / flightsim.verify (examples/
*.yaml). MUST-VERIFY ON A MAC: the additive consume-poses C++
(CameraDirector SetPoseTrack/ApplyPoseAtTime + commandlet
-camera-index= pass reading the card's cameras block, written by
capture --card) compiles logically but was never built or rendered --
the report's engine-boundary section carries the exact verification
steps. Suite 583 tests collected, 118 mutation guards. Measured on a
raster-less clone (no runs/terrain bakes): 104 guards fire; the FOUR
terrain-coupled planner guards (ridge-axis wind, rotor card word,
span-station clearance minimum, orographic pre-flight) report WEAK
there because their test_webapp tests silently take the flat path
without a baked raster -- bisected to the pre-camera base commit, so
it is an environment artifact of guard MEASUREMENT, not a regression;
they fire on a machine with the bakes. Worth fixing by giving those
tests a synthetic raster fixture (the camera tests' make_mountain
pattern) so every guard is machine-independent.

**Capture on the page (2026-09-01, one commit).** Camera Phase 1's
deliverable reached the webapp. webapp/capture.py drives the SAME
solver, scheduler, manifest, verifier and previews the CLI does: every
/run now captures beside the clip, and a new POST /capture runs the
labeled-data half alone with no platform gate (nothing there opens the
editor, so it works wherever flightsim.capture does). /runs/{id}/files
lists every artefact with a note saying what it is, /runs/{id}/file/{name}
serves one from a WHITELIST built out of what the run actually wrote
(not a path check -- an encoded traversal is a 404 by construction), and
/runs/{id}/bundle.zip is the same set in one download. The page renders
per-camera frame counts and the verifier's own five checks from
verify.json as run, never a second opinion. Both endpoints share
_prepare_run_spec, so the load-bearing planner ORDER cannot drift
between them. WHICH FLIGHT: the capture is solved from its own headless
run_spec and written under capture/ beside that run's telemetry; the
run's top-level telemetry.json stays the rendered flight's -- two hosts,
two files, neither presented as the other. Ten tests, four guards, all
verified firing.

**Aircraft fail-safe (2026-09-01, one commit).** A model a machine can
BUILD is no longer a refusal: the render flow provisions it on first
need, exactly as ensure_control_ridge synthesises the ridge, reporting
each step as a run status line (user: "i cant run commands for every
single mesh they should upload by themselves"). assets_pipeline/
importer.py is now the ONE implementation of fetch-at-pinned-commit ->
convert -> import-and-verify; scripts/import_aircraft.py is a thin CLI
over it, so the command and the app cannot drift. The owner's
placeholder rule is UNCHANGED and narrowed only where automation cannot
help: an airframe with no config, and one whose upstream ships no
license file (VALIDITY 3.3 -- refused BEFORE any fetch, so automation
is not a back door to unattributed geometry), still refuse
aircraft.mesh by name; a build that fails fails the run by name
(aircraft.mesh_import) and never reaches a render. Six guards, all
verified firing. Render path only -- tests and CI never provision, so a
checkout's asset state stays deterministic.

**Scene director + cross-platform (2026-08-13, two commits -- the full
narrative is docs/CONTEXT_SCENE_DIRECTOR_SESSION.md).** The LLM now
fills EVERY field it can justify under the new provenance source
`model` (declared guess, quoted phrase REQUIRED, plannable like a
default; SPEC_VERSION 5). PLANNABLE_SOURCES = (default, model, derived)
is the load-bearing line: user/inferred never move. New planners:
plan_terrain_environment (cross-ridge wind + along-ridge heading from
the raster's structure-tensor ridge axis, WHOLE degrees -- the UE wind
IC is integral), aircraft-aware default airspeed, plan_trim_recovery
(one recorded re-plan to documented cruise when the trim probe refuses
a plannable speed), guessed-tas -> cas in project_for_ue_host. Planner
ORDER is stated + pinned in server.py /run. Gate 8.1 gained the vague
coherent-and-declared category; verdict on gpt-4.1-mini after five
measured iterations (12 -> 7 -> 6 -> 4): **FAIL (4), determinism
IDENTICAL** -- all four misses are model shape/quality stumbles (empty
question options, a 4-question overflow, one 'windspeed' key typo, one
terrain-phrasing parity miss), recorded in runs/gate8_compiler/
report.json; the machinery rails all held. Acceptance measured: "storm
chasing in a small plane over Kansas" rendered END TO END
(runs/webapp/3ed4d58bc9ff); mountains-vs-flat rough wind measurably
differ (wind FROM 118 vs 8 deg, vertical air +-2.9 vs one-sided).
Scene-setting (user request, same day): plan_scene_setting stages
all-default coordinates on a fitting curated bake DETERMINISTICALLY
(desert -> grand_canyon, else flint_hills as the neutral stage;
'flat ground'/ocean opts out; stated places win; model may only choose
listed origins, never invent coordinates or dates -- parser rails).
needs_dynamic_bake refuses stated coords that fall on the control ridge
(not a place). Platform story: core/util/platform.py is the ONE OS-dispatch home;
UTF-8 encoding enforced statically (test_platform.py); UE refuses
`ue.platform` by name off-mac (scripts exit 3, webapp 409, /status
reports render_available); setup.ps1 + README matrix; CI matrix
(.github/workflows/ci.yml) runs pytest on ubuntu/windows/macos --
the off-mac legs ARE the acceptance measurement. MEASURED VERDICT:
CI matrix GREEN on ubuntu/windows/macos at fe36f81 (run 31754830177),
after its first two runs caught five real gaps (httpx missing,
anthropic missing, the platform refusal preempting two lock-logic
tests -- now covered on every OS instead of skipped -- one incidental
closure assertion, and a per-platform-libm turbulence ratio; fixes in
2e725e2 + fe36f81, no mac coverage loosened). DEFERRAL LIFTED
(2026-08-31, owner's decision): the UE host is now wired for Windows
too -- ue_available() there requires an installed engine AND a built
bridge (scripts/vendor_ue_plugin.ps1 + build_ue.ps1; ue_preflight.ps1
diagnoses), editor paths route through
core/util/platform.py:ue_editor_path(), and the render-claim rule is
unchanged in spirit: every render gotcha was measured on Metal only,
so a Windows machine's render claim is a green
experiments/gate6_visual.py run ON that machine (it re-measures the
visual clauses from the pixels), not this wiring. Do not report
Windows render results as validated until Gate 6 has passed there.

**Planned defaults (2026-08-13 -- "simple prompts must just fly").**
Measured: "rough wind over mountains" + everest refused over numbers the
system itself had chosen (defaulted altitude raised into air where the
defaulted 250 kt sits under the B747's Vs). Now `plan_flyable_defaults`
(webapp/runs.py) floors SYSTEM-CHOSEN numbers into the flyable envelope
before the verdict: defaulted altitude below the location's terrain
datum -> datum + 300 m; defaulted airspeed under the stall margin ->
1.25 x the measured Vs at the final altitude, rounded up to 5 kt. Edits
use the new `ScenarioSpec.plan()` (source becomes `derived`, movable by
later planners -- plan_terrain_flight now treats default|derived as
plannable and plans rather than set()s); user-stated values never move
and their refusals stand. Wired into /compile (both compilers) and /run
(re-plan after the raster track raise). Also: `_parse_payload` defaults
ABSENT notes/questions to [] (measured: gpt-4.1-mini omits empty lists
when the schema is guidance, not grammar; every other rail unchanged).
Weather events now compose their ENVIRONMENT too, visible at /compile:
a tornado/thunderstorm with system-chosen ambient fields plans
background wind to the vocabulary's 'strong' 25 kt and turbulence to
'severe' (the vortex/microburst stays position-coupled ON TOP); a
tornado still descends a defaulted altitude to 800 m. Stated words and
numbers are never moved. Suite 429 tests, 88 guards.

**Terrain physics (2026-08-11, second session -- "not taking all
mountain surfaces into physics consideration").** Two features, all
three hosts:

* **Airframe contact** (core/terrain/contact.py; `AirframeImpact` in
  FlightSimScenarioWorld.cpp; wired into Step(), the interactive
  substep loop, and run_spec): four span stations (wingtips +
  mid-semi-span) from the FDM's own `metrics/bw-ft` and attitude,
  checked every step against the raster; a station below the surface
  ends the run as a NAMED terrain impact (headless raises
  TerrainImpactError; UE hosts refuse like Crashed). Point samples,
  not a mesh intersection -- VALIDITY 2.10 carries the limits
  (no fuselage/nose/tail, no between-station spires, no crash model).
  The webapp clearance pre-flight plans against the same stations
  (clearance_m = min over stations, strictly tighter in a bank).
* **Terrain-driven airflow**: webapp terrain runs with wind now carry
  lee-rotor turbulence riding the same orographic field the card
  records (card word "lee-rotor" -- gotcha 14 respected; seed derived
  even when the spec word is "none"), and the clearance pre-flight
  flies through that same orographic field. Calm terrain runs carry
  neither and the conditions strip states why (orographic forcing is
  wind over terrain -- VALIDITY 2.8 note). Tests:
  tests/test_terrain_contact.py + new tests in test_webapp.py; 5 new
  mutation guards (77 total).
* **Conditions-effect report**: every coupled run's page ends with
  "what the conditions did" -- a headless still-air baseline of the same
  spec beside the run's telemetry (_effect_report; GET
  /runs/{id}/effect.json, 404 for uncoupled runs; initEffectReport in
  the page). Cross-host claim stated (Gate 5 parity); optional step,
  the clip survives its failure. Standalone A/B in runs/ab_terrain_air/.

**Phase 9 (2026-08-11, in progress -- docs/BRIEF_PHASE9.md governs the
storm/tornado/city features):** DELIVERED so far: 9.1 surface classes
(grassland/desert/ocean/forest/city; environment.surface); FOUR new
curated bakes (fuji / everest / grand_canyon / flint_hills -- everest
needed the N28 tile and the SLOPE-AWARE source verification, see
glo30.verify_against_source); ON-DEMAND GLO-30 baking for any
coordinates (POST /bake; "terrain.unbaked" refusal; dynamic scene
registry runs/terrain/dynamic); ERA5 HISTORICAL WEATHER
(environment.weather_date, SPEC_VERSION 3, Open-Meteo archive, stated
wind always wins, control ridge refuses). 9.2 STORMS + 9.3 TORNADO DELIVERED
(environment.weather_event, SPEC_VERSION 4: thunderstorm = documented
composition, tornado = Rankine vortex both hosts + funnel VISUAL
marker + probe-calibrated STORM_LOOK; card scene_crs for flat-scene
position-coupled blocks; measured run e81cea71ff89: c172p rolled to
-42.5 deg, n_z 0.66-1.64 g at 2.5 core radii). NEXT UP: 9.4 city
building collision, UE volumetric clouds + Niagara precipitation as
LABELED VISUAL-ONLY (task 12), NOAA HRRR deferred; WRF and trueSKY
refused (recorded).

## State

| Phase | Gate | Status |
|---|---|---|
| 0 core FDM | 0 | PASS 9/9 |
| 1 spec + NL | 1 | PASS 4/4 |
| 2 TECS + closure | 2 | PASS 4/4 |
| 3 environment | 3 | PASS 5/5 + convergence |
| 4 terrain | 4 | PASS 7/7 |
| 5 Unreal | 5 | PASS 3/3 clauses, each measured |
| 6 visual realism | 6 | PASS 4/4 measured clauses + side-by-side |
| 6B real assets/terrain/turbulence/matrix | — | DELIVERED |
| 7 imagery/coupling/atmosphere | — | **DELIVERED, every verdict measured** (docs/BRIEF_PHASE7.md) |
| 8 prompt-to-simulation interface | 8.1-8.3 | 8.3 PASS end to end; 8.2 replay+substep PASS (locked-session path); 8.1 live corpus + windowed clauses BLOCKED -- see below |

**Phase 8 remaining evidence, blocked on things only a person can provide:**
* **Gate 8.1 (live LLM corpus)**: UNBLOCKED by the provider layer and RUN
  live against the free local model (2026-08-11, qwen2.5:14b via ollama):
  **FAIL (6)** -- runs/gate8_compiler/report.json. The verdict measures
  THAT model, not the machinery: determinism came back IDENTICAL, the
  clarify entries passed (asked once, answered, landed on the bake), and
  all six failures are model-quality misses (asked questions on 3
  vocabulary prompts + 1 determined prompt where the documented mapping
  is the answer; 1 adversarial silent guess; 1 off-bake miss). A PASS is
  expected from a frontier model: set ANTHROPIC_API_KEY (or a strong
  FLIGHTSIM_LLM=openai endpoint) and rerun
  `.venv/bin/python experiments/gate8_compiler.py`. The mocked half
  (tests/test_llm_compiler.py, 39 tests) is green. The
  corpus now includes clarify entries (must ask, scripted answers close the
  round) and determined entries (must NOT ask), plus on-bake geography
  assertions against LOCATIONS origins. A missing key is now a NAMED
  preflight error (set the key in the environment of the SERVER process --
  the flightsim-web launch.json entry or the uvicorn shell); GET /status
  reports llm_available so the page states the compiler up front.
* **The windowed run** needs an UNLOCKED console session (gotcha 18):
  launch via `experiments/fps_probe.py` (it auto-detects the lock) or the
  webapp, and re-measure the windowed fps figure + Gate 8.2's on-screen
  clauses (-screenshot-at= is wired). Everything else about the
  interactive host -- substep ledger, replay parity, HUD, recorder,
  manifest -- is measured and PASSED via the commandlet wall-clock path.
  The on-screen clause checklist now also includes the HUD's AERO BLOCK
  (alpha/beta/qbar/lift/drag/n_z + stall margin with the model's own Vs
  and basis): grade it legible from the same screenshot pass; it must not
  displace or shrink the existing honesty items.

**Aero panel (this session).** The shared recorder (all three hosts, one
channel table) records the aero block -- alpha/beta, qbar, body- AND
wind-axis aero forces (lift = fwz, drag = fwx: the FDM's own outputs),
gamma, total wind, NED velocity -- property names verified live (gotcha
22), with a startup SelftestProperties refusal in every host (hazard 1).
The render path takes `-telemetry=` and the webapp passes it, so every
clip run writes `telemetry.json` served at `GET /runs/{id}/telemetry.json`
(404 until done; the recorder's own file, no resampling). The page shows
an aero side panel beside the video, indexed by the video clock (mapping
stated on the panel), with model-specific stall/Vs marks from the card's
`reference_speeds` block (write_run_card optional arg; ReadCard optional
parse; display-only). Gust null test + frozen Gate 5 graded set + selftest
wiring are suite members (tests/test_aero_channels.py); two new mutation
guards (selftest refusal, graded-set freeze).


```bash
.venv/bin/pytest                          # 395 tests
./scripts/mutation_check.sh               # 77 guards, all load-bearing
./scripts/ue_preflight.sh                 # "Preflight OK"
./scripts/build_ue.sh                     # builds the UE host
.venv/bin/python experiments/gate5_ue_parity.py    # gate 5 end to end
.venv/bin/python experiments/gate6_visual.py       # gate 6 (~4 min)
.venv/bin/python experiments/gate5_realmesh.py     # on-screen: B747 + c172p + A320
.venv/bin/python experiments/turbulence_ue.py --skip-runs
.venv/bin/python experiments/orographic_ue.py --skip-renders
.venv/bin/python experiments/environment_ue.py     # 4 Phase 7 ports + null evidence
.venv/bin/python experiments/agl_parity.py         # heightfield-collision parity
.venv/bin/python experiments/imagery_drape.py      # drape on geometry
.venv/bin/python experiments/evolving_flight.py    # the 150 s clip + phase checks
.venv/bin/python experiments/zermatt_run.py        # scripted valley run + cameras
.venv/bin/python experiments/showcase_matrix.py    # the matrix (resumable)
.venv/bin/python experiments/turb_perstep_measure.py  # the §13 measurement
.venv/bin/python experiments/fps_probe.py          # 8B.0 real-time frame cost (GO: 171 fps)
.venv/bin/python experiments/interactive_replay.py # Gate 8.2 replay parity
.venv/bin/python experiments/gate8_compiler.py     # Gate 8.1 (BLOCKED without ANTHROPIC_API_KEY)
.venv/bin/pytest tests/test_llm_compiler.py tests/test_webapp.py  # compiler v2: questions/preflight/locations (fast)
.venv/bin/pytest tests/test_aero_channels.py   # aero panel: schema sync, selftest wiring, gust null, frozen graded set
.venv/bin/uvicorn webapp.server:app --port 8008    # the web front door (manual)
```

**LLM compiler v2 (this session): geography + clarifying questions.** The
system prompt carries a locations block GENERATED from
`core.terrain.glo30.LOCATIONS` (import-time assert, mutation-guarded): a
prompt naming a bake lands on its exact origin so `pick_scene` selects the
real terrain; unknown places are never given invented coordinates (question
or note). One round of at most 3 clarifying questions, both bounds enforced
in `_parse_payload`; answers arrive as a structured Q&A conversation
(prompt / assistant questions / user answers); an answered field is source
`user` with `answer to "<question>": "<answer>"` recorded; the transcript
goes into the UTF-8 provenance sidecar via /run. The regex fallback never
asks and compiles the ORIGINAL prompt on any LLM failure. VALIDITY §2.14
carries the claims paragraph.

**LLM providers.** The compiler is provider-independent
(core/nl/providers.py): `FLIGHTSIM_LLM=ollama` runs a free LOCAL model
(default qwen2.5:7b via the ollama service, grammar-constrained by the
compiler's own RESPONSE_SCHEMA), `FLIGHTSIM_LLM=openai` any
OpenAI-compatible endpoint, else ANTHROPIC_API_KEY -> Claude API. Config
lives in ~/.flightsim.env, sourced by the flightsim-web launch entry.
Gate 8.1 runs against whichever provider is configured and records it;
a local-model verdict measures THAT model, not the machinery.

## Phase 7: what exists now and what was measured

* **Sentinel-2 imagery drape** (core/terrain/imagery.py): EOX s2cloudless
  2016 (the CC-BY-SA 4.0 release; year-suffixed layers are CC-BY-NC-SA and
  REFUSED, mutation-guarded). Texel grid shares the bake's CRS/origin/extent
  by construction (10 m = 30 m/3); verified vs source (Matterhorn p95 9.3
  counts / Yosemite 11.3) and ON GEOMETRY by landmark projection
  (runs/imagery_drape: summit texel 2.38x texture median, rendered summit
  1.70x frame median, A/B vs classification 22.2). `-imagery=<sidecar>`
  loads the PNG at runtime into M_TerrainImagery; provenance in every
  manifest. Control ridge keeps the labeled classification.
* **Heightfield collision + AGL parity** (Phase 7 1.2): `collision_terrain`
  in the card replaces the slab with the raster's FULL 30 m grid;
  TerrainGround wired into run_spec. Measured (runs/agl_parity): |ΔAGL|
  p50 1.30 / p95 4.77 / max 6.46 m over 1415 m of relief (bars 8/20).
  Slab-era clips keep their label; VerifyTrimmedCondition checks such cards
  against the raster under the aircraft.
* **JSBSIM_CORRECTIONS §13** (turb_perstep_measure.py): per-step intensity
  is sane ONLY as W20 below the 300 m AGL ceiling (ramps track
  0.107·W20(t)); mid-run POE severity changes overshoot sigma_w 2-5x,
  fractional severity floors, severity 0 is a master off-switch. Everything
  below drives W20 only, severity pinned 1.0, seed written once.
* **Lee-rotor turbulence** (core/environment/rotor.py + per-step W20 in the
  UE Step()): sigma_w = 1.0 x lee sink (Doyle & Durran anchor), W20 capped
  at "severe". Port cross-check 1.4e-14; null: 0.200 fps turb RMS coupled
  vs 0.00000 severed; headless lee-vs-windward null in the suite.
* **Position-coupled downburst** (FlightSimDownburst): port EXACT (0.0 over
  the grid); 26 fps outflow in the FDM vs 0 control. Matrix microburst
  cells now carry the block ("position-coupled" label).
* **Log-profile surface layer** (LogProfileWind, Stull Table 9-6 z0): port
  exact; held above 300 m; FDM null in suite. **Allen thermals**
  (NASA/TM-2006-214019 + its Appendix B, pinned to the paper's own check
  case; Table 3 vs code discrepancy recorded): port 4.6e-10; c172p climb
  event null test. Composed shear+thermals: 56.6 fps wind RMS vs 0 control.
* **Evolving-conditions 150 s flight** (runs/evolving_flight): schedule
  machinery COMPLETE (ScheduledDrydenTurbulence + card turbulence_schedule
  + orographic follow_schedule + sun animation). Verified from the
  recording: n_z RMS 0.0034/0.0160/0.0642/0.1136 g rising by phase, wind
  tracks the schedule to 0.133 fps, W20 to 0.000 fps.
* **Airframes**: A320 through the generic pipeline (gate5_realmesh
  r=0.9999). DHC6 + p51d REFUSED over licensing (no license file in mirror
  or upstream; converter refusal not weakened; configs ready) — VALIDITY
  1.6a2.
* **Zermatt valley run** (runs/zermatt_run): scripted S-turns, every number
  measured (torque bias 0.033 by sweep; counter-pulses; headless clearance
  gate 312 m); banks on screen ±; chase camera 0.000000 deg roll; the NEW
  CockpitShoulder preset is the one declared roll-inheriting camera
  (33.2 deg, manifest records camera_inherits_roll).
* **Propeller** spins via continuous animator bindings (rpm x 6 deg/s,
  318 deg accumulated measured on screen); excluded from the
  peak-deflection clause.
* **Engine-start mixture** (vendored patch 4 + card engine_mixture): the
  plugin force-started pistons FULL RICH; at altitude the engine dies and
  trims a glider (measured — it produced 8 false clips before the fix, all
  deleted and re-rendered). discovered_engine_mixture verifies the UE
  host's exact sequence (InitRunning + mixture + tFull trim + 5 s sustain);
  c172p 0.85 at 2600-3600 m.
* **Same-seed parity: PERMANENTLY visual-only** (decided + recorded in
  VALIDITY): the isolated-RNG patch would fork the pinned JSBSim under one
  host or both. **Von Kármán: stays not-modelled**, stated.
* **The matrix**: 139/144 clips + contact sheet + manifest
  (runs/showcase). 5 recorded refusals: 4x B747 microburst over real
  terrain (no 300 m AGL track clears the mountains — the clearance scan's
  own refusal) and 1x c172p yosemite storm at clear dawn (35 frames
  legitimately below the blank-frame floor in deep dawn shadow; the check
  was not weakened; the hazy_noon sibling exists).

## Operational gotchas (each cost real time; do not rediscover)

1. **Renders**: absolute paths and `-stdout -FullStdOutLogOutput` or the
   editor stalls; `-RenderOffScreen -AllowCommandletRendering` or blank
   frames. gate6_visual.py render() is the canonical subprocess pattern.
2. **Builds**: scripts/build_ue.sh only (DEVELOPER_DIR pinned; never sudo /
   xcode-select). Commandlets need no Xcode.
3. **Unity builds merge anonymous namespaces** — but only for files CLEAN
   in git (adaptive unity excludes dirty files). Same-named constexprs in
   different .cpp files compile fine all session, then break the fresh
   clone / post-commit build. Names are per-file-unique now; keep them so.
4. **Async asset compilation**: commandlets never tick the compiling
   manager, so big StaticMeshes stay "compiling" and render NOTHING while
   captures report success. FAssetCompilingManager::Get().
   FinishAllCompilation() before the first capture (in the render
   commandlet, next to the shader flush). Measured: 747 body absent, its
   26-triangle ailerons present.
5. **Interchange import**: Nanite OFF at import time via
   InterchangePipelineStackOverride (a post-import flag flip corrupts the
   asset — measured). MikkTSpace OFF post-import via
   EditorStaticMeshLibrary (degenerate tangents corrupt the build —
   "may result in mesh corruption" means it). Converter substitutes
   position-derived UVs for degenerate UV triangles. And
   StaticMesh.get_num_triangles(0) reports the NANITE FALLBACK (3563 of
   24471) — count real geometry by summing per-section extraction.
6. **Vertex colours double-brighten**: the procedural mesh sRGB-encodes on
   store, the material reads bytes raw, and the atmosphere adds blue
   in-scatter at distance. The ClassifyVertex palette is CALIBRATED against
   rendered frames (correct-albedo maths rendered navy; naive linear
   rendered mint — both measured). Recalibrate by probe render, not theory.
7. **Fog and exposure are per-scene parameters**: clear=0.0012 at showcase
   altitudes (Gate 6 keeps 0.0025 at 300 m), exposure bias 9.5 noon / 10.5
   dawn / 11.0 gate6. All recorded in manifests.
8. **DefaultEngine.ini**: runtime appends an AndroidFileServer block with a
   local LAN token. OWNER'S DECISION (2026-08-14): just commit it when it
   appears — it is a local file-server token, an older one already sits
   in public history, and the owner explicitly accepted the (negligible)
   risk to avoid the recurring revert hassle. Do not scrub it, do not
   ask again. The fixed-tick settings at the top are load-bearing.
9. **One editor at a time**: the matrix runs UnrealEditor-Cmd serially;
   don't launch probe renders while it runs (DDC/GPU contention). Kill via
   `pkill -f "UnrealEditor-Cmd.*FlightSimRender"` + `pkill -f
   showcase_matrix`; it resumes cleanly.
10. **mutation_check.sh mutates source in place** — never run pytest (or
    build cards) concurrently with it in a way that re-imports core/.
11. **Pillow is in the venv** (panel + contact sheet); ffmpeg at
    /opt/homebrew/bin/ffmpeg; fonts from /System/Library/Fonts/Menlo.ttc.
12. **You can look at frames**: Read any rendered PNG (or a python-cropped
    region) to verify visually. Several bugs this phase were caught only by
    looking. Probe pattern: runs/probe6b/card.json + short -seconds renders.

## Everything below is Phase 5 context that remains load-bearing

(unchanged: the six commandlet behaviours, the three patched upstream plugin
bugs re-applied by vendor_ue_plugin.sh and asserted by check_bridge_api.sh,
the parity discipline, and the do-not-regress list)

* The plugin's wind IC corrupts CAS → calm RunIC, wind via FGWinds props,
  re-trim (TrimInWind), same NED floats re-written every step.
* Trim snapshot exempt from comparison; heading compared on the circle;
  comparison on the recorded clock, never sample index.
* GetAGLevel cm/m ray bug (3.19 km reach) patched in VENDORED.json.
* Ground slab spawned for physics queries; aircraft placed by CG; actor yaw
  = heading − 90; LatchTrimmedControls after trim; render commandlet needs
  -AllowCommandletRendering; two warm-up captures discarded.
* On-screen clauses decided by reading PNGs; surface deflection read off
  scene component transforms; commandlets refuse what they cannot honour.
* docs/JSBSIM_CORRECTIONS.md before writing property code;
  docs/VALIDITY.md for what may be claimed.

## Phase 7 gotchas (continuing the numbering)

13. **FFileHelper::SaveStringToFile switches to UTF-16** if any manifest
    string contains a non-ANSI character ("§" cost a render day). Manifest
    strings stay ASCII.
14. **The card's `turbulence` word gates turbulence_properties**: a card
    with writes but word "none" flies still air. Phase 7 providers carry
    card_word.
15. **Georeferenced landmarks project AFTER the terrain build** aligns the
    CRS: calm cards never set a CRS via orographic, and projecting before
    put the summit tens of km wrong.
16. **The 10-minute Bash cap kills foreground renders** — long renders run
    nohup-detached with a Monitor.
17. **Piston engines at altitude**: full rich kills a force-started engine;
    a crank-started one stabilises at a sick ~500 rpm idle under starter
    assist, so only the discovery's trim-refusal discriminates. Every
    piston card carries its verified engine_mixture.

## Phase 8 gotchas (continuing the numbering)

18. **-game mode NEVER starts under a locked console session.** Both editor
    binaries (UnrealEditor and UnrealEditor-Cmd) park in the AppKit event
    loop forever (sampled: main thread in -[NSApplication run], ~6% CPU, no
    log progress past plugin mounting). Commandlets (-run=) are unaffected.
    The windowed interactive host therefore needs a person at the machine;
    the fps probe and the replay experiment fall back to the render
    commandlet's real-time probe loop (-probe-wall-seconds=, same
    Scenario.Step path, same wall-clock substep accumulator) and LABEL the
    exclusion in their artifacts. Related: a first -game launch invokes UBT
    -Mode=QueryTargets, which wedges without DEVELOPER_DIR; pre-generate
    the cache once with Build.sh -Mode=QueryTargets
    -Project=ue/FlightSim.uproject
    -Output=ue/Intermediate/TargetInfo.json -IncludeAllTargets.
19. **DefaultEngine.ini's bUseFixedFrameRate pins the engine frame delta**
    (load-bearing for the offline hosts, gotcha 8). The interactive host
    disables it at RUNTIME (config untouched) and measures wall time with
    FPlatformTime -- trusting DeltaSeconds would silently dilate sim time
    against the wall clock and report a fake 120 fps.
20. **The editor-lock check matches "Binaries/Mac/UnrealEditor"**, never
    plain "UnrealEditor" -- the broad pattern also matches the always-on
    UnrealEditorServices helper and the Epic launcher's EpicWebHelper and
    refuses runs that are actually safe (cost one probe run).
21. **A Matterhorn track at 3600 m flies INTO the massif** (tops at 4540 m
    on the raster) around t=52 s on heading 236 -- with heightfield
    collision that is a crash, not scenery. Long runs over the massif use
    the showcase altitude (B747: 5200 m).
22. **Verified JSBSim aero property names (do not re-guess; hazard 1).**
    `aero/alpha-deg`, `aero/beta-deg`, `aero/qbar-psf`,
    `forces/fb{x,y,z}-aero-lbs` (BODY-axis aero force),
    `forces/fw{x,y,z}-aero-lbs` (WIND axis: fwx = drag, fwy = side force,
    fwz = lift -- the FDM resolves lift/drag itself; never transform by
    hand), `flight-path/gamma-deg` -- all verified against the live
    property catalog of the pinned JSBSim on 2026-08-10. NOT present:
    `velocities/flight-path-gamma-rad`, `aero/fl-aero-lbs`,
    `aero/fd-aero-lbs`. The UE recorder's channel table and the headless
    REQUIRED_PROPERTIES carry these names; tests/test_aero_channels.py
    pins them and the SelftestProperties refusal in all three hosts.
23. **Do not restart the uvicorn server while a run is active.** The
    worker thread dies with the process; the render subprocess finishes
    orphaned and the page polls a run the new process never heard of
    (measured -- cost the user a 30-minute "rendering" freeze).
    Completed runs now recover from disk (RunManager._recover_from_disk)
    but interrupted ones are honestly gone. Check /status busy first.
24. **The control ridge is georeferenced at ~(0.14 N, 10.65 E) -- it is
    not at the spec's default 0,0.** Any flight meant to see it must be
    placed on it (place_on_scene does this, recorded); and terrain that
    is only scenery lets the aircraft fly THROUGH peaks -- terrain runs
    now carry collision_terrain and a pre-flown clearance plan
    (plan_terrain_flight: defaulted altitude raised + recorded, stated
    altitude refused by name).
25. **Contact-check the trimmed state BEFORE the first step.** An aircraft
    whose spec puts a wing inside the terrain integrates one full step of
    ground-reaction chaos (metres of gear compression -> enormous forces)
    before any per-step check can fire; run_spec therefore checks the
    trimmed initial state at t=0 and refuses immediately. Also: the span
    stations skip out-of-raster positions on purpose -- the heightfield's
    edge CLAMP would otherwise manufacture a boundary cliff and kill
    every run that grazes the raster edge.

26. **The funnel mesh renders BLACK under both vertex-colour materials**
    (lit AND the new M_VertexColorUnlit) while the terrain renders its
    vertex colours fine -- five probes, bit-identical frames, colours
    never reached the shading. Open question (procedural-section colour
    path?); the funnel ships on the DEFAULT material (solid grey,
    provably visible in the storm light). Frame-45 pixel sampling also
    misled for a while: diff a no-tornado card at FRAME 0 (before
    physics diverges) to isolate what the funnel contributes. The
    wall-cloud disc was removed (a 700 m disc at chase distance reads
    as a screen-filling artifact); funnel spin runs at the model's own
    core rate omega = v_max/r_core from SIM time (replay-identical).

27. **A camera pitched DOWN sees the horizon ABOVE its centre**: the
    horizon row is v = cy + fy tan(pitch) (pitch -4.8 deg at fy 1244
    puts it at row 256 of 720), and a camera rolled right sees it rise
    to the right (slope -tan roll). The brief's "cy - fy tan(pitch)"
    has the sign wrong; the preview tests pin the measured one.
28. **Pillow's ImageDraw.line has no clipping of its own**: a segment
    whose endpoint sits near the near plane projects to coordinates in
    the millions and Bresenham walks them all. core.capture.preview
    clips every segment at near_m in camera space and then to the image
    (Liang-Barsky) BEFORE drawing; that is why 4600 wireframe segments
    cost 49 ms and not seconds.
