# Gap analysis: this branch against a government-grade flight simulation for data collection

Written 2026-09-28 on `claude/relaxed-cori-gccjvx` (= `phase2`) at a25eea0, before Phase 3.
Every statement about the branch below was checked against the tree at that commit
(file names given); every statement about the yardstick names the standard it comes from.
"Government-grade" here means the requirements a government programme would put on a
simulation that produces perception-training data with physics-backed labels: the FAA/ICAO
flight-simulator qualification rules used as an engineering yardstick, the DoD and NASA
rules for model verification, validation, accreditation and credibility, the military
atmospheric and handling-qualities specifications, the interoperability protocols such
simulations speak, and the data-quality and software-assurance practices a programme
office audits.

## 0. The one-paragraph verdict

The branch is unusually strong on **honesty and reproducibility** (provenance on every
value, refusals by name, physics bit-reproducible, 1424 tests, 442 mutation guards each
shown to fire, a VV&A plan, report, accreditation statement and NASA-STD-7009A scorecard
that say where it is weak) and unusually weak on **fidelity and validation**: no airframe
has validated data, four of six validation targets are inconclusive or not attempted for
want of referents, the credibility scorecard is mostly below its own threshold of 2, the
sensor scores 0 (RGB only, no radiometry, no IR), rendering reproducibility is not
established on any engine, and the environment is an ISA atmosphere with one turbulence
spectrum. It speaks no interoperability protocol (no DIS, HLA, CIGI or CDB), models no
failure, no icing, no non-standard atmosphere, no humidity, no wake, no aeroelasticity, and
has no independent review. The method is government-grade; the model is not yet, and the
document that says so most clearly is the branch's own `docs/VALIDITY.md`.

## 1. The yardstick, named

| Area | Reference a programme would cite | What it asks for |
|---|---|---|
| Simulator qualification | FAA 14 CFR Part 60 (QPS Appendices A–D), ICAO Doc 9625 | Objective tests against flight-test data with stated tolerances (e.g. ±3 kt, ±100 ft, ±1.5° pitch), a Qualification Test Guide with every test reproducible, transport delay ≤ 150 ms, visual-system field of view, resolution, contrast and latency measured |
| Model VV&A and credibility | DoDI 5000.61, MIL-STD-3022, NASA-STD-7009A, ASME V&V 20 | Conceptual model, referent data, acceptability criteria declared in advance, independent V&V, credibility assessed per factor, results uncertainty and robustness reported |
| Atmosphere and disturbances | US Standard Atmosphere 1976, MIL-HDBK-310 (climatic extremes), MIL-F-8785C / MIL-HDBK-1797 (Dryden and von Kármán turbulence, discrete gusts, wind shear), FAA AC 120-41 (windshear training models) | Non-standard days (temperature and pressure deviations, humidity), shear profiles, both turbulence spectra, gust families with stated probability of exceedance |
| Icing and contamination | 14 CFR Part 25 Appendix C/O, FAA AC 20-73A | Aerodynamic degradation as a function of accretion severity, with the envelope it was derived for |
| Handling qualities | MIL-STD-1797A / MIL-F-8785C Level bands | Modal frequencies and damping (short period, phugoid, Dutch roll) from a linearised model, compared with the Level 1 bands |
| Sensors | EMVA 1288 (camera), NVESD NV-IPM / MODTRAN / DIRSIG conventions (EO/IR) | Radiometric units, spectral response, MTF/PSF, noise, IR bands, atmosphere transmittance by band |
| Interoperability | IEEE 1278 (DIS), IEEE 1516 (HLA), CIGI (image generator), OGC CDB / DTED / OpenFlight (terrain databases), WGS 84 + EGM2008 | Entity state exchanged in standard PDUs, image generator driven over a standard interface, terrain in a standard database, one geodetic datum with a geoid model |
| Data for machine learning | Datasheets for Datasets, ISO/IEC 5259 (data quality for ML), W3C PROV, NIST AI RMF | Documented collection process, quality metrics, label consistency, coverage against the target distribution, licensing per source, lineage from raw source to exported record |
| Software assurance | DO-178C / DO-330 as the ceiling; in practice: requirements traceability, coverage, static analysis, configuration management, SBOM | Every requirement traced to a test, coverage measured, lint and type gates in CI, pinned and audited dependencies, reproducible builds of every artefact including the engine half |

## 2. The branch, measured

What exists, with the evidence, so the gaps in §3 are gaps and not omissions of this
analysis.

* **Physics**: JSBSim 1.2.4, 6-DoF rigid body, fixed 120 Hz step, wrapped read-only
  (`core/fdm`, `core/telemetry/recorder.py`: 35 channels including the aero force block and
  the accelerometer load factor). Environment providers summed per step (`core/environment`):
  steady, log-profile and boundary-layer wind, Dryden turbulence through JSBSim's
  MIL-F-8785C implementation with a measured POE ladder (`turbulence.py`), lee rotor, Allen
  thermals, orographic wind over the baked terrain, discrete gust, downburst, tornado vortex,
  ERA5 mean wind (Open-Meteo). Trim, TECS autopilot injected by rewriting the aircraft XML
  (`core/control/derive.py`), closure assertions, terrain contact at wing stations.
* **Verification**: `docs/vva/VV_REPORT.md` V1–V12 all PASS (trim, initial conditions,
  reproducibility, envelope, step response, decoupling, closure, environment connectivity,
  numerical convergence, terrain round trip, sweep integrity, provenance). Null tests in
  `experiments/gate3_null_tests.py`. 1424 tests on three operating systems; 442 mutation
  guards, each shown to make its test fail (`scripts/mutation_check.sh`).
* **Validation**: A1 B747 stall speed validated at u_val (wide), A2 turbulence σ_w validated
  against MIL-F-8785C, A3 ground roll and A4 spool time inconclusive (no referent), A5 modal
  damping not attempted (no linearisation), A6 transport delay not applicable. Reporting form
  ASME V&V 20. Credibility: NASA-STD-7009A eight-factor scorecard (`core/validation/
  scorecard.py`), threshold 2 declared in advance, mostly below it; sensors 0; rendering 0.
  Accreditation statement (`docs/vva/ACCREDITATION.md`): internal research use only, no
  absolute performance claim, no qualification, no handling-qualities claim, no sensor
  imagery claim, no statement about a real place.
* **Camera and sensor**: intrinsics from the spec, a seeded post-pass with Brown–Conrady
  distortion, rolling shutter, EMVA 1288 shot + read noise and cos⁴ vignetting
  (`core/capture/profile.py`, two profiles), EV100 physical exposure in the engine.
  Explicitly not modelled: chromatic aberration, intra-exposure blur, demosaicing, flare
  (`docs/VALIDITY.md` §2.16).
* **Labels and verification of labels**: 2-D/3-D boxes, keypoints, horizon, per-object masks
  from a custom-stencil ID pass, depth as float32, visibility and occlusion, seven annotation
  gates graded by a verifier that never imports the producer; Gate 10-R instrument for
  render reproducibility (not yet run on an engine).
* **World**: Copernicus GLO-30 bake with sha256 provenance, tiled at native posting; imagery
  drape; vertex-palette land classification (not land cover); one volumetric cloud layer;
  wetness; sun from date, place and hour; height fog by Koschmieder extinction.
* **Data pipeline**: campaigns with a ledger as the only truth, index-seeded workers,
  identical output at 1 and 2 workers, realised-distribution and coverage report, COCO /
  KITTI / WebDataset / YOLO / VOC export with independent round-trip readers, a dataset
  card with sources and licences, a message catalogue with a two-way test, an agent tool
  layer with a deterministic authority policy.

## 3. What is lacking

Severity: **A** blocks a government-grade claim; **B** a programme would require before
accepting data; **C** expected of a high-end simulation, not a blocker.

### 3.1 Validation and credibility (methods)

| # | Gap | Yardstick | The branch, measured | Sev. | Closing step |
|---|---|---|---|---|---|
| M1 | No referent flight-test data for any airframe | Part 60 objective tests; ASME V&V 20 needs a D to compare S against | Stock JSBSim disclaimers on every model; A3/A4 inconclusive; the one production-flagged model with a cited wind-tunnel source (f16, NASA TP-1538) is not used | A | Adopt one documented-pedigree airframe and validate trim, drag polar and modal response against its published numbers with declared u_D; keep the others as "unvalidated" in the card |
| M2 | Handling qualities never assessed | MIL-STD-1797A Level bands | A5 "not attempted: requires linearisation" | A | Numerical linearisation about trim (finite differences on the JSBSim state), short-period / phugoid / Dutch-roll frequency and damping per case, written to the manifest and compared with the Level 1 bands |
| M3 | No independent review | NASA-STD-7009A level 3+ requires it; DoDI 5000.61 separates the V&V agent from the developer | Accreditation is by the authors; the scorecard is self-scored | A | An independent V&V pass with its own acceptability criteria, recorded in `docs/vva`; until then the scorecard ceiling stays 2 and the card must say so |
| M4 | Results uncertainty and robustness not reported per result | NASA-STD-7009A factors 3 and 4; ASME V&V 20 u_num, u_input | Uncertainty appears only in the six validation rows; no run carries a numerical or input uncertainty | B | Per-run u_num from the timestep-convergence measurement (V9), u_input from the spec's provenance (sampled vs stated), both in the manifest |
| M5 | No requirements traceability | DO-178C-style traceability; every programme audit asks "which test proves this requirement" | Requirements live in briefs and contracts pages; tests are named for behaviour, not linked | B | A traceability table (requirement id → contract clause → test → guard) generated from the tests' docstrings and checked by a test |
| M6 | Test coverage not measured; no lint or type gate | Programme audits ask for coverage numbers | CI runs pytest only (`.github/workflows/ci.yml`); no coverage, ruff, mypy | B | Coverage report in CI, a lint gate, gradual typing on `core/` |
| M7 | Engine half never built in CI | Every artefact reproducible | The C++ (FlightSimBridge, 5.7 pins) is uncompiled here; CI has no Windows engine runner | B | A self-hosted Windows runner with the engine, building the plugin and running Gate 6 and Gate 10-R on every push |
| M8 | Render reproducibility unestablished | Part 60 repeatability; a dataset regenerated must match | Gate 10-R exists and has never run on an engine; host vs headless flight differs by 1.38 m worst (stated, handled by the one-flight rule) | B | First Windows run of Gate 10-R; a bit-identical or bounded verdict recorded in VALIDITY §3 |

### 3.2 Physics fidelity (layers a government model carries)

| # | Gap | Yardstick | The branch, measured | Sev. | Closing step |
|---|---|---|---|---|---|
| P1 | Standard atmosphere only | MIL-HDBK-310 extremes; Part 60 tests at hot/cold/high | `atmosphere/delta-T` never written; humidity never set (dew point property exists); density altitude never recorded | A | Spec fields for temperature deviation, pressure and humidity with provenance; written per run; density and pressure altitude recorded per step and per frame; null test with vs without |
| P2 | One turbulence spectrum, one shear law | MIL-F-8785C offers Dryden and von Kármán; wind shear by MIL-F-8785C and FAA AC 120-41 profiles | Dryden only (JSBSim ttMilspec); log-profile shear only; the POE enum unverified from Python (VALIDITY §4) | B | von Kármán through JSBSim's own type where exposed, else stated absent; a layered wind profile from a cached NWP fixture (the live API is blocked here); shear stated per layer |
| P3 | No icing or contamination | Part 25 App C, AC 20-73A | No property, no model, no word in the vocabulary | A | Aerodynamic degradation tables injected the way TECS is injected (CLmax loss and CD rise vs a severity property), with the envelope stated and a null test |
| P4 | No weight-and-balance variation | Every qualification test states weight and CG | Pointmass stations and `inertia/cg-x-in` exist and are never varied; fuel burn only | B | Payload and fuel state as spec fields with provenance; CG recorded per step; the n_z envelope by category checked against the state |
| P5 | No structural or operational limit monitoring | Load-factor and speed limits are part of every envelope definition | n_z recorded, never compared with a limit; V_NE / M_MO not encoded | B | Category limits per airframe in `data/aircraft_config`, exceedance flags per step and per frame, a campaign summary of exceedances |
| P6 | No failure or malfunction library | Every FSTD carries one; robustness data needs it | Zero mentions of engine failure, control jam, sensor failure | B | Engine-out and control-authority reduction as spec events with provenance, applied through JSBSim properties, with the resulting trajectories labelled |
| P7 | No wake or traffic-induced disturbance | Wake vortex encounter models are standard in ATC and training simulations | The Phase 2 traffic aircraft is a scripted mesh; no wind field | C | A Hallock–Burnham vortex pair as a wind provider behind the traffic aircraft |
| P8 | Ground effect and ground operations unverified | Part 60 ground tests (taxi, takeoff, landing) | `aero/h_b-mac-ft` exists; no test flies below one span; no runway geometry | C | Approach and landing scenario family over a modelled runway with the gear model in the loop |
| P9 | Rigid body only | Large transports carry aeroelastic corrections in qualification models | JSBSim rigid 6-DoF | C | State as out of scope; not a data-collection blocker |
| P10 | Vertical datum mismatch | WGS 84 with EGM2008 geoid | GLO-30 heights are EGM2008 orthometric and "treated as MSL"; JSBSim's sea level is the ellipsoid; the separation (tens of metres, ~50 m in the Alps) is unaccounted | C | Apply the EGM2008 undulation at the scene origin when baking; record the datum shift |

### 3.3 Sensing and rendering

| # | Gap | Yardstick | The branch, measured | Sev. | Closing step |
|---|---|---|---|---|---|
| S1 | No radiometry, no spectral bands, no IR | NVESD / MODTRAN / DIRSIG conventions; EO/IR programmes need at least a stated radiance path | sRGB beauty; sensor scores 0; VALIDITY §2.5 "no EO/IR fidelity" | A | A linear-radiance path with stated units, a band model per sensor, an IR proxy declared as a proxy; transmittance by band |
| S2 | Sensor model partial | EMVA 1288 plus MTF/PSF, chromatic aberration, flare, motion blur | Noise, distortion, rolling shutter, vignetting only (stated) | B | PSF/MTF and intra-exposure blur from shutter time, recorded per profile |
| S3 | No ground-truth beyond masks and depth | Perception programmes expect normals, motion vectors, optical flow, amodal boxes, point clouds | Masks, class, depth, visibility, occlusion, boxes, keypoints | B | Normal, velocity and base-colour passes through the same post-process-material route; disparity and point clouds derived in Python; each with a verifier check |
| S4 | Render reproducibility and quality unmeasured on 5.7 | Part 60 visual tests; every look switch measured | Lumen, VSM, TSR, Nanite flags on but unmeasured; airframes flat-coloured GPL meshes with Nanite off | B | The Windows order in `docs/PHASE2_REPORT.md`; licence-clean PBR airframes |
| S5 | World content thin | Government scenes carry land cover, vegetation, structures, airports, day/night | Height, imagery drape, one cloud layer, no land cover, no vegetation, no buildings, no runway, no night sky | B | Landscape at native posting, land cover to weightmaps and PCG biomes, runway family, moon and starfield |

### 3.4 Interoperability and data standards

| # | Gap | Yardstick | The branch, measured | Sev. | Closing step |
|---|---|---|---|---|---|
| I1 | No simulation interoperability protocol | IEEE 1278 DIS entity-state PDUs, IEEE 1516 HLA | Bespoke run card JSON; zero mentions of DIS/HLA/CIGI/CDB | B | A DIS entity-state PDU writer over the telemetry (the state is already NED, WGS 84); HLA out of scope |
| I2 | No image-generator interface | CIGI | The commandlet is driven by the run card | C | State as out of scope: the card is the interface and is documented |
| I3 | Terrain not in a standard database | OGC CDB, DTED | Baked `.r16` + sidecar with provenance | C | DTED-level metadata in the sidecar; CDB out of scope |
| I4 | Dataset documentation partial | Datasheets for Datasets, ISO/IEC 5259 | Dataset card with sources and licences, realised distribution, coverage | B | Datasheet sections (motivation, composition, collection process, preprocessing, uses, distribution, maintenance), per-field quality metrics, label-consistency statistics |
| I5 | Airframe geometry licensing | Distributable dataset must be licence-clean | FlightGear meshes are GPL-2.0 (flagged in VALIDITY §5) | A for distribution | Licence-clean airframes or a stated non-distribution scope |

## 4. What is lacking, methods-wise

1. **Validation referents.** The method (ASME V&V 20 form, declared thresholds, refusals by
   name) is right; the inputs are missing. Nothing improves credibility as much as one
   airframe with published data flown through the existing gates.
2. **Independence.** Every check is self-administered. The verifier's independence from the
   producer is real for labels; nothing equivalent exists for the physics or the
   accreditation.
3. **Uncertainty per result.** A government reader asks "how sure" of every number in the
   manifest; the branch answers only for six quantities in one report.
4. **Traceability and coverage.** The evidence is strong but unindexed: a requirement cannot
   be followed to the test that proves it, and coverage is unknown.
5. **The engine half is unmeasured.** Every C++ claim on the branch is a source-reading test
   until a Windows runner exists. A programme would not accept "uncompiled" for the half that
   produces the pixels.
6. **Sensitivity and robustness.** No study shows which inputs move which outputs; the
   randomisation policy draws values without stating their effect size.

## 5. What is lacking, advancements-wise

1. **Physics layers**: non-standard atmosphere, humidity, icing, weight and balance, limit
   monitoring, failures, wake, von Kármán, layered shear. All are reachable through
   properties the installed JSBSim exposes (measured: `atmosphere/delta-T` moves density and
   reports density altitude; pointmass stations move the CG; engine EGT, CHT, oil, MAP, N1,
   N2 and fuel flow are readable).
2. **Data returned per variable**: today a variable is applied and recorded once in the
   spec; a government record carries the applied value, its provenance, the model and
   parameters, the per-step effect, the per-frame state, the realised distribution and a
   null test of its effect.
3. **Stronger models**: a documented-pedigree airframe measured against its source; modal
   analysis; instrument models (IMU, GPS, pitot-static, magnetometer) returning measured
   channels beside truth.
4. **Sensing**: radiance in stated units, bands, IR proxy, PSF, motion blur; normals, flow,
   point clouds as ground truth.
5. **World**: Landscape with Nanite as a measured toggle, land cover and vegetation, runway
   and airport scenes, night, precipitation, licence-clean PBR airframes, Substrate
   materials with liveries.
6. **Process**: Windows engine runner in CI, Gate 10-R verdict, coverage and lint gates, a
   traceability table, datasheet-grade dataset documentation, a DIS entity-state feed, sim-
   to-real evaluation (a detector trained on the output and scored on real imagery, the
   only measurement that says whether the data is useful).

## 6. Priority for Phase 3

Take the A items first where they can be measured here, because this container runs JSBSim
and Python but no engine: P1, P3 and M2 (atmosphere, icing, linearised modal analysis) with
M1 (one pedigree airframe), the data rule of §5.2 applied to every new variable, P4/P5
(weight, balance, limits), the instrument models, and I4 (datasheet-grade documentation).
Take the engine-side A/B items (S1 radiance path, S3 passes, S5 world) as written-and-pinned
code with the Windows verification order. Record M3 (independence) and M7 (engine runner) as
the two items no amount of work in this container can close.
