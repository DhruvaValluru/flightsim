# Resume here

## State

| Phase | Gate | Status |
|---|---|---|
| 0 core FDM | 0 | PASS 9/9 |
| 1 spec + NL | 1 | PASS 4/4 |
| 2 TECS + closure | 2 | PASS 4/4 |
| 3 environment | 3 | PASS 5/5 + convergence |
| 4 terrain | 4 | PASS 7/7 |
| 5 Unreal | 5 | **PASS 3/3 clauses, each measured** |
| 6 visual realism | 6 | **PASS 4/4 measured clauses + side-by-side produced** |
| 7 experiments/V&V | 7 | PASS 6/6 |

```bash
.venv/bin/pytest                  # 227 tests
./scripts/mutation_check.sh       # 41 guards, all load-bearing
./scripts/ue_preflight.sh         # should say "Preflight OK"
./scripts/build_ue.sh             # builds the UE host
```

Gate 5, end to end:

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

## The one thing to know about the toolchain

macOS 26 cannot *launch* Xcode 16.4's GUI, and that does not matter — UE invokes
`clang`/`xcodebuild`, which run fine. Xcode 16.4 lives at
`/Applications/Xcode_16.app`; the system default is still 26.6 and should stay
that way. Builds set `DEVELOPER_DIR`, so **no `sudo` and no `xcode-select`**.
Running either commandlet needs no Xcode at all.

## Where Gate 5 stands

**Trajectory parity.** B747, 3000 m, 250 kt CAS, 60 s, hands off from trim,
mass held:

| channel | max difference | tolerance |
|---|---|---|
| altitude | 3.6e-4 m | 5 m |
| true airspeed | 4.2e-5 kt | 2 kt |
| roll | 2.1e-8 deg | 1 |
| pitch | 1.1e-5 deg | 1 |
| heading | 7.9e-8 deg | 1 |
| load factor | 2.2e-7 | 0.05 |

Both hosts also trim to the same solution independently (throttle 0.579150 vs
0.579149769; pitch trim -0.276739 vs -0.27673930).

**On screen.** 110 frames at 5 Hz, 960x540, flying a scripted roll doublet:

* aircraft covers 2.77-3.79% of every frame
* max |camera roll| **0.000000 deg**
* 4 surfaces bound to geometry, 4 moved (ailerons 10.03 deg of travel each,
  elevator 5.55, rudder 1.07)
* apparent bank **measured from the pixels** tracks FDM roll at **r = 0.99923**,
  over -1.9..+17.0 deg against the FDM's -2.2..+16.8

The rendered aircraft is a **placeholder built from boxes**. That is the right
scope for Gate 5, which asks whether surfaces articulate and whether roll is
legible, and the wrong scope for Phase 6, which asks whether any of it looks
like anything. Do not let the frames be quoted as visual realism.

## Breadth behind Gate 5: envelope AND wind

`experiments/host_parity_matrix.py` runs the same comparison over three
airframes at four envelope points, plus two steady-wind cases per airframe
(25 kt crosswind, 15 kt quartering headwind). Not a gate; Gate 5's verdict is
unchanged.

| | |
|---|---|
| ran in both hosts | 16 of 18 |
| agree within the Gate 5 tolerances | 16 of 16 |
| worst channel anywhere | latitude at 16% of tolerance: a constant 1.24 m north phase = exactly one 1/120 s step (headless integrates one extra step during engine start) |

The two that never ran are 737 and B747 at 10000 m / 240 kt, refused by the
spec validator's stall-margin constraint. Gate 0 reaches those points by
building an FDM directly and never sees the validator. The fourth point
(8000 m / 280 kt) exists so the top of the envelope is not covered by one
airframe out of three.

Wind, and the three traps found wiring it (all mutation-guarded):

1. **The plugin's wind IC corrupts CAS** (250 in, 206 out of RunIC). The
   commandlet instead mirrors the headless sequence: calm RunIC, wind written
   to the FGWinds properties, re-trim via `simulation/do_simple_trim`, then
   the same NED properties re-written every step with the same float values.
2. **The trim snapshot is exempt from comparison, the flight is not.** The
   headless recorder force-samples before its environment loop applies wind
   (288 kt recorded, 301 kt one sample later in a 13 kt headwind). compare()
   starts at each host's second sample -- exactly one, guarded from both
   directions.
3. **Heading is compared on the circle.** Wind cases wander across north;
   unwrap before interpolation, difference with wrapping. lat/lon were added
   to the compared channels (1e-4 deg) because ground track is what catches a
   wind acting in one host only.

## A third upstream plugin bug

`GetAGLevel` builds the ground-query ray with its start in **centimetres** and
its end in **metres**, three lines apart. The intended ~319 km reach is cast as
319 km of centimetres, i.e. **3.19 km** — so above ~3.2 km AGL the trace hits
nothing, and JSBSim is silently told the aircraft is on the deck. At cruise
altitude. With no error.

Found by the commandlet's achieved-condition check: 3000 m answered correctly
(the short ray still reached), 6000 m reported height above terrain 0.0 m.
Patched, in `VENDORED.json`, re-applied by `vendor_ue_plugin.sh`, asserted by
`check_bridge_api.sh`.

## Gate 6: passed, criteria recovered

The brief's Phase 6 text was never in this repo; it was recovered verbatim
from the originating session transcript and recorded with provenance in
`docs/BRIEF_PHASE6.md`. `experiments/gate6_visual.py` runs the gate end to
end: bakes a ridge through the Phase 4 terrain pipeline (sha-verified into
the render manifest), renders six configurations, and measures the four
clauses from the PNGs. See `docs/VALIDITY.md` for the numbers and the honest
scope (box airframe, default terrain material, CSM not VSM, no MRQ).

The exposure clause carries its own negative control every run: the same
flight rendered with auto-exposure must trip the metric (34.4/255 vs the
manual run's 4.9) or the pass is void. §1.7's mutation-check discipline,
applied to a rendering measurement.

```bash
.venv/bin/python experiments/gate6_visual.py     # ~4 min, 6 renders
```

## Next task: Phase 6B — docs/BRIEF_PHASE6B.md

The owner authorized Phase 6B on 2026-08-06: real aircraft mesh, real Earth
terrain from named places (Matterhorn/Zermatt and Yosemite via Copernicus
GLO-30), turbulence in the UE host, and a rendered condition matrix.
**Execute it autonomously end to end — the brief says so explicitly; do not
stop for per-stage approvals.** Read docs/BRIEF_PHASE6B.md first; it carries
the full spec plus operational notes (render invocation gotchas, build
commands, verification loop).

## How the Unreal host is driven

`ue/Plugins/FlightSimBridge/.../FlightSimScenarioWorld.cpp` builds the world;
two commandlets fly it.

* `FlightSimScenarioCommandlet` — no renderer, writes telemetry.
* `FlightSimRenderCommandlet` — renderer up, writes frames plus `render.json`.

They share `FFlightSimScenarioWorld` so they cannot put the aircraft in
different places.

Six things in there are not obvious and are all load-bearing:

1. **A ground slab is spawned.** The plugin answers JSBSim's ground queries with
   a line trace against world geometry. With nothing to hit it returns height
   above terrain 0.0 at any altitude, which puts a cruising aircraft's gear in
   permanent contact.
2. **The aircraft is placed by its centre of gravity**, not its origin —
   `PrepareJSBSim` derives the initial condition from where the CG ends up.
3. **Actor yaw is heading minus 90**, because the plugin adds 90 back.
4. **`LatchTrimmedControls` copies the trimmed FDM state into the plugin's
   command struct.** The plugin re-sends that struct every tick, and after trim
   it still holds throttle 0.0 — so without this the first tick silently
   commands the engines to idle.
5. **The render commandlet needs `-AllowCommandletRendering`.** Commandlets come
   up with a null RHI otherwise, and every capture writes a blank frame while
   reporting success. `-RenderOffScreen` is the other half; it is the opposite
   of `-nullrhi`, not a synonym.
6. **Two warm-up captures are discarded, and the camera is aimed before the
   first one.** A `USceneCaptureComponent2D` resolves nothing on its first
   calls, and its transform reaches the render thread a frame late, so an
   un-aimed camera puts empty sky at t=0.

`scripts/check_bridge_api.sh` asserts the upstream behaviours behind 1-4 and the
ground-ray patch, so a re-vendor at a different plugin version cannot leave the
compensation in place and wrong.

Running either commandlet appends an `AndroidFileServerRuntimeSettings` block,
with a machine-generated security token, to `ue/Config/DefaultEngine.ini`. That
is an unrelated editor plugin writing its defaults; discard it
(`git checkout ue/Config/DefaultEngine.ini`) rather than committing the token.
The fixed-tick settings at the top of that file are load-bearing and must stay.

## Three upstream plugin bugs, patched and recorded

All in `ue/Plugins/JSBSimFlightDynamicsModel/VENDORED.json`. Re-running
`scripts/vendor_ue_plugin.sh` re-applies them.

1. `Build.cs` staged `Resources/JSBSim` through a Windows path literal, so the
   aircraft data was silently not staged on macOS/Linux.
2. `JSBSimMovementComponent.cpp` used `FGPropertyNode*`, absent from JSBSim
   1.2.4. `GetNode()` returns `SGPropertyNode*`. Without this the plugin does
   not compile at all on Unix.
3. `GetAGLevel` cast the ground-query ray in metres from a centimetre origin,
   so it reached 3.19 km instead of 319 km and every cruise scenario was told
   it was on the deck. See above.

## Do not regress these

* The on-screen clauses are decided **by reading the PNGs**, never by reading
  what the engine said about them. §1.5's failure was a clip whose telemetry was
  entirely correct and whose pixels showed nothing.
* Surface deflection is read **off the scene component's transform**, not
  recomputed from the JSBSim property. `UFlightSimSurfaceAnimator` originally
  computed deflections and rotated nothing; a check that recomputed the property
  would have passed it.
* The parity comparison is on the **recorded clock**, never the sample index.
  The two recorders' actual periods differ by 7% (~0.1075 s headless against
  0.1 s in UE), which is four seconds of skew by the end of a 60 s run.
* The parity spec is **open loop in both hosts** (`hold_state` false), and the
  render spec is a **different** scenario — it carries a roll doublet, and the
  telemetry commandlet refuses a card with control inputs so the two cannot be
  confused.
* The commandlets **refuse** turbulence, a non-calibrated airspeed, a held
  state, and fractional wind directions rather than approximating them.
  Steady whole-degree wind is implemented; nothing else environmental is.
* `docs/JSBSIM_CORRECTIONS.md` — 13 measured JSBSim behaviours that fail
  silently. Read before writing new property code.
* `docs/VALIDITY.md` — what may and may not be claimed. Validation is mostly
  INCONCLUSIVE and that is the finding, not a gap to paper over.
* Every guard has a mutation-checked test. Add to `scripts/mutation_check.sh`
  when adding a guard.
