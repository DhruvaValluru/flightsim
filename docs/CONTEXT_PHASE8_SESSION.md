# Phase 8 session context — everything that happened, for a fresh session

Written 2026-08-10 at the end of the Phase 8 run (commits
`68f556a..a4d6056`, 16 commits). Read this WITH `NEXT.md` (operative resume
state + gotchas 1-21), `docs/BRIEF_PHASE8.md` (the brief, verbatim),
`docs/VALIDITY.md` (§2.14 is new — the interactive tier's claims ledger)
and `docs/JSBSIM_CORRECTIONS.md` (unchanged this phase). This file is the
session narrative: what was done in what order, what broke, what was
measured, and why each decision went the way it did.

## Final state in one paragraph

Phase 8 delivered the prompt-to-simulation front door end to end: an LLM
compiler that fills the EXISTING spec schema under strict parsing (Claude
API, structured output, regex-identical defaults, validator unchanged), a
FastAPI web app with a provenance-coloured editable spec table and
refusals-by-name, and the windowed interactive host
(AFlightSimInteractiveMode) with a wall-clock 1/120 substep accumulator,
HUD honesty layer, flight recorder and session manifest. Gate 8.3 PASSED
end to end (prompt → table → edit → run → panelled clip, one digest
content-addressing response == provenance == card == manifest, refusal
case by name in the browser AND at the endpoint). Gate 8.2's substep and
replay clauses PASSED measured (still air 3.6e-4 m, wind 0.021°,
turbulence diverges exactly as the visual-only verdict predicts; ledgers
exact, zero caps). The 8B.0 fps probe came back GO at 171 fps over the
full Matterhorn scene (5.7× headroom). Suite: **338 tests, 66 mutation
guards, all load-bearing, all green.** Two things remain BLOCKED on the
user: Gate 8.1's live LLM corpus (no ANTHROPIC_API_KEY on the machine)
and the literally-windowed run + Gate 8.2's on-screen clauses (the console
session was locked the whole session; -game cannot start under a lock).

## Session timeline (what happened, in order)

1. **8A.1** — `write_run_card` + `discovered_engine_mixture` promoted
   verbatim from `experiments/gate5_ue_parity.py` into
   `core/scenario/card.py`; old module re-exports so all 15 import sites
   are untouched; the two mutation guards on the moved lines re-targeted
   and re-verified load-bearing. (Note: the suite collects 306 tests at
   68f556a, not the 307 the Phase 7 notes recorded — pre-existing, both
   sides of the refactor identical.)
2. **8A.2** — `core/nl/llm_compiler.py`: the JSON schema is GENERATED from
   `ScenarioSpec.FIELD_ORDER` (import-time assert that schema fields ⊆
   spec fields); the model may claim only `user`/`inferred` provenance
   with the phrase recorded; defaults come from running the regex compiler
   on an EMPTY prompt and overlaying — so untouched fields are
   bit-identical between compilers and the validator cannot judge them
   differently (the property Gate 8.1's refusal-for-refusal rests on).
   Strict `_parse_payload` rejects unknown fields, wrong types (bool is
   not a number), out-of-vocabulary enums, claimed-default provenance,
   missing phrases, extra keys, refusals, transport errors —
   `LLMCompileError` is user-facing, never patched. Host-policy fields
   (rate/seed/mass_held/hold_state) are not model-settable. 20 mocked
   tests; live smoke: `python -m core.nl.llm_compiler "<prompt>"`.
   Calls run at **effort low** (short schema-constrained extraction; the
   strict parse + validator are the correctness rails). anthropic SDK
   0.121.0 installed into the venv.
3. **8B.1** — `webapp/` (server.py, runs.py, static/index.html — one
   self-contained page, no build system). /compile (LLM with stated regex
   fallback + reason), /run (server-side re-validation; refusals are 409s
   by constraint name), /status, /runs/{id}[/clip.mp4|/provenance.json],
   WS /telemetry. Run manager: scene by LOCATIONS proximity (±0.1°) →
   real bake + imagery; unnamed mountains → control ridge; else labeled
   flat slab. Seed derived from spec digest when defaulted (recorded).
   22 s clip cap. Panel composited on every clip. Editor lock via pgrep
   on "Binaries/Mac/UnrealEditor" (gotcha 20). Prompt/model provenance in
   a Python-written UTF-8 sidecar; UE manifests stay ASCII.
4. **The locked-session saga (8B.0)** — three failed windowed launches:
   -game parks BOTH editor binaries in the AppKit event loop forever
   under a locked console session (sampled call stacks; gotcha 18).
   En route: the editor's UBT `-Mode=QueryTargets` also wedges without
   DEVELOPER_DIR — fixed permanently by pre-generating
   `ue/Intermediate/TargetInfo.json`. Solution: the render commandlet
   gained `-probe-wall-seconds=` — a real-time loop through the SAME
   `Scenario.Step` path paced by the same wall-clock accumulator, one
   CaptureScene per frame, NO readback/PNG, optional
   `-probe-telemetry=`/`-probe-manifest=`. Exclusions (window
   compositing, HUD draw) stated in every artifact.
5. **The scenario-world refactor (for 8C)** — `Build` split into
   world-creation + `Populate`; new `BuildInto(LiveWorld)` populates an
   already-playing world with a DEFERRED aircraft spawn (a live-world
   SpawnActor dispatches BeginPlay mid-configuration and the plugin would
   trim an unconfigured aircraft); `Step` split into `ApplyStepWrites` +
   `Crashed`; `Teardown` forgets external worlds instead of destroying
   them. Commandlet behavior byte-identical.
6. **8C.1 + 8C.2** — `AFlightSimInteractiveMode` (+
   `AFlightSimInteractiveHUD`): same card contract (-card/-imagery/
   -camera/-telemetry/-manifest/-screenshot-at). Wall-clock accumulator:
   whole 1/120 substeps, 250 ms catch-up cap, deficit COUNTED, movement
   component's own tick disabled (one stepping path);
   `bUseFixedFrameRate` disabled at runtime and wall time measured via
   FPlatformTime (gotcha 19 — trusting DeltaSeconds would silently
   dilate sim time). HUD: commanded vs achieved, wind actually in the
   FDM, turbulence seed + visual-only label, physics-ground label,
   camera preset + roll-inheritance callout, substep ledger with explicit
   SIM RUNNING BEHIND. Recorder = the commandlets' own component (t =
   FDM sim time). Camera keys 1-4 (needed "InputCore" in Build.cs).
   ASCII session manifest with the full deficit ledger.
7. **8B.0 measured: GO.** First probe crashed at t=51.8 s — the 3600 m
   card flew INTO the 4540 m massif (gotcha 21); rerun at the showcase's
   5200 m: **171.3 fps mean, frame ms p50 5.8 / p95 7.3 / max 41.8,
   60.0 s sim in 60.0 s wall, substeps 7199 == 7199, zero caps** over
   georeferenced Matterhorn + Sentinel-2 drape + converted B747 mesh +
   30 m heightfield collision at 1280x720 offscreen. GO threshold was
   30 fps.
8. **8C.3 measured: PASS.** `experiments/interactive_replay.py` flies
   three 30 s sessions through the wall-clock loop and re-flies each
   headless under Gate 5's compare(): still air max |Δalt| **3.6e-4 m**;
   25 kt crosswind max |Δroll| **0.021°**; moderate turbulence seed
   424242 **diverges** (26.3 m / 18.4 kt / 11.1°) exactly as the
   permanent visual-only verdict predicts. Ledgers exact (3601 ==
   round(30.01 × 120)), zero caps, every session.
9. **Gate 8.3: PASS** (after two honest failures). First run: the render
   commandlet REFUSED the card — a compiled spec defaults
   hold_state=True and the UE host has no autopilot → `project_for_ue_host`
   applies reference_spec's own projection (open loop, mass held),
   recorded in provenance, and the projection runs in /run BEFORE the
   digest is answered so the response content-addresses what actually
   runs. Second run exposed my check reading the wrong manifest key
   (terrain sha lives under `scene.terrain_sha256`; physics-ground label
   asserted too). Final: all checks green, clip at
   `runs/webapp/c1651c2076c2/clip.mp4`.
10. **8D** — 4 new mutation guards (LLM provenance claim, out-of-vocab
    refusal, editor lock, run-endpoint re-validation); full
    `mutation_check.sh`: **66/66 load-bearing, suite restored green**.
    VALIDITY §2.14 written with all measured numbers. NEXT.md gotchas
    18-21 + Phase 8 verification-loop commands.
11. **Post-wrap UX fix (user hit it live)** — "why is Interpret slow":
    the user clicked the RAW index.html that a preview pane had opened;
    fetch to /compile had no backend and the page spun forever. Fixed:
    the fetch catch now names the failure and the fix; a `flightsim-web`
    entry exists in ~/.claude/launch.json (uvicorn, port 8008); verified
    live in the browser pane — instant interpretation, fallback reason
    printed on the page.

## Gate scoreboard

| Gate | Verdict |
|---|---|
| 8.1 compiler corpus (live) | **BLOCKED** — no ANTHROPIC_API_KEY; mocked half (20 tests) green; runner ready: `experiments/gate8_compiler.py` (exit 2 = BLOCKED by design) |
| 8.2 substep accounting | **PASS** — ledgers exact in probe + all replay sessions |
| 8.2 replay parity | **PASS** — table above; via the locked-session commandlet path (same stepping + clock; window absent and stated) |
| 8.2 environment liveness | NOT RUN as a dedicated check this session (ports' selftests unchanged from Phase 7; in-session null still to do in the windowed host) |
| 8.2 on-screen clauses | **BLOCKED on user presence** — -screenshot-at= wiring exists; needs an unlocked session |
| 8.3 end to end | **PASS** — `runs/gate8_end_to_end/report.json` |

## Where everything lives

| What | Where |
|---|---|
| Resume state + gotchas 1-21 | `NEXT.md` |
| The brief (verbatim) | `docs/BRIEF_PHASE8.md` |
| Claims ledger for the tier | `docs/VALIDITY.md` §2.14 |
| LLM compiler + tests | `core/nl/llm_compiler.py`, `tests/test_llm_compiler.py` |
| Card writer (promoted) | `core/scenario/card.py` (gate5_ue_parity re-exports) |
| Web app + tests | `webapp/{server,runs}.py`, `webapp/static/index.html`, `tests/test_webapp.py` |
| Interactive host | `ue/.../FlightSimInteractiveMode.{h,cpp}`, `FlightSimInteractiveHUD.{h,cpp}` |
| Scenario-world refactor | `FlightSimScenarioWorld.{h,cpp}` (BuildInto/Populate/ApplyStepWrites/Crashed) |
| Probe loop (locked-session path) | `FlightSimRenderCommandlet.cpp` (-probe-wall-seconds/-probe-telemetry/-probe-manifest) |
| Experiments | `experiments/{fps_probe,interactive_replay,gate8_compiler,gate8_end_to_end}.py` |
| Measured reports (untracked, on disk) | `runs/{fps_probe,interactive_replay,gate8_end_to_end,webapp}/` |
| Server launch | `~/.claude/launch.json` name `flightsim-web` → uvicorn 127.0.0.1:8008 |

## Loose ends a future session should pick up

* **When the user is at the unlocked Mac**: run
  `experiments/fps_probe.py` (auto-detects the lock; will go windowed) for
  the windowed fps figure; run the interactive host with
  `-screenshot-at=5:10:15 -screenshot-dir=...` and grade Gate 8.2's
  on-screen clauses (camera roll 0.000000° via chase, HUD legible,
  aircraft in frame); try camera keys 1-4 by hand.
* **When a key exists**: `ANTHROPIC_API_KEY=... .venv/bin/python
  experiments/gate8_compiler.py` — Gate 8.1's live corpus (30 prompts,
  refusal-for-refusal, adversarial honesty, determinism re-assert).
* The interactive host still flies a **placeholder box** — wiring the
  converted mesh + surface animators (the render commandlet's airframe
  code) into `SetupScenario` is the natural 8C follow-up; every artifact
  currently records "placeholder" so nothing over-claims.
* Environment liveness in-window (a rotor card + the -NoOrographic-style
  sever) was not run as a dedicated in-session null this session.
* WS /telemetry currently streams orchestration status; the interactive
  host should eventually stream live FDM telemetry through it.
* Keyboard/joystick flying (8C stretch): recorder logs the input stream,
  session labeled human-in-loop, replay parity explicitly NOT claimed.
* The webapp uvicorn server may still be running on port 8008.

## How to verify everything from scratch

Run the loop in NEXT.md's code block. All of it is green as of `a4d6056`
except the two BLOCKED items above, which are BLOCKED, not failed.
