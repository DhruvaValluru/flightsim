# Phase 7 session context — everything that happened, for a fresh session

Written 2026-08-08 at the end of the Phase 7 run (commits `468c032..1c4e84e`,
21 commits). Read this WITH `NEXT.md` (operative resume state + gotchas),
`docs/BRIEF_PHASE7.md` (the brief that was executed), `docs/VALIDITY.md`
(what may be claimed) and `docs/JSBSIM_CORRECTIONS.md` (§13 is new). This
file is the session narrative: what was done in what order, what broke, what
was measured, and why each decision went the way it did.

## Final state in one paragraph

Phase 7 delivered end to end: Sentinel-2 imagery draped and verified on
geometry, heightfield collision with measured AGL parity between hosts,
lee-rotor turbulence built on a measured JSBSim contract (§13), three new
environment providers ported to the UE host with exact cross-checks, the
complete evolving-conditions schedule machinery and its verified 150 s
clip, the A320 airframe (DHC6/p51d refused over licensing), the Zermatt
scripted valley run with camera presets, a spinning propeller, and the
same-seed-parity question closed as permanently visual-only. The 144-cell
showcase matrix finished at 139 clips + 5 recorded refusals. Suite: 307
tests, 62 mutation guards all verified load-bearing, every gate green.

## Session timeline (what happened, in order)

1. **Step 0 discovery.** `showcase_manifest.json` listed 1 clip but 70 mp4s
   existed. A PRE-EXISTING matrix process (started 13:51 the previous day)
   was found still running and HUNG: its editor had burned ~6 h at 99% CPU
   on `c172p_matterhorn_gusty15_clear_noon` with 0 frames after a "Trim
   Failed!!!" and a shutdown ensure. A duplicate matrix I started was
   killed; the stale one was later killed too.
2. **Tier 1.3 measure-first** (while the matrix ran): wrote
   `experiments/turb_perstep_measure.py`. Results became
   **JSBSIM_CORRECTIONS §13**: rewriting severity/W20 per step with
   unchanged values is a bit-exact no-op; the W20 route below 300 m AGL is
   sane for steps AND continuous ramps (sigma tracks 0.107·W20(t)); the
   POE route is NOT (nonzero→nonzero severity changes overshoot sigma_w
   2–5× with ~20–40 s settle; fractional severity floors; severity 0 is a
   master off-switch that silences the W20 route too — pin severity to a
   nonzero constant, 1.0).
3. **Lee-rotor provider** (`core/environment/rotor.py`): W20-only coupling
   to `OrographicWind.lee_sink`, severity pinned 1.0, seed once, W20 capped
   at "severe", validity below 300 m AGL stated (above: the constant POE
   index-1 floor). Stack gained a `step_writes` hook (W20 only, ever).
   Null test: single Gaussian ridge (a periodic ridge makes "windward"
   ambiguous — every point is in some crest's lee), lee track 0.93 fps
   turb RMS vs windward exactly 0.
4. **Tier 1.1 Python side** (`core/terrain/imagery.py`): EOX Sentinel-2
   cloudless **2016** — verified CC-BY-SA 4.0 from EOX's release
   announcement; the year-suffixed layers are CC-BY-NC-SA and are refused
   (mutation-guarded). WMTS WGS84 z13 (~native 10 m), mosaic → warp onto a
   texel grid sharing the bake's CRS/origin/extent (10 m = 30 m/3, exact
   by construction). verify_drape: 400 texels round-tripped to source —
   Matterhorn mean 2.5 / p95 9.3 counts, Yosemite 3.2 / 11.3. Snow
   cross-check: brightness 194 above the 3100 m snowline vs 96 below.
5. **Tier 2.1** log-profile wind (`LogProfileWind`, Stull 1988 §9.7 +
   Table 9-6 z0), held at the 300 m surface-layer top, log-linearity shape
   test, FDM null, microburst composition test.
6. **Tier 2.2** Allen thermals (`core/environment/thermals.py`): NASA/TM-
   2006-214019 eqs 11–23 implemented FROM THE PAPER'S APPENDIX B CODE
   (fetched the TM PDF; its Table 3 "k4" column disagrees with the code's —
   the code produced the paper's check case, so the code wins, discrepancy
   recorded). Suite pins the paper's own worked example (r2 79.4 m, five
   updrafts, centre 2.7 m/s, sink −0.128). En route: **c172p headless
   engine start** solved (mixture rich + magnetos both + starter + crank
   past 500 rpm; later: mixture sweep because full rich doesn't fire at
   altitude); the c172p null test flies through a planted column (+7.5 m
   alt, +0.77 m/s climb; column placed EARLY on the track because the
   hands-off c172p spirals slowly left under torque and misses a far one).
7. **THE BIG BUG (matrix root cause).** All windy c172p Matterhorn cells
   were failing UE trim; the 4 "successful" calm clips also had 2 trim
   failures each in their logs — they had VERIFIED an untrimmed state
   (VerifyTrimmedCondition checks state, not equilibrium) and flown as
   gliders. Root cause measured stepwise: the plugin's
   `bStartWithEngineRunning` hardcodes **Mixture = 1.0** and a
   force-started (`InitRunning`) piston at 3600 m dies from 2799 rpm to 0
   in seconds; trim then fails (or the IC state verifies). Headless repro
   confirmed; leaning to 0.8 immediately fixes trim (calm AND wind).
   Fix: **vendored plugin patch #4** (`InitialMixture` property, written to
   the FCS BEFORE the BeginPlay trim — EngineCommands alone applies too
   late), card field `engine_mixture`, recorded in VENDORED.json,
   re-applied by vendor_ue_plugin.sh, asserted by check_bridge_api.sh.
   Probe: the exact failing cell trims clean (3600.000 m/100.000 kt/236°).
   4 glider clips deleted; matrix restarted.
8. **Mixture discovery hardened** after a second stall: at 2600 m
   (Yosemite band) full rich CATCHES on the starter and then dies — the
   crank-based discovery returned 1.0 and four MORE glider clips rendered
   before the watchdog caught the next trim failure. The discovery now
   sweeps the UE host's EXACT sequence (RunIC + InitRunning + mixture into
   FCS + tFull trim + 5 s sustain) and refuses if nothing passes. c172p:
   0.85 across 2600–3600 m. Those 4 clips deleted + re-rendered. The
   crank-start path measured separately: with starter assist full rich
   stabilises at a sick ~500 rpm idle, so only the DISCOVERY's
   trim-refusal discriminates (this is why its mutation guard targets the
   trim refusal, not the crank threshold).
9. **UE C++ batch** (written while the matrix rendered, built after):
   `FlightSimDownburst` (line-for-line port), rotor W20 per-step writes,
   log-profile + thermals ports in `FFlightSimScenarioWorld` (all four
   selftest-gridded into the manifest), heightfield collision
   (`collision_terrain` card field, full 30 m grid, slab replaced,
   VerifyTrimmedCondition re-aimed at the raster under the aircraft),
   imagery drape loading (`-imagery=<sidecar>`, runtime PNG →
   `M_TerrainImagery` MID; refuses rather than falling back), the COMPLETE
   schedule machinery (`turbulence_schedule` times+W20-fps only,
   `orographic_follow_schedule`, sun animation via
   `-sun-elev-end/-sun-azim-end`), camera presets
   (`-camera=chase|wingman|tower|shoulder`; CockpitShoulder is the ONE
   declared roll-inheriting preset; manifests record `camera_preset` +
   `camera_inherits_roll`), continuous animator bindings (propeller: rpm ×
   6 deg/s integrated, wrapped, excluded from the peak-deflection clause),
   `agl_m` added to both telemetry recorders.
10. **Python providers gained `card_block()`s** (downburst/rotor/
    log_profile/thermals) and `ScheduledDrydenTurbulence`
    (+ `card_word` — see gotcha 14). `write_run_card` grew the matching
    optional args. Matrix microburst cells switched to the position-coupled
    downburst block (test updated to verify the same staging through the
    block's own field).
11. **Airframes**: cloned FGMEMBERS A320family/p51d/dhc6 pinned. Fixed
    three real .ac parser bugs (a material NAMED "trans"; CRLF byte counts
    in data blocks; doubled "kids 0" terminators + overdeclared child
    counts in the p51d). Built `assets_pipeline/estimate_hinges.py`
    (per-span-slice leading edges — a global forward band collapses on
    swept wings, measured). **A320 delivered** (explicit GPL-2.0 LICENSE;
    parts assembled with offsets transcribed from the model's own XML;
    engines/gear placed). **DHC6 + p51d REFUSED**: no license file in
    mirror or upstream, FGAddon's GPLv2+ policy is a submission
    recommendation not a per-aircraft grant, converter refusal not
    weakened; configs committed ready (VALIDITY 1.6a2).
12. **Matrix completion**: 139/144. Five recorded refusals: 4× B747
    microburst (no 300 m AGL track clears the real mountains — clearance
    scan's own refusal, best −131 m Matterhorn / −203 m Yosemite) and 1×
    `c172p_yosemite_storm25_clear_dawn` (35/660 frames legitimately below
    the blank-frame floor in deep dawn shadow — frames inspected by eye;
    the check cannot distinguish that from a missing world and was NOT
    weakened; hazy_noon sibling exists).
13. **Post-matrix verification wave** (each with its own measured fix):
    - `gate5_realmesh`: B747 r=0.99918, c172p r=0.99999 with the propeller
      spinning 318°, A320 r=0.99990 (chase re-framed −110 m after 0.45%
      coverage measured under the 0.5% floor). ALL PASS.
    - `environment_ue`: downburst port **0.0**, rotor 1.42e-14, log-profile
      **0.0**, thermals 4.6e-10; null evidence for each vs severed
      controls (26 fps outflow / 0.200 fps turb RMS / 56.6 fps wind RMS,
      controls 0). Fixes en route: a "§" in a manifest string made
      `SaveStringToFile` emit UTF-16 (gotcha 13); the card's `turbulence`
      WORD gates the writes — a rotor card labeled "none" flew still air
      writing W20 into a process never switched on (gotcha 14 →
      `card_word`); control cards must reset the word; low-Yosemite scenes
      need showcase noon light.
    - `agl_parity`: **PASS** — |ΔAGL| p50 1.30 / p95 4.77 / max 6.46 m
      over 1415 m of relief (bars 8/20 stated first). Slab label off
      per-card; VALIDITY updated.
    - `imagery_drape`: **PASS** — after fixing a real landmark bug (the
      georef peak was projected BEFORE the terrain build aligned the CRS;
      calm cards projected it through the DEFAULT CRS, tens of km wrong —
      gotcha 15). The bake's peak is Monte Rosa (Dufourspitze 45.9426,
      7.8697), not the Matterhorn; the scene heads at its measured
      bearing 122°. Verdict: summit texel 2.38× texture median, rendered
      summit 1.70× frame median, A/B vs classification 22.2 over the
      terrain half (at the summit alone both surfaces are snow-white —
      4.1 — so the A/B is regional).
    - `evolving_flight`: **PASS** — n_z RMS 0.0034/0.0160/0.0642/0.1136 g
      strictly rising by phase; wind tracks the schedule to 0.133 fps; W20
      to 0.000 fps; sun 8→30° recorded; panel narrates phases.
      (Long renders must run nohup-detached — the 10-min Bash cap killed
      the first attempt: gotcha 16.)
    - `zermatt_run`: **PASS** after strengthening left pulses to −0.18
      (the UE host banked −11.2° against the stated 12° bar; its
      power/torque differs slightly from the headless twin). Headless
      clearance gate 312 m; banks −36.9/+18.4 headless, on-screen both
      directions; chase camera 0.000000°; shoulder declares AND rolls
      33.2°. Script numbers all measured: torque bias 0.033 by sweep
      (0.02→−14°, 0.04→+5° over 20 s), counter-pulses (uncorrected holds
      spiralled to −116°).
    - Full `mutation_check`: 2 stale targets surfaced (refactored lines);
      one re-targeted, one REPLACED onto the discovery's trim-refusal
      (with a new regression test) after measuring that no crank criterion
      discriminates at 2600 m. All 62 guards verified load-bearing.
14. **Decisions recorded** in VALIDITY.md: same-seed turbulence parity is
    **permanently visual-only** (an isolated-RNG patch would fork the
    pinned JSBSim under one host or both — worse than the measured RNG
    stream offset); **von Kármán stays not-modelled**, stated.

## Where everything lives

| What | Where |
|---|---|
| Resume state + all gotchas (1–17) | `NEXT.md` |
| The brief executed | `docs/BRIEF_PHASE7.md` |
| §13 turbulence contract + piston findings | `docs/JSBSIM_CORRECTIONS.md` |
| Claims ledger (imagery, ground, thermals, parity, refusals) | `docs/VALIDITY.md` |
| This narrative | `docs/CONTEXT_PHASE7_SESSION.md` |
| Vendored plugin patches (4 now) | `ue/Plugins/JSBSimFlightDynamicsModel/VENDORED.json` |
| Matrix deliverable | `runs/showcase/` (139 clips, contact_sheet.png, showcase_manifest.json with 5 skips) |
| Measured reports | `runs/turb_perstep/`, `runs/environment_ue/`, `runs/agl_parity/`, `runs/imagery_drape/`, `runs/evolving_flight/`, `runs/zermatt_run/`, `runs/gate5_realmesh/` — each `report.json` |
| Imagery bakes + sidecars | `runs/terrain/{matterhorn,yosemite}_imagery.{png,json}` (tile cache in `runs/terrain/imagery_cache/`) |
| New Python modules | `core/terrain/imagery.py`, `core/environment/{rotor,thermals}.py`, `LogProfileWind` + `ScheduledDrydenTurbulence` in existing modules, `assets_pipeline/estimate_hinges.py` |
| New experiments | `turb_perstep_measure, environment_ue, agl_parity, imagery_drape, evolving_flight, zermatt_run` (all under `experiments/`) |
| New UE sources | `FlightSimDownburst.{h,cpp}`; heavy edits in `FlightSimScenarioWorld`, `FlightSimRenderCommandlet`, `FlightSimVisualScene`, `FlightSimSurfaceAnimator`, `FlightSimCameraDirector`, plugin `JSBSimMovementComponent` |
| Airframe configs (A320 live; DHC6/p51d ready-but-refused) | `assets/aircraft_config/` |

## Loose ends a future session might pick up

* The rotor null scenario climbs out of the 300 m ceiling mid-run (its
  turb RMS 0.200 fps is dominated by the early below-ceiling segment);
  a terrain-following or lower-energy scenario would measure the coupling
  over the full run.
* Showcase matrix clips still use the classification surface (imagery came
  after the matrix design); re-rendering all 139 with `-imagery` is ~14 h
  of editor time if ever wanted. The imagery path is proven on stills,
  the Zermatt run, and available to any new render.
* DHC6/p51d unlock automatically if upstream ever carries an explicit
  license statement (configs + estimated hinges are committed).
* The 5 refused matrix cells are refusals by design, not TODOs.

## How to verify everything from scratch

Run the loop in NEXT.md's code block. All of it is green as of `1c4e84e`.
