# Phase 8B session context -- everything that happened, for a fresh session

Written 2026-08-11 at the end of the session that ran from `32f2a6b` to
`799e094` (7 commits). Read this WITH `NEXT.md` (operative resume state +
gotchas 1-24), `docs/CONTEXT_PHASE8_SESSION.md` (the previous session),
`docs/VALIDITY.md` (SS2.14 grew three paragraphs this session) and
`docs/BRIEF_PHASE8.md`. Two briefs drove the session (LLM compiler v2;
the aerodynamics panel) and the rest was user-driven: a free LLM
provider, and two honesty bugs the user caught by looking at their own
clip.

## Final state in one paragraph

The webapp is a complete free-running loop on localhost:8008: prompt ->
LLM compile (a LOCAL Ollama model by default -- no key, no account, no
network) -> one round of clarifying questions -> provenance table -> run
-> terrain-coordinated, clearance-planned, heightfield-collision clip
with a live aerodynamics side panel synced to the video. Suite: **376
tests, 72 mutation guards, all load-bearing, all green.** Gate 8.1 ran
LIVE for the first time (qwen2.5:14b): FAIL (6), all six misses being
model quality, machinery verified (determinism identical, clarify
entries passed). Still blocked on the user: the windowed session
(unlocked console) and a frontier-model Gate 8.1 PASS (needs
ANTHROPIC_API_KEY or a strong FLIGHTSIM_LLM=openai endpoint).

## Session timeline (what happened, in order)

1. **LLM compiler v2** (`c611920`, brief PROMPT_LLM_COMPILER_V2): key
   preflight (presence-only, named fix, `llm_available` on /status +
   badge); locations block GENERATED into SYSTEM_PROMPT from
   `glo30.LOCATIONS` (import-time assert, guard); ONE round of <=3
   clarifying questions enforced in `_parse_payload` (round-ness carried
   by `answers` alone, no server state); answered fields are the user
   speaking (`answer to "...": "..."` enforced source=user); Q&A
   transcript -> UTF-8 provenance sidecar via /run; question cards in the
   UI. 4 new guards. Gate 8.1 corpus gained clarify/determined kinds
   with scripted answers + on-bake assertions.
2. **Aerodynamics panel** (`52e584b`, second brief): the SHARED recorder
   (one channel table -- sampling, selftest, writer all iterate it)
   gained alpha/beta, qbar, body- AND wind-axis aero forces (lift=fwz,
   drag=fwx: the FDM's own outputs, never a transform here), gamma,
   total wind, NED velocity. Property names verified LIVE against the
   pinned JSBSim before use (gotcha 22). `SelftestProperties` refusal in
   all three hosts (hazard 1). Render path takes `-telemetry=`; webapp
   serves `/runs/{id}/telemetry.json` (404 until done); canvas side
   panel indexed by video clock (mapping stated on panel): dials with
   the MODEL's own measured stall alpha, stall margin vs model Vs with
   basis printed (card gained optional display-only `reference_speeds`),
   wind triangle (x4 scaling stated), lift/drag/n_z bars, surfaces,
   honesty strip. HUD gained the matching aero block. Gust null test
   (quiet in trim, moving under a 6 m/s written gust) + frozen Gate 5
   graded set, both guarded. Acceptance run measured: alpha jittering
   2.9-5.0 deg under seeded turbulence, lift ~2.3 MN == the B747's
   weight, Vs 175.9 (CLmax 1.192) marks on screen.
3. **Free LLM providers** (`f32d3b4`, user: "not anthropic find another
   llm"): `core/nl/providers.py` -- OllamaClient (local, native
   /api/chat, `format`=RESPONSE_SCHEMA grammar-constrains the local
   model exactly as the Claude API would) and OpenAICompatClient (Groq/
   Gemini/OpenRouter), both behind the anthropic-shaped `client=` seam
   the suite always mocked. Env-driven: FLIGHTSIM_LLM=ollama|openai wins
   over ANTHROPIC_API_KEY; preflight error names every option. Installed
   ollama (brew service) + qwen2.5:7b, then 14b (7b mislabeled "a
   cessna" as A320). A GENERATED worked example in the geography rules
   ("all three fields together") measured-fixed the 14b's lat/lon skip:
   ON-BAKE True. Config in ~/.flightsim.env (sourced by the
   flightsim-web launch entry): FLIGHTSIM_LLM=ollama,
   FLIGHTSIM_LLM_MODEL=qwen2.5:14b.
4. **Gate 8.1 first live run** (`f09a5d6`): runner now survives a
   validated-but-untrimmable/unclosable spec in the determinism phase
   (records the refusal, tries the next). Verdict on qwen2.5:14b:
   **FAIL (6)** -- runs/gate8_compiler/report.json; determinism
   IDENTICAL; clarify entries passed end to end; all six failures are
   model quality (asked on 3 vocabulary + 1 determined prompt, 1 silent
   guess, 1 off-bake). The report records the provider; the verdict
   measures the model, not the machinery.
5. **Restart-orphaned run** (`141e18a`, user: "its been 30 minutes"):
   my server restart landed mid-run -- render finished (660 frames +
   telemetry) but the worker died before encode, and the page polled a
   run the new process never heard of. Fixed: the orphan was finished by
   hand through the same encode/panel path, and `RunManager.get()` now
   recovers COMPLETED runs from disk (provenance sidecar carries the
   conditions strip too); interrupted runs are not resurrected. Lesson
   absorbed: do not restart uvicorn while a run is active (gotcha 23).
6. **"why is there no mountains"** (`ad7cab6`): the synthesised control
   ridge is georeferenced at an arbitrary spot (~0.14N, 10.65E); a
   mountainous spec with the default 0,0 origin flew ~1,180 km from the
   mesh. Every label was truthful; the frames showed empty sky (read
   the pixels, gotcha 12). `place_on_scene()` moves the origin to the
   ridge raster centre, recorded in provenance, BEFORE the digest is
   answered. (Gate 8.3 had graded the digest chain and labels, not
   ridge pixels -- the showcase never hit this because it set origins
   itself.)
7. **"just passing through the mountains"** (`799e094`): ridge tops at
   3299 m, defaulted altitude 3000 m, physics ground a flat slab -- the
   plane flew THROUGH scenery peaks, straight, hands-off. Fix = the
   Zermatt discipline generalised to every terrain run:
   `plan_terrain_flight()` pre-flies the card's own S-turn script
   (trimmed+delta convention, steady wind included) headlessly on the
   scene's raster; a DEFAULTED altitude is raised to track-peak + 300 m
   (recorded, pre-digest); a STATED altitude is never moved -- refusal
   by name `terrain.clearance` (the showcase's own pattern); untrimmable
   specs are left to validate(). Terrain runs now carry
   `collision_terrain` (the raster IS the physics ground) and the
   SHOWCASE_DOUBLET banks. Verified: altitude 3000->3380 recorded,
   frames show the B747 banked above the ridgeline, telemetry (vs the
   raster) roll to 11.5 deg, min AGL 301 m.

## Operational setup (this machine)

* **ollama**: brew service (`brew services start ollama`), models
  qwen2.5:7b + qwen2.5:14b pulled. 14b is the configured default.
* **~/.flightsim.env**: FLIGHTSIM_LLM / FLIGHTSIM_LLM_MODEL exports,
  sourced by the `flightsim-web` entry in ~/.claude/launch.json (which
  now runs `sh -c '. ~/.flightsim.env; ... uvicorn ...'`). To switch to
  the Claude API: comment those, set ANTHROPIC_API_KEY, restart.
* The user has a Claude Max plan -- which does NOT cover API keys; they
  declined paid API usage, hence the local provider.
* Server: uvicorn on 127.0.0.1:8008 via the launch entry. Do NOT restart
  it while a run is active (gotcha 23).

## Gate scoreboard delta

| Gate | Verdict |
|---|---|
| 8.1 live corpus | RUN (first time): FAIL (6) on local qwen2.5:14b -- model quality, machinery verified; frontier-model PASS still open |
| 8.2 on-screen clauses | still BLOCKED on an unlocked console; checklist now also includes the HUD aero block legibility |
| 8.3 | PASS stands; ridge-pixels gap it never graded is closed by ad7cab6/799e094 |

## Where the new things live

| What | Where |
|---|---|
| Session narrative (this file) | docs/CONTEXT_PHASE8B_SESSION.md |
| Providers (ollama / openai-compat) | core/nl/providers.py; tests in tests/test_llm_compiler.py |
| Questions/preflight/locations | core/nl/llm_compiler.py |
| Aero channels + selftest | FlightSimTelemetryRecorder.{h,cpp} (one channel table); REQUIRED_PROPERTIES in core/fdm/state.py |
| Aero tests (gust null, frozen graded set, selftest wiring) | tests/test_aero_channels.py |
| Web aero panel | webapp/static/index.html (initAeroPanel) |
| HUD aero block | FlightSimInteractiveMode.cpp HudLines() |
| Scene placement + clearance planner + disk recovery | webapp/runs.py (place_on_scene, plan_terrain_flight, _recover_from_disk) |
| Card reference_speeds (display-only) | core/scenario/card.py + ReadCard optional parse |
| Gate 8.1 report (local model) | runs/gate8_compiler/report.json |
| Proof clips | runs/webapp/{8907c0286d23 (terrain-coordinated), 4f7d882f39f3 (placed), 96147222ef39 (recovered orphan)} |

## Loose ends a future session should pick up

* **Valley-following flight**: the user wants the aircraft to fly "in
  coordination with the mountains". What ships now is clearance-planned
  banking OVER terrain; true valley-chasing (following a gorge, heading
  schedule derived from the raster) is the natural next feature -- the
  Zermatt VALLEY_SCRIPT generalised into a route planner.
* **S-turn asymmetry under crosswind**: in the 40 kt run the right bank
  reached 11.5 deg but the left bank barely -0.7 (trim aileron bias
  eats the -0.12 delta). A wind-aware script (deltas scaled about the
  trimmed aileron) would balance the banks.
* Gate 8.1 with a frontier model (key or strong openai endpoint) for
  the real PASS; the runner is provider-agnostic now.
* The windowed session + HUD aero block screenshot grading (unlocked
  console; unchanged).
* Interactive host: mesh+animators still placeholder; live WS telemetry
  still pending (unchanged from Phase 8).
* qwen tuning if the local model stays primary: it maps "rough wind" to
  40 kt/no-turbulence sometimes (documented mapping is 25 kt +
  moderate); the spec table remains the control.

## How to verify everything from scratch

The NEXT.md block, plus this session's rows: pytest
tests/test_{llm_compiler,webapp,aero_channels}.py;
./scripts/mutation_check.sh (72 guards); FLIGHTSIM_LLM=ollama python
experiments/gate8_compiler.py (needs the ollama service; verdict is the
local model's). All green at `799e094` except the two user-blocked
items.
