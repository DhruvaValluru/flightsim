# Phase 8 brief — a prompt-to-simulation interface

Delivered by the owner on 2026-08-10, recorded verbatim below (same
provenance rule as BRIEF_PHASE6/7: the criteria this phase is graded
against are the brief's own words, kept in the repo, not paraphrased
from memory).

---

Goal, in one sentence: type "simulate a plane in rough wind conditions over
mountains" into a local web page, review the interpreted scenario, click
Run, and watch that scenario live in a real-time Unreal window — without
weakening a single claim VALIDITY.md currently makes.

Written against 68f556a (307 tests, 62 guards, all gates green). Read with
docs/VALIDITY.md (claims discipline), docs/JSBSIM_CORRECTIONS.md (§9/§13
turbulence contract), and NEXT.md (gotchas 1–17, all of which apply here).

Decisions taken before writing this brief: local web app; LLM → validated
spec for prompt interpretation; real-time interactive view as the output
(not a rendered clip); spec shown for confirmation before anything runs.

## 0. What already exists, and what is genuinely new

Almost the whole pipeline exists. What Phase 8 adds is a front door and a
windowed host.

| Piece | Status |
|---|---|
| Prompt → spec with per-field provenance | EXISTS — core/nl/compiler.py (regex; deterministic, narrow) |
| Spec validation with refusals by name | EXISTS — core/scenario/validate.py (stall margin, trim feasibility, terrain clearance) |
| Spec → run card with every Phase 7 block | EXISTS — write_run_card (turbulence + seed, orographic, downburst, rotor, thermals, log profile, schedules, collision_terrain, engine_mixture, imagery sidecar) |
| Terrain + imagery bakes | EXIST — Matterhorn, Yosemite, control ridge under runs/terrain/; new locations go through the same glo30.py/imagery.py path |
| Scenario world in UE (terrain, drape, collision, environment ports, cameras, animators) | EXISTS — FFlightSimScenarioWorld + friends in FlightSimBridge |
| A way to RUN that world | commandlets only — offscreen, fixed-step, no window, no interactivity |
| A way to ASK for a scenario in plain English beyond the regex vocabulary | does not exist |
| A UI of any kind | does not exist |

The two genuinely new artifacts are (A) an LLM compiler that emits the
existing spec schema, and (C) an interactive game-mode host that ticks
FFlightSimScenarioWorld in a window. Everything else is plumbing (B).

## 1. Architecture

Three pillars, deliberately separable — each lands and is verified alone.

    browser ──► FastAPI backend (Mac) ──► compiler (LLM or regex) ──► spec
       ▲              │                                                │
       │              │        spec table (provenance-coloured) ◄──────┘
       │   user reviews/edits, clicks Run
       │              │
       │              ├──► validate() — refusals BY NAME end the flow here
       │              ├──► card builder (terrain bake reuse, engine_mixture
       │              │     discovery cache, environment blocks, seed)
       │              └──► UE launcher (single-instance lock, gotcha 9)
       │                        │
       │                        └──► NEW: windowed interactive host
       │                              fixed 1/120 FDM substeps, HUD,
       │                              camera presets, flight recorder
       └── WS: status + live telemetry ◄──┘

### A. The LLM compiler (core/nl/llm_compiler.py)

Claude API, structured output constrained to a JSON schema generated from
ScenarioSpec's own fields — the LLM fills the SAME schema the regex
compiler fills. Every field carries the existing provenance tags: an
explicit number in the prompt → user, a vague phrase ("rough wind") →
inferred with the phrase recorded, untouched → default. Anything the
prompt mentions that the schema cannot express goes to spec.notes, not
the bin — same rule the regex compiler already follows.

The LLM's output is never trusted. It is parsed into ScenarioSpec, and
the EXISTING validate() still governs: an infeasible request is refused
by name (altitude.terrain_clearance, airspeed.stall_margin,
envelope.trim_feasible) exactly as today. A response that fails schema
parsing is an error shown to the user, never silently patched.

The reproducibility claim does not move. §2.6's line — the spec is the
reproducible unit, the prompt is a historical note — was written for
exactly this moment. The LLM adds nondeterminism on the prompt→spec edge
only; spec→run stays bit-reproducible and content-addressed. The manifest
records prompt, model ID, raw response, and which compiler produced the
spec. The spec-review step is the control for misinterpretation, which is
why "show spec, then run" was the right choice.

The regex compiler remains as the offline fallback and as a cross-check
corpus (Gate 8.1). The UI always states which compiler ran.

ANTHROPIC_API_KEY from the environment; never committed, never in a
manifest.

### B. The web app

FastAPI backend on the Mac + a single self-contained HTML page (no build
system). Endpoints: POST /compile (prompt → spec + validation verdict),
POST /run (spec digest → card → launch), GET /status, WS /telemetry.

The spec table is spec.render() made clickable: provenance-coloured
fields (stated / inferred / defaulted), editable before running — the
Phase 1 flow (rendered, edited, validated, only then run) with a UI on
it. Validation refusals render as first-class results, not errors.

The card builder is today's write_run_card promoted out of
experiments/gate5_ue_parity.py into core/scenario/card.py — it has long
outgrown "experiment helper". Pure refactor, suite stays green, guards
re-targeted where line numbers move.

Run manager responsibilities, all reusing existing machinery: pick or
bake the terrain (existing bakes reused by digest; a new named location
triggers the glo30 + imagery path with its verification checks), attach
the imagery sidecar, look up the cached engine_mixture for piston cards
(the discovery sweep runs once per airframe/altitude band and is cached —
gotcha 17), derive the turbulence seed per spec, set the card's
turbulence WORD to match the blocks (gotcha 14), and take the
single-instance editor lock before launching (gotcha 9 — the UI refuses a
second concurrent run, and refuses while a matrix render owns the
editor).

Manifest strings stay ASCII (gotcha 13) — the prompt text is stored in a
sidecar JSON, not embedded in any UE-written manifest string.

### C. The interactive host (the real C++ work)

Today FFlightSimScenarioWorld::Step(card, t) is driven only by offscreen
commandlets. Phase 8 adds a windowed driver — a game mode (working name
AFlightSimInteractiveMode) in FlightSimBridge that:

* reads the SAME card format (-card=, -imagery=, -camera= …) — one
  scenario description, three hosts (headless, render commandlet,
  interactive). The card is the contract; nothing interactive-only creeps
  into it without the other hosts refusing it explicitly.
* builds the same scenario world: terrain mesh + imagery drape (or the
  labeled classification), heightfield collision when the card carries
  collision_terrain, all environment providers through the same
  step_writes path, sun geometry, fog/exposure per the card.
* fixed-substep physics, non-negotiable. JSBSim never sees a variable
  dt. Each render frame accumulates wall delta and steps the FDM in whole
  1/120 s substeps; the remainder carries. Catch-up is capped (~250 ms);
  when the cap trips, the sim clock falls behind wall clock and the
  deficit is COUNTED in the manifest — time dilation over dt-stretching,
  always. An on-screen indicator shows when the sim is running behind.
* camera presets via the existing FlightSimCameraDirector — number keys
  switch chase/wingman/tower/shoulder; CockpitShoulder remains the one
  declared roll-inheriting preset and the HUD says so while it's active.
* an on-screen HUD carrying the telemetry panel's honesty core:
  commanded vs achieved state, the wind actually inside the FDM,
  turbulence seed with the visual-only label, physics-ground label
  (heightfield vs slab), AGL, and the substep/deficit counter. Labels on
  screen, not in a file nobody opens — same principle as the clip panel.
* a flight recorder, and this is the verification story. Every
  interactive session writes its card and full telemetry exactly like
  the commandlets do. The claim-bearing artifact of an interactive
  session is its recorded card, which the headless host can re-fly
  deterministically. Interactive mode is a viewport; claims come from
  the replay.
* v1 flies hands-off from trim (or the card's scripted inputs — the
  Zermatt machinery), which is what makes replay comparison meaningful.
  Keyboard/joystick flying is a stretch goal (8C): the recorder then
  logs the input stream, the session is labeled human-in-loop, and
  replay parity is explicitly NOT claimed for it in v1.

What real-time costs, stated up front (future VALIDITY §2.14):

* Rendering was never reproducible (§3) and interactive rendering is
  less so; no claim rides on the pixels except the on-screen clauses.
* A turbulent interactive session diverges from its headless replay by
  the measured per-host RNG offset — the permanent visual-only verdict
  applies unchanged; the HUD and manifest both say so.
* Frame-rate headroom is unmeasured: the Mac has only ever rendered this
  scene offline where a slow frame costs wall time, not correctness. An
  early probe (8B.0) measures real-time fps over the full Matterhorn
  scene (30 m collision + drape + panel HUD) before anything depends on
  it. Mitigations exist (visual stride already 2; HUD cost bounded), but
  the budget gets measured, not assumed.

## 2. Gates — measured, in the repo's sense

**Gate 8.1 — the compiler.**
* A ~30-prompt corpus (including "simulate a plane in rough wind
  conditions over mountains") → every output parses into the schema,
  validates or is refused by name, and carries provenance on every
  field. No silent drops: unexpressible prompt content appears in
  spec.notes.
* On the regex compiler's own documented vocabulary, the LLM compiler
  must produce specs the validator judges identically
  (refusal-for-refusal).
* Adversarial prompts (impossible altitude/speed, unknown aircraft,
  cinematic-only language) are refused or noted — never guessed into a
  runnable spec that misrepresents the request.
* Determinism statement tested, not assumed: same SPEC twice →
  identical digest → identical run (existing Phase 1 property,
  re-asserted through the new path).

**Gate 8.2 — the interactive host.**
* Substep accounting: over a timed session, FDM steps == expected whole
  substeps of elapsed sim time; any deficit equals the recorded
  catch-up-cap events. No code path can hand JSBSim a dt ≠ 1/120.
* Replay parity: a still-air and a steady-wind interactive session's
  recorded cards re-flown headless; interactive telemetry vs replay held
  to Gate 5's channels and tolerances (comparison on the recorded clock,
  trim snapshot exempt, heading on the circle — all the existing
  discipline). A turbulent session is compared only to confirm it
  DIVERGES as the visual-only verdict predicts.
* Environment liveness: the ports' startup selftest grids run in the
  interactive host and match Python, and one in-session null (e.g. rotor
  card vs -NoOrographic-style sever) shows the coupling reaches the FDM.
* On-screen clauses, read from captured frames as always: chase camera
  roll 0.000000°, HUD present and legible, aircraft in frame.

**Gate 8.3 — end to end.** Browser prompt → spec table with provenance →
edit one field → run → window opens → session recorded → manifest
carries prompt, model, compiler, spec digest, seed, terrain tiles +
sha256, and the honesty labels. One refusal case end to end too (e.g.
the B747 microburst clearance refusal surfacing in the browser by name).

Mutation guards ride along as usual: the LLM-output schema refusal, the
substep cap counter, the editor lock, the replay-comparison exemptions.

## 3. Order of work

| Step | What | Size |
|---|---|---|
| 8A.1 | Promote write_run_card + run orchestration into core/scenario/card.py (pure refactor, guards re-targeted) | S |
| 8A.2 | llm_compiler.py + schema + tests (API mocked in suite; live smoke separate) | M |
| 8B.0 | Real-time fps probe of the full Matterhorn scene in a window — the go/no-go number for 8C | S |
| 8B.1 | FastAPI backend + spec-table page, wired first to the EXISTING render commandlet (prompt → clip). Cheap given the machinery, and the whole UI is proven before the new host exists | M |
| 8C.1 | AFlightSimInteractiveMode: card-driven world, fixed substeps, camera keys | L |
| 8C.2 | HUD + flight recorder + editor lock integration | M |
| 8C.3 | Replay-parity experiment (experiments/interactive_replay.py) | M |
| 8D | Gates 8.1–8.3, VALIDITY §2.14, NEXT.md gotchas, mutation guards | M |

8B.1 is the deliberate hedge: after it, "prompt → simulation" already
works end to end with clips, so the interactive host lands as an upgrade
rather than a prerequisite. If 8B.0's fps number comes back bad, the
plan degrades gracefully instead of dying.

## 4. Standing rules that bind this phase

Builds via scripts/build_ue.sh only. One editor instance, enforced by
the run manager, not by discipline. Long anything runs detached
(gotcha 16). DefaultEngine.ini runtime append never committed
(gotcha 8) — note its fixed-tick settings interact with the interactive
host and must be re-examined for windowed play. Every piston card
carries its verified engine_mixture (gotcha 17). Turbulence: seed once,
severity pinned, W20 only, below 300 m AGL (§13). ASCII manifests
(gotcha 13). card_word matches the blocks (gotcha 14). And the
meta-rule over all of it: a check that cannot fail is not a check —
every gate above names what failure looks like.
