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

## Addendum: second 2026-08-11 session -- terrain physics

User's complaint, verbatim shape: "it's not taking all mountain surfaces
and everything into physics consideration." Diagnosis confirmed two real
gaps: (1) JSBSim's ground model is one ray straight down from the CG, so
a banked wingtip could pass through a slope unfelt; (2) mountains only
shaped the air when a card happened to carry an orographic block, and
never shaped turbulence in webapp runs.

What shipped (see NEXT.md "Terrain physics" block for the operative
summary):

1. **core/terrain/contact.py** -- AirframeContact: four span stations
   (wingtips, mid-semi-span) from `metrics/bw-ft` (verified live against
   the pinned JSBSim's catalog, with attitude/{phi,theta,psi}-rad) rotated
   by the ZYX DCM's second column; a station below the raster ends the
   run. run_spec raises TerrainImpactError (and checks the trimmed t=0
   state BEFORE the first step -- gotcha 25); both UE hosts refuse via
   `AirframeImpact` (same stations, same math, source-pinned by
   tests/test_terrain_contact.py so the tables cannot drift apart).
2. **Wingspan-aware clearance planning** -- _fly_clearance_track's
   clearance_m is now min over stations (cg_clearance_m kept alongside);
   plan_terrain_flight's refusal message states the claim.
3. **Terrain-driven airflow** -- webapp terrain runs with wind carry
   lee-rotor turbulence (LeeRotorTurbulence as turbulence_provider, card
   word "lee-rotor", background = the spec's own word, seed derived even
   for word "none"); the pre-flight flies through the SAME OrographicWind
   the card records (_orographic_provider builds it from
   orographic_card_block's own numbers). Calm terrain runs carry neither;
   the conditions strip states why. VALIDITY 2.8 gained the
   wider-application note, 2.10 the contact-model limits paragraph.

Suite: 395 tests (was 376), 77 mutation guards (was 72). UE host
rebuilt clean. Valley-following flight remains the open feature thread.

### Conditions-effect report on the run page (same session, user request)

Every terrain-coupled run now ends with a "what the conditions did" section
under the clip: after the panel composites, the server flies the SAME spec
headlessly with the coupling severed (_effect_report in webapp/runs.py,
sampled on the run's own 0.1 s clock) and serves both series at
GET /runs/{id}/effect.json (404 until done; absent for uncoupled runs --
nothing approximated). The page (initEffectReport) draws tiles (vertical-air
range, n_z roughness x, alpha jitter x, altitude band) and three canvas
charts (vertical air, n_z, altitude), with the cross-host claim stated in
the formula line: baseline is the headless host, actual is the UE recording,
compared under the Gate 5 parity discipline; VALIDITY 2.8 applies. The
report step is optional -- a failure logs to the events feed and the clip
still delivers. Backfilled for c6ed0ac4c80a. A standalone A/B pair (UE
baseline render, fuller report.html) lives in runs/ab_terrain_air/.

### Phase 9.1 surface classes (same session; BRIEF_PHASE9 governs)

`environment.surface` spec field (SPEC_VERSION 1 -> 2; from_dict refuses
old dicts by design, recovery reads provenance.json). Classes in
core/environment/surface.py: grassland/desert/ocean/forest/city =
Davenport z0 (ROUGHNESS_M grew "smooth" 0.005 and "city" 2.0) + Allen
(w*, zi) from the TM's own Table 2 (desert = July directly; others
stated proxies; ocean = None). Wind composition: the log profile CARRIES
the base wind (card flag carries_base -> UE Step REPLACES instead of
adds; Phase 7 cards byte-identical). Flat-scene thermals declare their
CRS in the thermals block (spec origin's UTM zone; UE applies it only
when no terrain set one). Webapp: blocks on the card, surface line in
the conditions strip + aero panel, coupling_needs_seed() shared by /run
and the render flow (digest correctness), effect report covers surface
coupling with a widened claim. tests/test_surface.py (12) + 3 mutation
guards (80 total). Remaining Phase 9: 9.2 storm word, 9.3 tornado,
9.4 city geometry -- BRIEF_PHASE9.md has the settled designs.

### Phase 9 terrain + weather expansion (same session, continued)

* **Four new curated bakes** (all summit/datum identity-verified, values
  web-verified before entry): fuji (volcano cone, origin 1465 m),
  everest (extreme relief, origin 4720 m -- needed TWO fixes:
  a missing N28 tile whose absence merged zeros above 28 N and was
  caught by the mean gate, and a SLOPE-AWARE verification tolerance:
  per-sample allowance |grad h| x half-pixel, p95 of the EXCESS faces
  the same 30 m gate, flat ground unchanged -- p95_excess 12.1 m PASS),
  grand_canyon (canyon, three butte anchors), flint_hills (prairie,
  town-datum anchors ~10 m -- DSM sees rooftops).
* **On-demand GLO-30 baking**: dynamic_location() computes tiles/UTM/bbox
  for ANY coordinates; /run refuses "terrain.unbaked" for user-stated
  coordinates with no bake; the page POSTs /bake (sync fetch+verify,
  cached in runs/terrain/dynamic with .scene.json registry) and re-runs.
  Identity: source-verified only, labeled. LLM prompt: unknown places
  ask ONE question for coordinates, never invent them.
* **ERA5 historical weather** (SPEC_VERSION 3, environment.weather_date):
  an ISO date fetches that day's reanalysis mean wind (Open-Meteo
  archive, ERA5-derived, free, ~25 km hourly) at the nearest standard
  pressure level; applied as recorded pre-digest spec edits; stated
  wind always wins; control ridge refuses (not a place); offline
  refuses by name. NO gusts/turbulence claimed from reanalysis.
  User's plugin list adjudicated: ERA5 done, HRRR deferred, WRF and
  trueSKY refused, UE clouds/Niagara queued as labeled visual-only
  (task list).
* Guards now 85. Suite ~430 tests.

### Phase 9.2/9.3: storms + tornado (same session)

environment.weather_event (SPEC_VERSION 4): "thunderstorm" = documented
COMPOSITION (microburst 1000 m/12 m/s ahead on track + severe turbulence
when the word was defaulted -- never moves a stated word -- + storm
look); "tornado" = kinematic Rankine vortex (core/environment/tornado.py:
solid-body core/1-over-r exterior per Davies-Jones 1986, schematic core
updraft, EF2-band constants, linear fade 1500-3000 m AGL), C++ port
TornadoWindMps line-for-line, placed 45% ahead + 2.5 core radii abeam
(1.2 put the chase camera INSIDE the funnel mesh -- probe-measured grey
frames). Funnel = dark procedural tube, VISUAL marker labeled, no
collision. STORM_LOOK probe-calibrated (sun 10 / bias 9.6 / fog 0.007;
0.02 fog greyed out everything, 8.9 bias was night). Card scene_crs
declares the flat-scene frame for ALL position-coupled blocks. Headless
environment_for honours the event too (§1.6). Measured on camera + in
telemetry (run e81cea71ff89): c172p rolled -42.5..+29.2 deg, n_z
0.66-1.64 g, peak vortex wind 49.9 m/s, thrown +255 m in altitude.
Closure honestly fails under a held-state tornado (autopilot defeated).
tests/test_weather_events.py; 87 guards. Remaining: 9.4 city, clouds/
precipitation visuals (task 12), HRRR.

### "Through a tornado" (user request, same session)

"through/into a tornado" records aim=core in weather_event.detail
(digest-relevant); both hosts place the vortex axis ON the track (near =
2.5-radii abeam unchanged). A DEFAULTED altitude descends to 800 m via
plan_weather_event (the vortex fades out by the 3000 m default; stated
altitudes never move). Airspeed defaults are per-aircraft now
(CRUISE_DEFAULT_KT: the old universal 250 kt made a bare c172p prompt
refuse on trim). Core-aim runs render from the TOWER camera: the chase
camera sat inside the funnel and the blank-frame floor correctly refused
the run (c33db2c326e0) -- the floor was not weakened, the camera moved.
Measured core transit (run 1f7ae4097959): roll to -71.9 deg, 0.61-1.72 g,
heading spun 52+ deg off, CAS bled 7 kt in the core, 20 fps downdraft on
exit side. Funnel now renders genuinely tornado-like from the tower
(lit/shadow sides, sinuous taper).

### Pilot view (user request): shoulder camera fixed for small airframes

The CockpitShoulder offset was B747-scale and sat INSIDE the c172p's
fuselage (probe: overexposed paint). The render commandlet now scales it
by the model's own span (clamped 0.3-1.0 of B747 scale, Z floored at
1.3 m to clear small cabins) and logs the result. The through-the-core
shoulder render was REFUSED by the blank-frame floor over exactly ONE
frame (inside the funnel = honest darkness; floor not weakened); the
pilot-view deliverable is the abeam flyby, where the funnel crosses the
windscreen while the horizon rolls (roll-inheriting BY DECLARATION --
nothing from this camera may be graded as aircraft motion). Rendered
via -camera=shoulder on an existing card; not yet a webapp page option.

### Sharing & LLM tiers (2026-08-13 session close) -- RESUME HERE

* Repo is PUBLIC: github.com/DhruvaValluru/flightsim. History rewritten
  by Dhruva (sole author, no co-author trailers -- KEEP IT THAT WAY on
  every future commit; git config in-repo is his identity). Android
  file-server token scrubbed from HEAD before publishing (still in old
  history; negligible risk, offer full erase if asked).
* Quick start shipped: requirements.txt + scripts/setup.sh + README
  rewrite. Compiler TIERS in core/nl/providers.py resolve_client():
  llm7 (hosted, KEYLESS, verified live end to end -- the zero-setup
  fail-safe), ollama (local), groq/openrouter (free-key presets),
  openai (any compatible endpoint), Anthropic key. Tests pin the wiring.
* Dhruva has an OpenAI key with ~$35 credits (gpt-4.1-mini is the agreed
  cheap model, ~half a cent per compile). THE KEY IS NOT in the repo,
  not in ~/.flightsim.env yet (the write was interrupted), and MUST
  NEVER be committed (public repo -> auto-revocation + theft). He will
  paste it in-session when needed.
* DONE 2026-08-13 -- the Vercel relay (`1e62a4f`, `3c54e60`): relay/ in
  the repo, deployed at https://flightsim-relay.vercel.app (Vercel
  project flightsim-relay, key ONLY in the project's OPENAI_API_KEY env
  var), pins gpt-4.1-mini server-side (verified: a request naming gpt-4o
  was served by 4.1-mini), 40 req/hour/IP (in-memory limiter, per-
  instance scope stated in the code). FLIGHTSIM_LLM=relay preset in
  resolve_client() (FLIGHTSIM_RELAY_URL overrides), README tier entry,
  test pins the wiring. Two measured strict-mode fixes: OpenAI's
  json_schema strict:true 400s on RESPONSE_SCHEMA's optional fields, so
  the relay downgrades strict server-side AND OpenAICompatClient sends
  strict:false (the strict parser is the rail either way). His key is
  wired into ~/.flightsim.env (FLIGHTSIM_LLM=openai direct, gpt-4.1-mini;
  ollama + relay presets kept commented) -- verified live end to end on
  both paths. REMIND HIM: set a hard usage limit at
  platform.openai.com/settings if not already -- the relay's limiter is
  per-instance, not a billing guarantee.
  Still pending: camera picker on the web page, 9.4 city buildings,
  task 12 clouds/precipitation visuals, NOAA HRRR.
* Google Doc build report exists in his Drive ("FLIGHTSIM -- Complete
  Build Report").
