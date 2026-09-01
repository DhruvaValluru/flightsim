# Resume here

**Fresh session? Read docs/CONTEXT_SCENE_DIRECTOR_SESSION.md and
docs/CONTEXT_PHASE8B_SESSION.md first**, then this file's gotchas 1-26.

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
