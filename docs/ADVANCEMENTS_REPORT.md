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
