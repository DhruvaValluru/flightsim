# The advancement additions: demonstration

Written from 2026-09-28 on `claude/relaxed-cori-gccjvx` (= `phase2`). One
section per item, in the form the Phase 2 report uses: what was measured and
what was defective before, what was built, how to demonstrate it on any
platform, what is not verified here, limitations. The gaps each item closes are
numbered as in `docs/PHASE3_GAP_ANALYSIS.md` §3; the contracts are in
`docs/ADVANCEMENTS_CONTRACTS.md`.

Sections are appended by the integrator as each item lands.

## I1 -- the vertical datum (P10): the geoid undulation, measured and recorded, not converted

**What was measured, and what was defective.** (1) JSBSim's sea level is the
WGS 84 ellipsoid: with `ic/h-sl-ft` 10000 at latitudes 0, 27.9 and 46.005,
`position/radius-to-vehicle-ft` equals the WGS 84 ellipsoid radius plus
10000 ft to 0.1 ft, and `geod-alt-ft` agrees with `h-sl-ft` to 0.06 ft; there
is no geoid anywhere in the FDM. (2) The GLO-30 bakes are EGM2008 orthometric
and `core/terrain/glo30.py` labelled them "treated as MSL"; pyproj here has no
geoid grid and EPSG:4326+3855 -> 4979 returns 0.0 in silence. (3) From the
GeographicLib EGM96 15-minute grid (tarball sha256 8b1ebad1..., grid sha256
2a12f13b..., header MaxBilinearError 1.152 m) the undulation at the six
curated origins is Matterhorn +52.52, Yosemite -25.94, Fuji +41.47, Everest
-29.84, Grand Canyon -23.40, Flint Hills -30.54 m ((0, 0) = 17.16 m): every
georeferenced scene on the branch was 23-53 m off in absolute ellipsoidal
height, unrecorded. (4) EGM96 is not the bakes' datum. Measured from
GeographicLib's egm2008-5 grid (10.4 MB tarball, sha256 9a57c143...; not
committed): |EGM2008 - EGM96| at every one of the 1,038,240 EGM96 nodes is at
most 11.985 m (28.5 N, 94.5 E, eastern Himalaya), RMS 0.722 m, p99 3.04 m; at
the six origins +2.23, +0.51, +0.94, +0.87, -0.02, +0.23 m.

**What was built.**

* `assets/geoid/egm96-15.pgm` (2,076,888 bytes) with a README stating the
  source URL, both sha256 digests, the header figures, the licence (EGM96 NGA
  public domain; PGM packaging GeographicLib MIT/X11) and the measured
  EGM2008 difference.
* `core/terrain/geoid.py`: sha256-checked load (absent or altered grid
  refuses `terrain.geoid` by name; measured: one flipped sample byte near
  46 N 7.75 E refuses, and unchecked the same file answers 1.7 m differently
  at the Matterhorn origin), bilinear `undulation(lat, lon)` (measured: at a
  cell centre it is the four-node mean to 1e-9 m; the Alpine nodes differ by
  more than 0.02 m, so nearest-neighbour is detected), `datum_block` /
  `flat_datum_block` / `datum_for_heightfield`, and `undulation_variable`,
  the `AppliedVariable` with a null test (N against 0, threshold 1.152 m;
  difference at the Matterhorn = 52.525 m, ok).
* The datum block on the bake sidecar (`glo30.bake`, `provenance.datum`;
  measured on a synthetic-tile bake through the whole mosaic/ingest/verify/
  summit path: undulation at 45.9 N 7.1 E, orthometric origin 3000 m +-30,
  ellipsoidal = orthometric + N), on the run card (`orographic_card_block`
  carries it, `write_run_card` lifts it to the top level so the orographic
  block keeps the C++ keys), and on the capture manifest (`datum` and
  `applied_variables`; measured through `flightsim.capture` headlessly: flat
  run -> "flat slab, spec terrain_elevation", undulation null; `--synth-terrain`
  run -> "synthesised heightfield ... (not a real place)", undulation null).
  The frame sidecar's context carries both. `scripts/bake_terrain.py` prints
  the datum line per bake, and names a sidecar that predates the block.
* The verifier clause `verify_datum` (returned as a patch; verify.py is
  another item's): its own 15-line PGM reader, NOT RUN on flat/synthesised,
  FAIL `scene.datum` on a missing key, a foreign grid sha256, |dN| > 0.01 m or
  an inconsistent ellipsoidal height. Measured: the checker's reader and the
  producer agree to 1e-9 m at all seven test points; N + 0.009 m passes,
  + 0.011 m fails.
* 27 tests in `tests/test_geoid.py`; nine mutation guards, each shown to fire.

**How to demonstrate (any platform).**

    .venv/bin/pytest -q -p no:cacheprovider -p no:warnings tests/test_geoid.py
    .venv/bin/python - <<'PY'
    from core.terrain.geoid import undulation, datum_block, undulation_variable
    from core.terrain.glo30 import LOCATIONS
    for key, loc in LOCATIONS.items():
        print(f"{key:13s} N = {undulation(loc.origin_lat, loc.origin_lon):+7.2f} m")
    print("(0,0)", round(undulation(0.0, 0.0), 2))          # 17.16
    block = datum_block(46.005, 7.72, 2400.0, location_key="matterhorn")
    print(block["ellipsoidal_height_of_origin_m"], block["model_difference_at_origin_m"])
    print(undulation_variable(block).to_dict()["null_test"])
    PY
    # -> matterhorn +52.52, yosemite -25.94, fuji +41.47, everest -29.84,
    #    grand_canyon -23.40, flint_hills -30.54; 2452.52, 2.231; null test ok
    .venv/bin/python scripts/bake_terrain.py matterhorn   # needs the GLO-30 bucket; prints the datum line
    .venv/bin/python -m flightsim.capture examples/cameras_terrain.yaml --synth-terrain --out runs/datum_demo
    .venv/bin/python -c "import json; m=json.load(open('runs/datum_demo/capture_manifest.json')); print(m['datum']); print(m['applied_variables'])"
    ./scripts/mutation_check.sh --match "geoid|undulation|datum"   # after integration

**Not verified here.** No GLO-30 bake exists on this machine and the bucket
was not fetched, so the sidecar block was measured on a synthetic tile
through the real bake code path, not on a curated mountain; the first
`scripts/bake_terrain.py matterhorn` on a networked machine is the
verification of that line (expected: N = +52.52 m). The verifier clause was
run from the patch text and from a by-hand application to verify.py; its
place in `verify_run` is the integrator's. The EGM2008 paper (Pavlis et al.
2012) and the GeographicLib licence page could not be fetched (proxy); both
are cited unverified. Nothing engine-side reads the block and no engine ran.

**Limitations (stated, not claimed).** No height is converted: JSBSim
altitude on this branch still equals orthometric height, and the block records
N so the ellipsoidal height can be formed; absolute ECEF placement remains as
it was, now stated. The committed model is EGM96, not the bakes' EGM2008; the
difference is measured at the six curated origins (2.23 m at most) and bounded
globally at 13.7 m from the node maximum plus both grids' bilinear bounds --
between nodes nothing finer was measured. The 1.152 m interpolation bound is
the header's, not the model's error against the true geoid. A flat slab's
terrain elevation is fed to JSBSim as an ellipsoidal height and is whatever
the spec says; no undulation is evaluated for it (the block says so with a
null, never a zero). The bake's `dynamic_location` keys are not in the
EGM2008 difference table, so `model_difference_at_origin_m` is null there.
Observed, not fixed: `core/telemetry/limits.py` (another item, in the same
tree) emits `limits.config` with no catalogue entry, which is the only other
failure in `tests/test_messages.py` once the three entries here are added.

## I2 -- operational and structural limit monitoring: the run graded against its certification envelope (gap P5)

**What was measured, and what was defective.** (1) `n_z`, `cas_kt` and `mach`
have been recorded on every run since Phase 1 and compared with nothing: no
aircraft config carried a load-factor, V_NE/V_MO or M_MO figure, and
`core/scenario/validate.py` has no speed-limit rule at all -- a spec for the
c172p at 183 kt CAS (V_NE 163 + 20) is refused, but by `envelope.trim_feasible`
(the stock aero tables do not trim there; 170 kt likewise), never by a limit.
Measured 2026-09-28 at efb12d7: `validate(compile_prompt("fly the c172p at 1500 m
and 183 kt for 5 seconds")).violations == [envelope.trim_feasible]`, same at
170 kt; the p51d refuses the same way at 250 and 460 kt at 1500 m. (2) The JSBSim
A320 and B747 DO trim and fly beyond their placards: A320 at 1500 m, 370 kt CAS
(V_MO 350 + 20) flies 10 s open-loop at 370.0 kt, Mach 0.608, n_z 0.997; B747
at 385 kt (V_MO 365 + 20) at 1500 m and at Mach 0.892 at 11000 m / 300 kt
(M_MO 0.92, margin 0.028). So the "flown at V_NE + 20 vs cruise" null test the
contract asks for is real on the A320 and unreachable on the c172p; the tables'
notes say which. (3) None of the five models states an `<alphalimits>` element
(grep of each `<name>.xml`), so no alpha limit is monitored and each table says
so. (4) `compile_prompt("fly the DHC6 ...")` compiles to aircraft `dhc6`, refused
`aircraft.exists`, although `FlightDynamics("DHC6")` loads -- the DHC6 table is
written and loadable but was not flown through the prompt path. (5) Flying the
c172p at 110 kt with the compiler's default `hold_state: true` raises
`TrimError` inside `Autopilot.engage` (the sign probe's longitudinal trim) after
validation passed -- pre-existing, not touched here; the tests fly open-loop.

**What was built** (contracts I2). `core/telemetry/limits.py`: the table
(`parse_limits`, `load_limits`, refusal `limits.config`), the monitor (strict
comparison, one 0/1 column per stated limit plus `any_exceedance`, per-limit
count / first exceedance time / worst margin), `Recorder.annotate` to write the
columns beside the recorded ones (refuses a clash or a length mismatch; names
them in `derived`), the per-run null test and the `limits.monitor`
AppliedVariable, and `monitor_run` -- the runner's one call. `run_spec` digests
the recorded telemetry FIRST, then monitors, then carries `manifest["limits"]`
and `manifest["applied_variables"]` (`attach_record`, additive, refuses a
repeated name). Five `limits` blocks in `assets/aircraft_config`: load factors
from 14 CFR 23.337 (c172p, DHC6 normal +3.8/-1.52; p51d aerobatic +6.0/-3.0 as a
stated proxy for a military type) and 25.337 (A320, B747 +2.5/-1.0); placard
speeds c172p V_NE 163 kt, DHC6 V_NE 170 kt, p51d V_NE 439 kt (505 mph), A320
V_MO 350 kt / M_MO 0.82, B747 V_MO 365 kt / M_MO 0.92, each cited `unverified
here: from memory of ...`; M_MO null with a reason for the three propeller
types; alpha limit null with the grep reason on all five. 38 tests in
`tests/test_limits.py`; 11 mutation guards, each shown to fire.

Measured on real flights (JSBSim 1.2.4, 120 Hz, 0.1 s sampling, open-loop):
A320 at 1500 m / 370 kt for 10 s -> 96 samples, `exceed_vne_or_vmo` 96/96,
`any_exceedance` 96 (first at t = 0.0083 s, the first sample after trim), V_MO
worst margin -20.00 kt, n_z_pos margin +1.503 g, M_MO margin +0.212;
`limits.monitor` null test with 96 / without 0, ok. The same model at 250 kt:
0 flagged, V_MO margin +100.0 kt, Mach 0.412; null test (the run's samples
offset +120 kt) with 96 / without 0, ok. c172p at 1500 m / 110 kt: 0 flagged,
margins n_z_pos 2.800 g, n_z_neg 2.512 g, V_NE 52.34 kt (peak 110.66 kt CAS);
`exceed_mmo` absent (M_MO null), `summary.monitored == [n_z_pos_g, n_z_neg_g,
speed_limit_kt]`. B747 at 11000 m / 300 kt: 0 flagged, M_MO margin 0.028.
`frame_state` returns 44 keys for the A320 (39 recorded + 5 flags) and 43 for
the c172p, with no change to `core/capture/manifest.py`. `output_digest ==
digest_columns(columns minus derived)` and `!= digest_columns(all columns)`.
The campaign parity test (one vs two workers) passes with the change (1 passed,
9.45 s).

**How to demonstrate (any platform).**

```
.venv/bin/pytest -q -p no:cacheprovider -p no:warnings tests/test_limits.py      # 38 passed in ~1 s
.venv/bin/python - <<'EOF'
from core.nl.compiler import compile_prompt
from core.scenario.runner import run_spec
for kt in (370, 250):
    spec = compile_prompt(f"fly the A320 at 1500 m and {kt} kt for 10 seconds"); spec.set("hold_state", False)
    r = run_spec(spec, assert_closure=False)
    s = r.manifest["limits"]["summary"]; nt = r.manifest["applied_variables"]["applied_variables"][0]["null_test"]
    print(kt, "kt:", s["any_exceedance"]["count"], "of", s["samples"], "samples flagged; V_MO margin",
          s["per_limit"]["speed_limit_kt"]["worst_margin"], "kt; null test with/without", nt["with"], nt["without"], nt["ok"])
EOF
# prints: 370 kt: 96 of 96 samples flagged; V_MO margin -20.0 kt; null test with/without 96.0 0.0 True
#         250 kt: 0 of 96 samples flagged; V_MO margin 100.0 kt; null test with/without 96.0 0.0 True
scripts/mutation_check.sh --match 'limits|recorder.annotate' --no-suite            # after the guards are integrated: 11 ok
```
After integration patch 2, `python -m flightsim.capture examples/cameras_multi.yaml
--out build/demo` writes `build/demo/run.json` with `limits` and
`applied_variables` (measured on the test suite's demo capture: `limits.monitored
true`, `any_exceedance 0`, record `limits.monitor`), and after patch 3 a campaign
`--report` prints an `exceedances:` line (measured on a fabricated ledger: "1 of 2
monitored case(s) beyond a stated limit, 96 sample(s) flagged (speed_limit_kt
x96); 1 case(s) unmonitored").

**Not verified here.** The placard values themselves -- every speed and Mach
limit is from memory of the POH/AFM/FCOM/TCDS and the table says so; no
document was reachable through the proxy. Nothing renders: the flags reach the
per-frame `state` through `frame_state` (measured) and the frame sidecars
(measured in the demo capture with patch 1), but no engine ran. The
campaign-level line is measured on a fabricated ledger and a one-case demo, not
on a multi-case campaign with a real exceedance.

**Limitations (stated, not claimed).** Placard KIAS against JSBSim CAS with no
position-error model. The monitor observes: an exceedance flags the sample and
the run continues; no damage, fatigue, aeroelastic or gust-load model. No alpha
limit is monitored because no model states one; the validator's measured CLmax
alpha is a derived quantity and is not used as a limit. The c172p and p51d
cannot be flown beyond V_NE on their stock tables, so their speed flags are
exercised only through the per-run probe (the run's own samples offset by 20
kt); the A320 is the airframe that flies the real null test. The `limits.monitor`
record is attached only for monitored airframes; an airframe without a block
is `{monitored: false, reason}` and has no record. The per-run null test is a
statement about the monitor's discrimination on that run's samples, not a
second flight. `state_units` reports `?` for the flag columns until integration
patch 1 lands (`tests/test_camera_cli.py` is red by exactly that test until then).

## I3. Instrument models: measured channels beside truth

### What was measured, and what was defective

* The recorder's channel set (core/telemetry/recorder.py DEFAULT_CHANNELS) carries `n_z`, `roll_rate_dps`, `pitch_rate_dps`, `lat_deg`/`lon_deg` (runner extras), `altitude_m`, the three NED velocities, `cas_kt` and `heading_deg`, but NOT `n_x`, `n_y` or `yaw_rate_dps`, although the state reads accelerations/Nx, Ny and velocities/r-rad_sec. So the IMU measures one accelerometer axis and two gyro axes today; the other three are listed under `absent` in every measured file (measured: 12 channels present, 3 absent on the c172p run). Nothing is derived to fill them.
* The recorder's stated `interval_s` is 0.1 s; the measured sample spacing on the c172p run (examples/cameras_waypoint.yaml, 120 Hz) is 0.10833 s median (13 steps, min 0.1000, max 0.10833): 280 samples over a 29.958 s span, i.e. 9.35 Hz, not 10. The `t < self._next_sample` comparison accumulates a floating-point step. The models take the stated 0.1 s for the noise sigma (the check uses the same figure, so it is consistent), and the GPS schedule uses the recorded `t`, so the fix count is right (150 fixes in 30 s at 5 Hz). A recorder fix belongs to the recorder's owner (open issue).
* The c172p run turns through the full 360 deg with 38 deg of bank, so the lever arm and the hard iron are exercised, not idle: with the tactical antenna offset (-1.0, 0.0, -0.8) m the GPS altitude residual before removing the arm is 3.44 m RMS against a 3.0 m sigma, and the heading residual is 1.40 deg RMS against a 0.5 deg noise sigma (hard iron drawn (-0.0223, +0.0165) of the field: up to 1.6 deg of heading-dependent error).
* The normalised residual RMS on the c172p run is 4.33 (12 channels): dominated by the GPS hold, which lets the truth move up to one fix interval (0.2 s at 50 m/s in a turn: 0.28 m/s RMS on `v_north_mps_meas` against a 0.05 m/s noise sigma). That is the hold, not a defect, and the check grades the GPS at the fix samples only.

### What was built

* `core/telemetry/instruments.py`: three profiles applied as an observer after the run: IMU (constant bias per run from the repeatability sigma, white noise from the random-walk density at the recorder's interval, first-order Gauss-Markov bias instability with the stated correlation time), GPS (per-axis white noise, 5 Hz fixes with a zero-order hold at the 10 Hz recorder, antenna lever arm rotated by the attitude and converted with the WGS 84 radii), pitot-static (backward-Euler first-order lag plus white noise on CAS and pressure altitude), magnetometer (hard-iron offset pair plus white noise). Every draw from one of four named seed streams (`imu`, `gps`, `pitot_static`, `magnetometer`, added to core/experiments/seeds.py). `telemetry_measured.json` carries the profile with its sources and sha256, the seed streams, the truth's sha256, every `<truth>_meas` beside its truth, `gps_fix`, the per-run draws and the `instruments.profile` record. Measured: 0.018 s to apply the tactical profile to 280 samples; the file is 178187 bytes.
* `core/telemetry/instruments_check.py`: the verifier-side check, independent code (its own rotation written axis by axis, its own lag filter, its own unit conversions, its own hard-iron formula; no import of the producer, asserted by a test over both source files). Residual std within 0.67..1.50 x the profile's sigma per channel, mean within the bias bounds, drawn biases within 5 sigma, the hold exact, the truth equal to telemetry.json, the record present.
* `assets/instrument_profiles/{ideal,tactical,consumer_mems}.json`, each citing its sources (IEEE Std 952-2020; Groves 2013 Table 4.1; El-Sheimy et al. 2008; Woodman 2007; HG1700 and MPU-6050 datasheets; u-blox NEO-M8; GPS SPS Performance Standard 2020; Titterton & Weston 2004; Caruso 2000), every number marked 'unverified here'.
* `flightsim/capture.py --instruments <profile>`: refuses an unknown profile by name (`instruments.profile`, exit 2) before any flight (measured: the run directory is not created); default `ideal` writes nothing and prints one line; otherwise writes the file beside telemetry.json, attaches the record to the capture manifest and prints one line. The existing verifier still passes on such a run (11 passed, json_schema PASS).
* Measured on the synthetic 3000-sample truth with the tactical profile (relative tolerance 10 %, sampling error 1.3 %): every channel's residual std matches its sigma -- IMU 0.000326 g and 0.00659 deg/s white, GPS 1.5 / 3.0 m and 0.05 m/s at the 1500 fix samples after removing the lever arm, pitot-static 0.5 kt / 3.0 m about the lagged truth, magnetometer 0.5 deg about the hard-iron-bent heading. The check on the model's own output: PASS, worst channel 0.93 x (tactical, 600 samples), 0.92 x (consumer_mems), 1.10 x (the real c172p run, `altitude_m_gps_meas`). The check on a file whose every noise term was doubled but which still claims the tactical profile: FAIL `instruments.residual`, 12 channels off, measured ratios 1.85..2.05 x; halved: FAIL, 0.47..0.51 x.
* Null test in the record: normalised residual RMS 4.33 (c172p, tactical) against the ideal profile's 0.0, threshold 0.5: ok. The ideal profile's own record measures 0 vs 0 and is NOT ok, which is the honest reading of an instrument that leaves no trace.
* Determinism: two real captures of examples/cameras_waypoint.yaml with `--instruments tactical` produce byte-identical telemetry_measured.json (cmp; also tested); seed 43 and profile consumer_mems each differ.
* 31 tests in tests/test_instruments.py (3.1 s); 11 mutation guards, each applied to the real file and shown to fail the tests, each file restored byte-identically.

### How to demonstrate (any platform)

    find . -name __pycache__ -type d -prune -exec rm -rf {} +
    .venv/bin/python -m flightsim.capture examples/cameras_waypoint.yaml --out runs/i3_tactical --max-previews 0 --instruments tactical
    # prints: instruments: tactical -> telemetry_measured.json (12 measured channels beside truth, 3 truth columns absent from the recording, normalised residual RMS 4.329)
    .venv/bin/python -m flightsim.capture examples/cameras_waypoint.yaml --out runs/i3_again --max-previews 0 --instruments tactical
    cmp runs/i3_tactical/telemetry_measured.json runs/i3_again/telemetry_measured.json && echo BYTE-IDENTICAL
    .venv/bin/python -m flightsim.capture examples/cameras_waypoint.yaml --out runs/i3_ideal --max-previews 0
    # prints: instruments: ideal (the recorded channels are the measurement; no telemetry_measured.json written)
    .venv/bin/python -m flightsim.capture examples/cameras_waypoint.yaml --out runs/i3_nope --max-previews 0 --instruments nope
    # prints: REFUSED -- instruments.profile: no instrument profile 'nope' in .../assets/instrument_profiles (available: consumer_mems, ideal, tactical)   (exit 2, no run directory)
    .venv/bin/python -c "from core.telemetry.instruments_check import check_instruments; print(check_instruments('runs/i3_tactical'))"
    # PASS: 12 measured channels graded against profile 'tactical' over 280 samples; residual std within 0.67..1.50 x the stated sigma on every channel (worst altitude_m_gps_meas at 1.10 x); biases within bounds; GPS hold exact
    .venv/bin/python -m flightsim.verify runs/i3_tactical      # after the verify.py patch: [PASS] instruments; on an ideal run: [NOT RUN] instruments
    .venv/bin/pytest -q -p no:cacheprovider -p no:warnings tests/test_instruments.py
    scripts/mutation_check.sh --match "instruments|seeds: the instrument|capture: --instruments" --no-suite

### Not verified here

* Any profile number against a real instrument: the values are grade-typical figures from the cited surveys and datasheets, none measured in this repository.
* The `instruments` check inside `flightsim.verify` (the registration is an integration patch to core/capture/verify.py; the function was exercised directly, and the wrapper is four lines).
* The x/y accelerometer and yaw gyro channels on real telemetry (the recorder does not carry them; the code path is tested with synthetic columns added).
* The message catalogue's two-way test with the six new names (entries returned, not written).

### Limitations

* Second-moment statistics only: the check grades standard deviations and means, not distribution shape (no chi-square, no normality test), and needs at least 30 samples (30 GPS fixes) to run.
* The IMU's expected residual sigma is `hypot(white, bias_instability)`; a profile whose bias instability exceeds its white sigma would sit near the band's edge on a short run. Neither shipped profile does (worst ratio bias_instability / white: 0.27 for the consumer gyro).
* The GPS lever arm applies to position only; the velocity term omega x arm needs the yaw rate, which is not recorded. The magnetometer takes the field level and the heading true (no declination, tilt or soft iron). The pressure altitude is the geometric altitude under the ISA assumption until a `pressure_altitude_m` column exists (the entry says so).
* The recorder's real spacing (0.10833 s) differs from its stated interval (0.1 s) by 8 %; the noise sigma follows the stated interval. Fixing the recorder is not this item's to do.
* The measured file is per step; nothing is attached to the capture frames (`frame_keys` empty, stated).

## I4 -- linearised modal analysis against the handling-qualities bands (gap M2, row A5)

**What was measured, and what was defective.** Row A5 of the V&V report read "not attempted -- no linearisation", and `docs/VALIDITY.md` said the build does not linearise. Probed 2026-09-28: the installed JSBSim 1.2.4 exposes `jsbsim.FGLinearization` (13 attributes: `system_matrix`, `input_matrix`, `x0`, `u0`, `x_names`, `x_units`, ...) and runs on a trimmed executive, so the Jacobian is JSBSim's own and nothing had to be re-implemented. What it does was read from the jsbsim-1.2.4 sdist (the proxy allows pypi's file host): a four-point central difference at `h = 1e-4` in each state's unit, each state set through the initial-condition object and the model re-initialised and run once with integration suspended (`FGStateSpace::linearize`, `numericalJacobian`, `run`). Three things were found by measurement. (1) Linearising DISTURBS the executive: 223 readable properties change by 1e-10..1e-6 (qdot 1.2e-10 -> -8.8e-6 rad/s^2; sim time unchanged), so the analysis must never run on the FDM that records the flight -- it builds its own, and the flight's `output_digest` is unchanged with the block computed (equal digests on `examples/cameras_waypoint.yaml`, 280 samples). (2) The independent Jacobian (this module's `ic/` + `run_ic()` route, derivatives from the property tree) agrees with JSBSim's to 3.2e-3 relative Frobenius (c172p, longitudinal), 1.0e-5 (lateral), 2.3e-9 / 7.1e-7 (A320), 2.1e-9 / 2.5e-7 (B747) at step 1e-4; the c172p's 0.121 rad/s^2-per-rad difference in the Q-row alpha entry (0.35 percent of M_alpha = -34.1) is constant across steps 1e-4..1e-3 and absent on the turbines, consistent with `FGStateSpace::run()` re-settling the propeller with `GetSteadyState()` at each perturbed point where this module holds the rpm -- stated, not proven. (3) At a wider step (1e-3) the A320's longitudinal residual jumps to 4.7e-2 while the B747's stays at 2.1e-7: the A320's Vt-dot slope against alpha changes from +3.86 to -2.07 ft/s^2 per rad between 0.4 and 0.6 mrad below the 250 kt / 3000 m trim alpha (3.03 deg) -- a CD-table breakpoint (`aero/coefficient/CDalpha`) next to the trim; JSBSim's stencil (+/-1e-4, +/-2e-4) stays on one side of it. Also seen: a longitudinal trim leaves the c172p with pdot = -0.27 rad/s^2 (the lateral axes are not trimmed by `TrimMode.LONGITUDINAL`), which is why one-sided differences are not used.

**What was built.** `core/fdm/linearize.py`: `linearize(fdm)` -> `LinearModel` (JSBSim's full A, B, x0, u0 with names and units; the SI classical 4x4 blocks by the similarity transform `T A T^-1`, `T = diag(0.3048, 1, 1, 1)`; the residual per block at 1e-4 against a bound of 1e-2, refused by name `modes.residual`; the linear-range residual at 1e-3, reported unbounded; the disturbance left in the analysis executive), `modes.untrimmed` and `modes.linearization` refusals. `core/fdm/modes.py`: eigenvalues to modes by stated rules (fastest longitudinal pair = short period, next = phugoid; fastest lateral pair = Dutch roll; reals: largest magnitude = roll, smallest = spiral; coupled roll-spiral and non-oscillatory cases reported as such), the MIL-F-8785C tables (Table IV, Figures 1-3 as CAP, 3.2.1.2, Table VI general rows, Table VII, Table VIII) each with reference, confidence and `unverified here`, the class table (c172p I, DHC6 II, A320 III, B747 III, p51d IV, f16 IV, sourced), `analyse`, `analyse_spec` (own FDM via `configure_from_spec`), `modes_block(spec)` (the result or a named refusal, never an abort). `flightsim/modes.py`: the CLI and its ASCII table. `tests/test_modes.py`: 28 tests. Seven mutation guards, each shown to fire.

Measured modes (JSBSim models as shipped; Category B; a level describes the model):

| condition | short period wn / zeta / period | phugoid wn / zeta / period | Dutch roll wn / zeta | roll tau | spiral | levels (SPd, SPf, ph, DR, roll, spiral) |
|---|---|---|---|---|---|---|
| c172p 1200 m / 100 kt CAS (the example) | 7.01 rad/s / 0.610 / 1.13 s | 0.243 / 0.114 / 26.1 s | 2.44 / 0.185 | 0.146 s | stable, T1/2 29.4 s | 1, 1, 1, 1, 1, 1 (CAP 2.96, n/alpha 16.6) |
| c172p 1200 m / 120 kt CAS | 8.31 / 0.611 / 0.95 s | 0.217 / 0.147 / 29.3 s | 2.89 / 0.182 | 0.121 s | stable, T1/2 27.7 s | all 1 (CAP 2.95, n/alpha 23.4) |
| A320 3000 m / 250 kt CAS | 2.53 / 0.225 / 2.55 s | 0.091 / 0.110 / 69.2 s | 3.41 / 0.561 | 0.567 s | stable, T1/2 24.3 s | 2, 1, 1, 1, 1, 1 (zeta_sp 0.225 < 0.30; CAP 0.61) |
| B747 3000 m / 250 kt CAS | 1.30 / 0.503 / 5.59 s | 0.076 / 0.061 / 82.9 s | 0.918 / 0.343 | 0.837 s | stable, T1/2 38.7 s | all 1 (CAP 0.18, n/alpha 9.4) |

The null test of the analysis: between 100 and 120 kt the c172p's short-period wn moves 7.01 -> 8.31 rad/s (+19 percent), the Dutch roll 2.44 -> 2.89 (+18 percent), the phugoid period 26.1 -> 29.3 s; an analysis that did not read the trim would return the same modes (tests/test_modes.py::test_modes_differ_between_two_airspeeds). Cost: c172p analysis 1.04 s wall including its own trim (FGLinearization 1.2-1.5 s standalone, propeller model), A320 0.26 s, B747 0.31 s; a 30 s open-loop c172p run is 0.49 s, so the runner patch roughly triples that run's wall time.

**How to demonstrate (any platform).**

    .venv/bin/python -m flightsim.modes examples/cameras_waypoint.yaml --json runs/modes_c172p.json
    .venv/bin/python -m flightsim.modes examples/cameras_waypoint.yaml --category A
    find . -name __pycache__ -type d -prune -exec rm -rf {} + ; .venv/bin/pytest -q -p no:cacheprovider -p no:warnings tests/test_modes.py
    bash scripts/mutation_check.sh --match 'modes\.|short period|Table IV' --no-suite   # once the guards are integrated

The first prints the c172p table above (Level 1 on every line, residual 3.19e-03 / 1.03e-05, bound 0.01, ok) and writes the record; the second grades the same modes against Category A (short-period damping floor 0.35: still Level 1 at zeta 0.610). A refusal reads `REFUSED -- modes.airframe_class: ...` (exit 1); an untrimmed FDM `modes.untrimmed`; a residual beyond the bound `modes.residual`.

**Not verified here.** The band numbers against a copy of MIL-F-8785C or MIL-STD-1797A (the network here reaches neither; every table is marked `unverified here` with a confidence: `high` for Tables IV, VI, VII, VIII and 3.2.1.2, `moderate` for the CAP figure bounds encoded from memory of Figures 1-3). Any flight-test referent: A5 moves from "not attempted" to "attempted, unvalidated" -- there is a simulation value S and no D. The DHC6 and p51d (no JSBSim aircraft named dhc6; the p51d engine file Packard-V-1650-7 is missing here). The cause of the c172p's 0.35 percent M_alpha difference (consistent with the propeller steady-state re-settle; not proven from the C++). Windows and the engine host: nothing here touches them.

**Limitations.** The classical 4x4 blocks drop the engine, altitude, heading and position couplings (kept in the full matrix: the c172p's full 13-state matrix carries a real root at +2.2e-4 1/s, time to double 52 min, in the altitude/engine coupling, and the A320/B747 12-state matrices carry roots at +/-0 from position). n/alpha is `-V A[alpha,alpha]/g`, neglecting the alpha-dot and pitch-rate lift terms. The A320's linear model sits 0.5 mrad from a CD-table breakpoint, so its longitudinal derivatives are one-sided by construction; the 4.7e-2 linear-range figure records it. The airframe class table lives in `core/fdm/modes.py`, not in `assets/aircraft_config` (a follow-up for the config owner). `FGLinearization`'s step is not settable from Python; JSBSim prints its banner on every executive it constructs (the analysis constructs one more per run). A level is a statement about a stock JSBSim model with no validated data (docs/VALIDITY.md), never about the aeroplane; the A320's Level 2 short-period damping at cruise says that about the model.

## I5. The DIS entity-state feed (gap I1)

Contract: docs/ADVANCEMENTS_CONTRACTS.md I5. Measured at efb12d7 on
2026-09-28 in the Linux container (JSBSim 1.2.4, pyproj 3.6.1, no engine).

**What was measured, and what was defective.** The gap analysis (§3.4 I1)
measured zero mentions of DIS, HLA, CIGI or CDB on the branch: a run's
state left the system only as the bespoke run card and `telemetry.json`.
What the telemetry does carry, measured on a fresh capture of
`examples/cameras_multi.yaml` (B747, 12 s, 115 samples at 0.1 s): geodetic
`lat_deg`/`lon_deg` (added this batch as runner extras from
`position/lat-geod-deg` and `position/long-gc-deg`), `altitude_m`,
`heading_deg`/`pitch_deg`/`roll_deg`, NED ground velocity
`v_north_mps`/`v_east_mps`/`v_down_mps`, `roll_rate_dps` and
`pitch_rate_dps` -- but no yaw rate and no acceleration, which the RVW
dead-reckoning block needs, and no ECEF anything. JSBSim's altitude is
above the WGS 84 ellipsoid by definition while a georeferenced scene's
heights are orthometric (the geoid item's finding: 23-53 m at every
committed origin), so an ECEF position formed from a bare altitude would be
that far wrong on every terrain run. pyproj here has no geoid grid, so the
undulation must come from the run's own datum block.

**What was built.** `core/interop/geodesy.py` (240 lines, imports only
`math`): WGS 84 geodetic <-> ECEF (closed form forward, fixed-point back to
1e-13 rad), the NED axes in ECEF, the body-from-NED matrix, and the DIS
Euler convention `Rx(phi).Ry(theta).Rz(psi)` read off the composed
body-from-ECEF matrix, with the inverse. Measured: ECEF identical to pyproj
EPSG:4979 -> EPSG:4978 (0.0 m) at all six committed origins at the
ellipsoid, at the measured undulation, 5 km up and 100 m down; round trip
over 500 random points on the globe within 1e-9 deg and 1e-5 m (worst
height error 2.1e-9 m at the origins); the body axes in ECEF reconstructed
from the NED route and from the DIS angles alone agree to 1.5e-14 (worst
over 2000 random attitudes and places), and heading/pitch/roll come back
within 1e-8 deg; the hand-derived case (level, heading east, 45 N 10 E)
gives psi 100 deg, theta 0, phi -135 deg as derived in the test's comment.
`core/interop/dis.py`: the 144-byte Entity State PDU as one big-endian
struct format (calcsize 144, the offsets table checked against the summed
field sizes), encode/decode, the stream walker by the header's length, the
run reader, the three-case datum handling, the six-airframe entity-type
table with per-field basis, the forward-difference dead reckoning, the
pyproj position check and the `interop.dis` record. `flightsim/dis.py`: the
CLI, write or `--decode`. `tests/test_dis.py`: 32 tests, 1.76 s, including
a decoder written out field by field with `struct.unpack` at stated offsets
that never calls `dis.decode`, and a real capture as a module fixture.

Measured on the real runs: `cameras_multi.yaml` 115 samples -> 115 PDUs,
16560 bytes (= 115 x 144), first-PDU residual against pyproj 0.0 m,
timestamp error against the sample time at most 8.3e-7 s (unit 1.676 us),
capture 1.0 s wall, feed 0.25 s wall on the 558-sample run;
`cameras_event_trigger.yaml` (60 s) 558 samples -> 558 PDUs, 80352 bytes,
residual 0.0 m. The derived dead-reckoning rates against the recorded ones
on that manoeuvring run (recorded pitch rate up to 4.34 deg/s): q within
0.0062 deg/s worst, 0.0021 deg/s rms of the interval mean of the recorded
`pitch_rate_dps`; p within 1.9e-5 deg/s; largest derived acceleration 3.78
m/s^2. On a fabricated run carrying a datum block with N = +52.52 m
(Matterhorn), the first PDU lands within 1e-3 m of pyproj at altitude +
52.52 and 52.52 m from the orthometric point. Eight mutation guards, each
applied on the working file and shown to fire (5, 2, 3, 3, 2, 4, 10 and 1
failing tests), each file restored byte-identically.

**How to demonstrate (any platform;** `.\.venv\Scripts\python.exe` on
Windows):

```
.venv/bin/python -m flightsim.capture examples/cameras_multi.yaml --out runs/dis_demo --max-previews 0
.venv/bin/python -m flightsim.dis runs/dis_demo --out runs/dis_demo/entity_state.dis --site 7 --application 3 --entity 42
#   wrote 115 Entity State PDU(s) for 115 telemetry sample(s) ... (16560 bytes)
#   position check: first PDU 0.000e+00 m from pyproj (tolerance 0.001 m) -> ok
.venv/bin/python -m flightsim.dis --decode runs/dis_demo/entity_state.dis --limit 5
#   115 Entity State PDU(s) ...; one line per PDU with lat/lon/h and hdg/pitch/roll recovered from the wire
cat runs/dis_demo/dis_manifest.json    # counts, datum.handling, entity_type_basis, position_check, applied_variables
.venv/bin/pytest -q -p no:cacheprovider -p no:warnings tests/test_dis.py     # 32 passed
./scripts/mutation_check.sh --match 'DIS|WGS 84' --no-suite                  # the 8 guards, once integrated
```
A refusal to try: `python -m flightsim.dis /tmp --out x.dis` prints
`REFUSED -- interop.dis.run: ...` and exits 2.

**Not verified here.** No DIS consumer (no open-dis, no KDIS, no
commercial gateway) read the stream: the wire form is checked by the
test's own reading of IEEE 1278.1-2012, written from memory, not by a
second implementation. The SISO-REF-010 country, category and subcategory
values are unverified (the document could not be fetched); the sidecar
marks each field. No georeferenced run with a real GLO-30 bake exists in
this container (only synthesised terrain), so the datum path was measured
on a fabricated run carrying the geoid item's block shape, not on a bake.
Nothing was sent on a network.

**Limitations.** One entity per stream (the primary airframe; traffic
aircraft are scripted meshes with no telemetry). Dead reckoning is
forward differences at the telemetry's 10 Hz, not the FDM's own rates and
accelerations, and the first interval of a run is 0.108 s rather than 0.1
s (the recorder's first sample is at t = dt). Timestamps are relative and
wrap hourly; a run longer than an hour is refused upstream (`run.duration`)
so no wrap occurs in practice. Appearance and capabilities are zero.
Gimbal lock at |theta| = 90 deg exactly returns one valid pair of angles.
The `not_claimed` list in the sidecar and I5.8 in the contracts say the
rest.

## I6. Normals, motion-vector and albedo ground-truth passes (gap S3)

### What was measured, and what was defective
* The bundle carried masks, class, depth, visibility and boxes only (`FlightSimRenderCommandlet.cpp` label block, 5 file kinds per frame); no normal, motion-vector or base-colour ground truth existed anywhere in the tree (0 occurrences of `PPI_WorldNormal`, `PPI_Velocity`, `PPI_BaseColor` before this item).
* Pillow 11.3.0 opens a 16-bit RGB PNG as mode RGB uint8 (measured on a 4x4 file holding 0x1234: the low byte is gone); rasterio 1.4.3 reads the same file as uint16 exactly, 0.055 s at 1280x720. A filter-0 zlib encoder written in numpy (0.232 s at 1280x720) round-trips through rasterio bit for bit. So the readers cannot go through Pillow.
* A half float's step at 0.5 is 2^-11 = 4.88e-4; on a 1280 px wide frame an offset-encoded motion vector would quantise at 0.31 px -- 15 % of the 2 px verifier tolerance. The velocity target is therefore RGBA32f, the other two RGBA16f as designed.

### What was built
* Commandlet: `-passes=` parsing, three refusals by name, three pass captures through `ConfigureLabelCapture` + `SCS_FinalColorHDR` + one blendable, the velocity capture first after the step with persisted view state and `r.Velocity.ForceOutput=1`, per-frame writes (`RenderWriteRgba16Png`, float32 flow), record keys null when off, root `passes` block with encodings (+289 lines, ASCII in every engine-read string; 0 non-ASCII characters added).
* `scripts/ue_create_materials.py`: `create_pass_material` from a three-row table (`PASS_MATERIALS`), `SIGNED_SCALE/OFFSET` 0.5/0.5 wired through Multiply + Add for the two signed textures; three creators called at import.
* `core/render/flags.py`: `PASS_NAMES`, `passes_flag`, `passes=` on `render_flags`; the default list is pinned token for token.
* `core/capture/labels.py`: six readers/writers, `passes_declared`, `passes_record` (the AppliedVariable), `attach_engine_labels` records `labels.passes` per frame and `render.passes` in `applied_variables`.
* `core/capture/verify.py`: `normals_vs_depth`, `flow_vs_motion`, `albedo_range`, registered in `verify_run` after `applied_pose`; three FAIL names.
* `experiments/gate6_visual.py`: the "albedo sun invariance" look clause with its control (NOT RUN here, stated measurement).
* Tests: `tests/test_annotation_passes.py` (30, new), 13 clause and source-pin tests in `tests/test_gate6_visual.py` (49 total), 2 in `tests/test_ue_materials.py`.

Measured on the synthetic bundles (`tests/test_annotation_passes.py`, 320x180, fx = fy = 400 px, identity camera at the scene origin):
* Normals: a plane 20 m below the camera, normal (-0.3, 0.1, 1)/|.|, its depth painted per pixel through the pinhole; the verifier's depth-derived normals agree with the encoded plane normal to a median 0.06 deg over 50 244 smooth pixels (PASS); the same image rotated 5 deg about east measures 4.92 deg (PASS, under the 10 deg tolerance); rotated 30 deg measures 29.8 deg and FAILS `annotation.normals`.
* Flow: a 70 x 60 x 10 m box 600 m north, translated (0, +6, +2) m between two frames 0.2 s apart; 294 box pixels, |flow| 4.48 px everywhere on the box; the flow painted from where each visible surface point WAS. The verifier's keypoint prediction is a median 0.26 px from the painted flow (worst 0.49 px at the nose, whose pixel shows the aft face 70 m nearer: the stated parallax) -> PASS; scaled by 2 -> median 4.74 px FAIL `annotation.flow`; negated -> 8.69 px FAIL; a first frame holding one moving pixel FAILS; one frame -> NOT RUN; a flow file 8 bytes short FAILS.
* Albedo: a flat 20000/65535 image beside a random beauty frame differs on 100 % of pixels -> PASS with "mean albedo over sky pixels 0.3052" reported; the beauty frame re-encoded as 16-bit differs on 0.00 % -> FAIL `annotation.albedo`; an 8-bit albedo is refused ("uint8 samples, not 16-bit"); absent -> NOT RUN.
* Attach: two frames declaring flow (both), normal and albedo (one) -> `labels.passes` per frame as declared, `render.passes` value `["normal","velocity","albedo"]`, null test with 2.0 files per frame vs 0.0, threshold 1, ok; a second attach leaves one record. Without pass keys: all null, no record.
* Flags: `passes=["albedo","normal","velocity","normal"]` -> one token `-passes=normal,velocity,albedo` after `-deterministic`, before `-GeorefTerrain`; `passes=()` equals the omitted argument and the 23-token pre-passes list exactly; `passes=["normals"]` raises.
* Gate 6 clause on fabricated stills: identical albedo under two suns -> PASS "0.000 %"; albedo shaded by 1000 counts over the ground rows -> FAIL at 50.000 % changed; beauty unchanged between suns -> FAIL "vacuous"; a record naming no albedo -> FAIL by the record.
* Mutation: 14 guards each applied, 1 failed each, restored byte-identically. `--check-targets`: 486/486 targets still unique.

### How to demonstrate (any platform)
```
find . -name __pycache__ -type d -prune -exec rm -rf {} +
.venv/bin/pytest -q -p no:cacheprovider -p no:warnings --override-ini="addopts=" tests/test_annotation_passes.py
.venv/bin/pytest -q -p no:cacheprovider -p no:warnings --override-ini="addopts=" tests/test_gate6_visual.py tests/test_ue_materials.py tests/test_render_flags.py
bash scripts/mutation_check.sh --check-targets
bash scripts/mutation_check.sh --no-suite --match "0.5 offset|flow|normals_vs_depth|albedo|passes|velocity capture|pass material"   # once the guards are integrated
```
On Windows with the engine: `UnrealEditor-Cmd ue/FlightSim.uproject -run=pythonscript -script=scripts/ue_create_materials.py` (creates the seven materials, MATERIAL-CREATED lines), then `python -m flightsim.capture <spec> --out runs/i6 --render --passes normal,velocity,albedo` (after the capture.py patch), `python -m flightsim.verify runs/i6` (the three checks move from NOT RUN to a verdict), and `python experiments/gate6_visual.py --look` for the albedo clause.

### Not verified here
Everything the engine does: that the three materials compile and the `PPI_*` ids are accepted by 5.7's Python enum; that the tonemapper-replacing emissive reaches the float target unclamped (the 0.5 offset exists so that it need not); the `PPI_Velocity` decoding and its clip-space (x right, y up) convention and the (W/2, -H/2) conversion; that rendering the velocity capture first makes its time base the previous captured frame (the verifier's `flow_vs_motion` is the measurement, threshold 2 px); `GetENUVectorsAtEngineLocation` at the camera and the sign of north in the engine frame; what the cleared GBuffer decodes to on sky pixels; UE's PNG wrapper writing RGBA at 16 bits in the byte order rasterio reads (the same call the 16-bit depth PNG uses); `r.Velocity.ForceOutput` existing in the build (a warning names its absence). The catalogue entries and the capture.py `--passes` wiring are returned, not applied.

### Limitations
The velocity's time base is a design tension stated in the source: the engine's motion vector is a difference against the previous scene render, the contract promises the previous captured frame, and the capture loop renders several passes per instant; the commandlet orders the velocity capture first and the verifier decides on the first Windows bundle. A run with `-passes=velocity` renders one more scene before the beauty capture, so its beauty digest is not claimed equal to a run without (Gate 10-R must compare equal flag lists) and TSR/motion blur in the beauty capture may see a zeroed object velocity. Keypoints the airframe itself occludes are graded against a nearer surface of the same rigid body (0.49 px at 600 m on the synthetic box; larger nearer and under rotation) inside the 2 px tolerance. The normals check grades smooth-depth pixels only (no silhouettes, no sky) and needs the float32 depth. The albedo check proves the pass is not the beauty picture and is in range; correctness of the base colour is Gate 6's Windows clause. The synthetic bundles are painted by the test's own arithmetic, which shares the pinhole convention with the verifier by design; what an engine's pixels do inside the tolerances is not measured in this container.

## I7 -- land cover from ESA WorldCover (gap S5, the data half)

**What was measured, and what was defective.** The branch's world carried height
(GLO-30), an imagery drape and a vertex palette classified by slope and altitude
(approximated, VALIDITY.md); no land cover source, no weightmap, and the words
"landcover", "WorldCover" and "land cover" occur in neither the advancement
contracts, the report, NEXT.md, README.md nor the message catalogue (grep, HEAD
efb12d7). Measured here on 2026-09-28: the WorldCover bucket answers a ranged GET
with 206 and a HEAD with `Content-Length: 115482414`, ETag
`"71495d1ab2ce752b50fb08dbdf36f360-14"`, Last-Modified 2022-10-26 for N36W120;
rasterio `/vsicurl/` opened it (36000 x 36000, uint8, nodata 0, 1024 x 1024 blocks,
overviews 2..64, pixel 8.333e-05 degree) and read the Yosemite bbox window (4800 x
3000 px, 14.4 M cells) in 2.7 s, with three proxy configurations (none;
GDAL_HTTP_PROXY only; CURL_CA_BUNDLE only) all opening the tile -- so the scene
window is read and no tile is downloaded. The raw window's classes: 10 tree cover
9,834,908 (68.30 %), 30 grassland 3,136,402, 60 bare 1,359,376, 80 water 43,737,
20 shrubland 12,411, 100 moss 6,219, 50 built-up 5,613, 70 snow 1,327, 40 cropland
6, 90 wetland 1 -- every value in the legend, none of 95. The product user manual
was fetched from the bucket (4,102,952 bytes, sha256 `4301a3d9...8490107`, text
read with pypdf installed into the scratchpad, not the venv): licence "Creative
Commons Attribution 4.0 International", attribution text and the Zanaga et al. 2022
citation with `doi:10.5281/zenodo.7254221`, Table 3 legend with colours, global
overall accuracy 76.7 +/- 0.5 % (North America 74.6 +/- 1.2 %). zenodo.org,
doi.org and esa-worldcover.org are blocked (CONNECT 403), so the DOI is unverified
here.

**What was built.** `core/terrain/landcover.py`: `fetch` (windowed vsicurl reads or
cached whole tiles, mosaic on the product's global grid, legend check, crop written
with sha256 + `.json` provenance carrying licence, attribution and citation, the
bucket's ETag/size/date per tile), `read_grid` (the bake sidecar's grid, refused
`terrain.landcover_grid` when missing), `reproject_classes` (nearest onto the bake
grid subdivided 3 x 3), `weight_counts` / `weightmaps` (255 x fraction with
largest-remainder rounding: exact 255 per cell), `majority_map`,
`verify_against_source` (400 texels pushed back to the source), `landcover_variable`
(the `scene.landcover` AppliedVariable with its null test), `rasterise` (the whole
step, refusing `terrain.landcover` by name when the source is unreachable, corrupt
or unverified), `landcover_records` / `scene_dir_for` (the manifest hook).
`scripts/bake_landcover.py --location <key> --cache <dir> --out <dir> [--bake PATH]
[--source TIF]`. `tests/test_landcover.py`: 22 tests -- synthetic COGs written with
rasterio (quadrants of 10/30/60/80) on an aligned 4326 grid give exactly 0.25 per
class and pure 255/0 cells; a grid shifted one source pixel gives the exact thirds
(170 / 85) against weights re-derived in the test from the source array; a UTM 11 N
grid sums to exactly 255 per cell within 0.05 of a quarter each; the JSON carries
the record (record_version 1, source derived, null test 0.25 vs 1/11 ok, licence
and attribution inside the parameters); garbage bytes, a value 37, a row-flipped
rasterisation and a wrong-posting cached tile refuse `terrain.landcover` by name;
a sidecar without `origin_x_m` or absent refuses `terrain.landcover_grid`; two
synthetic tiles under their bucket names mosaic across 39 N offline with both
sha256s recorded; the script exits 0 printing the attribution, 1 with `REFUSED --
<name>:`, 2 for an unknown location; the verifier's source never mentions land
cover; everything the engine or a reader sees is ASCII.

Measured end to end on real data (this container, no engine): Yosemite -- GLO-30
bake 1151 x 894 cells at 30 m (EPSG:32611, source verification mean 0.82 m, p95
excess 7.05 m, 4.4 s), then land cover in 11.6 s first run (7.3 s on the cache
hit, no network): window col 2400 / row 13800, 4800 x 3000 px, crop 993,703 bytes,
sha256 `f104dd16635c74a2550eaa801a428f1f46de1a01a25cbc898d988e192d00df9c`; fine
grid 3453 x 2682; tree cover 68.66 %, grassland 21.69 %, bare/sparse 9.18 %,
permanent water 0.31 %, shrubland 0.08 %, built-up 0.04 %, moss/lichen 0.03 %,
snow/ice 0.01 %, cropland 4e-07, wetland 1e-07, mangroves 0; nodata 2.1e-06 (19
fine cells at the bake's edge); weights sum 255..255 in every cell; 400 of 400
texels agree with the source; null test 0.6866 vs 0.0909 = 0.5957 >= 0.05.
Grand Canyon (bbox 35.98 N crosses the 36 N tile edge): tiles N33W114 (120,157,309
bytes; window 3240 x 240 at row 0) and N36W114 (124,750,491 bytes; 3240 x 2400 at
row 33600) mosaicked to 3240 x 2640; bake 802 x 806 in EPSG:32612; tree cover
30.15 %, grassland 24.31 %, bare/sparse 23.25 %, shrubland 21.33 %, water 0.91 %,
built-up 0.05 %; 99.2 % of 400 texels agree (boundary texels between the 10 m
geographic and the 10 m UTM grids); 9.5 s; sha256 `42886763...0faf43`. Eight
mutation guards, each applied by hand, each firing (1 to 5 tests red), the file
restored byte-identically (sha256 `74073ac0...8dc3` before and after).

**How to demonstrate (any platform).**

    .venv/bin/pytest -q -p no:cacheprovider -p no:warnings -o addopts= tests/test_landcover.py
        # 22 passed in ~5 s; the real-tile test is skipped by name when the bucket is unreachable
    .venv/bin/python scripts/bake_terrain.py yosemite
        # GLO-30 bake into runs/terrain (downloads one 41 MB tile once)
    .venv/bin/python scripts/bake_landcover.py --location yosemite --cache data/worldcover --out runs/terrain
        # ~12 s: runs/terrain/yosemite_landcover/{tree_cover_weight.png, ..., nodata_weight.png,
        # class_map.png, landcover.json}; prints the fractions, the source sha256 and the
        # attribution line; exit 1 with "REFUSED -- terrain.landcover: ..." or
        # "REFUSED -- terrain.landcover_grid: ..." when refused
    .venv/bin/python scripts/bake_landcover.py --location grand_canyon --cache data/worldcover --out runs/terrain
        # the two-tile mosaic path (after `scripts/bake_terrain.py grand_canyon`)
    .venv/bin/python -c "import json; d=json.load(open('runs/terrain/yosemite_landcover/landcover.json')); print(d['fractions'], d['weight_sum_per_cell'], d['applied_variables']['applied_variables'][0]['null_test'])"
    ./scripts/mutation_check.sh --match "land cover|landcover|255|WorldCover|uniform prior"   # once the guards land
    (Windows: .\.venv\Scripts\python.exe for .venv/bin/python; `data/glo30` and `runs/` are gitignored, `data/worldcover` should join them)

**Not verified here.** Nothing engine-side: no material, landscape layer or PCG
biome reads the weightmaps, so no rendered pixel is measured; the first Windows
render with a consumer must show the class map on the geometry (a landmark
projection, as the imagery drape's Gate 6 clause does). The DOI's resolution
(blocked proxy). WorldCover's own class accuracy (the manual's 76.7 %, not measured
here). Behaviour when the bucket rate-limits or changes a tile (the ETag and size
are recorded so a change is visible; no retry logic beyond GDAL's own). The whole
suite was not run (owner instruction); tests/test_messages.py fails on the two new
names until the catalogue entries land.

**Limitations.** Weights are fractions of 10 m cells, not of area; the 10 m posting
is 1/12000 degree (9.3 m N-S, 7.3 m E-W at 37 N), so a bake cell's 3 x 3 fine cells
sample the source unevenly and the UTM-grid agreement is 99.2 % rather than 100 %
at Grand Canyon. Largest-remainder rounding makes the sum exact but a single
weight can be up to one count from 255 x fraction. Nearest-neighbour reprojection
is deliberate (a class is a label); a class narrower than one fine cell can vanish.
2021 classes are not the drape's 2016-2017 or the DEM's 2010-2015 state (snow,
water and cropland move between years). The class map is a majority, so a 4/3/2
cell is labelled by its plurality. A cached whole tile's size is not checked. The
scene bbox derived from a bake path is padded 5 source cells; a bake that exceeds
its location's bbox records the excess as nodata rather than fetching more.

## I8 -- the record every variable returns, made checkable (record 2, the registry, the null pair, the uncertainty block)

### What was measured, and what was defective

* Readback on a trimmed c172p (JSBSim 1.2.4), each property written then read after three steps: `atmosphere/delta-T` 36 -> 36.0 (difference 0.0), `atmosphere/P-sl-psf` 2000 -> 2000.0 (0.0), `inertia/pointmass-weight-lbs[1]` 300 -> 300.0 (0.0), `atmosphere/RH` 0.5 -> 0.5000000000505 (1.0e-10 relative; 0.37 -> 0.37000000003846584, 1.0e-10) and 0.5 -> 0.5 exactly before any step. The research session's 6.6e-8 was at another state; the registry's 1e-6 relative covers both readings by two orders. So delta-T, P-sl and the pointmass are registered exact (0 absolute); RH 1e-6 relative with the reason in the entry.
* Record 1 had no way to say "this variable must NOT change the output": every invariance the World and Datum skeptics asked for read as a failed `reached`. `NullTest.kind = bounded` gives ok = |d| <= bound (measured: 0 vs 0 with bound 0.5 is ok as bounded and not ok as reached; 2.0 with bound 0.5 is the reverse).
* `state_units` reported `?` for any channel without a suffix: with the registry consulted first, every registered channel of the 8 entries and the 30 s c172p capture has a unit (measured: no `?` in the demo manifest's `state_units`; `temperature_k` reads `K`, `rh_pct` `%`, `f_x_mps2` `m/s^2`).
* A one-second c172p flight costs 1.30 s at 120 Hz and 1.39 s at 240 Hz (trim dominates), so a null pair costs 2.21 s and a dt/2 twin 2.33 s at one second (both measured in the tests and printed), 2.2 s for the twin of the 30 s example inside the patched capture.
* The recorder's sample count differs by one between rates (11 samples at 120 Hz, 10 at 240 Hz over one second: the `t < self._next_sample` accumulation), so the twin's SRQs are interpolated onto the coarse sample times (280 compared on the 30 s run) rather than compared index by index. The recorder fix belongs to its owner (open issue, same as I3's).
* One real null pair on the c172p over a test registry (no spec-8 field is a registered variable yet; `environment.wind_speed` stands in, 10 kt against still air, one second): `wind_speed_mps` peak 5.144 m/s (reached, floor 0.051), altitude peak 0.8035 m (reached: the wind is present at trim so the trimmed state differs), latitude 2.0e-6 deg (below the 0.05 deg floor), output digests differ, verdict reached, the record's null test ok.
* One real dt/2 twin on the c172p, one second: u_num altitude 3.5e-5 m, tas 2.0e-3 kt, heading 6.7e-3 deg. On the 30 s example through the patched capture: altitude diff 0.106 m -> u_num 0.318 m (Fs 3, p 1; consistent with V9's 0.098 m at 60/120 Hz), north 1.14 -> 3.41 m, east 1.28 -> 3.85 m, tas 0.018 -> 0.054 kt, pitch 0.0074 -> 0.022 deg, roll 0.045 -> 0.135 deg, heading 0.145 -> 0.435 deg; u_input empty (no registered spec field stated); u_val = u_num per SRQ; form "ASME V&V 20; u_D absent per run".
* The committed spec-8 examples digest exactly as at HEAD (eight sha256s pinned; measured twice: in the working tree and from `git archive HEAD` in the scratchpad) and state no claimed section, so `record.unregistered` refuses nothing today.

### What was built

* `core/records.py`: record 2 under `RECORD_VERSION` 1 -- `from`, `std`, `Readback`, `JsbsimWrite`, `Model` (`model_block`), the shape-checked `uncertainty`, `NullTest.kind` in {reached, bounded}, `from_dict` on every shape. Every new key is absent until set; the twelve record-1 keys are pinned by test; `null_test.kind` is emitted always.
* `core/registry.py`: `VariableRecord`, `Registry`, `REGISTRY` with the four batch-1 entries and the four atmosphere entries (JSBSim properties, when written, effect channels with units, null values with their basis, readback tolerances with measured reasons, u_input bin widths / spreads, host channels); `unregistered_fields`, `require_registered`, `stated_variables`, `channel_units`, `host_channels`; the four refusals by name; duplicates and malformed entries as ValueError.
* `core/record_null.py`: `run_null_pair`, `null_pairs_for_spec`, `null_pairs_block`, `attach_null_pair`, the floor constants with the V9 reference, `NullPair.null_test()`.
* `core/uncertainty.py`: `u_num_twin`, `three_rate_study`, `richardson`, `observed_order`, `twin_spec`, `srq_series`, `u_x`, `central_sensitivity`, `u_input_for`, `u_val`, `uncertainty_block`, `uncertainty_for_run`, `record_u_num`.
* `core/capture/manifest.py`: eight new unit suffixes, `suffix_unit()`, the registry-first `channel_unit`, `build_capture_manifest(uncertainty=)` (key written only when given), `SIDECAR_CONTEXT_KEYS` += `uncertainty`.
* The four record-1 producers emit `model_block`, `from` and `std`; `landcover_records` re-types through `AppliedVariable.from_dict` (a landcover.json written before record 2 reads unchanged, tested by the 22 landcover tests).
* 44 tests in the four R1 files (5.9 s of JSBSim in three of them); 12 mutation guards, each applied to the real file and shown to fail the tests, each file restored byte-identically.

### How to demonstrate (any platform)

    find . -name __pycache__ -type d -prune -exec rm -rf {} +
    .venv/bin/pytest -q -p no:cacheprovider -p no:warnings tests/test_records.py tests/test_registry.py tests/test_record_null.py tests/test_uncertainty.py -rA | grep -E "null pair|dt/2 twin|passed"
    # prints: null pair c172p 1 s: 2.21 s; altitude peak 0.8035 m; lat peak 2.00e-06 deg
    #         dt/2 twin c172p 1 s: 2.33 s; u_num altitude 3.518e-05 m, tas 2.031e-03 kt, heading 6.746e-03 deg
    .venv/bin/python -c "from core.registry import REGISTRY; print(REGISTRY.unregistered_fields({'atmosphere': {'temperature_deviation_c': {'value': 15}, 'foo': {'value': 1}}}))"
    # prints: ['atmosphere.foo']
    .venv/bin/python -c "from core.registry import REGISTRY; REGISTRY.get('atmosphere.nothing')"
    # raises: record.unregistered: 'atmosphere.nothing' is not a registered variable (registered: ...)
    .venv/bin/python -c "from core.capture.manifest import channel_unit as u; print(u('temperature_k'), u('rh_pct'), u('f_x_mps2'), u('rho_kgm3'), u('stall_flag'), u('unknown_thing'))"
    # prints: 1 % m/s^2 kg/m^3 1 ?
    # after the flightsim/capture.py patch lands (run here on a scratch copy of the patched file):
    .venv/bin/python -m flightsim.capture examples/cameras_waypoint.yaml --out runs/r1 --max-previews 0 --null-tests --uncertainty
    # prints: null tests: 0 pair(s) flown (this spec states no registered variable)
    #         uncertainty: dt/2 twin flown; u_num altitude 3.179e-01 m (ASME V&V 20; u_D absent per run)
    .venv/bin/python -m flightsim.verify runs/r1      # verification PASSED (11 passed, 0 failed, 24 not run, 2 superseded)
    .venv/bin/pytest -q -p no:cacheprovider -p no:warnings tests/test_geoid.py tests/test_limits.py tests/test_instruments.py tests/test_landcover.py tests/test_platform.py
    scripts/mutation_check.sh --match "readback|null floor|null pair|bounded|suffix|registry|record.unregistered|effect channel|u_num" --no-suite

### Not verified here

* The `--null-tests` / `--uncertainty` options inside `flightsim/capture.py` and the `validate_registry` call inside `core/scenario/validate.py` (returned as integration patches; each applied to a scratch copy, compiled, and exercised -- the capture end to end on the 30 s example, the validator on a fake spec dict and on the real example).
* A null pair or a sensitivity pair on a REAL registered spec field: no spec-8 field is registered; the mechanics ran on a test registry over `environment.wind_speed` and on fake runners. The first real pairs are P1's (the atmosphere block).
* The dew-point-R readback tolerance (stated at 1e-6 relative, not measured: no dew-point write was probed).
* The host recorder's channels (`REGISTRY.host_channels()`): a contract for the C++ recorder, no engine here.
* The message catalogue's two-way test with the four new names (entries returned, not written).

### Limitations

* `RECORD_VERSION` stays 1: the structured model rides as `model_block` beside the string `model`; at the integrator's bump the blueprint's spelling (`model` = block, `model_name` = string) is a rename in `to_dict`/`from_dict` and in the four producers' readers.
* The limits monitor's `exceed_*` columns keep their names (the blueprint's `*_flag` rename is the limits owner's and would move I2's contract and 38 tests); `channel_unit` keeps its `exceed_` special case AND the registry entry, so no `?` appears either way.
* The null floors are three constants by unit (m, deg, kt, m/s); Pa, %, g, `1` have no floor and are reported ungraded. u_num's order is assumed 1 unless `three_rate_study` ran (three extra flights); the sensitivity is a secant at the final common sample.
* `srq_series` derives north/east from lat/lon with the WGS 84 radii at the first sample (fine over a 30 s track, not over a long one).
* `null_spec_dict` rewrites the spec's dict and re-reads it: a section the spec's `from_dict` does not carry (any block a later wave adds without `to_dict` support) would be silently dropped in BOTH runs and the pair would compare a run with itself -- `digests.differ: false` and verdict `silent` make that visible, and `record.null_value` catches the stated-equals-null case, but not a dropped section.
* The parallel item's uncommitted edits (`core/environment/atmosphere.py`, `core/scenario/spec.py`, `validate.py`, `runner.py`, `stack.py`, `state.py`, `recorder.py`, `blocks.py`, `card.py`) were present in the working tree while these tests ran; the R1 tests are green with them and the example digests equal HEAD's.

## P1 -- the non-standard atmosphere and humidity: a stated day written before the trim and every step, read back, recorded per variable, and measured against the closed form (gap P1)

### What was measured, and what was defective

* `atmosphere/delta-T` was never written and no humidity was ever set; `EnvironmentStack.configure()` runs AFTER the trim, so a day written there would trim the aircraft in ISA air. Measured with the pre-trim hook removed (the mutation guard's failing test): the trimmed throttle is identical with and without the hot day; with the hook, delta-T +30 degC moves the trimmed throttle 0.7392 -> 0.7488 on the c172p (1500 m / 100 kt) and 0.9418 -> 0.9550 on the A320 (6000 m / 250 kt).
* JSBSim caps a dew point silently, twice, and prints: `dew-point-R` 540 written at ISA sea level reads back 518.67 (RH 100 %); a dew point of 10 degC written together with a +20 degC bias BEFORE any recomputation is capped at the pre-bias 5.25 degC ("Dew point temperature has been capped to 501.124") because `SetDewPoint` checks against the last computed temperature and pressure; 500 R written at 5000 ft reads back 499.63 R (the per-altitude vapour table, looked up at the pressure altitude on the write). Each is now a refusal by name at the scene (`atmosphere.dew_point`) and a counted limit along the flight.
* The closed form transcribed from `FGStandardAtmosphere.cpp` (v1.2.4, fetched) reproduces what the installed build delivers through the provider's own `prepare` on a real FDM over 2 airframes x 6 days (c172p 1500 m and A320 6000 m; +30, -40, +20/990 hPa/-10 degC dew point, RH 90 %, +45/1085 hPa, -60/870 hPa/-90 degC): worst relative error density 2.2e-16, temperature 1.9e-16, pressure 2.8e-16, RH 8.8e-15, vapour pressure 2.6e-15, density altitude 2.3e-14, pressure altitude 8.4e-16 -- the tests pin 0.5 %. ISA at 0 / 3000 / 11000 m agrees to 1e-9 relative. The Magnus constants reproduce JSBSim's 35.540351 psf saturation at 518.67 R only with JSBSim's own 47.88 psf-to-Pa factor (with the exact factor: 5e-6 off), so the source's factor is used there and only there.
* JSBSim's `atmosphere/sigma` divides by the DAY's sea-level density (measured 1.0 at sea level with +30 degC), not the standard day's; the item's `sigma` is the ISA ratio and the tests compare densities.
* The read-back after a step is not the property store alone: the dew point moves with one step's pressure change (JSBSim conserves the vapour mass fraction): 1.5e-6 R over 360 steps (c172p, 3 s), 2.3e-7 R over 600 steps (A320 autopilot, 5 s); delta-T and P-sl-psf read back with 0.0 error on every step; before the trim all three read back with 0.0 error.
* `compile_prompt` defaults `hold_state` to true and the autopilot's sign probe trims every airframe at a fixed 6000 m / 280 kt, which the c172p cannot reach ("udot doesn't appear to be trimmable"): any "fly the c172p" prompt fails in `run_spec` at HEAD, independent of this item (the tests state hold_state false; open issue).

### What was built

* `core/environment/atmosphere.py`: the transcription (constants, tables, lapse rates, biased breakpoints, layer pressure, Magnus, mass fraction, both cap lookups, moist gas constant, the two altitude inversions), `closed_form` / `expected_density_ratio` in SI, `problems()` (the five refusals, one list for validator and provider), `day_problem()`, and `NonStandardAtmosphere`: `from_spec`, `writes_at`, `dew_point_write_r` (the least of stated / modelled T / JSBSim's held T / the cap), `properties` (every step, counted), `observe` (read back before each write), `prepare` (before the trim: write, re-latch, read; per-variable with/without densities; exact read-back; the closed-form prediction), `applied_variables` (one record per stated variable; refuses a run never prepared), `card_block` (fixed key order), `vocabulary`, `provenance`.
* `EnvironmentStack.prepare(fdm)` (the pre-trim hook), the `observe` call at the top of `apply`, `applied_variables()`; `configure_from_spec(spec, environment=None)` calls `environment.prepare(fdm)` between the initial conditions and the trim (the feasibility probe gets a stack holding the atmosphere alone); `run_spec` builds the stack first, passes it in, and attaches the records after the limits record.
* `AtmosphereSpec` (five provenanced fields, `resolved()` applying the day word to defaulted fields only), the optional `atmosphere` spec field behind `set()`/`plan()`, `validate_atmosphere`, the `atmosphere_properties` card block, four `REQUIRED_PROPERTIES`, four state fields plus `pressure_hpa`, six recorder channels.
* Measured on the demonstration run (c172p, 1500 m / 100 kt, hot_day + 990 hPa + RH 60 %): density at the initial altitude 1.058113 -> 0.971876 kg/m3 after delta-T (54.0 R written), -> 0.949570 after P-sl-psf (2067.657989 psf), -> 0.934988 after dew-point-R (539.025531 R, the dew point RH 60 % implies at 35.25 degC): three null tests ok at threshold 0.1 %; delivered = predicted to 1e-9 (T 308.4023 K, P 840.6309 hPa, DA 2727.886 m, PA 1548.033 m, RH 60.0000, e 3415.066 Pa); the first telemetry sample carries the same six numbers; the trimmed throttle 0.7565. The ISA-trimmed aircraft held at its trim controls for 5 s: mean climb rate -0.059 m/s in ISA against -1.516 m/s in +30 degC air (c172p), +0.011 against -0.810 m/s (A320). The A320 autopilot (TECS) flight on the hot humid day holds closure (altitude 6000.02 m within 15 m, settled). Two runs of the same hot spec give the same output digest; the hot digest differs from ISA's; a STATED zero deviation differs from the default run only at the floating-point floor (4.0e-10 N lift, 3.5e-11 kg weight, 1.6e-13 deg pitch: the re-latch runs the models one more pass) -- pinned under 1e-8, bit-identity not claimed. A 60 s c172p flight costs 2.43 s (ISA) and 2.18 s (hot, humid, three writes and three read-backs per step): no measurable cost. Every committed spec example (8 spec files) keeps its canonical form and digest. 60 tests in tests/test_atmosphere.py (5.8 s); 20 mutation guards, each applied to the real file and shown to fail the tests, each restored byte-identically (sha256 checked).
* A real capture with the block stated (`examples/cameras_waypoint.yaml` + hot_day, 990 hPa, RH 60 %): 5 frames in 1.86 s, `flightsim.verify` PASSED (11 passed, 0 failed, 24 not run), the frame sidecars carry the six channels with units, run.json carries the three atmosphere records beside `limits.monitor`, the card carries `atmosphere_properties` in the fixed order, everything ASCII.

### How to demonstrate (any platform)

    find . -name __pycache__ -type d -prune -exec rm -rf {} +
    .venv/bin/pytest -o addopts="" -q -p no:cacheprovider -p no:warnings tests/test_atmosphere.py     # 60 passed
    .venv/bin/python - <<'EOF'
    from core.nl.compiler import compile_prompt
    from core.scenario.runner import run_spec
    spec = compile_prompt("fly the c172p at 1500 m and 100 kt for 3 seconds"); spec.set("hold_state", False)
    spec.set("atmosphere.day", "hot_day"); spec.set("atmosphere.sea_level_pressure_hpa", 990.0); spec.set("atmosphere.relative_humidity_pct", 60.0)
    r = run_spec(spec)
    for rec in r.manifest["applied_variables"]["applied_variables"]:
        if rec["name"].startswith("atmosphere."):
            n = rec["null_test"]; p = rec["parameters"]
            print(rec["name"], rec["value"], rec["source"], "written", p["written"], "density", round(n["without"], 6), "->", round(n["with"], 6), n["ok"], "per-step max error", p["per_step_readback"]["max_abs_error"])
    print("first sample", {c: round(r.telemetry.series(c)[0], 3) for c in ("density_altitude_m", "pressure_altitude_m", "rh_pct", "vapour_pressure_pa", "temperature_k", "pressure_hpa")})
    EOF
    # atmosphere.temperature_deviation_c 30.0 inferred written 54.0 density 1.058113 -> 0.971876 True per-step max error {'atmosphere/delta-T': 0.0, 'atmosphere/P-sl-psf': 0.0, 'atmosphere/dew-point-R': 1.5e-06}
    # atmosphere.sea_level_pressure_hpa 990.0 user written 2067.6579890818557 density 0.971876 -> 0.94957 True ...
    # atmosphere.relative_humidity_pct 60.0 user written 539.0255314802437 density 0.94957 -> 0.934988 True ...
    # first sample {'density_altitude_m': 2727.886, 'pressure_altitude_m': 1548.033, 'rh_pct': 60.0, 'vapour_pressure_pa': 3415.066, 'temperature_k': 308.402, 'pressure_hpa': 840.631}
    .venv/bin/python -c "from core.nl.compiler import compile_prompt; from core.scenario.validate import validate; s = compile_prompt('fly the c172p at 1500 m and 100 kt for 3 seconds'); s.set('atmosphere.dew_point_c', 20.0); print(validate(s, check_feasibility=False).render())"
    # ... REJECTED -- 1 constraint violated: [atmosphere.dew_point] dew point exceeds the modelled air temperature at the scene (5.25 degC at 1500 m); JSBSim would silently cap it there (requested 20 degC, limit 5.25 degC)
    .venv/bin/python - <<'EOF'
    from core.scenario.spec import ScenarioSpec
    spec = ScenarioSpec.read("examples/cameras_waypoint.yaml")
    spec.set("atmosphere.day", "hot_day"); spec.set("atmosphere.relative_humidity_pct", 60.0); spec.set("atmosphere.sea_level_pressure_hpa", 990.0)
    spec.write("runs/hot_humid_waypoint.yaml")
    EOF
    .venv/bin/python -m flightsim.capture runs/hot_humid_waypoint.yaml --out runs/p1_demo --max-previews 0 --card
    # captured: 5 frames across 1 camera(s); card: runs/p1_demo/card.json  (card.json -> "atmosphere_properties": delta-T 54.0, P-sl-psf 2067.658, dew-point-R 542.311, applied, dew_point_rule, stated)
    .venv/bin/python -m flightsim.verify runs/p1_demo        # verification PASSED (11 passed, 0 failed, 24 not run, 2 superseded)
    scripts/mutation_check.sh --match "^atmosphere:" --no-suite      # after the integrator appends the 20 guards

### Not verified here

* Any number against a real atmosphere: JSBSim's standard day is taken as the US Standard Atmosphere 1976 on the source's word (not compared with the published tables), the Magnus constants on Sonntag as the source cites him, the day words are stated choices (MIL-HDBK-310 is unreachable here).
* The engine side: the card block is pinned; no host applies it (W3 of the blueprint's Windows order: the host trim throttle within the parity bound at delta-T +30).
* The five catalogue entries and integration patch 3 (the records lifted into the capture manifest) landed at integration; see "Wave 1 integration" below.

### Limitations

* The dew point is held constant along the flight and limited to the modelled temperature and the vapour cap where the air would not admit it (counted, recorded); no humidity profile with height, no inversion, no changed lapse rate; RH 0 is dry air and writes nothing (its record's null test is honestly not ok).
* A relative humidity is stated at the scene's INITIAL altitude on the modelled temperature there; the dew point it implies is what is written and read back.
* A stated 1013.25 hPa writes 2116.2166 psf, 5.4e-6 below JSBSim's own 2116.228 psf (the exact conversion factor); the default block writes nothing.
* A stated standard day is not bit-identical to the default flight (the pre-trim re-latch; pinned under 1e-8 per column).
* The prompt compiler has no atmosphere vocabulary; the block is stated through YAML or `spec.set`.
* Record 1 shape: the read-back rides in `parameters.readback` / `parameters.per_step_readback` until the integrator lifts it into record 2's `readback` / `jsbsim_writes` fields.

## Wave 1 integration (R1 with P1)

Integrated from the returned text: nine catalogue entries, 32 guards plus four for the reconciliation below, the contracts and report sections, and the patches to `flightsim/capture.py` (the `--null-tests` and `--uncertainty` opt-ins; the records lifted into the capture manifest), `core/scenario/validate.py` (the registry check) and `core/fdm/fdm.py` (`relatch_initial_conditions`).

### What integration measured, and what was defective

* A stated day was refused by the validator: the registry claimed the `atmosphere` section with four entries and the block has five fields (the `day` word). Registered; the registry's spec fields now equal the block's field order, pinned.
* Two registry entries named `sigma` as an effect channel; no recorder writes it, so their null pairs would have refused `record.effect_channel`. Replaced by the recorded `temperature_k` and `pressure_hpa`; pinned that every spec-field entry's channels are recorded columns.
* The null of an absent field removed the key from the spec dict; every provenanced block lists all its fields, so `from_dict` refused the null spec ("missing required field"). The null is now the field unstated (`value: null`, provenance `derived`), and a spec's unstated fields run no pair.
* Floors for the atmosphere's own channels were absent (their effects were ungraded): a stated tenth of a unit, said so in the reference sentence.

### Measured here

All six null pairs on the c172p (1500 m, 100 kt, 3 s; ~2 s each): hot day 847.60 m of density altitude and 30.000 K; humid 35.99 m and 90.000 %; +30 degC 847.60 m; 990 hPa 188.85 m of pressure altitude and 19.40 hPa; 60 % humidity 532.3 Pa; a 5 degC dew point 98.26 %, 871.7 Pa, 39.30 m. A worded spec runs the word's pair only. The affected suites green; every guard target occurs exactly once; the four new guards fire.

## P2 -- the XML-injection pipeline: three physics layers enter the stock model by rewriting its XML, at neutral values to the bit (blueprint section 1, corrections 1-3)

**What landed.** `core/control/derive.py` is now an ordered pipeline over the stock aircraft XML (`tecs? -> failures -> icing -> icing_alpha -> gust_rotation`), four new system templates under `core/control/systems/`, `FlightDynamics.with_injections` beside an unchanged `with_tecs`, and `tests/test_derive_injections.py` (32 tests, 1.3 s). The default derivation is pinned unchanged: `derive("c172p")` still builds `c172p-tecs` from the same template with the same hash, and `with_injections("c172p", ("tecs",))` loads it under `expected_derived_sha256` = that hash.

**Measured here (JSBSim 1.2.4, c172p, 120 Hz).**

* *Neutral bit-identity (V18).* Stock vs derived, 8 s trimmed elevator step (-0.3 at 1 s), 960 steps x 15 properties: worst |diff| **0.0** for failures alone, icing alone, icing_alpha alone, gust_rotation alone and all four together. Every injected property reads back **exactly** what was written (12 properties, before and after three steps).
* *Correction 1, re-measured.* The research's pass-through actuator (reading and writing `fcs/elevator-cmd-norm`) with authority 0.5 and -0.3 written once: **-0.15, -0.075, -0.0375, -0.01875, ... 7e-5 by step 12** -- the command floats to zero between the host's writes. The re-anchored chain (the FCS input moved to `failure/<s>/cmd-in`, the host's property untouched) holds **-0.15 on all 100 steps**, and the elevator sits at 0.01495360487503992 rad, equal to the bit to the stock airframe commanded -0.15. The blueprint's literal "actuator output = fcs/<s>-cmd-norm" was therefore not built; the chain writes the new property.
* *JSBSim's own malfunctions on the injected actuator, position read back:* `fail_stuck` holds -0.15 through six steps of a +0.8 command; `fail_zero` -> 0 (elevator 0.07515610487503992 rad, trim only); `fail_hardover` -> +1 for a positive command (0.40135 rad, the airframe's +23 deg) and -1 for a negative one (-0.39710561145647316 rad).
* *Icing factor.* Lift factor 0.8 on the trimmed c172p at 1500 m / 100 kt CAS: **1872.5287 -> 1498.0230 lbf** on the next step, 0.8 x to 1e-12 relative (every LIFT function wrapped, 31 wraps over the six axes). The research's 2772 -> 2322 lbf (ratio 0.838) was another state and a partial wrap; the whole-axis factor is the claim, the pinned number is this one.
* *A JSBSim correction found while building icing_alpha.* A `<system>` computing alpha + shift reads the PREVIOUS step's alpha (the Systems model runs before FGAuxiliary): measured lag 5.3e-4 .. 1.5e-3 rad over six steps, and 6.8e-9 rad even at the trim's first step, so a system route is not bit-identical at shift 0. The sum is injected as a pre-axis `<function>` in `<aerodynamics>` instead: difference **0.0** at every step; the test pins `icing/alpha-effective-rad == aero/alpha-rad + shift` to the bit at shift 0 and 0.05 rad while alpha moves > 5e-4 rad per step. (Candidate for docs/JSBSIM_CORRECTIONS.md, owned by the integrator.)
* *Stall-onset shift.* Static sweep 8..22 deg in 0.25 deg steps at 100 kt CAS: the c172p lift peak at 16.25 deg requested (CL 1.4490; achieved alpha 15.95 deg) moves to **14.25 deg** (CL 1.4497) with the shift 2 deg (0.0349066 rad): **-2.0 deg**, the shift at the sweep's resolution.
* *Rotational gust.* p-equivalent 0.3 rad/s summed into the Clp term for 2 s from the longitudinal trim: roll **-30.2129 deg** against **-3.6706 deg** at 0 (p -0.2594 vs -0.0313 rad/s); the research read -30.3 vs -2.7 deg at its state. 0 is bit-identical (above).
* *Refusals, each measured on a real stock file:* DHC6 failures -> `derivation.anchor_missing` (its FCS lives in `Conventional Controls.xml`, a shared system file); p51d icing_alpha -> anchor_missing (lift against `aero/alpha-deg`); f16 failures -> anchor_missing (`<test value="fcs/aileron-cmd-norm">` reads the command outside an `<input>`); f16 icing_alpha -> anchor_missing (five alpha-rad tables); a fabricated c172p with two roll-rate terms -> anchor_missing; unknown / repeated / empty selection and deriving `c172p-fail-ice-alpha-gust` again -> `derivation.injection_conflict`; an appended byte on the built airframe or on `Systems/icing.xml`, and `with_injections(..., expected_derived_sha256="0"*64)` -> `derivation.hash_mismatch`. A320 and B747 derive with all four; p51d with three.
* *Headless vs host (correction 2).* `c172p-fail-ice-alpha-gust` and `c172p-tecs-fail-ice-alpha-gust` differ by exactly one airframe line (`    <system file="tecs"/>`) and the one `Systems/tecs.xml`; the other system files are byte-equal.
* *Guards.* 23 `mutate` lines returned (re-anchor, the cumulative-loop template, the eight neutral defaults, the wrap, the alpha substitution, the roll sum, the two hash checks and the door call, the five anchor/conflict refusals, the order, the suffix): each applied on the working copy, **23/23 fire**, nine files restored byte-identically (sha256 checked).

**The records.** Four driven variables carry a measured `reached` null test in an `AppliedVariable` built by `derive.injection_variable` (readback exact, model block versioned by the template hash, the derivation's hashes as parameters; `to_dict`/`from_dict` round trip pinned); the other eight carry the record at their neutral value with no null test. Template digests: failures.xml.tmpl fb9b4600256d..., icing.xml 295f3b0c4992..., icing_alpha.xml 8d935995c633..., gust_rotation.xml 25c585d6b59f.... The registry text (spec_path None until P3/P5/P6/P7 land the blocks) and two floors (1 N for `lift_n`/`side_force_n`, 0.1 deg/s for `roll_rate_dps`, stated) are integration patches.

**Windows note.** The host has never loaded a derived airframe: the aircraft root is hard-coded in the vendored plugin (`JSBSimMovementComponent.cpp` L411-423) and the host refuses `hold_state`. Correction 2's fifth local patch (configurable aircraft path + sha256 at the door, `VENDORED.json`) is the named next step; `ue/` is untouched here, and `verify_hashes(derived, expected_derived_sha256)` is the Python side of that door. W1 (plugin build with the patched path and the logged hash equal to the manifest's) and W6 (jammed surface constant in host telemetry) stay NOT RUN.

**Not claimed.** No airframe's icing, failure or gust response is validated (a factor scales a whole axis; the alpha shift moves the LIFT table only; the gust reaches the roll-damping term only); `icing/eta` maps to nothing until P5; the failure chain has no rate limit, lag or hydraulic topology; the rewrites hang on the stock files' spelling of their anchors; the pre-existing `tecs.xml` keeps 12 non-ASCII comment lines (not this item's); nothing engine-side reads any of it; no version bumped.

## D1 -- the EGM2008 datum extension and the datum blocks: the bakes' own geoid, cubic, cropped for an independent evaluator, declared in the spec, applied at export (gap P10)

### What was measured, and what was defective

* The EGM2008 5-minute grid fetched here from sourceforge (tarball 10,414,793 bytes, sha256 `9a57c143...` as recorded; member `geoids/egm2008-5.pgm` 18,671,444 bytes, sha256 `96d55e88...` as the research measured; header MaxBilinearError 0.478, MaxCubicError 0.294, RMS 0.012 / 0.005 m, 4320 x 2161). N(0, 0) = 17.226 m bilinear and 17.225 m cubic (EGM96: 17.163 / 17.161). The six origins (EGM2008 cubic / bilinear): Matterhorn +54.780 / +54.756, Yosemite -25.431 / -25.432, Fuji +42.421 / +42.413, Everest -28.897 / -28.968, Grand Canyon -23.435 / -23.419, Flint Hills -30.305 / -30.304 m; the bilinear numbers reproduce the blueprint's to 0.01 m, and the live EGM2008 - EGM96 difference reproduces the curated table (2.231 at the Matterhorn) to 0.001 m.
* GeographicLib's default is the 12-point cubic, not the bilinear the branch had: the three transfer matrices were transcribed from GeographicLib 2.3 `Geoid.cpp` (fetched: tarball sha256 `31148478...`, 1,701,815 bytes) and re-derived exactly in rational arithmetic from the stencil weights (C3 over 240, C3N over 372, C3S = C3N under y -> 1 - y over 372); the cubic differs from the bilinear by 0.024 m at the Matterhorn origin (EGM2008) and 0.044 m (EGM96), within the headers' bounds everywhere tested.
* N varies over a scene: over the six curated bboxes on a quarter-node lattice the EGM2008 cubic range is Matterhorn 1.232 m (364 points), Yosemite 3.388 m, Fuji 1.792 m, Everest 3.241 m, Grand Canyon 0.813 m, Flint Hills 0.600 m -- the blueprint's 0.6-3.4 m, now recorded in every block as the bound on taking the origin's N.
* A node-aligned crop IS independently evaluable: PROJ 9.3 `+inv +proj=vgridshift` on the written `.gtx` reads the grid's bilinear value at the Matterhorn origin to 1.2e-6 m (EGM2008, 7 x 10 nodes, 45.75..46.25 N, 7.333..8.083 E) and 6e-7 m (EGM96, 5 x 6 nodes), worst 1.9e-6 / 2.1e-6 m over 100 interior points, inf one node outside; `+inv` reads +17.226 m at (0, 0) and the forward pipeline -17.226 m; a header corner moved half a node misses the origin by 0.043 m (a third: 0.028 m) -- beyond the 0.01 m tolerance, which is why the alignment is recorded and checked.
* The datum block moves nothing inside the simulation and everything at export: on the synthetic bake (real bake path, EGM2008 cubic, N0 = +53.850 m at 45.9 N 7.1 E) the c172p flight with the spec's datum block stated and without it gives identical output digests (0 of the recorded columns differ), and the exported ECEF radial distance from `hae_m` minus that of JSBSim's altitude taken as ellipsoidal is +53.8495 m at every one of 28 samples, worst |difference - N0| 3.03e-4 m (the ellipsoidal normal against the geocentric radius), both flights in 1.8 s.
* Appending the channels after the digest is measurable: the recorded (non-derived) columns re-digest to `output_digest` on every run (the flat c172p run, the bake run, the A320 limits runs under the patched pins); the guard that appends them before the digest fails that pin.

### What was built

* `core/terrain/geoid.py`: `load_egm2008` / `fetch_egm2008` / `egm2008_grid` / `grid_for_model` (refusals `geoid.grid_missing`, `geoid.grid_digest`, measured on an absent file, the EGM96 grid under the EGM2008 name, a self-described EGM2008 PGM with another digest, and a fabricated tarball); `GeoidGrid.undulation_cubic` with `_raw` (pole reflection, wrap), `undulation_at`, `interpolation_bound_m`, `posting_deg`, `model_key`; `gtx_crop_nodes`, `write_gtx`, `GtxCrop` / `read_gtx`, `interior_samples`, `write_geoid_samples`, `write_gtx_bundle` (`datum.outside_grid` on a crop beyond a pole and on a point beyond a crop); `undulation_range`, `physics_frame_block`, `datum_block` extended (every I1 key kept), `bake_datum`, `model_key_of`, `datum_for_heightfield(require_block)` (`datum.sidecar_without_datum`), `dted_block` (`dted.metadata_incomplete`), `cdb_descriptor_block`, `datum_spec_problems` (`datum.physics_frame_unsupported`, `datum.model_mismatch`), `check_model_declared`, `undulation_variable(datum, run)`.
* `core/terrain/glo30.py`: `bake(..., geoid_model="auto")` chooses and refuses before fetching, writes `<key>_geoid.gtx` (6 x 6 nodes, 184 bytes on the synthetic scene) and `<key>_geoid.json`, and extends the sidecar with the re-evaluated block, `geoid_files`, `dted` (25 DSI fields, 8 ACC fields with the declared u_D and the bake's own verification) and `cdb_descriptor`.
* `core/scenario/blocks.py` `DatumSpec` (three fields, the vocabulary and its standards) and `core/scenario/spec.py` (the optional `datum` block behind `set()` / `plan()`, absent-canonical: the eight committed examples keep their digests, pinned).
* `core/scenario/runner.py`: `refuse_datum_spec`, `scene_datum_for` (before the flight), `datum_run` (after the digest: the two derived columns, the readback, the invariance, the record), `_digest_columns`; the manifest's `datum` key and the record attached after the atmosphere's.
* `experiments/datum_null_test.py`: the two-flight measurement above, printed and written with the run's record.
* 44 tests in `tests/test_geoid.py` (17 new; 4 skip by name without the cached grid) and 22 in `tests/test_datum_block.py`; 20 mutation guards, each applied to the real file and shown to fail its tests, each file restored byte-identically (sha256 checked). The verifier text (`verify_datum` v2 and `verify_datum_independent`) executed from the patch string against verify.py's own `Check` on a real bake: PASS, and FAIL by name on eight corruptions (a flipped byte, a corner off the nodes, negated nodes, nodes raised 0.05 m, a stale block, a missing file, stale samples, 99 samples).

### How to demonstrate (any platform)

    find . -name __pycache__ -type d -prune -exec rm -rf {} +
    .venv/bin/python -c "from core.terrain.geoid import fetch_egm2008; print(fetch_egm2008())"   # sourceforge, 10 MB; the digests are checked
    .venv/bin/pytest -q -o addopts="" -p no:cacheprovider -p no:warnings tests/test_geoid.py tests/test_datum_block.py -rs   # 66 passed (4 skip without the cache)
    .venv/bin/python - <<'EOF'
    from core.terrain.geoid import egm2008_grid, default_grid
    from core.terrain.glo30 import LOCATIONS
    g, e = egm2008_grid(), default_grid()
    print("(0,0)", round(g.undulation(0, 0), 3), round(g.undulation_cubic(0, 0), 3), round(e.undulation(0, 0), 3))
    for k, loc in LOCATIONS.items():
        print(f"{k:13s} EGM2008 cubic {g.undulation_cubic(loc.origin_lat, loc.origin_lon):+8.3f}  bilinear {g.undulation(loc.origin_lat, loc.origin_lon):+8.3f}")
    EOF
    # (0,0) 17.226 17.225 17.163; matterhorn +54.780 / +54.756; yosemite -25.431 / -25.432; ...
    .venv/bin/python -m experiments.datum_null_test          # bounded: digests identical True; reached: +53.8495 m (N0 +53.850); worst |d - N0| 3.03e-04 m
    .venv/bin/python -m flightsim.capture examples/cameras_waypoint.yaml --out runs/d1 --max-previews 0 && .venv/bin/python -m flightsim.verify runs/d1
    # verification PASSED (11 passed, 0 failed, 24 not run, 2 superseded); frame state carries hae_m and undulation_m (0.0 on the flat slab)
    .venv/bin/python scripts/bake_terrain.py matterhorn      # needs the GLO-30 bucket; expected: EGM2008 5-minute grid, cubic +-0.294 m, N = +54.78 m
    scripts/mutation_check.sh --match "^datum:" --no-suite   # after the integrator appends the 20 guards

### Not verified here

* A real GLO-30 bake (the bucket was not fetched): the sidecar, the crop and the DTED block were measured on a synthetic tile through the real bake path; the first `scripts/bake_terrain.py matterhorn` on a networked machine is that verification (expected N = +54.78 m cubic, crop 7 x 10 nodes).
* The verifier clauses inside `core/capture/verify.py`, `validate_datum` in the validator, the registry entries, the capture manifest's flown record and the four pin changes in other items' tests: returned as 14 integration patches, all applied together to the real files here (254 passed, 1 skipped over 11 test files; a capture and `flightsim.verify` end to end) and restored byte-identically.
* The catalogue entries (eight returned; `tests/test_messages.py` names exactly the seven refusals until they land).
* Pavlis et al. 2012 (the 0.10 m declared model uncertainty), the tide system of the grids, MIL-PRF-89020B, OGC CDB and the Copernicus DEM Product Handbook could not be fetched: every number and field name taken from them is marked declared or `[unverified here]`.
* Nothing engine-side: the host recorder's `undulation_m` / `hae_m` are the C++ contract (`host_channels`); the render.json `georeference` block and Gate 6's `datum_pixels_invariant` are the Windows order's.

### Limitations

* N is the scene origin's for the whole flight; the per-scene range (0.60-3.39 m at the curated scenes) is recorded as the bound, and a per-sample evaluation from the crop is the named next step.
* On a scene with no geoid the `undulation_m` column carries 0 by the frame's definition (as the DIS feed's I5.3 handling) and `hae_m` equals `altitude_m`; the datum block keeps `undulation_m` null and the record says which is which.
* EGM96 blocks stay bilinear (the in-tree verifier clause); the cubic alternative is available on both grids (`undulation_at`) but a cubic EGM96 block is only what a caller asks for.
* The verifier's `datum_independent` is independent of the producer's interpolation code, not of its data: the only external anchors are the recorded tarball digests and N(0, 0).
* The limits monitor's derived-column pins and the atmosphere registry pin needed patches (the two datum channels are derived columns too); the derived list now reads `[undulation_m, hae_m, <flags>]`.
* The other item's uncommitted work (`core/control/derive.py`, `core/fdm/fdm.py`, `tests/test_control.py`, the new `core/control/systems/*.xml*`, `tests/test_derive_injections.py`) was present in the working tree while these tests ran; the D1 tests are green with it and its three `derivation.*` names are the only other uncovered catalogue names.

## Wave 2 integration (P2 with D1)

Integrated from the returned text: eleven catalogue entries (three `derivation.*`, seven `geoid.*` / `datum.*` / `dted.*`, `check.datum_independent`), 44 guards, the two contracts and report sections, and the patches to core/registry.py (P2's twelve injected properties and their helper; D1's three datum words), core/record_null.py (floors in N and deg/s), core/capture/verify.py (the datum block replaced by the test-pinned P10 / D1 text; `datum_independent` run after the datum clause), core/scenario/validate.py (`validate_datum`), flightsim/capture.py (the datum record into the capture manifest), scripts/bake_terrain.py (the datum line names the interpolation and its bound), docs/JSBSIM_CORRECTIONS.md (section 15) and the test pins that enumerate registry names, derived columns and per-run records.

### What integration measured, and what was defective

* D1's verifier patch named its replacement text by reference ("the constant in tests/test_geoid.py") rather than carrying it; the block was reconstructed from that pinned constant, so the file and the pin agree by construction. Both items' other patches applied by exact text, one (the datum registry entries) re-anchored after P2's entries landed first in the same file.
* tests/test_mutation_targets.py read 569 of 590 guards: 21 D1 guards ended in a `# fires: yes` comment after `|| failures=$((failures+1))`, which the parser's line-end anchor does not read. Comments removed; the parser reads 590; every target occurs exactly once.
* The registry population pin listed neither P2's twelve injected properties nor (until D1's own test patch landed) the datum words; extended to four enumerated groups.

### Measured here

The affected suites: 482 passed, 1 skipped (58.8 s). The 44 wave-2 guards: all fire in the integrated tree (151 s). Full suite: see the commit.

## W1 -- land-cover weight layers at the Landscape's resolution, the import manifest with the datum, and the roughness inference

**What was measured, and what was defective.** The Landscape exporter (`core/terrain/landscape.py`, Gate-4 verified) resamples the heightmap to a square layout Unreal accepts, while I7's weightmaps sit on the bake grid: a layer painted at the bake grid would be one silent resampling away from the geometry under it, and no import manifest stated which layers, which datum or which bake a Landscape came from. The surface table had no row for snow or bare ground, and a georeferenced run over a baked land cover flew the steady wind with `surface: unspecified` however dense the forest. The other item is editing `core/scenario/runner.py`, `core/registry.py` and the environment stack concurrently in this tree; every patch here is against HEAD 579a8fc's text.

**What was built.** `core/terrain/weightmaps.py`, the extension of `landscape.py` (manifest, layers, three refusals), the extension of `surface.py` (snow/bare, the map, the inference, the recording provider), the script's Landscape step, 44 tests (18 + 24 new files, +3 in the extended ones), 14 guards.

**Measured on the real bakes (this container, 2026-09-28, from the scratchpad's I7 bakes).**

Yosemite (GLO-30 bake 1151 x 894 cells at 30 m, EPSG:32611, sha256 `103499666088...`; land cover tree cover 0.6866, grassland 0.2169, bare 0.0918, water 0.0031, nodata 2.1e-06): layout 1149 x 1149 (164 components x 1 section x 7 quads + 1), the heightmap's own; 12 layers of 1,320,201 bytes each written in 7.6 s; sum per texel 255..255; 6 exact texels (2 rows x 3 columns land on bake cells) agree to the count; argmax round trip 0.9601 over 1,320,201 texels, per class tree cover 0.9813 (912,126 texels), bare/sparse 0.9247 (119,364), water 0.9319 (3,863), grassland 0.9085 (283,362), snow/ice 0.7297 (74), moss/lichen 0.6944 (252), built-up 0.6853 (375), shrubland 0.6586 (785) -- the rare classes are one or two bake cells wide, so blending across their boundary moves the argmax on most of their texels; heights round trip max 0.0228 m (quantisation 0.0456 m), aspect error 0.0; manifest `datum` copied: "EGM2008 orthometric (GLO-30)", N = -25.939 m; verify with layers 0.2 s. Inference: dominant `tree_cover` 0.6866 >= 0.5 -> `forest`, z0 1.0 m, thermals None, from "WorldCover tile N36W120: dominant class 'tree_cover' (code 10) at 0.6866 of the scene (threshold 0.5); map row 10 -> 'forest' -> z0 'forest' = 1.0 m".

Grand Canyon (bake 802 x 806, EPSG:32612, sha256 `354cd02e9efd...`; tree cover 0.3015, grassland 0.2431, bare 0.2325, shrubland 0.2133, water 0.0091): layout 806 x 806 (115 x 1 x 7 + 1); 1,612 exact texels (every row lands on a cell: 806 = the bake height) agree to the count; argmax agreement 0.9572 over 649,636 texels, tree cover 0.9799 (196,785), bare 0.9613 (150,525), grassland 0.9472 (157,611), water 0.9381 (5,766), built-up 0.9372 (239), shrubland 0.9328 (138,710); 1.1 s; heights max 0.0213 m (quantisation 0.0425 m); N = -23.403 m copied. Inference: dominant `tree_cover` 0.3015 < 0.5 -> REFUSED `landcover.surface_inference` ("no one roughness describes this scene -- state a surface in the spec").

Synthetic fixture (the I7 quadrant scene, 20 x 20 bake of pure 10/30/60/80 cells): layout 127 x 127 (2 x 1 x 63 + 1); sum 255..255; 4 exact texels; argmax agreement 0.9843 (tree cover 1.0, grassland 0.9844, bare 0.9844, water 0.969), the four quadrant centres reproduce 10/30/60/80; a hand-built 3 x 3 -> 5 x 5 case gives exactly 20/25 (the five texels halfway between a 10 and an 80 column tie to 10 by legend order while the nearest cell is 80).

**The null pair, measured** (`core/record_null.run_null_pair` on a registry entry shaped as the returned patch; c172p, 50 m AGL over the flat slab, 80 kt, 15 kt from 270, 3 s open loop; `surface: forest` with provenance `inferred` against the null `unspecified` through the same log-profile path a stated word takes): `wind_speed_mps` peak |with - without| 2.4241 m/s = **4.712 kt** (with 5.2926 m/s = 10.288 kt, without 7.7167 m/s = 15.000 kt), `wind_east_mps` the same 2.4241 m/s, `wind_north_mps` 0; verdict reached (floor 0.0514 m/s), output digests differ, 4.2 s for the pair. Closed form: 15 x ln(50/1) / ln(300/1) = 10.288 kt. The in-run record on the same flight: null test with 10.288 kt, without 15.0 kt, difference -4.712 kt, threshold 0.5 kt, ok, peak at 50.0 m AGL over 360 steps; readback `log_profile_wind.z0_m` 1.0 = 1.0 (agrees); the recorded `wind_speed_mps` at the first sample after trim 5.2926 m/s (the profile's, not the spec's); the stack's providers `InferredRoughnessWind`, `DrydenTurbulence` -- no thermals. JSBSim wind-property readback on the trimmed c172p: `atmosphere/wind-north-fps`, `-east-fps`, `-down-fps` written 12.5, read 12.5 before and after three steps, `total-wind-*` 12.5 (no turbulence) -- the registry tolerance 0 absolute is measured.

**Guards.** 14, each applied to the real file with a byte copy kept, its test file run with `-x`, the file restored (sha256 of the three guarded files identical before and after): all 14 fire.

**How to demonstrate (any platform).**

    .venv/bin/pytest -q -p no:cacheprovider -p no:warnings -o addopts= tests/test_weightmaps.py tests/test_surface_inference.py
        # 39 passed, 3 skipped (the real-bake tests skip by name without a bake)
    FLIGHTSIM_BAKE_DIR=runs/terrain .venv/bin/pytest ... tests/test_weightmaps.py tests/test_surface_inference.py
        # after scripts/bake_terrain.py yosemite grand_canyon and scripts/bake_landcover.py --location <key> ...: the real-bake tests measure
    .venv/bin/python scripts/bake_landcover.py --location yosemite --cache data/worldcover --out runs/terrain
        # runs/terrain/yosemite_landcover/{yosemite_landcover_<code>.u8 x 12, yosemite_landcover_layers.json,
        #   yosemite_landscape.r16, yosemite_landscape.json}; prints the layout, sums, argmax agreement, datum line
    .venv/bin/python -m flightsim.capture examples/cameras_terrain.yaml --out runs/w1 --terrain runs/terrain/yosemite
        # after the runner patch: manifest applied_variables carries environment.surface (source inferred, forest)
    (Windows: .\.venv\Scripts\python.exe; the Landscape layer import in the editor -- ALandscape::Import with the
     manifest's weight_layers by file and code, the sha256 tag, the datum block -- is W5 and is NOT run here)

**Not verified here.** Nothing engine-side: no Landscape was built, no layer painted, no pixel measured (W5). The argmax agreement is a resampling statement, not WorldCover's accuracy (76.7 % per its manual). A real run over the Yosemite bake with the inferred surface through `flightsim.capture` (the runner and capture patches are not applied in this tree; the record was measured on the hand-built stack the patch constructs). The `--null-tests` pair for an inferred surface (the spec keeps `unspecified`). The whole suite was not run (owner instruction); `tests/test_messages.py` is red on the five new names until the catalogue entries land, and `tests/test_registry.py` / `tests/test_record_null.py` change only with the registry patch and its pins.

**Limitations.** Bilinear blending of fractions at the Landscape texels is deliberate (a fraction is a quantity; the heightmap is bilinear too) and costs 4 % of the argmax round trip on the real bakes, mostly on class boundaries and one-cell classes; nearest resampling would make the round trip exact and the class edges blocky -- a stated choice, recorded in the sidecar. One file per class (12 x R^2 bytes; 15.8 MB for Yosemite) rather than an interleaved file. The inferred class is the dominant class of the WHOLE bake, not the cover under the track; a scene split between classes refuses rather than guessing, which means a baked-land-cover scene such as Grand Canyon must state its surface to fly. z0 `smooth` for snow and bare is a stated choice, not a table row. The record's readback grades the provider's store; the JSBSim readback of the wind property is measured once. The trim is solved in the spec's wind (a stated approximation below 300 m, as for a stated word).

## P6 -- the gust provider, von Karman turbulence and layered shear: a second spectrum through JSBSim's persisting gust channel, written every step including zero, and three wind profiles that carry the whole wind (gap P2; blueprint section 1, corrections 4-6 and 9)

**What was measured, and what was defective.**

* JSBSim 1.2.4 has no von Karman type and its turbulence channel cannot be driven from outside: `atmosphere/turb-north-fps` written 10 reads 0 after one step (turb-type 0) and the Dryden process's own 0.0182 (turb-type 4); rewritten every step it reads 0.0 or the process's values (0.031, -0.043, -0.264, -0.314, -0.095). `atmosphere/gust-north-fps` written 7.0 once reads 7.0 on every one of 11 steps, the total wind 6.999999999999574; written 0 it reads 0; beside an active ttTustin process the total equals wind + gust + turb to 0.0 (5.5013). `FGWinds.h`'s "turb-type 4 resp. 5" is off by one against its enum: type 3 delivers a peak |turb-down| 9.80 fps, 4 delivers 8.13, 5 reads back 5.0 and delivers 0.0000. The vendored header is byte-identical to the fetched v1.2.4 source. Sections 16-18 for docs/JSBSIM_CORRECTIONS.md are returned as an integration patch.
* Two more facts from the same reading, stated rather than assumed: the Dryden ladder is entered with the altitude ABOVE SEA LEVEL (`Run` passes `in.AltitudeASL`, L145), and JSBSim's own trim resets `atmosphere/wind-*-fps` to 0 (33.756 fps written before `do_trim` reads 0.0 after a longitudinal trim and -4.8e-16 after a full one; trimmed throttle 0.7392 and pitch 0.386 deg identical with and without the wind). So the branch's "trimmed in the steady wind" -- and P6's profile written the same way -- is trimmed in still air, the first per-step write restoring the wind (the first sample of every windy run reads a total wind of 1e-13 m/s at HEAD too). Not changed here (every windy run's columns stay bit-identical); the `ic/vw-mag-fps` / `ic/vw-dir-deg` route (both RW; `ic/vw-north/east-fps` read-only) is the candidate fix, an open item.
* JSBSim's Tustin Dryden channel does not deliver the ladder's sigma: at the c172p's 4921 ft (exceedance row 3: 7.181 ft/s = 2.189 m/s for the moderate word) the channel's std over 60 s at seed 7 (10 Hz, controls held) is 2.39 / 15.21 / 4.07 m/s (n/e/d): w 1.9 x the ladder, v 7 x; over 600 s (the held aircraft descending) 2.92 / 12.41 / 2.99; ttMilspec 2.83 / 2.70 / 1.69. The low-altitude W20 route the branch measured (sigma_w/W20 0.107) is not the high-altitude behaviour.

**What was built.**

* `core/environment/base.py`: `OwnShipState` (position, NED velocity, attitude, span, TAS) and `GustProvider` (`gust_at`, `p_equivalent_at`, both zero by default); every existing class byte-compatible.
* `core/environment/stack.py`: the `gust` list; `own_ship_of` (span from `metrics/bw-ft`); `prepare` runs the gust providers' hooks after the atmosphere's; `apply` reads the wind and gust channels back before each write, writes the summed gust EVERY step including 0.0, writes `gust/p-equivalent-rad_sec` only where the airframe declares it and records `property` / `absent`; `delivery_report`, `recorder_extras`, `profile_wind_at`. V20 measured: 1 + 2 m/s from two providers read 3 m/s on the channel and 4 + 3 m/s in the total wind (1e-9 fps); an empty stack's apply after a 7 fps write reads 0; a provider that goes quiet is written 0 the next step; read-back error 0.0 on every gust and wind property over a 3 s run (360 written, 359 checked). Every pre-existing recorded column of four runs (c172p base / Dryden moderate / 20 kt wind; A320 light with the autopilot) is bit-identical to a `git archive HEAD` run: worst |diff| 0.0; the seven new columns are the only difference.
* `core/environment/von_karman.py`: the MIL-F-8785C spectra (integral/sigma^2 measured 1.00013 u, 0.99997 w, 1.0000 p), the sigma ladder transcribed from FGWinds.cpp L273-L288 with the Fig. 7 table (L95-L107), the scale lengths (L_u = 2 L_v = 2 L_w = 2500 ft above 2000 ft; L_w = h, L_u = L_v = h/(0.177+0.000823h)^1.2 below 1000 ft; linear between, a stated choice), sigma_p / L_p (Yeager eqs. 8, 10 via FGWinds L292-L295: 0.06450 rad/s, 81.36 m for the c172p), the Shinozuka-Jan sum of 256 log-spaced frequencies snapped to whole cycles of the table (113 distinct for 361 rows, 179 for 7201), bin energies from a log-grid cumulative integral (a linear Simpson lost 4.3 % of u in the first bin and was replaced), phases from `default_rng(SeedSequence(seed, spawn_key=(stable_hash("von_karman"),)))` (first phase 2.51559109465875 for seed 7, 3.1082881788848336 for seed 8, pinned), the frozen field convected at the pre-trim TAS (107.537 kt, kept by the trim to 2.3e-13 kt), the table `[t, u, v, w, p_g]` with row 0 latched to the run's first step (JSBSim's clock 4.875 s after the crank), `%.17g` card rows (every value round-trips str -> float exactly), the fixed-order card block and its rows digest, the record.
* Measured on the table (c172p moderate, 1500 m, 120 Hz): realised std u 2.1867, v 2.1844, w 2.1844, p 0.06441 against commanded 2.1889 / 0.06450 -- within 0.5 % on the 3 s and the 60 s table (claimed 10 %); truncated energy 0.19 % u, 0.41 % v/w, 0.37 % p; mean 0 to 1e-15; the periodogram's log-log slope over 0.1..1 rad/m on the 60 s table -1.665 (12 bands; u, v and w) against -5/3, pinned within 0.1 -- the 3 s table's -1.87 has too few lines per band and is reported, not pinned; a synthetic Omega^-2 line spectrum fits -2.0 through the same fitter; the same seed gives the same table to the bit, seed 8 differs; build 19 ms / 274 ms.
* `core/environment/shear.py`: `LayeredWind` (measured: 22.5 kt from 255 deg at 1500 m for layers 5/15/30 kt at 0/1000/2000 m, layer 1, dV/dz 0.00772 1/s; the shorter arc across north; held beyond the ends), `MilSpecShear` (u(20 ft) = W20; 12.245 kt at 3 ft and 35.991 kt at 1000 ft for W20 20 kt, z0 0.15; held and counted outside 3..1000 ft; z0 0.3 refused), `NwpFixture` (digest-checked; levels at 110.9 / 762.1 / 1457.7 / 3013.6 / 5579.4 m standard height for 1000..500 hPa), the refusals `wind_profile.layers` (fewer than two, unsorted, negative, non-numeric), `wind_profile.kind` (z0, the 3..1000 ft range), `weather.fixture_missing`, `weather.fixture_digest` (a fixture with one value edited refuses; restored it loads). `assets/nwp/synthetic_profile_2026-09-28.json` + `.provenance.json` + README: a SYNTHETIC STAND-IN (NOMADS unreachable), the sidecar carrying the URL the cache would fetch, `fetched_at: null`, `synthetic: true`, sha256 76eebcca...
* The `turbulence_model` and `wind_profile` blocks (blocks.py, spec.py, absent-canonical: the eight committed examples' digests unchanged), `validate_turbulence_model` / `validate_wind_profile` (validate.py), `environment_for` (von Karman with JSBSim's Dryden OFF; a profile in place of the uniform wind; a stated Dryden intensity/seed honoured), `trim_wind_fps`, `fdm_at_initial_conditions`, the recorder extras, `environment_delivery` in the manifest (runner.py), `gust_table_card_block` / `layered_wind_card_block` (card.py; the card's Dryden switched off beside a table), five state fields + `REQUIRED_PROPERTIES`, five `DEFAULT_CHANNELS`, seven registry entries with `_rad_s` / `_per_s` resolved before the suffix table.
* Demonstration run (c172p, 1500 m / 100 kt, 3 s, moderate, model von_karman): the gust channel read back at 120 Hz has std 2.187 / 2.177 / 2.174 m/s (the 10 Hz recorder's 31 samples 2.10 / 2.18 / 2.18); altitude within 1500 +- 0.6 m and roll to -10.05 deg (against -5.58 deg in still air over the same 3 s); every gust property read back with 0.0 error; the model record's readback agrees (tolerance 0), null test 2.174 vs 0 m/s reached, `p_equivalent: absent` (a stock airframe), table sha256 acd2ceacc242... equal to the card's; the Dryden run's gust channel is 0 everywhere; two runs of the same spec give the same digest, seed 8 differs. On the airframe derived with the `gust_rotation` injection the property exists, is written every step with 0.0 read-back error, and the roll after 3 s of the same table is -0.402 deg against -0.681 deg stock (the roll gust reaches the Clp term only there). A 60 s von Karman flight costs 3.71 s against 2.53 s Dryden (the 7201-row table 0.27 s of it); on that flight the channel std is 2.187 / 2.185 / 2.184 m/s, roll swings to -48.3 deg and altitude 1113..1529 m with the controls held.
* Null pairs (`core.record_null.run_null_pair`, c172p, 3 s, ~3 s each, digests differ, reached): intensity moderate vs none: gust 3.40 / 3.95 / 3.43 m/s, altitude 0.591 m, roll 4.47 deg; model von_karman vs dryden at the same word: gust 3.40 / 3.95 / 3.43, altitude 0.505 m, roll 4.55 deg; seed 99 vs the run's: gust 4.91 / 6.73 / 2.50, altitude 1.64 m; kind layered vs uniform: `wind_profile_speed_mps` 1.2865 (22.5 - 20 kt), dV/dz 0.0077 1/s, layer index 1, altitude 3.43 m (a crosswind; a headwind change measured 15.8 m); roughness 2.0 vs 0.15 ft at 100 m: speed 7.50 m/s, dV/dz 0.0237. The `layers` and `fixture` pairs refuse by name (their kind needs them), pinned. The "same sigma" comparison with Dryden holds at the commanded ladder (equal by construction) and NOT in the delivered channel (1.9 x / 7 x, above), said so in the test and the record.
* Tests: tests/test_von_karman.py 23, tests/test_shear.py 22, tests/test_gust_provider.py 19, tests/test_environment.py +2 (the von Karman rung of the null ladder on the B747; the persistence fact); the required suites green (195 + 232 passed) apart from the two enumerations the integrator extends. 17 mutation guards returned, each applied to the real file, its tests red, the file restored byte-identically (sha256): 17/17 fire. `scripts/mutation_check.sh`, `core/messages/catalog.yaml` and every other shared file untouched (sha256 equal to HEAD's).

**How to demonstrate (any platform).**

    find . -name __pycache__ -type d -prune -exec rm -rf {} +
    .venv/bin/pytest -o addopts="" -q -p no:cacheprovider -p no:warnings tests/test_von_karman.py tests/test_shear.py tests/test_gust_provider.py   # 64 passed
    .venv/bin/python - <<'EOF'
    from core.nl.compiler import compile_prompt
    from core.scenario.runner import run_spec
    spec = compile_prompt("fly the c172p at 1500 m and 100 kt for 3 seconds with moderate turbulence"); spec.set("hold_state", False)
    spec.set("turbulence_model.model", "von_karman")
    r = run_spec(spec)
    d = r.manifest["environment_delivery"]["gust"]
    print("gust channel std m/s", d["channel_std_mps"], "readback max error", d["max_abs_error"], "p_equivalent", d["p_equivalent"])
    rec = [x for x in r.manifest["applied_variables"]["applied_variables"] if x["name"] == "turbulence_model.model"][0]
    print(rec["readback"]["agrees"], rec["null_test"]["with"], rec["null_test"]["ok"], rec["parameters"]["table_sha256"][:12], rec["parameters"]["table"]["realised"]["w"])
    EOF
    # gust channel std m/s {'north': 2.1866, 'east': 2.1769, 'down': 2.1739} readback max error {...: 0.0, 0.0, 0.0} p_equivalent absent
    # True 2.1739 True acd2ceacc242 {'sigma_commanded': 2.1889, 'sigma_amplitudes': 2.1844, 'truncated_fraction': 0.0041, 'psd_slope': ...}
    .venv/bin/python -c "from core.nl.compiler import compile_prompt; from core.scenario.validate import validate; s = compile_prompt('fly the c172p at 1500 m and 100 kt for 3 seconds'); s.set('wind_profile.kind', 'layered'); s.set('wind_profile.layers', [[1000, 15, 260], [0, 5, 270]]); print(validate(s, check_feasibility=False).render())"
    # ... REJECTED -- 1 constraint violated: [wind_profile.layers] layer altitudes must be strictly ascending, not [1000.0, 0.0]
    scripts/mutation_check.sh --match "gust sum|von Karman|MIL-F-8785C log law|fixture|roll gust|W20|gust_table|layer index|per-second" --no-suite   # after the integrator appends the 17 guards

**Not verified here.** Any number against MIL-F-8785C, MIL-HDBK-1797 or Yeager's report themselves (unreachable; the ladder and constants are FGWinds' transcription and the blueprint's correction 5); the engine side (both card blocks pinned; W5 of the Windows order: the gust table row for row); a real NWP fetch; the catalogue entries and the enumeration patches (returned).

**Limitations.** The field is frozen along the trim heading and convected at the trim TAS; the low-wavenumber energy below the table's fundamental rides on the lowest component (the field has no wavelength longer than the table); the p_g spectrum is Yeager's first-order form; q_g, r_g are not delivered; the roll gust reaches only the derived airframe (the runner flies stock airframes today, so every run_spec record says `absent`); JSBSim's trim resets the wind written before it, for the steady and the profile paths alike; the ladder is entered with the altitude ASL; `wind_layer_index` has no floor (the existing `floor_for_unit("1") is None` pin) and `shear_dv_dz_per_s` / `gust_p_equivalent_rad_s` have none until patch 6 lands; the 3 s table's slope fit has too few lines per band; the seed stream is derived with `spawn_key=(stable_hash("von_karman"),)` directly rather than through `core.experiments.seeds.derive` (its scheme adds a replicate index); the prompt compiler has no vocabulary for the blocks and reads "wind from 270" as direction 0 (pre-existing).

## Wave 3 integration (P6 with W1)

Integrated from the returned text: thirteen catalogue entries, 31 guards plus one for the reconciliation below, the two contracts and report sections, and the patches to core/registry.py (the six environment entries), core/scenario/runner.py (the inference wired into P6's surface branch; the land-cover path threaded from run_spec), flightsim/capture.py (the bake's landcover.json resolved for a georeferenced run; the null pairs and the dt/2 twin fly the same configuration), core/capture/manifest.py (two `_s` channel names resolved through the registry, not the seconds suffix), core/record_null.py (floors for 1/s and rad/s), tests/test_messages.py (the three host-side card refusals allowed as future), docs/JSBSIM_CORRECTIONS.md (sections 16-18) and the test pins that enumerate registry names and sections.

### What integration measured, and what was defective

* Both items patched the same three pins in tests/test_registry.py (population, sections, spec fields); P6's landed by text and W1's were merged by hand into the union.
* W1's runner patch was written against HEAD's surface branch, which P6 had already rewritten for the wind profile; merged by hand into P6's version.
* The blueprint's "refusing landcover.surface_inference where no mapping exists" reached the flight itself: a georeferenced run over the Grand Canyon bake with no stated surface would have refused. Changed at integration to an offer -- the default surface flies, the reason rides in the environment provenance -- with a test and a guard; W1's API-level refusal and its tests are unchanged.
* tests/test_messages.py reported a phantom `randomization.seed` emitter: the f-string expansion matched P6's quoted `"seed"` unit anywhere in the validator file. Scoped to the emitting function.
* One catalogue hint carried the identifier `von_karman`; reworded.
* One P6 guard was WEAK in the integrated tree: it emptied the registry's own per-second suffix table (`_rad_s`, `_per_s`), but P6's optional patch had also added the two suffixes to the manifest's shared table, which the registry falls back to -- so nothing failed. The registry now keeps no table of its own (one convention, longest suffix first, in core/capture/manifest.py), the guard targets that table, and tests/test_registry.py pins the two names; measured firing.

### Measured here

The affected suites: 567 passed, 4 skipped (104.9 s) before the guard repair, 49 on the repaired files after it; 622 guard targets each occurring exactly once; the 32 wave-3 guards all fire (338 s for the run that found the weak one, 2 s for its re-run). Full suite: 1930 passed, 4 skipped, one R1 test whose premise ("no spec-8 field is registered") W1 ended -- restated to the six environment inputs at u_x 0 -- then green.

## P4 -- loading: payload stations and fuel written once before the trim, the centre of gravity read back against the hand calculation on five airframes, the trimmed state measured with and without (gap P4)

### What was measured, and what was defective

* Point-mass stations and `inertia/cg-x-in` existed and were never varied (PHASE3_GAP_ANALYSIS P4). Measured on JSBSim 1.2.4: the hand calculation `CG = sum(m x) / sum(m)` over the XML's `<emptywt>` at its CG location, every `<pointmass>` and every `<tank>` at the XML's own inches equals `inertia/cg-x-in` on all five configured airframes after writes and a re-latch: c172p 7.1e-15 in (46.679151 in with 136 kg at the rear seat and full fuel), A320 0.0 in (653.528372 in at 0.8 fuel), B747 6.8e-13 in (1327.000000 in with 20000 kg of fuel: every tank sits at the empty CG), DHC6 2.8e-14 in (209.351653 in), p51d 1.4e-14 in (99.264218 in) -- V13 at the 0.1 in tolerance, with margin of thirteen orders.
* The CG property is STALE until a model pass: 300 lb written to the c172p's baggage station reads `cg-x-in` 42.11702 in until `run_ic`, then 49.39450 in. The loading re-latches the initial conditions after every write (two guards, each fires).
* A write after the trim is the wrong order, measured: 300 lb at the baggage station written AFTER the trim keeps the trimmed elevator at 4.3061 deg and the aircraft, held at its trim controls, pitches 0.386 -> 9.722 deg and climbs 20.0 m in 5 s (20.29 m and 9.56 deg from the unloaded flight); written BEFORE the trim the elevator goes to 5.5368 deg (throttle 0.7392 -> 0.7584, CG +7.28 in = +0.185 m) and the loaded aircraft holds altitude like the unloaded one (-0.289 m against -0.291 m in 5 s). The loading therefore rides in `EnvironmentStack.prepare`, after the atmosphere writes, and the validator's feasibility probe trims the loaded aircraft (its CG after the trim is the hand value; guard fires).
* The p51d's twelve weapon stations are written by `Systems/weapons-weight.xml` every pass: 300 lb written reads 0.0 after one pass (the pilot station holds). They are configured unloadable with that reason and refuse `loading.station_unknown`.
* The c172p handbook arms do not equal the XML's: 37 / 73 / 95 in against 36 / 70 / 95 in (the wing tanks 48 against 56 in). Both are recorded; the XML datum is TAKEN AS the handbook datum with a 3 in uncertainty (status `inferred`); the four other airframes have no handbook half (status `unverified`) and their envelope check is recorded as not made, by name, never refused from the runner.
* The engine crank burns 0.0055 lb of the c172p's fuel before the trim (sim time 4.875 s), so the tank read-back is taken before the start and the post-trim state is recorded beside it (the trim moved the CG -4.4e-5 in).
* A tank's capacity is not a property; it is recovered from `pct-full` and agrees with every configured capacity to 1e-9 (the cross-check every prepare makes; a configured arm 5 in off refuses `loading.config` before any write, measured).
* The "0 vs 136 kg at the aft-most station" pair cannot fly on the c172p as worded: the aft-most station is the baggage area (95 in), whose handbook maximum is 120 lb (54.4 kg), and 300 lb there would also put the CG at 49.39 in, aft of the 47.3 in limit -- both refusals measured by name. The pair was flown at the aft-most SEAT (70 in) with 136 kg and at the baggage area with its 54.4 kg maximum (numbers below).

### What was built

* `core/scenario/loading.py`: the config reader (`parse_loading_config`, `load_loading_config`, refusing `loading.config`), `Station` / `Tank` / `LoadingConfig`, `point_in_polygon` (even-odd, on-edge inside), `hand_cg_in`, `LoadingPlan` (`from_spec`, `station_loads`, `tank_loads` with the proportional fill rule, `masses_and_arms`, `hand_cg_in`, `gross_lb`, `problems` -- the one refusal list --, `envelope_check`, `require_envelope`, `card_block`), `LoadingProvider` (`prepare` before the trim: cross-check, per-station writes with re-latch and read, the tanks, exact read-backs, the hand CG check; `observe` once after the trim; `applied_variables`; `manifest_block`; `card_block`; `provenance`).
* The `loading` block in the five `assets/aircraft_config/*.json` (insert-only; empty weight, stations by name with XML and handbook arms, maxima and sources, tanks with capacities, the maximum takeoff weight, the envelope polygon or its reason, the datum comparison, the policy station); `LoadingSpec` (payload, fuel_kg, fuel_fraction; absent-canonical: the eight committed examples' digests unchanged, pinned); `validate_loading`; `loading_for` / the stack wiring / the manifest's `loading` block in the runner; `loading_card_block` and the card's `loading_properties`; `cg_x_m` and `iyy_kgm2` on the state and the recorder; three registry entries; the `fuel_fraction` and `payload_kg` policy leaves with their card and realised-distribution counting.
* Measured on the demonstration run (c172p, 1500 m / 100 kt, hot day, 136 kg at "Right Passenger", full fuel): CG 42.11702 -> 45.95224 in after the seat -> 46.67915 in after the tanks (hand 46.67915 in); first sample `cg_x_m` 1.185649 m, `iyy_kgm2` 1980.18, `weight_kg` 1065.86; elevator 4.3417 deg against 4.3061 deg unloaded; the two records carry record-2 `readback` (cg-x-in against the hand CG, agrees; tank 0 contents 185.0 = 185.0), `jsbsim_writes`, `model_block`, and null tests ok (CG 42.117 -> 45.952 in at threshold 0.1 in; fuel 90.72 -> 167.83 kg at threshold 0.5 kg); the manifest lists the atmosphere before the loading; two runs give one output digest, which differs from the unloaded run's; the default block records nothing and its manifest block is null (the existing per-run record list `[limits.monitor, scene.geoid_undulation_m]` unchanged).
* Null pairs through `core.record_null.run_null_pair` on the c172p (3 s, ~2.7 s per pair, digests differ, verdict reached): 136 kg at the aft-most seat -> `cg_x_m` 0.0974 m, `iyy_kgm2` 73.1 kg m^2, `weight_kg` 136.0 kg, `elevator_deg` 0.223 deg, `pitch_deg` 0.548 deg (both reached), `altitude_m` 0.018 m; 54.4 kg at the baggage area -> 0.0806 m, 98.5 kg m^2, elevator 0.500 deg, pitch 0.179 deg; full fuel against the XML's 200 lb -> 77.11 kg, 0.0292 m, 30.2 kg m^2, elevator 0.183 deg; 150 kg of fuel -> 59.28 kg, 0.0229 m, elevator 0.141 deg; full against half fuel (two runs) -> 83.9 kg, 0.0321 m, 33.1 kg m^2, elevator 0.199 deg, pitch 0.354 deg, altitude 0.0015 m. With the floors patch applied temporarily (mass 0.5 kg, inertia 1 kg m^2, the CG channel's own 0.00254 m) `cg_x_m`, `iyy_kgm2` and `weight_kg` all read `reached`; without it the metre floor grades `cg_x_m` silent at 0.0974 m and the two new units are ungraded (said so in the record).
* A real capture (`examples/cameras_waypoint.yaml` + the loading, `--card --null-tests`): 23.3 s wall for the 30 s flight plus four pair flights; `flightsim.verify` PASSED (0 failed, 25 not run, 2 superseded); the capture manifest's `applied_variables` = geoid, instruments, limits, `loading.payload_kg`, `loading.fuel_fraction`; `null_tests` both reached; `card.json` carries `loading_properties` in the fixed order; frame 0 state `cg_x_m` 1.18565 m / `iyy_kgm2` 1980.18 with units m / kg m^2; everything ASCII. A 60 s loaded run costs 2.27 s against 2.83 s unloaded.
* 41 tests in tests/test_loading.py (39 + 2 added, all green; the full file 4 min); 20 mutation guards, each applied on a copy of the tree, shown to fail its named test, and the file restored byte-identically (sha256 compared) -- the fires log is scratchpad/guard_results.txt.

### How to demonstrate (any platform)

    find . -name __pycache__ -type d -prune -exec rm -rf {} +
    .venv/bin/pytest -q -p no:cacheprovider -p no:warnings tests/test_loading.py          # 41 passed
    .venv/bin/python - <<'EOF'
    from core.nl.compiler import compile_prompt
    from core.scenario.runner import run_spec
    spec = compile_prompt("fly the c172p at 1500 m and 100 kt for 3 seconds"); spec.set("hold_state", False)
    spec.set("loading.payload", {"Right Passenger": 136.0}); spec.set("loading.fuel_fraction", 1.0)
    r = run_spec(spec)
    for rec in r.manifest["applied_variables"]["applied_variables"]:
        if rec["name"].startswith("loading."):
            rb = rec["readback"]; n = rec["null_test"]
            print(rec["name"], rec["value"], "readback", rb["property"], round(rb["value"], 5), "vs", round(rb["written"], 5), rb["agrees"], "null", round(n["without"], 3), "->", round(n["with"], 3), n["unit"], n["ok"])
    print("first sample", {c: round(r.telemetry.series(c)[0], 4) for c in ("cg_x_m", "iyy_kgm2", "weight_kg", "elevator_deg")})
    EOF
    # loading.payload_kg {'Right Passenger': 136.0} readback inertia/cg-x-in 46.67915 vs 46.67915 True null 42.117 -> 45.952 in True
    # loading.fuel_fraction 1.0 readback propulsion/tank/contents-lbs 185.0 vs 185.0 True null 90.718 -> 167.829 kg True
    # first sample {'cg_x_m': 1.1856, 'iyy_kgm2': 1980.1789, 'weight_kg': 1065.8593, 'elevator_deg': 4.3417}
    .venv/bin/python -c "from core.nl.compiler import compile_prompt; from core.scenario.validate import validate; s = compile_prompt('fly the c172p at 1500 m and 100 kt for 3 seconds'); s.set('loading.payload', {'Baggage': 136.0}); print(validate(s, check_feasibility=False).render())"
    # ... REJECTED -- 1 constraint violated: [loading.station_mass] c172p: 136 kg at 'Baggage' is over its stated maximum (...max 120 lb = 54.4 kg from memory of the Cessna 172P POH ...) (requested 136 kg, limit 54.4 kg)
    .venv/bin/python -m flightsim.capture <spec with the loading stated> --out runs/p4_demo --max-previews 0 --card --null-tests
    .venv/bin/python -m flightsim.verify runs/p4_demo        # verification PASSED (0 failed, 25 not run, 2 superseded)
    scripts/mutation_check.sh --match "^loading:" --no-suite   # after the integrator appends the 20 guards

### Not verified here

* Every handbook number: the c172p arms, the 150 kg seat maximum (a stated choice), the 120 lb baggage limit, the envelope polygon and the five maximum takeoff weights are from memory and marked `[unverified here]` in the configs; the arm comparison's handbook half exists for the c172p only.
* The engine side -- **W4 (named, not run)**: the host applies `loading_properties` after `RunIC` and before its trim, reads `inertia/cg-x-in` back and it must lie within `tolerance_in` (0.1 in) of `expected_cg_in` (46.679 in on the demonstration card), refusing `card.loading_properties` otherwise; the host's `cg_x_m` and `iyy_kgm2` within the Gate 5 parity bound of the headless run's (W2).
* The eight catalogue entries, the twenty guards, the two floors, the `_kgm2` suffix and the ALLOWED_FUTURE line land at integration (patches below).

### Limitations

* The loading provider is an `AtmosphereProvider` by type: the stack's pre-trim hook is its atmosphere slot and `core/environment/stack.py` / `base.py` are not this item's; a `PreTrimProvider` base would be the cleaner home.
* Only `cg-x-in` is compared; JSBSim also moves the lateral and vertical CG, recorded nowhere here.
* A stated fuel MASS is shared in proportion to capacity (the p51d's drop tanks fill beside its wing tanks); no priority, unusable fuel or schedule.
* The realised distribution's counting of the two leaves is measured on a fabricated record; no campaign with them was run here.
* Without integration patch 1 the CG channel is graded against the 0.5 m altitude floor (silent at 0.097 m) and `weight_kg` / `iyy_kgm2` are ungraded.
* The prompt compiler has no loading vocabulary; the block is stated through YAML or `spec.set`.
* Observed, not this item's: the open-loop unloaded c172p descends 317 m over 60 s at 1500 m / 100 kt while the loaded one holds 1483 m; the trim's behaviour at HEAD, unchanged here.

## P3 -- the failure schedule (measured 2026-09-28/29, JSBSim 1.2.4 in .venv, 120 Hz)

**Refuted before building, from the vendored source and the A320.** The blueprint's turbine engine-out write ``propulsion/engine[i]/set-running = 0`` gives thrust 0.0 on ONE step: 11943.05 lbf trimmed, 0.000 on step 1, 11942.99 on step 2 and 11942.96 at 5 s (FGTurbine.cpp L146-L147 enters tpStart with Cutoff false and qbar 210 psf > 30; L292-L309 relights). JSBSim's cutoff (active_engine i, cutoff_cmd 1, active_engine -1) gives 0.000 lbf on every one of 600 steps, set-running 0.0, N1 83.66 -> 83.31 (step 1) -> 50.69 (1 s) -> 19.89 % (5 s), engine 1 11924.65 lbf. The piston's set-running 0 reads 1.0 on the next step (FGPiston.cpp L595-L598, windmilling relatch); magneto_cmd 0 reads back nothing (write-only, FGPropulsion.cpp L819-L820: the catalog says (W)), set-running 0.0 on the next step, power 89.07 -> -3.54 hp, thrust 226.68 lbf halved at step 47 (0.39 s), 10 % at 1.30 s, zero at step 201 (1.68 s), -40.6 lbf at 4 s; rpm 2299.9 -> 1386 (2 s) -> 823 (5 s) -> 697 (8 s) -> 686 (10 s); the mixture cutoff route differs by 0.3 % at most. Stated in the module docstring and the record's model block with the source lines.

**V15, the timing.** Run clock zero = JSBSim's sim time at the run's first step (c172p 4.900 s because the engine start cranks; A320 0.0083 s). Measured t_applied - at_s: c172p hardover at 1.0 -> 1.00000000000005 s (5e-14 late), jam at 0.0 -> 0.0 (the first step), A320 cutoff at 1.0 -> 1.00833 s (one dt late: 120 accumulated dt sum below 1.0); all within one step; every write read back on the following step with agrees true (14 of 14 events across the tests).

**The jam hold, the hardover, the float, the authority.** c172p (1500 m / 100 kt, ``("failures",)`` derivation): rudder jam at 0 s holds the rudder at 0.0 rad with max drift 0.0 over 100 steps; elevator hardover at 1 s moves the elevator from the trim-only 0.07515610487503992 rad to the +23 deg stop 0.40135 rad on the next step (null test reached, threshold 8.73e-4 rad); float of an elevator commanded -0.3 writes cmd-in 0 and the elevator returns to 0.07515610487503992 rad; float of an uncommanded aileron 0 -> 0, honestly not reached; authority 0.5 on -0.3 written once: cmd-in -0.15 on the read-back step and on every one of the next 100 (drift 0.0), elevator 0.01495360487503992 rad (P2's number to the bit). A320 with ``("tecs", "failures")``: the elevator jammed at 1 s holds at -0.12645121403107676 rad with drift 0.0 over 100 steps while TECS moved the command (range > 0 over those steps). A jam and an authority loss on the same surface: the jam wins and the authority hold reports max drift 0.1 (ok false) -- said, not hidden.

**Null pairs** (run_null_pair on failures.events, ~2.5 s per c172p pair, ~1 s per A320 pair; digests differ in all seven): c172p hardover 84.06 m / 4.87 deg / 53.31 deg pitch / 20.43 kt (reached); c172p jam 0.0 everywhere (silent: the open-loop command never moves; TECS cannot engage on the c172p here -- measured TrimError in the sign probe at 6000 m / 280 kt -- so the jam that diverges a flight is measured on the A320); c172p engine-out 8 s: 1.88 m / 4.14 deg / 1.94 deg / 14.83 kt; A320 engine-out open loop 3.08 m / 0.82 deg / 0.73 deg / 7.26 kt; under TECS 10.05 m / 0.63 deg / 1.29 deg / 3.03 kt ("energy held" is what the loop does, the measured altitude excursion is 10 m in 6 s; no yaw compensation, 0.63 deg); A320 jam under TECS calm 0.020 m (silent), in moderate turbulence 1.59 m / 1.50 deg pitch / 0.27 kt (reached; heading 0.014 deg below floor). attach_null_pair writes the hardover pair into the ``failures.events`` record (verdict reached).

**The channels.** The c172p run records ``failure_state_flag``, ``engine0_thrust_n`` (1008.39 N at the first sample), ``engine0_rpm`` (2266.2); the A320 run ``engine0/1_thrust_n`` (thrust 0 on every sample after 1.05 s of the run, > 50 kN before) and ``engine0/1_n1_pct`` (19.9 / 83.7 at the end); the flag is 0 on samples 0..10 and 1 from sample 11 for an event at 1 s (the sample at 1.0 s precedes the write inside the following step). No NaN token in telemetry.json or the manifest (measured); ``state_units`` reports N / % / rpm / 1 with no ``?``. The "NaN where absent" design was built first and measured to break tests/test_atmosphere.py's column-by-column pin and, more seriously, the browser's JSON.parse in webapp/static/index.html; it was replaced by per-airframe columns (open issue 2).

**Wiring on the patched tree** (scratch copy of HEAD 5ca68f0 + patches): tests/test_failures_block.py 20 passed; the eight committed examples' digests unchanged; the validator refuses all eight bad schedules by name and the DHC6 jam as failures.actuator_missing before any flight; the c172p run derives ``c172p-fail`` (suffix ``-fail``), the A320 engine-out run flies the stock airframe, the A320 jam under hold_state derives ``A320-tecs-fail``; the manifest's ``failures`` block, the four records (``limits.monitor``, ``failures.hardover[0]``, ``failures.engine_out[1]``, ``failures.events``, ``scene.geoid_undulation_m`` in that order) and the card block (``magneto_cmd`` 0 for the c172p engine-out, ``cutoff_cmd`` 1 for the A320) as specified; 336 neighbouring tests green including tests/test_mutation_targets.py (guard 620's target kept through ``{...} | schedule.recorder_extras()``) and tests/test_messages.py with the six entries.

**Guards**: 13, all measured to fire (each on a copy, the file restored byte-identically).

**JSBSIM_CORRECTIONS candidates for the integrator** (sections 19-22): a turbine's set-running 0 relights within one step in flight; a piston's set-running 0 is relatched by the windmilling propeller; magneto_cmd is tied with no getter (write-only); the sim clock at a run's first step is the engine start's cranking time, so a scheduled time counts from the first recorded sample.

## Wave 4 integration (P4 with P3)

Integrated from the returned text: fourteen catalogue entries, 33 guards, the two contracts and report sections, P4's patches (the loading floors and the per-channel floor table in core/record_null.py with their pin, the `_kgm2` suffix, `card.loading_properties` allowed as future) and P3's 26 patches (the `failures` block through core/scenario/blocks.py, spec.py, validate.py, runner.py, card.py, core/registry.py, the `_rpm` suffix and floor, the registry-test pins, `card.failure_schedule` allowed as future, and tests/test_failures_block.py as a new file).

### What integration measured, and what was defective

* Eleven of P3's hunks no longer matched once P4's edits to the same anchors had landed; each was merged by hand as the union the two items described.
* P3's guards field carried a prose paragraph after the last guard; it broke the script (`bash -n`) and the target parser. Removed.
* R1's `_mps2` guard lost its target when P4 extended the suffix line; retargeted.
* P4's null-pair pin expected the pitch channel as the strongest relative to its floor; P4's own floors patch makes the mass channel the strongest (136 kg over 0.5 kg). The pin now says so.

* Wave 3's CI (run 36497924281) was red on all three platforms on two P6 pins: the von Karman table's first row to 1e-15 and its `%.17g` strings byte for byte, plus the rows' sha256 as a constant. A 256-term cosine sum differs at 1e-14 relative between hosts. The same-seed pin is now bit identity within one process plus the values to 1e-12; the sha256 pin is the writing host's own text. The card's contract stands: the host reads the text, it recomputes nothing.

### Measured here

The affected suites: 640 passed, 1 skipped (97.3 s) before the two repairs, 50 on the repaired files after; tests/test_loading.py 40 passed (the 29 module-scoped flights and pairs); 655 guard targets each occurring exactly once; the 33 wave-4 guards and the retargeted one: see below. Full suite: see the commit.

## P5 -- the icing provider: Bragg's factor form on a severity ramp, written every step to the derived airframe and read back exactly, the lift falling by the factor on the first step (gap P3; blueprint section 1)

### What was measured, and what was defective

* The lift at fixed alpha falls by exactly the factor on the first step (P8's ladder row, eta 0 vs 0.2): two identically trimmed c172p (1500 m / 100 kt, the DHC6 row as a named proxy), the provider's first-step writes made on each, one step: 1872.5287 lbf un-iced, 1838.8232 lbf iced, 0.982 x to 1.1e-16 relative, alpha 0.38578 deg on both; the DHC6 (1500 m / 120 kt, its own row) 10078.629 -> 9897.214 lbf, the same ratio. "Within 1 %" is met exactly because the whole LIFT axis is wrapped (P2's form).
* The trimmed flight diverges: eta 0.2 against 0 on the c172p over 3 s moves `lift_n` 100.4 N, `drag_n` 75.5 N, `pitch_deg` 0.134 deg, `tas_kt` 0.40 kt (reached) and `altitude_m` 0.25 m (below the floor); over 10 s altitude 3.86 m, pitch 0.79 deg, TAS 0.51 kt. On the DHC6 3 s: altitude 0.61 m, pitch 0.31 deg, TAS 0.24 kt, lift 725.7 N, drag 349.8 N; 10 s: altitude 6.80 m, pitch 1.08 deg, TAS 0.50 kt.
* Every one of the eight injected properties reads back 0.0 from the value written on every one of 359 checked steps of a 360-step run (both airframes); the neutral values written before the trim read back unchanged after it.
* The aerodynamic forces at the initial conditions recompute only on a model pass (`run_ic`): the factor 0.8 leaves the lift at 1476.19 lbf until the re-latch, 1183.91 lbf after it. Each re-latch moves the c172p's IC lift by about 0.1 lbf (7e-5 relative; the DHC6 0.0), so the pre-trim measurement quotes its ratio against that: c172p 0.98222 for the factor 0.982, DHC6 0.982 exactly.
* The alpha shift moves the stall-onset alpha: P2's static sweep re-made through the provider's writes on the c172p moves the lift peak 16.25 -> 14.25 deg (-2.0 deg for 2 deg at full eta); in flight the 2 deg cue at eta 0.2 moves alpha 0.72 deg, lift 3697 N, altitude 17.7 m and pitch 11.8 deg over 3 s (DHC6: 0.84 deg, 11147 N, 7.9 m, 3.7 deg).
* A stated eta 0 keeps every recorded column within 4.0e-10 of the stock run (the five pre-trim re-latches), trimmed elevator 4.306127613982291 vs 4.306127613982379 deg; bit-identity is not claimed and the digests differ.
* The run clock: JSBSim's clock at the c172p's first step is 4.875 s (the crank), so `onset_s` counts from the first step; an onset of 1 s lands at step 120 where the accumulated clock reads 1.00000000000005 s (P3's 5e-14), and a 1 s ramp from it spans 121 steps (120..240). The recorded `icing_eta` column carries 0 through sample 10 and the ramp from sample 11 (a sample is taken after the step whose write was made at its top).
* DEFECTIVE, found and patched: the derived DHC6 does not load at HEAD -- core/control/derive.py copies the stock model's sibling FILES only, and the DHC6 keeps `Engines/PT6A-27.xml`, `Engines/Propeller.xml` and its four `Systems/*.xml` in aircraft-local subdirectories ("Could not open file: Propeller", measured). The returned derive patch copies the subdirectories (never overwriting an injected system file); with it the derived DHC6 loads and its hashes are unchanged (idempotent, measured). tests/test_icing.py flies the DHC6 through a stand-in that copies the same files into the build directory, so the test is green at HEAD and a no-op once the patch lands.
* The severity words are a STATED mapping (trace 0.05, light 0.10, moderate 0.20, severe 0.30) inside the 0..0.3 range of Bragg's Twin Otter cases; AIM 7-1-19's words are pilot reports of an accretion rate. Said in every record and in the catalogue sentence.
* The k-table numbers (k_lift -0.09, k_drag +0.34, k_pitch -0.20, k_roll -0.10, k_yaw -0.10, k_side -0.20) are a transcription from memory of the published Twin Otter k' set (Bragg et al. AIAA 2000-0360); the paper is not reachable from this container and every entry is marked `[unverified here]`. The A320, B747 and p51d carry no block and refuse `icing.airframe_data` by name (measured).

### What was built

* `core/environment/icing.py`: the k-table reader (`parse_icing_config`, `load_k_table`, `require_k_table`), `problems` (the one refusal list), `eta_at`, `icing_injections_for`, `IcingProvider` (`from_spec`, `prepare` before the trim with the five-relatch with/without measurement, `properties` every step, `observe` every step before the write, `applied_variables`, `card_block`, `manifest_block`, `vocabulary`, `provenance`).
* The `icing` block in `assets/aircraft_config/DHC6.json` (the Twin Otter row) and `c172p.json` (the same row, `proxy: true, proxy_of: DHC6`), insert-only, ASCII; `IcingSpec` (severity, eta_max, onset_s, ramp_s, alpha_shift_deg, envelope; absent-canonical, the eight committed examples' digests unchanged, pinned); `validate_icing`; `icing_for` / the stack / the derived airframe / the manifest's `icing` block in the runner; `icing_schedule_card_block` and the card's `icing_schedule`; the eight `icing_*` channels on the state and the recorder (0 / 1.0 / 0 on a stock airframe, never NaN); the registry: P2's eight icing entries given their spec fields (icing.eta -> eta_max, icing.alpha_shift_rad -> alpha_shift_deg) or kept as producer-measured observers (the six factors), plus icing.severity / onset_s / ramp_s / envelope; the `icing_eta_max` and `icing_onset_s` policy leaves with their card and realised-distribution counting.
* Measured on the demonstration run (c172p, 1500 m / 100 kt, eta_max 0.2, 3 s, 1.33 s wall): `c172p-ice-alpha` derived; 360 writes, 359 read-backs at 0.0; the trim sample carries eta 0 and factors 1.0; from the first sample eta 0.2, factors 0.982 / 1.068 / 0.96 / 0.98 / 0.98 / 0.96; seven records (`icing.eta` + six factors) each with readback agrees, jsbsim_writes, the model block and a null test: eta and lift 6566.15 -> 6449.44 N (0.98222), drag 842.8 -> 900.1 N, pitch 4048.35 -> 3923.26 N m, roll -223.56 -> -219.58, yaw 28.70 -> 30.65 N m reached, side 0 -> 0 honestly not reached; the manifest ASCII; the default block records nothing, its manifest block is null and the per-run record list stays `[limits.monitor, scene.geoid_undulation_m]`.
* A stated word, onset, ramp, shift and envelope each return a record: light / 1 s / 1 s / 2 deg / appendix_c -> `icing.severity` (readback of eta 0.10, the lift null test), `icing.onset_s` (first iced step at 1.00000000000005 s against 0, threshold one step), `icing.ramp_s` (121 steps to full against 1), `icing.alpha_shift_rad` (0.034907 rad, lift at the ICs 6566 -> 11378 N with the full shift), `icing.envelope` (bounded, 0 properties written).
* A real capture (`examples/cameras_waypoint.yaml` + severity moderate, onset 2 s, ramp 5 s, shift 2 deg; `--card --null-tests`): 16.8 s wall for the 30 s flight plus four pair flights; four pairs reached (`icing.severity`, `icing.onset_s`, `icing.ramp_s`, `icing.alpha_shift_rad`) and written into the records by `attach_null_pair`; `flightsim.verify` PASSED (11 passed, 0 failed, 25 not run, 2 superseded); the capture manifest's `applied_variables` = geoid, instruments, limits, the four stated fields and the six factors; `card.json` carries `icing_schedule` in the fixed order (eta_max 0.2, onset 2.0, ramp 5.0, the six k values, the PROXY source); the last frame's state carries eta 0.2, the factors and the 2.0 deg shift with units 1 / deg; everything ASCII.
* 32 tests in tests/test_icing.py (35 s); 17 mutation guards, each applied on a copy of the tree, shown to fail its named test (exit 1) and the file restored byte-identically (sha256 compared): 1-2 s each for the pure ones, 8-11 s for the ones that fly (the fires log is scratchpad/p5/fires_g{1,2,3}.txt).

### How to demonstrate (any platform)

    find . -name __pycache__ -type d -prune -exec rm -rf {} +
    .venv/bin/pytest -q -p no:cacheprovider -p no:warnings tests/test_icing.py          # 32 passed
    .venv/bin/python - <<'EOF'
    from core.nl.compiler import compile_prompt
    from core.scenario.runner import run_spec
    spec = compile_prompt("fly the c172p at 1500 m and 100 kt for 3 seconds"); spec.set("hold_state", False)
    spec.set("icing.severity", "moderate"); spec.set("icing.alpha_shift_deg", 2.0)
    r = run_spec(spec)
    b = r.manifest["icing"]
    print(r.manifest["fdm"]["aircraft"]["name"], "read-backs", b["per_step_readback"]["steps_checked"], "max error", max(b["per_step_readback"]["max_abs_error"].values()), "pre-trim lift ratio", round(b["prepared"]["lift_ratio_with_factors"], 5))
    for rec in r.manifest["applied_variables"]["applied_variables"]:
        if rec["name"].startswith("icing."):
            n = rec["null_test"]; rb = rec.get("readback")
            print(rec["name"], rec["value"], "readback", None if rb is None else (rb["property"], rb["value"], rb["agrees"]), "null", round(n["without"], 2), "->", round(n["with"], 2), n["unit"], n["ok"])
    print("first sample", {c: round(r.telemetry.series(c)[1], 4) for c in ("icing_eta", "icing_lift_factor", "icing_alpha_shift_deg", "lift_n")})
    EOF
    # c172p-ice-alpha read-backs 359 max error 0.0 pre-trim lift ratio 0.98222
    # icing.severity moderate readback ('icing/eta', 0.2, True) null 6566.15 -> 6449.44 N True
    # icing.alpha_shift_rad 0.0349 readback ('icing/alpha-shift-rad', 0.0349066, True) null 6566.08 -> 11377.6 N True
    # icing.lift_factor 0.982 ... icing.side_factor 0.96 null 0.0 -> 0.0 N False (symmetric ICs, said so)
    .venv/bin/python -c "from core.nl.compiler import compile_prompt; from core.scenario.validate import validate; s = compile_prompt('fly the A320 at 6000 m and 250 kt for 3 seconds'); s.set('icing.severity', 'moderate'); print(validate(s, check_feasibility=False).render())"
    # ... REJECTED -- 1 constraint violated: [icing.airframe_data] A320: no icing k-table is configured for this airframe ...
    .venv/bin/python -m flightsim.capture <spec with the icing block stated> --out runs/p5_demo --max-previews 0 --card --null-tests
    .venv/bin/python -m flightsim.verify runs/p5_demo        # verification PASSED (11 passed, 0 failed, 25 not run, 2 superseded)
    scripts/mutation_check.sh --match "^icing:" --no-suite   # after the integrator appends the 17 guards

### Not verified here

* The k-table: every number is from memory of Bragg et al. 2000 and marked `[unverified here]`; no Cessna 172 icing coefficient exists here (the c172p row is a proxy, said so in its source, its record and its card).
* The engine side -- **W9 (named, not run)**: the host loads `<fdm>-ice-alpha` through the plugin's patched aircraft path (P9's fifth local patch) with the XML sha256 checked at the door, applies `icing_schedule` at the top of every step of its own run clock (eta(t), the six factors 1 + eta k, the shift), refuses `card.icing_schedule` when a key is missing or out of order or the table is not six numbers, and its first-step lift ratio must equal the card's lift factor exactly (0.982 for eta 0.2 on the demonstration card); the eight `icing_*` channels within the Gate 5 parity bound (W2).
* The five catalogue entries, the seventeen guards, the per-channel floors, the derive subdirectory copy, the ALLOWED_FUTURE line and the registry-test pins land at integration (patches below).

### Limitations

* The provider is an `AtmosphereProvider` by type (P4's precedent): the stack's atmosphere slot carries the three hooks; a `PreTrimProvider` base would be the cleaner home.
* The factor scales the WHOLE axis: with k_pitch on the PITCH axis the elevator's Cm_delta_e is scaled with Cm_alpha, and with k_lift the C_L0 and C_L_delta_e terms with C_Lalpha -- a stated simplification of Bragg's per-coefficient k.
* The pre-trim with/without measurement re-latches the initial conditions five times; on the c172p each re-latch moves the IC lift by 0.1 lbf (the ratio reads 0.98222 for 0.982) and the recorded flight by 4.0e-10; the DHC6 shows neither.
* At HEAD the eta and factor channels have no floor (unit 1): the two-flight pairs are graded on the aero and attitude columns and the channels are reported; integration patch 1 gives them their own floors (0.01 / 0.001) without moving any pin.
* The DHC6 flies only with the derive patch (or the test's stand-in); the p51d refuses `icing.airframe_data` before its lift-in-degrees table would refuse `icing_alpha`.
* `hold_state` derives `c172p-tecs-ice-alpha` (measured) but no iced held-state flight was flown: the c172p cannot hold its state here (P3's finding) and the A320 has no k-table.
* The prompt compiler has no icing vocabulary; the block is stated through YAML or `spec.set`.
* The other item of this wave (D2) is editing core/interop and flightsim/dis.py in this same working tree; its seven `dis.*` refusal names are uncatalogued there, so tests/test_messages.py stays red at HEAD+tree until its entries land (mine are covered by the entries above).

### JSBSIM_CORRECTIONS candidates for the integrator

* The aerodynamic forces at the initial conditions are stale until a model pass: a factor written into an injected `<product>` wrap reads through `forces/fwz-aero-lbs` only after `run_ic` (1476.19 -> 1183.91 lbf for 0.8), the same stale-until-pass rule P4 measured for `inertia/cg-x-in`; each `run_ic` moves the cranked c172p's IC lift by 0.1 lbf.
* (derive.py, not JSBSim) a stock model whose engine, thruster or system files live in aircraft-local subdirectories (the DHC6) needs them beside the derived airframe: JSBSim resolves `<thruster file="Propeller">` against the aircraft directory's `Engines/` before the engine path.

## D2 -- the DIS entity-state stream: the full-rate Entity State PDU log beside the manifest, the empty-by-design entity table, the dis block, and the verifier's own round trip (gap I1; blueprint section 5)

Contract: docs/ADVANCEMENTS_CONTRACTS.md D2. Measured at ec655e2 on 2026-09-29 in the Linux container (JSBSim 1.2.4, pyproj 3.6.1 / PROJ 9.3.0, no engine); the wiring this item does not own measured on a scratch worktree of HEAD with every D2 patch applied.

### What was measured, and what was defective

* Batch 1's feed wrote an Entity State PDU log after the fact with an entity type written from memory, forward-difference dead reckoning, relative timestamps only, an orthometric-or-datum height and no verifier clause. The telemetry now carries D1's `hae_m` (so the geoid is applied at the export boundary from a recorded column) and, with the recorder patch, `yaw_rate_dps` (`velocities/r-rad_sec`, which the state already read and the recorder dropped -- I3's measured "3 absent" instrument channels were n_x, n_y and this one; with the patch the tactical profile measures 13 channels on a real capture, pinned).
* The entity type had no honest source: SISO-REF-010 could not be fetched, so the standard table ships with every septuplet null and the stream REFUSES by name until a person with the document fills a row; 5 rows (the configured airframes), 5 refusals measured, the remembered batch-1 rows kept only as the marked fallback (`--dis-entity-type fallback`), 0 = Other as the third way (`unspecified`, the absence recorded).
* The geoid at export, on a georeferenced flight through the real bake path (the synthetic peak of tests/test_datum_block.py, EGM2008 cubic, N0 = +53.850 m, c172p 3 s, 28 samples, 1.0 s flight): the decoded first PDU sits 0.000e+00 m from pyproj's EPSG:4979 -> 4978 of the recorded place at `hae_m`, and 53.8498 m (= N0 to 1e-4) from the same place at the orthometric height -- the record's null test (threshold the branch's 0.5 m altitude floor), reached, with `u_input` 0.10 m from the bake's declared u_model_m; every one of the 28 PDUs re-decoded lands on pyproj to 0.0 m. (The blueprint's "~0.02 m with N" was the JSBSim-ECEF cross-check's residual; JSBSim's own ECEF is not recorded, so the export's reference here is pyproj and the residual is at floating point.)
* Dead reckoning from recorded quantities only: on v = c t^2 the central difference is exact (2 c t) where the forward difference misses by c dt (pinned, guarded). On the 60 s B747 event run (558 samples, largest acceleration 3.778 m/s^2) central minus forward acceleration is 0.0789 m/s^2 worst, 0.0281 rms (the blueprint measured 0.069 on a banked c172p); the recorded q against batch 1's forward-difference rotation rate 0.0743 deg/s worst (|q| to 4.34 deg/s); the recorded r against the attitude's central difference 0.0043 deg/s worst, 0.0026 rms on the georeferenced run (|r| to 0.863 deg/s).
* Timestamps: absolute mode hand-checked (epoch 2026-09-29T10:15:30Z + 12.5 s = 942.5 s past the hour, LSB 1); worst error against the sample clock 8.345e-7 s (115 PDUs) and 8.369e-7 s (558 PDUs), unit 1.676 us; the modulo rollover keeps 3599.9999999 s inside 32 bits (without it: 2^32, a 33-bit field).
* The thresholded emitter reconstructs the full-rate stream within its thresholds, measured on every thresholded stream and written into the index: the 60 s event run writes 21 of 558 PDUs (3.8 %) at 1 m / 3 deg / 5 s with worst reconstruction 0.9997 m and 2.829 deg (0.22 s); 44 (7.9 %) at 0.1 m / 0.5 deg with 0.0984 m and 0.458 deg; the straight 12 s run 3 of 115 (the heartbeat alone), 0.034 m and 1.6e-4 rad. A fabricated turning, accelerating, kinematically consistent flight (120 samples) re-measures the position claim in the test with the kinematic formula written out and shows a tighter threshold emits more.
* Writing costs nothing the flight notices: 0.082 s for 558 PDUs (80352 bytes), 0.015 s for 28; a UDP send to a local receiver delivers 5 datagrams equal to the file's bytes in order; with the socket constructor forbidden the default path writes the file untouched; a campaign case refuses before any socket exists.
* The block reaches no equation of motion: six null pairs flown for real (site 7, application 3, entity 42, force_id 1, marking N12345, timestamp_mode absolute, each against its null; 12 c172p flights of 1 s) give equal output digests and peak 0.0 on lat_deg, lon_deg and hae_m -- verdict silent, the bounded invariance the registry basis states.
* The verifier's own decode (nothing imported from core/interop) on the 558-PDU capture: PASS, location 0.00e+00 m (tolerance 0.05 m), orientation 1.19e-7 rad (tolerance 1e-4 rad), timestamps strictly increasing; `flightsim.verify` prints `[PASS] dis_roundtrip` (12 passed, 0 failed, 25 not run, 2 superseded) and NOT RUN on a capture without `--dis`. FAIL by name (`check.dis_roundtrip`) on: a PDU moved 1.000 m (a 0.02 m move still passes), phi negated, psi negated, a stale undulation (52.5 m), a clock stepped back 0.17 s, a changed site id, a frame key at a PDU the stream does not hold, a header length altered, a record without its files.
* The catalogue scanner over the working tree names exactly the seven `dis.*` refusals (with the other item's four `icing.*` names present concurrently); over the patched worktree the ten names returned (the seven, the two `interop.*`, `check.dis_roundtrip`); with the returned entries appended to the worktree's catalogue tests/test_messages.py is green (23 passed).

### What was built

* `core/interop/dis.py` (extended in place, every batch-1 name kept): `load_entity_type_table`, `standard_entity_type`, `entity_type_row` (the three policies), `parse_epoch`, `timestamp_for`, `marking_for`, `sample_frames`, `central_difference`, `rvw_vectors`; refusals `dis.entity_type_unknown`, `dis.timestamp_epoch_missing`, `dis.timestamp_mode`, `dis.marking_too_long`, `dis.frame_without_geodetic`.
* `assets/dis_entity_types.yaml`: the standard table, five rows, every septuplet null with the reason, the SISO-REF-010 edition / UIDs / table cited (UIDs as remembered, marked).
* `core/interop/dis_stream.py`: `StreamOptions`, `dis_spec_problems`, `options_from_spec`, `preflight`, `in_campaign_worker`, `extrapolate` (RVW), `build_stream`, `reconstruction`, `location_null_test`, `stream_record`, `UdpSender`, `parse_udp_target`, `write_stream`, `read_index`, `frame_keys_for`, `attach_frame_keys`; refusals `dis.force_id`, `dis.udp_in_campaign` and the ones above.
* `flightsim/dis.py`: the `--stream` form (`RUN_DIR --stream [--out-dir] [--emitter] [--timestamp-mode --epoch] [--entity-type] [--marking] [--force-id] [--udp]`), so a run captured before the option existed gets its log after the fact.
* Tests: tests/test_dis.py 43 (32 batch-1 kept + 11 new), tests/test_dis_stream.py 20 (the verifier text executed against verify.py's own Check with nine corruption cases), tests/test_dis_block.py 19 (returned as a new-file patch; measured green on the patched worktree together with the 24 other affected files: 575 tests, every one green but the two catalogue tests that wait for the returned entries, 1 skip). 27 mutation guards, each applied on the real file and shown to fail its tests, each file restored byte-identically (sha256 checked): 15 on the owned files in the working tree (first reds in tests/test_dis.py and tests/test_dis_stream.py), 12 on the patched files in the worktree (the five verifier guards fail the pin test first and, with it deselected, the corruption tests themselves; the capture guards fail the capture tests; the recorder guard the capture's r-source assertion).

### How to demonstrate (any platform)

    find . -name __pycache__ -type d -prune -exec rm -rf {} +
    .venv/bin/pytest -q -p no:cacheprovider -p no:warnings tests/test_dis.py tests/test_dis_stream.py tests/test_dis_block.py    # 82 passed once the patches land
    .venv/bin/python -m flightsim.capture examples/cameras_event_trigger.yaml --out runs/d2 --max-previews 0 --dis
    #   REFUSED -- dis.entity_type_unknown: the entity-type table's row for 'B747' carries no septuplet (entered from the standard, never guessed); ...   (before any flight)
    .venv/bin/python -m flightsim.capture examples/cameras_event_trigger.yaml --out runs/d2 --max-previews 0 --dis --dis-entity-type fallback
    #   dis:      558 Entity State PDU(s) (full_rate) in runs/d2/dis_entity_state.bin, index dis_entity_state.json, keys on 29 frame(s); entity type fallback; timestamps relative; udp off
    .venv/bin/python -m flightsim.verify runs/d2                # [PASS] dis_roundtrip: 558 Entity State PDUs walked by the checker's own layout: location within 0.00e+00 m ...
    .venv/bin/python -m flightsim.dis runs/d2 --stream --entity-type unspecified --emitter thresholded --timestamp-mode absolute --epoch 2026-09-29T10:00:00Z
    #   wrote 21 Entity State PDU(s) for 558 telemetry sample(s) ... emitter thresholded (21 emitted, 537 suppressed)
    .venv/bin/python -m flightsim.dis --decode runs/d2/dis_entity_state.bin --limit 3
    .venv/bin/python -m flightsim.capture examples/cameras_multi.yaml --out runs/x --cigi     # REFUSED -- interop.cigi_not_implemented: ...
    scripts/mutation_check.sh --match "^DIS D2" --no-suite      # the 27 guards, once integrated

### Not verified here

* No DIS consumer read the stream: the wire form is checked by two readings of IEEE 1278.1-2012 written from memory (the batch-1 test's decoder and the verifier's walk), not by a second implementation. Wireshark's DIS dissector on a pcap of the UDP datagrams, or `opendis`'s PDU factory over the file's 144-byte chunks, is the networked / Windows step; neither is in the venv.
* SISO-REF-010 was not fetched: the septuplets are not asserted (the table ships empty), the cited UIDs are from memory, the force-id enumeration and the default thresholds are as remembered.
* No real GLO-30 bake: the geoid-at-export null test was measured on the synthetic peak through the real bake path (EGM2008 cubic, from the bake cache).
* Everything in the integration patches (the block, the validator, the registry, the recorder channel, the capture options, the verifier clause, the test pins) was applied and measured on a scratch worktree of HEAD, not in the working tree the other item is editing.

### Limitations

* The entity type policy `standard` refuses on every airframe out of the box: that is the honest state of the table, and `--dis-entity-type fallback | unspecified` are the two stated ways out until a row is filled.
* One entity per stream (the primary airframe; traffic aircraft are scripted meshes with no telemetry).
* The epoch is an option of the export (`--dis-epoch`), not a spec field: an instant is not part of the reproducible scenario.
* r is a recorded rate only on captures made after the recorder patch; older recordings get the attitude's central difference and the index says so.
* The run-card `dis` block the blueprint's table lists is not added: no host applies it, the card's C++ reader is P9's, and the CIGI correspondence is documentation (the contracts table).

### VV rows (docs/vva/VV_REPORT.md, section 1)

| V26 | DIS round trip: the Entity State PDU log against the recording, by the checker's own decode | **PASS** here. 558 PDUs of the 60 s B747 run: location within 0.00e+00 m of pyproj EPSG:4979 -> 4978 at the recorded (lat, lon, hae_m) (tolerance 0.05 m), orientation within 1.19e-7 rad of the checker's own Euler composition (tolerance 1e-4 rad), timestamps strictly increasing (8.4e-7 s off the sample clock); on a georeferenced bake (EGM2008, N0 = +53.850 m) the export lands on pyproj with N and 53.850 m off without; FAIL by name on a PDU moved 1 m, a flipped Euler sign, a stale undulation, a clock stepped back. Not attempted: an independent DIS decoder (Wireshark / opendis, networked) | tests/test_dis_stream.py, tests/test_dis_block.py; `python -m flightsim.verify <run>` (dis_roundtrip) |

## Wave 5 integration (P5 with D2)

Integrated from the returned text: fifteen catalogue entries, 44 guards, the two contracts and report sections, P5's nine patches (the eta / factor floors, the derive.py subdirectory fix, the registry-test pins, `card.icing_schedule` allowed as future) and D2's 24 (the `dis` block through blocks.py, spec.py, validate.py, the registry, the recorder's yaw rate, the capture command's `--dis` / `--dis-udp` / `--cigi` / `--hla`, the verifier's `dis_roundtrip` clause pinned by tests/test_dis_stream.py, the registry-test and instruments pins, and tests/test_dis_block.py as a new file).

### What integration measured, and what was defective

* Ten of D2's hunks no longer matched once P5's edits to the same anchors had landed; merged by hand as the unions both items described.
* Nothing else was defective: every other patch applied by exact text; the affected suites were green on the first run after the merges (726 passed).
* Wave 4's CI (run 36503916763): Ubuntu green; Windows red on eight shear tests and two derivation pins, macOS red on two gust pins. Two causes. (a) `.gitattributes` says `* text=auto`, so a Windows checkout writes the NWP fixture JSON and the vendored JSBSim XML with CRLF: the fixture's sha256 no longer matches its sidecar and the derivation's hashes no longer match the Linux constants. The files a hash contract covers (the vendored JSBSim data, the injected templates, the weather fixtures, the entity table) are now `-text`. (b) JSBSim's Dryden generator draws from the platform's C++ random library, so "the same seed" gives a different channel per platform (w ratio 1.86 Linux, 2.13 Windows, 2.60 macOS; the Dryden pair's roll 4.56 Linux, 6.22 macOS); the two pins that depended on it are bands with the three measurements in their docstrings. The von Karman table (our own numpy field) is unaffected.

### Measured here

The affected suites (28 files): 726 passed (144 s); 699 guard targets each occurring exactly once; the 44 wave-5 guards: see below. Full suite: see the commit.
