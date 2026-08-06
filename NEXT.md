# Resume here

## State

| Phase | Gate | Status |
|---|---|---|
| 0 core FDM | 0 | PASS 9/9 |
| 1 spec + NL | 1 | PASS 4/4 |
| 2 TECS + closure | 2 | PASS 4/4 |
| 3 environment | 3 | PASS 5/5 + convergence |
| 4 terrain | 4 | PASS 7/7 |
| 5 Unreal | 5 | **builds, gate NOT passed** |
| 6 visual realism | 6 | not started |
| 7 experiments/V&V | 7 | PASS 6/6 |

```bash
.venv/bin/pytest                  # full suite
./scripts/mutation_check.sh       # 22 guards, all load-bearing
./scripts/ue_preflight.sh         # should say "Preflight OK"
./scripts/build_ue.sh             # builds the UE host
```

## The one thing to know about the toolchain

macOS 26 cannot *launch* Xcode 16.4's GUI, and that does not matter — UE invokes
`clang`/`xcodebuild`, which run fine. Xcode 16.4 lives at
`/Applications/Xcode_16.app`; the system default is still 26.6 and should stay
that way. Builds set `DEVELOPER_DIR`, so **no `sudo` and no `xcode-select`**.

## Next task: Gate 5

Gate 5 needs a trajectory out of the UE host to compare against the headless
reference. Everything else for it exists.

* `experiments/gate5_ue_parity.py` already writes the headless reference and
  compares; run it with `--unreal-telemetry <file>`. It exits **2 = BLOCKED**
  when there is no UE trajectory, and must never report PASS on half the
  evidence.
* `UFlightSimTelemetryRecorder` (compiled) writes the shared schema — column
  names match `core/telemetry/recorder.py` exactly. That matching is what makes
  the comparison possible; do not let them drift.
* What is missing: a way to drive a scenario headlessly in-engine. A commandlet
  that builds a minimal world, spawns an actor with `UJSBSimMovementComponent`,
  applies the spec's initial conditions, steps at fixed rate, and calls
  `WriteToDisk()`. `Config/DefaultEngine.ini` already pins a 120 Hz fixed tick.
* Tolerances are declared in `TOLERANCE` in the gate. Both hosts run the *same
  JSBSim commit*, so a divergence is the integration (substep accumulator, ECEF
  round trip), not the physics.

## Two upstream plugin bugs, patched and recorded

Both in `ue/Plugins/JSBSimFlightDynamicsModel/VENDORED.json`. Re-running
`scripts/vendor_ue_plugin.sh` re-applies them.

1. `Build.cs` staged `Resources/JSBSim` through a Windows path literal, so the
   aircraft data was silently not staged on macOS/Linux.
2. `JSBSimMovementComponent.cpp` used `FGPropertyNode*`, absent from JSBSim
   1.2.4. `GetNode()` returns `SGPropertyNode*`. Without this the plugin does
   not compile at all on Unix.

## Do not regress these

* Bridge C++ compiled once, cleanly. It is *not* exercised — nothing has run it.
* `docs/JSBSIM_CORRECTIONS.md` — 13 measured JSBSim behaviours that fail
  silently. Read before writing new property code.
* `docs/VALIDITY.md` — what may and may not be claimed. Validation is mostly
  INCONCLUSIVE and that is the finding, not a gap to paper over.
* Every guard has a mutation-checked test. Add to `scripts/mutation_check.sh`
  when adding a guard.
