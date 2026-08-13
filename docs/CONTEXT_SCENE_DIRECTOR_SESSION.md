# Scene-director + cross-platform session context (2026-08-13)

Read WITH `NEXT.md` (gotchas 1-26 all stand) and
`docs/CONTEXT_PHASE8B_SESSION.md`. Two-part brief, landed as separate
commits so either reverts alone. Everything below was measured, not
asserted; the misses that drove each fix are recorded inline.

## Part A -- the scene director (LLM full-scene interpretation)

The problem, user's words: prompts are "very very like human language and
sometimes vague"; the LLM must "take all the info and alter ALL the
values accordingly, not just wind." Guessing allowed and encouraged;
SILENT guessing stays a graded failure.

* **Source `model`** (fields.py; rank user > inferred > model > derived >
  default): the director's declared interpretation, always carrying the
  quoted prompt phrase. `_parse_payload` refuses a model row with no
  reason BY NAME (mutation-guarded). SPEC_VERSION 4 -> 5 (a v5 dict may
  carry a source v4 builds refuse; decision recorded in spec.py, pinned
  by test). `spec.plan()` moves default|derived|model; `set()` stays the
  human edit. PLANNABLE_SOURCES in webapp/runs.py is THE line: planners
  move system-chosen values only, user/inferred never (guarded).
* **SYSTEM_PROMPT rewritten as a director**: fill every field the prompt
  justifies, coherently, three claimable sources, numeric guesses where
  vocabulary can't express ("treetop level" -> 150 m), geography rules
  unweakened. Measured model behaviours that forced parse-layer
  normalizations (each tolerates ONLY a semantically-empty shape, all
  other strictness intact): absent notes/questions -> [], null value ->
  entry dropped (JSON's spelling of omission), redundant "unit" key
  tolerated iff it states the CANONICAL unit (CANONICAL_UNITS),
  model-sourced lat/lon DROPPED as an invented place (geography rail,
  now structural).
* **Vocabulary widened** (words before numbers): WIND_STRENGTH +=
  breezy 12 / gusty 18 / rough 25 / violent 40 / howling 40;
  TURBULENCE_WORDS += bumpy/choppy 15, rough 30, violent 45. The table
  REMAINS the control (Gate 8.1 grades against it). "Kansas" is now a
  flint_hills alias.
* **plan_terrain_environment** (webapp/runs.py): the raster's principal
  ridge axis via the structure-tensor doubled-angle trick
  (`_ridge_axis_deg`, pinned on synthetic rasters: N-S 0 / E-W 90 /
  anti-diagonal 135; everest 104, control ridge 2). System-chosen wind
  direction planned ACROSS the axis (WHOLE degrees -- the UE wind IC is
  integral and refuses fractions, measured), heading ALONG it (the seed
  of valley-following). Calm specs get no invented direction; flat
  scenes no-op; ERA5 wind (source user) blocks it. Planner order is
  stated + pinned in server.py /run: place_on_scene ->
  apply_weather_event -> apply_historical_weather ->
  plan_terrain_environment -> derive_seed -> plan_terrain_flight ->
  plan_flyable_defaults -> plan_trim_recovery -> project_for_ue_host ->
  validate. /compile runs the cheap planners so the table IS the run.
* **plan_flyable_defaults grew aircraft-awareness** (measured: "a plane"
  -> c172p kept the B747's 250 kt default -> TrimError): a still-default
  airspeed re-plans to THIS airframe's documented cruise.
  **plan_trim_recovery** (new): a PLANNABLE airspeed the trim probe
  refuses re-plans ONCE to the documented cruise (measured: model-guessed
  120 kt exceeds the c172p's level-flight power at 2500 m); user-stated
  conditions keep their refusal. **project_for_ue_host** re-plans a
  GUESSED airspeed_kind "tas" to "cas" (the plugin's only speed IC is
  calibrated; a stated TAS still refuses).
* **UI**: the provenance table reads like director's notes -- model rows
  blue with `interpreting "phrase"`, derived purple, plus a legend line.
* **Gate 8.1 vague category**: coherent-and-declared grading (fair-quote
  check incl. quoted segments, min_filled breadth, expect_fields
  coherence pins, flyable after the webapp's own planning).
* **VALIDITY §2.14**: the claims paragraph -- a model row is a DECLARED,
  overridable proposal; nothing the model writes is evidence.

Acceptance (measured live):
1. "storm chasing in a small plane over Kansas" -> c172p/flint_hills/
   thunderstorm/120 kt (model, "storm chasing")/altitude 713 derived/
   heading 9 along axis/wind 25 kt from 99 across axis; VALID; rendered
   END TO END (runs/webapp/3ed4d58bc9ff: clip + telemetry + effect
   report). Two honest refusals on the way are recorded in failed run
   dirs: guessed tas (e3d08dd7d991), fractional wind direction
   (421f6f28a248) -- both machinery fixes above.
2. Mountains vs flat with the same "rough wind" (10 s headless,
   open-loop): wind FROM 118 deg vs 8 deg, vertical air [-2.2, +2.9] m/s
   (orographic lift AND sink) vs one-sided turbulence-only, different
   n_z character. Specs differ exactly by the planned rows.
3. Stated "wind from 180" over the matterhorn: untouched (heading still
   planned -- system-chosen).
4. Gate 8.1 on gpt-4.1-mini: see NEXT.md for the recorded verdict and
   the per-iteration miss history (12 -> 7 -> 6 -> ...).

## Part B -- cross-platform (mac / linux / windows)

* `core/util/platform.py` is the ONE home for OS dispatch: os_name(),
  find_ffmpeg() (env FLIGHTSIM_FFMPEG -> PATH -> per-OS locations;
  missing = NAMED ffmpeg.missing with the per-OS install command, raised
  at the point of use), find_mono_font()/mono_fonts() (env FLIGHTSIM_FONT
  -> per-OS chains -> Pillow bitmap font WITH a logged warning).
  showcase_panel/showcase_matrix/evolving_flight route through it;
  editor_running() short-circuits False off-mac.
* **UTF-8 sweep**: 164 call sites got explicit encoding="utf-8"
  (Windows cp1252 corrupts the provenance sidecar), and
  tests/test_platform.py::test_no_text_io_without_utf8_encoding enforces
  it STATICALLY forever (balanced-paren scan, no binary/encoding=
  false-positives). .gitattributes pins *.sh to LF.
* **UE refuses by name off-mac**: all five UE shell scripts exit 3 with
  the ue.platform text before doing anything; RunManager.start returns
  the same refusal (409, never a 500) and GET /status reports
  platform + render_available so the page states it up front. The UE
  port itself is a RECORDED DEFERRAL: it compiles in principle, but
  every render gotcha was measured on Metal/macOS only -- do not claim
  render support nobody measured.
* **Setup**: scripts/setup.ps1 (Windows twin), README "Platform support"
  matrix + per-OS notes (~/.flightsim.env is a POSIX convention; Windows
  sets env vars on the server process).
* **Tests**: shared `mac_ue` marker in conftest.py (skip visibly, never
  weaken); tests/test_platform.py covers dispatch, ffmpeg refusal, font
  degradation, the webapp ue.platform 409, and the static encoding scan.
* **CI**: .github/workflows/ci.yml -- pytest on ubuntu/windows/macos
  (FLIGHTSIM_LLM=none; the suite is fully mocked). The windows/linux
  legs ARE the off-mac acceptance measurement.
