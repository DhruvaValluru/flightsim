# flightsim

A research-grade flight simulation system: defensible physics data and credible
visual output, driven by natural language through a validated, reproducible
scenario spec.

**Status: Phases 0-7 — every gate passes.** Gate 5 measured across both hosts
(trajectory parity to 1e-4 of tolerance, on-screen clauses read back from the
pixels), Gate 6 on its four measurable clauses with a placeholder airframe. See
[docs/VALIDITY.md](docs/VALIDITY.md) for exactly what that does and does not
support — the scope statements are the point of this project.

## Quick start (any machine, ~2 minutes)

```bash
git clone https://github.com/DhruvaValluru/flightsim.git
cd flightsim
./scripts/setup.sh
.venv/bin/uvicorn webapp.server:app --port 8008
```

Open http://127.0.0.1:8008, type a scenario ("fly the c172p through a
tornado over the prairie"), review the compiled spec, and run. **No API
keys or accounts are needed for anything**: terrain elevation comes from
the public Copernicus bucket, historical weather from the free Open-Meteo
API, and the natural-language compiler **works out of the box** -- with
nothing configured, prompts compile through [relay/](relay/), a small
Vercel function holding the author's own OpenAI key server-side, pinned
to `gpt-4.1-mini`, rate-limited to 40 requests/hour per IP. Best-effort
on a personal budget; if it refuses or dies, the deterministic parser
below catches the prompt and every other tier is one env var away:

* **No AI (`FLIGHTSIM_LLM=none` in `~/.flightsim.env`):** the built-in
  deterministic parser covers the whole documented vocabulary (aircraft,
  altitudes, winds, turbulence, surfaces, storms, tornadoes, dates).
  Only place *names* need AI -- state coordinates instead
  ("at 27.99, 86.92"). This parser is also the automatic fallback
  whenever any LLM tier fails.
* **Free local model (one-time download):** `brew install ollama`, then
  `ollama pull qwen2.5:7b` (~4.7 GB) or `qwen2.5:14b` (~9 GB, better);
  set `FLIGHTSIM_LLM=ollama` in `~/.flightsim.env`. Runs fully offline
  afterwards; ~16 GB RAM recommended for the 14b.
* **Keyless hosted model (no download, no account, nothing):** set
  `FLIGHTSIM_LLM=llm7` in `~/.flightsim.env` -- llm7.io serves free
  OpenAI-compatible models anonymously. Rate-limited and best-effort (an
  anonymous service can change); the tiers below are sturdier.
* **Free hosted model (no download, 2-minute signup):** make a free
  account at console.groq.com (no credit card), create an API key, then
  set `FLIGHTSIM_LLM=groq` and `GROQ_API_KEY=...` in `~/.flightsim.env`.
  (`FLIGHTSIM_LLM=openrouter` + `OPENROUTER_API_KEY` works the same via
  openrouter.ai's free models.)
* **Anthropic API key (no download, paid):** set `ANTHROPIC_API_KEY`
  and the app uses it automatically.

The page states which tier is active next to the Interpret button.

## Platform support

One codebase, platform dispatch inside it (`core/util/platform.py`):

| | macOS | Linux | Windows |
|---|---|---|---|
| Prompt → LLM compile → spec → validate | ✓ | ✓ | ✓ |
| Headless JSBSim physics + telemetry | ✓ | ✓ | ✓ |
| Web app on localhost:8008, terrain baking, effect reports | ✓ | ✓ | ✓ |
| Rendered frames and clips (Unreal Engine host) | ✓ after the build below | refused by name | ✓ after the build below |

Everything in the first three rows is pure Python and is exercised by CI
on all three OSes. The UE render half runs on macOS (where every render
calibration was measured, on Metal) and on Windows, on each once the
engine is installed at `UE_ROOT` (default `/Users/Shared/Epic Games/UE_5.5`
or `C:\Program Files\Epic Games\UE_5.5`) AND the build steps below have
produced the bridge -- until then BOTH refuse as `ue.platform` with the
exact missing piece ("no engine on this machine: set UE_ROOT ..." or
"FlightSimBridge not built: run scripts/ue_preflight.sh then
scripts/build_ue.sh"), the run form's engine options are disabled with
that reason and its default is Headless, and the web app still delivers
the headless half (spec, provenance, validation, telemetry, the capture
manifest, full-resolution geometry previews with a contact sheet per
camera, and verification).
The render calibrations were measured on Metal only, so on Windows run
`experiments/gate6_visual.py` once after building: it re-measures the
visual clauses from the rendered pixels on YOUR machine, which is the
project's standard of evidence -- a green Gate 6 there is the Windows
render claim. Linux remains headless-only.

Per-OS setup notes:

* **macOS / Linux**: `./scripts/setup.sh`. **Windows**:
  `.\scripts\setup.ps1` (PowerShell), then
  `.\.venv\Scripts\python.exe -m uvicorn webapp.server:app --port 8008`.
  Or deploy with one pasted command -- no clone, no prerequisites
  (installs git/Python via winget only if missing, clones, sets up,
  starts the server and opens the browser):

  ```powershell
  irm https://raw.githubusercontent.com/DhruvaValluru/flightsim/master/scripts/deploy_windows.ps1 | iex
  ```

  Windows note: install Python 3.10-3.12, not 3.13+ -- `numpy==2.0.2`
  ships no Windows wheel past 3.12, and both setup scripts check this.
* **ffmpeg** (only for encoding clips/panels): `brew install ffmpeg` /
  `sudo apt install ffmpeg` / `winget install ffmpeg`. Missing ffmpeg is
  a named refusal (`ffmpeg.missing`); nothing else needs it. Override
  the binary with `FLIGHTSIM_FFMPEG=/path/to/ffmpeg`.
* **Ollama** (the free local LLM tier): `brew install ollama` on macOS;
  the installer from ollama.com on Linux/Windows.
* **Env config**: `~/.flightsim.env` is a POSIX convention sourced by
  whatever shell launches uvicorn. On Windows, set the same variables
  for the server process instead (`$env:FLIGHTSIM_LLM = "relay"` in the
  PowerShell session that starts uvicorn, or System Properties).
* The `FLIGHTSIM_LLM=relay` default and the keyless `llm7` tier need
  ZERO setup on any OS: a fresh clone compiles a prompt before
  installing anything optional.

**Rendering video clips** needs Unreal Engine 5.5 (free from the Epic
Games Launcher) plus the platform toolchain:

* **macOS** (Xcode 15.2-16.9):
  `./scripts/vendor_ue_plugin.sh && ./scripts/build_ue.sh`
* **Windows** (Visual Studio 2022 with the C++ workload):
  `.\scripts\vendor_ue_plugin.ps1` builds the Win64 JSBSim library with
  upstream's own `JSBSimForUnreal.sln` (the patched plugin sources are
  already committed), then `.\scripts\build_ue.ps1` builds the host.
  `.\scripts\ue_preflight.ps1` diagnoses exactly what is missing at any
  point, and `experiments\gate6_visual.py` validates the render output
  on your machine afterwards.

Then two asset steps, either OS -- **optional since 2026-09-01**: a
render provisions whatever it needs itself, in the open, so these are
for priming a machine ahead of time rather than prerequisites.

* **Real terrain**: `python scripts/bake_terrain.py` bakes the showcase
  terrains (Matterhorn, Yosemite, the synthesised control ridge) into
  `runs/terrain/`; `--all` bakes every curated location. Renders also
  carry a fail-safe: a scene the SYSTEM chose never falls back to the
  featureless slab -- the control ridge is synthesised on first need --
  while a user-stated flat place stays honestly flat.
* **Real aircraft**: `python scripts/import_aircraft.py` fetches each
  configured model at its pinned commit (license verified on disk),
  converts it, and imports it into the Unreal project. Renders carry
  the same fail-safe the terrain does: the first run that needs a model
  this machine can build **builds it then and there**, with a status
  line per step (user request 2026-09-01 -- a missing mesh is not the
  user's chore). Placeholder airframes still never render on ANY
  machine (owner's rule, extended 2026-08-31), so two things still
  refuse by name before any editor time and no automation reaches
  around them: an airframe with **no model config** (nothing to fetch),
  and one whose **upstream ships no license file** (section 3.3 -- the
  p51d today, physics-only until upstream publishes one). A build that
  starts and fails fails the run by name (`aircraft.mesh_import`); it
  never falls through to blocks.

Materials come from `scripts/ue_create_materials.py` (run inside
UnrealEditor-Cmd; `ue_preflight` names the exact invocation when they
are missing). Read `NEXT.md` for operational state and the 26 recorded
gotchas before deep work.

`rasterio` ships GDAL in its wheel, so no separate GDAL build is needed.

## Run the gates

```bash
.venv/bin/python experiments/gate0_trim_hold.py
```

```bash
.venv/bin/python experiments/gate1_spec.py
```

```bash
.venv/bin/python experiments/gate2_control.py
```

```bash
.venv/bin/python experiments/gate3_null_tests.py
```

```bash
.venv/bin/python experiments/gate4_terrain.py
```

```bash
.venv/bin/python experiments/gate7_sweep.py
```

```bash
.venv/bin/python experiments/gate6_visual.py
```

Gate 6 renders the §6.6 scene offscreen and measures its four clauses from the
PNGs — extinction, valley shadows, the aircraft's ground shadow, and manual
exposure (validated against an auto-exposure negative control every run). The
criteria are quoted verbatim, with provenance, in `docs/BRIEF_PHASE6.md`.

Gate 5 needs the Unreal host. Check whether this machine can build it, build it,
then fly the same spec in both hosts and compare:

```bash
./scripts/ue_preflight.sh
```

```bash
./scripts/build_ue.sh
```

```bash
.venv/bin/python experiments/gate5_ue_parity.py
```

```bash
./scripts/run_ue_scenario.sh runs/gate5/ue_scenario.json runs/gate5/unreal.json
```

```bash
./scripts/render_ue_scenario.sh runs/gate5/ue_render_scenario.json runs/gate5/frames
```

```bash
.venv/bin/python experiments/gate5_ue_parity.py --unreal-telemetry runs/gate5/unreal.json --unreal-render runs/gate5/frames/render.json
```

All three of its clauses pass, each measured — trajectory parity from the two
telemetry files, and the two on-screen clauses by reading the rendered PNGs
back. The rendered aircraft is a placeholder built from boxes; visual realism is
Phase 6. See `docs/VALIDITY.md`.

The same comparison across three airframes and four envelope points — not a
gate, the breadth behind Gate 5's single case:

```bash
.venv/bin/python experiments/host_parity_matrix.py
```

## Capture camera geometry (Camera Phase 1, any platform)

Cameras are spec elements (provenanced, validated, digest-relevant --
see `docs/CAMERA_PHASE1_REPORT.md`). A run captures a DEFINED number of
frames, each with full recoverable geometry, engine or no engine:

```bash
.venv/bin/python -m flightsim.capture examples/cameras_multi.yaml --out runs/demo
.venv/bin/python -m flightsim.verify runs/demo
```

Off macOS the pixel render refuses by name (`ue.platform`) while the
capture manifest, geometry previews (full resolution: terrain wireframe
or ground grid with distance rings, horizon, the aircraft as a body
scaled from the FDM's own span, the camera's boresight and field of
view, a header with pose and lens; `contact_sheets/<camera>.png` per
camera; measured 0.049 s/frame) and verification complete; the
refusal example (`examples/cameras_refusal.yaml`) shows a camera placed
inside terrain refused as `camera.terrain_clearance`.

With the engine (`--render frames`, the default where it exists) the
same command renders exactly the scheduled PNGs per camera under
`frames/<camera_id>/NNNN.png` -- one consume-poses pass per camera --
and the verifier's `engine_parity` check grades every frame's applied
pose against the solved one, and `overlays/<camera_id>/NNNN.png` draws
the manifest's aircraft box, ground and horizon over every rendered
frame so the check is visible; the clip is a by-product of camera 0.
Without the engine that check reads `[AWAITING] engine_parity`, never
a pass. The Windows verification steps, exact commands and expected
log lines are in `docs/CAMERA_PHASE1_REPORT.md` ("Engine verification
(Windows)"), marked NOT YET RUN until measured there.

**The same thing from the web app**, with nothing to download by hand:
the run form carries the render choice -- **Render frames and clip**
(engine, one pass per camera, the frame set is the deliverable),
**Clip only** (today's clip, capture geometry beside it, nothing
rendered as frames) or **Headless** (manifest, previews, verification;
no engine, any machine) -- defaulting to the richest the machine
supports, with unavailable options disabled and the reason shown; the
choice is recorded in the run's provenance and the status line names
what was produced. The page then lists every artefact the run wrote
(rendered frames per camera, manifest, verification, previews,
telemetry, card, provenance, the spec as run) as links, with a
one-click `bundle.zip` for all of them, and shows per camera "N
scheduled, M rendered, K verified" and the verifier's own checks. The
capture is solved from its own headless flight and written under
`capture/` beside that flight's telemetry, so a reader can always tell
which host produced which number -- the run's top-level
`telemetry.json` stays the rendered flight's.

## Airborne physics, phase 2

`docs/AIRBORNE_PHASE2_REPORT.md` is the report: the aircraft is trimmed
in the spec's wind on both hosts, the control-sign probe and the
performance model are measured at the engaging state, the TECS throttle
loop is normalised by the measured thrust-to-weight authority, the
altitude setpoint is raised ahead of terrain (or the run refuses
`terrain.lookahead`), the lee rotor carries its word only when the FDM
delivered turbulence, turns are coordinated from a measured sideslip
gain, and every run's closure report reaches the page. Each number in
the report reproduces from a script under `experiments/airborne/`.

## Run the tests

```bash
.venv/bin/pytest
```

Every guard has a regression test, and the tests are checked against removal of
the guard they cover:

```bash
./scripts/mutation_check.sh
```

## Layout

```
core/            zero Unreal dependency (§2.9)
  fdm/           JSBSim wrapper, trim, checked property I/O, read-only state
  environment/   wind, boundary layer, turbulence, gusts, orographic lift
  control/       TECS as a JSBSim XML system, run at FDM rate
  scenario/      spec schema, validation, provenance, run harness
  nl/            prompt -> spec compiler. Emits a spec, never runs anything.
  capture/       camera pose solver, capture scheduler, manifest, verifier
  telemetry/     read-only observers
  terrain/       DEM ingestion, spectral synthesis, heightfield query, Landscape export
experiments/     gates, sweeps, analysis, validation
  airborne/      the phase-2 reconstruction measurements (every report number)
analysis/        flight-dynamics audit, research ledger, the executed brief
docs/vva/        V&V plan, report, accreditation statement
ue/              Unreal project                    (Phase 5)
docs/            VALIDITY.md, JSBSIM_CORRECTIONS.md, vva/
tests/
```

## The architectural guards already in place

The previous build of this project failed by reporting success while being
wrong. These exist to make the specific mechanisms impossible:

| Guard | Prevents | Where |
|---|---|---|
| Catalog-checked property access | A misspelled property that writes successfully and does nothing | `core/fdm/properties.py` |
| Aircraft resolution + post-load verification | Running F-16 aerodynamics under an F-15 mesh | `core/fdm/aircraft.py` |
| Ordered ICs + post-condition check | Commanding 233 kt and starting at 201 kt | `core/fdm/fdm.py` |
| Trim failure is a hard error; engines verified by spool | Recording an initialisation transient, or trimming an unpowered glider | `core/fdm/trim.py`, `core/fdm/fdm.py` |
| Validation before execution, constraints named | Rendering a plausible video of a scenario that cannot be flown | `core/scenario/validate.py` |
| Unimplemented conditions are fatal | A spec that asks for turbulence running in smooth air | `core/scenario/runner.py` |

Every guard has a regression test, and every test has been **mutation-checked**:
the guard was disabled in turn to confirm the test actually fails. A suite that
passes while the system is broken is the failure of §1.7, and a green run is not
by itself evidence.

## Documented deviations from the brief

* **Gate 0 asserts on a mass-held run**, not the literal fuel-burning one, and
  publishes both numbers. A fuel-burning aircraft has no equilibrium; asserting
  on it would mean a tolerance loose enough to hide a real trim defect.
  Rationale and measurements in [docs/VALIDITY.md](docs/VALIDITY.md) §2.3.
* **The divergence window is 3 phugoid periods, not 60 s.** 60 s is shorter than
  one phugoid period at these speeds, so a "growing oscillation" test over it
  measures the first quarter-cycle rising rather than divergence. The literal
  60 s figures are still reported.
* **Six §6 reference items are wrong** in ways that silently produce bad runs,
  and two remain unverified. See
  [docs/JSBSIM_CORRECTIONS.md](docs/JSBSIM_CORRECTIONS.md).

## Environment hazard

macOS system Python caches bytecode **outside the repo**, at
`~/Library/Caches/com.apple.python/<abs-path>`, so `find . -name __pycache__`
purges nothing. A restored source file was once shadowed here by bytecode
compiled from a mutated version, making a correct fix look broken.
`scripts/mutation_check.sh` purges both locations; be aware of it when a change
appears to have no effect.
