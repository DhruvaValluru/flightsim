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
