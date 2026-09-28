# The advancement additions: contracts

Written 2026-09-28 on `claude/relaxed-cori-gccjvx` (= `phase2`) after
`docs/PHASE3_GAP_ANALYSIS.md`. These are additions to the branch, not a phase.
Each section is a contract an item is built against; the demonstration of each
item is in `docs/ADVANCEMENTS_REPORT.md`. Shared rules first.

## 0. Rules every item obeys

* **The record.** Every variable an item introduces returns the record in
  `core/records.py` (`AppliedVariable`: value, unit, provenance source, model,
  parameters, references, properties written, telemetry columns, frame keys, a
  measured null test, what is not claimed), serialised under
  `applied_variables` in the run manifest (`RunResult.manifest`) and the
  capture manifest. `record_version` 1.
* **Versions bump once.** No item bumps `SPEC_VERSION`, `MANIFEST_VERSION` or
  the bundle version on its own. New keys are optional and absent-canonical;
  the integrator bumps each version once when the addition closes, with the
  list of new keys in this file.
* **Refusals by name**, entries in `core/messages/catalog.yaml` with the
  two-way test; **verifier independence** (`core/capture/verify.py` never
  imports a producer); **a test that fails without each safeguard and a
  mutation guard** in `scripts/mutation_check.sh`; **measured, not asserted**
  (a null test here, a Gate 6 clause with a control render on Windows).
* **Shared files** (`core/messages/catalog.yaml`, `scripts/mutation_check.sh`,
  this file, the report, `NEXT.md`, `flightsim/capture.py` argument wiring)
  are integrated by one integrator in one commit per batch, from text the
  item returns; items never edit them concurrently.

## Batch 1 (no spec change): the items whose design the probes settled

Sections are appended by the integrator as each item lands.

## I1 -- the vertical datum (gap P10)

**The fact.** GLO-30 heights are EGM2008 orthometric. JSBSim's `h-sl` is height
above the WGS 84 ellipsoid (measured here: `position/radius-to-vehicle-ft` equals
the WGS 84 ellipsoid radius plus `h-sl` to 0.1 ft at latitudes 0, 27.9 and 46.005;
`geod-alt-ft` agrees to 0.06 ft). The separation is the geoid undulation N:
ellipsoidal = orthometric + N. Measured from the committed EGM96 grid at the six
curated origins: Matterhorn +52.52, Yosemite -25.94, Fuji +41.47, Everest -29.84,
Grand Canyon -23.40, Flint Hills -30.54 m; (0, 0) = 17.16 m.

**The grid.** `assets/geoid/egm96-15.pgm` (GeographicLib egm96-15, 1440 x 721
big-endian uint16, N = -108 + 0.003 * value, origin 90N 0E, header
`MaxBilinearError 1.152`), sha256
`2a12f13b6df65cdea52432c7fa1b43f34b007148eb817bf032af5af710905caa`, from tarball
sha256 `8b1ebad1ebae0a045502d0edb9cc51553da1d3914f01e07470c11b3bed75048e`
(assets/geoid/README.md: source URL, digests, licence -- EGM96 NGA public domain,
PGM packaging GeographicLib MIT/X11).

**`core/terrain/geoid.py`.** `load_grid(path=GRID_PATH, expected_sha256=GRID_SHA256)`
checks the digest on every load; `undulation(lat, lon)` is bilinear on the four
surrounding nodes (GeographicLib's default), longitude wrapped, latitude clamped
to the last row pair. `datum_block(lat, lon, orthometric_height_m, location_key)`
and `flat_datum_block(terrain_elevation_m)` build the block; `datum_for_heightfield(hf)`
returns the sidecar's own block verbatim, evaluates one from `provenance.origin_lat_deg/
origin_lon_deg` for a bake made before the block existed (orthometric height =
the raster at the projected origin), or the synthesised block when the raster names
no real place. `undulation_variable(datum)` is the `AppliedVariable`.

**Refusal by name: `terrain.geoid`** (`GeoidError.constraint`): the grid file is
absent, its sha256 is not the committed one, or it is not a GeographicLib geoid
PGM (no P5 header, no Offset/Scale, origin not 90N 0E, wrong sample count).
Also raised for a coordinate outside [-90, 90] latitude.

**The datum block** (bake sidecar `provenance.datum`; run card top-level `datum`;
capture manifest top-level `datum`; frame sidecar `context.datum`):

    vertical_datum_of_heights      "EGM2008 orthometric (GLO-30)"
    geoid_model                    "EGM96 15-minute grid (GeographicLib egm96-15)"
    origin_lat_deg, origin_lon_deg the scene origin N is evaluated at
    undulation_m                   N at the origin, bilinear
    undulation_source              {file, sha256, tarball_sha256, tarball_url,
                                    description, interpolation: "bilinear", grid: [1440, 721]}
    bilinear_error_bound_m         1.152 (the header's MaxBilinearError)
    model_difference_bound_m       13.7 (see below)
    model_difference_basis         the sentence stating how the bound was measured
    model_difference_at_origin_m   EGM2008 - EGM96 at THIS origin where measured
                                   (the six curated keys), else null
    orthometric_height_of_origin_m the raster at the projected origin
    ellipsoidal_height_of_origin_m orthometric + undulation_m
    note                           "JSBSim h-sl is ellipsoidal; heights fed to the FDM
                                    are orthometric, so JSBSim altitude equals orthometric
                                    height here; ellipsoidal = altitude + undulation_m"

A scene with no georeferenced heights carries
`{vertical_datum_of_heights: "flat slab, spec terrain_elevation" | "synthesised
heightfield, spec terrain_elevation (not a real place)", geoid_model: null,
undulation_m: null, terrain_elevation_m, note}`: `undulation_m` is null, never 0.
The glo30 sidecar's `provenance.vertical_datum` now reads "EGM2008 orthometric
(GLO-30); see the datum block" (was "treated as MSL"). `orographic_card_block`
carries `datum`; `write_run_card` lifts it to the card's top level (`datum=` also
accepted directly) so the orographic block keeps exactly the keys the C++ reads.

**The record** (`applied_variables`, `records_block`, record_version 1):
`scene.geoid_undulation_m`, unit m, source `derived`, model `EGM96 bilinear`,
parameters {vertical_datum_of_heights, origin, interpolation, bilinear_error_bound_m,
model_difference_bound_m, model_difference_at_origin_m, grid_sha256,
ellipsoidal_height_of_origin_m}, references (Lemoine et al. 1998; Pavlis et al.
2012; the grid header), no properties written, no telemetry columns, no frame
keys; null test = N at the origin (with) against 0 (without), threshold 1.152 m,
difference = the datum error the branch carried. On a flat or synthesised scene:
value null, null_test null, model "EGM96 bilinear (not applied: no georeferenced
heights)", not_claimed says why.

**Model difference, measured.** From GeographicLib `egm2008-5.pgm` (tarball sha256
`9a57c14330ac609132d324906822a9da9de265ad9b9087779793eb7080852970`, grid sha256
`96d55e88db186ddae892b00c5f8cc42a37cdac8ddb69b6de00af8c75dffb34a3`, not committed):
max |EGM2008 - EGM96| over all 1,038,240 EGM96 nodes 11.985 m (28.5 N, 94.5 E),
RMS 0.722 m, p99 3.04 m; Himalaya window 11.99, Andes 7.19, Alps 2.44, Sierra
1.79 m; at the six origins +2.231, +0.507, +0.943, +0.870, -0.016, +0.232 m.
The bound 13.7 m = node maximum + both bilinear bounds (1.152 + 0.478).

**Verifier (`verify_datum`, check name `datum`, FAIL name `scene.datum`,
patch for core/capture/verify.py).** NOT RUN when the manifest has no block or
`undulation_m` is null. FAIL by name when a key of DATUM_KEYS is missing, the
checker's own grid is absent, the block's `undulation_source.sha256` is not the
checker's grid, |manifest N - own N| > `DATUM_TOL_M` = 0.01 m, or
ellipsoidal != orthometric + N (1e-6). The checker's reader is its own 15 lines
(regex header, `>u2` frombuffer, bilinear) and imports nothing from core.terrain.

**Not claimed.** No height is converted anywhere: JSBSim altitude on this branch
still equals orthometric height and the block records N so a consumer can form
the ellipsoidal one. EGM96 is not EGM2008; the difference is bounded and measured
at the curated origins only. The bilinear bound is the interpolation error, not
the model's error against the true geoid. Nothing engine-side reads the block.
No version was bumped: `datum` and `applied_variables` are optional, absent-canonical.

## I2 -- operational and structural limit monitoring (gap P5)

**Owner files.** `core/telemetry/limits.py` (new), `core/telemetry/recorder.py`
(`Recorder.annotate`, `Recorder.derived`), `core/scenario/runner.py` (the hook and
`attach_record`), `assets/aircraft_config/*.json` (`limits` block), `tests/test_limits.py`.

**The table** (`assets/aircraft_config/<name>.json` -> `limits`). Every key present;
every number cited; every null reasoned. Refused by name `limits.config` otherwise.

```
limits:
  category:        {value: normal|utility|aerobatic|commuter|transport|military,
                    regulation: str, source: str}          # optional block
  n_z_pos_g:       {value: number > 0 | null, source: str | reason: str}
  n_z_neg_g:       {value: number < 0 | null, source | reason}
  speed_limit_kt:  {value: number > 0 | null, kind: V_NE|V_MO, source | reason}
  m_mo:            {value: number in (0, 1) | null, source | reason}
  alpha_stall_deg: {value: number in (0, 90) | null, source | reason}
  note:            str                                          # optional
```
Unknown keys, a missing limit key, a number without a source, a null without a
reason, a boolean or NaN, a wrong sign, an unknown category or speed kind: each
refuses `limits.config: <aircraft>: <why>` (`LimitsConfigError.constraint`).
An airframe with no config file or no `limits` block is NOT a refusal.

The five tables landed: c172p normal +3.8/-1.52 g, V_NE 163 kt; A320 transport
+2.5/-1.0 g, V_MO 350 kt, M_MO 0.82; B747 transport +2.5/-1.0 g, V_MO 365 kt,
M_MO 0.92; DHC6 normal +3.8/-1.52 g, V_NE 170 kt; p51d aerobatic +6.0/-3.0 g
applied as a stated PROXY for a military type, V_NE 439 kt (505 mph). Load
factors cite 14 CFR 23.337 / 25.337; every placard speed is cited
`unverified here: from memory of the POH/AFM/FCOM/TCDS`; every `m_mo` and
`alpha_stall_deg` that is null carries its reason (none of the five JSBSim
models states an `<alphalimits>` element, measured by grep).

**The monitor** (`core.telemetry.limits.monitor(columns, table) -> MonitorResult`).
Reads `t` and, per stated limit, `n_z` (g, JSBSim `accelerations/Nz`), `cas_kt`
(`velocities/vc-kts`), `mach`, `alpha_deg`. Writes one 0/1 int column per
MONITORED limit and `any_exceedance` (the OR): `exceed_nz_pos`, `exceed_nz_neg`,
`exceed_vne_or_vmo`, `exceed_mmo`, `exceed_alpha_stall`. A limit that is null,
or whose channel is not recorded, gets NO column and is listed in
`summary.unmonitored` with its reason -- a flag column for an unstated limit
would read "not exceeded" about a comparison never made. Comparison is
STRICT: `>` a positive limit, `<` a negative one; a sample exactly at the limit
is not flagged. Ragged columns or a missing `t` raise `ValueError` (a
programming error, not a refusal).

`summary`: `samples`, `comparison`, `monitored` (keys), `unmonitored`
({key: reason}), `per_limit` ({key: limit, unit, kind, channel, column,
monitored, count, first_exceedance_s, worst_margin, worst_value, worst_t_s,
source}; `worst_margin` is the distance INSIDE the limit, negative when beyond),
`any_exceedance` ({column, count, fraction, first_exceedance_s}), `columns_added`,
`columns_in_output_digest: false`, `interval_s`.

**The recorder.** `Recorder.annotate(name, values)` adds a DERIVED column after
the run: refuses a name already recorded and a length other than the sample
count; names it in `Recorder.derived`, serialised as `telemetry.json` ->
`derived` (a new, absent-canonical key). `DEFAULT_CHANNELS` is unchanged.

**The runner.** `run_spec` takes `output_digest` over the RECORDED columns, then
calls `monitor_run(recorder, aircraft)`, which loads the table, monitors,
annotates the recorder, and returns the manifest block and the record:

```
manifest["limits"] = {monitored: true, aircraft, config_path, config_sha256,
                      table: LimitsTable.to_dict(), summary: <above>}
                   | {monitored: false, aircraft, reason}
manifest["applied_variables"] = records_block([...])   # record_version 1
```
`attach_record(manifest, record)` creates the block or appends to it and
refuses a repeated name. New keys are optional and absent-canonical; no
version bumped. The flag columns are NOT in `output_digest` (measured: the
digest equals `digest_columns` over the columns minus `derived`), so a placard
change never changes the digest of a flight it did not touch. Per-frame:
`core.capture.manifest.frame_state` copies every column, flags included, with
no change to that file (measured).

**The record** `limits.monitor`: value = the five stated limits by key; unit
"g | kt CAS | Mach | deg (per key)"; source `derived`; model "exceedance
monitor against the certification envelope"; parameters {aircraft, category,
regulation, comparison, monitored, unmonitored, probe_offset, config_path,
config_sha256}; references 14 CFR 23.337, 14 CFR 25.337 and each limit's
source; `properties_written` empty (an observer); `telemetry_columns` =
`frame_keys` = the columns added; `null_test` measured PER RUN on the run's own
samples: `with` = flagged samples on the beyond side of the probe limit,
`without` = on the inside side, threshold 1 sample, where one side is the run
as flown and the other is the same samples offset so the peak sits 20 kt
(speed limit) or 0.5 g (n_z_pos, when no speed limit is stated) beyond or
inside the limit; the note says which side was flown and the offset applied.
None when neither probe limit is monitored. The record is attached only when
the airframe is monitored (an unmonitored airframe has no variable applied).

**Refusal names.** `limits.config` (new). No other name; an unmonitored airframe
and a missing channel are reported, not refused.

**Not claimed.** Position-error correction (placard KIAS compared against
JSBSim CAS); any consequence of an exceedance (the run is flagged, not
stopped; no damage, fatigue or aeroelastic effect); a stall-alpha limit where
the model states none; the placard values marked `unverified here`; a run
beyond V_NE on the c172p or p51d models (their aero tables do not trim there,
measured); a campaign-level summary (integration patch to
`core/campaign/report.py`, measured on a fabricated ledger and the demo
capture, not landed here); the V_MO+20 flight of the A320 as a statement about
the real aircraft (it is a statement about the stock JSBSim table).

## I3. Instrument models: measured channels beside truth (gap M-data, section 5.3)

**Producer** `core/telemetry/instruments.py`; **check** `core/telemetry/instruments_check.py` (imports nothing from the producer; `core/capture/verify.py` wraps it as `verify_instruments` -> check name `instruments`); **profiles** `assets/instrument_profiles/<name>.json`; **CLI** `python -m flightsim.capture ... --instruments <profile>` (default `ideal`).

**An observer, after the run.** The models read the recorded columns of `telemetry.json` and write nothing to JSBSim; no trajectory changes. The default profile `ideal` writes no file and the capture prints `instruments: ideal (the recorded channels are the measurement; no telemetry_measured.json written)`. Any other profile writes `telemetry_measured.json` beside `telemetry.json` and prints one line naming the profile, the count of measured channels, the count of truth columns absent from the recording and the normalised residual RMS.

**The profile** (`name`, `basis`, `source`, `references[]`, `imu.accelerometer`, `imu.gyro`, `gps`, `pitot_static`, `magnetometer`; every number >= 0 and finite; unknown keys refuse). Keys: `imu.accelerometer`: `bias_repeatability_mg`, `velocity_random_walk_mps_per_sqrt_h`, `bias_instability_mg`, `correlation_time_s` (> 0); `imu.gyro`: `bias_repeatability_deg_per_h`, `angle_random_walk_deg_per_sqrt_h`, `bias_instability_deg_per_h`, `correlation_time_s`; `gps`: `north_east_sigma_m` (per axis), `vertical_sigma_m`, `velocity_sigma_mps` (per axis), `update_rate_hz` (> 0), `antenna_offset_body_m` `[x fwd, y right, z down]`; `pitot_static`: `cas_sigma_kt`, `cas_lag_s`, `pressure_altitude_sigma_m`, `pressure_altitude_lag_s`; `magnetometer`: `hard_iron_sigma_fraction` (of the horizontal field, per component), `heading_sigma_deg`. A profile with no `source`, no `references`, a negative or non-finite number, a missing block, an unknown key, a zero update rate or a name that is not its file stem refuses by name **`instruments.profile`** -- BEFORE the flight (a pre-flight gate like the cameras). Shipped: `ideal` (all zero), `tactical`, `consumer_mems` (illustrative grade-typical values, every one cited as 'unverified here').

**The models** (constants from the profile; `dt` = the recorder's `interval_s`):
* IMU per body axis: constant bias `~ N(0, repeatability)` drawn once per run; white noise `sigma = density / 60 / sqrt(dt)` (VRW -> m/s^2, divided by g0 = 9.80665 to ride on the load-factor channel in g; ARW -> deg/s); bias instability as first-order Gauss-Markov `x[i] = a x[i-1] + sqrt(1-a^2) sigma w`, `a = exp(-dt/tau)`, started stationary (IEEE Std 952-2020 terms; El-Sheimy 2008; Woodman 2007). Truth = JSBSim's own accelerometer channel `n_z` (accelerations/Nz) and the recorded rates. Nothing is derived.
* GPS: fixes on the receiver's clock every `1/update_rate_hz` s from the first sample, ZERO-ORDER HOLD between fixes (`gps_fix` column: 1 at a fix sample); at a fix, position = CG + `R_body_to_NED(roll, pitch, heading) * antenna_offset_body_m` (ZYX Euler) + per-axis white noise, north/east converted to degrees by the WGS 84 meridional / prime-vertical radii at the truth latitude, down subtracted from altitude; velocity = truth + per-axis white noise (Titterton & Weston 2004 for the arm).
* Pitot-static: `y[i] = y[i-1] + dt/(tau+dt) (x[i]-y[i-1])`, `y[0] = x[0]` (backward Euler, stated in each channel entry as `discretisation`), plus white noise; CAS from `cas_kt`; pressure altitude from `pressure_altitude_m` when recorded, else `altitude_m` with `note: ISA assumed` in the entry.
* Magnetometer: `psi_meas = atan2(sin psi - by, cos psi + bx) + noise`, wrapped [0, 360), `(bx, by) ~ N(0, hard_iron_sigma_fraction)` drawn once per run (Caruso 2000).

**The file** `telemetry_measured.json` (sorted keys, indent 1, ASCII, trailing newline; `measured_version` 1): `profile` (the full profile with `sha256` and repo-relative `path`), `seeds` (`experiment_seed` = the spec's run seed, `replicate` 0, `derivation`, `generator` PCG64, `streams` {imu, gps, pitot_static, magnetometer} = the folded seeds from `core.experiments.seeds.derive`), `interval_s`, `samples`, `truth_source` "telemetry.json", `truth_sha256` (of the telemetry.json bytes beside it), `naming`, `channels[]` (per channel: `truth`, `measured`, `instrument`, `axis`, `unit`, `residual_rms`, the sigmas in the channel's unit, and the per-run draws `drawn_bias` / `drawn_hard_iron_fraction`), `absent` {truth column: why}, `draws`, `summary` {`normalised_rms`, `residual_rms` per channel}, `columns` {`t`, every truth column used, every `<truth>_meas`, `gps_fix`}, `applied_variables` (records_block with the one record). **Naming**: `<truth>_meas` beside `<truth>`; the one stated exception is `altitude_m`, measured twice as `altitude_m_gps_meas` and `altitude_m_baro_meas`. Channels whose truth the recorder lacks (`n_x`, `n_y`, `yaw_rate_dps` today) are listed under `absent`, never invented; their draws are still made so a channel's noise does not move when another appears.

**The record** `instruments.profile` (`core.records.AppliedVariable`, value = profile name, unit "profile", `source` `user` when `--instruments` was given -- even `--instruments ideal` -- else `default`, model "IEEE 952 IMU + GPS + pitot-static + magnetometer error models", parameters = the profile, the seed streams, the file name, the absent truth columns; references = the profile's; `properties_written` (); `telemetry_columns` = the measured names; `frame_keys` (); null test = measured-minus-truth RMS over every measured channel, each residual divided by its channel's stated sigma (dimensionless), `with` the profile's value, `without` 0.0 (the ideal profile, by construction), threshold 0.5). It rides in the capture manifest's `applied_variables` (attached before the manifest is written, also for `ideal`, whose null test is then 0 vs 0 and NOT ok) and in the measured file.

**Determinism**: the same run seed and profile give a byte-identical file (tested on the synthetic truth and on two real c172p captures); a different seed or profile differs.

**The check** (`instruments`; NOT RUN without `telemetry_measured.json` and with fewer than 30 samples or 30 fixes): FAIL **`instruments.file`** (unreadable, or `measured_version` not 1); FAIL **`instruments.truth`** (no telemetry.json, its sha256 differs from `truth_sha256`, `interval_s` differs, or any truth column differs value for value); FAIL **`instruments.record`** (no version-1 block, no `instruments.profile` record naming the file's profile, or a null test not ok); FAIL **`instruments.residual`** (per channel, with its OWN unit conversions, rotation, lag filter and hard-iron formula: residual standard deviation outside [1/1.5, 1.5] x the profile's sigma -- expected sigma for the IMU is `hypot(white, bias_instability)`, GPS statistics taken at the fix samples after removing the re-rotated lever arm, pitot-static about the re-filtered truth, magnetometer about the re-applied drawn hard iron; a mean residual further than 5 sampling sigmas (plus 6 x bias instability for the IMU) from its expectation (the drawn bias for the IMU, 0 otherwise); a drawn IMU bias or hard-iron component beyond 5 sigma of the profile; a held GPS sample that does not repeat the previous one exactly; a fix count off `floor(span x rate) + 1` by more than one, or a first sample that is not a fix; a non-finite measurement; a declared column absent).

**Seed streams**: `core/experiments/seeds.py` SUBSYSTEMS gains `imu`, `gps`, `pitot_static`, `magnetometer` (derivation unchanged; no other stream's sequence moves).

**Not claimed**: scale-factor, misalignment, g-sensitivity, quantisation and temperature errors; the rate random walk; GPS multipath, ionosphere, clock and geometry; the velocity lever-arm term (omega x arm: the yaw rate is not recorded); magnetometer soft iron, tilt and declination (true heading, level field); air-data position error; correlation between instruments; the fidelity of any profile number (all 'unverified here'); per-frame keys (the file is per step); any distribution shape beyond the second moment; that the draws came from the stated seed (bounded by the check, graded by the tests).

## I4. Linearised modal analysis against the handling-qualities bands (gap M2, row A5)

**What it is.** A RESULT, not a variable: `core/fdm/linearize.py` takes JSBSim's own linear model about a trimmed state (`jsbsim.FGLinearization`, exposed by the installed 1.2.4), checks it independently, and returns the classical 4x4 blocks in SI; `core/fdm/modes.py` names the modes, grades them against the MIL-F-8785C Level bands for the airframe's class and the flight phase category, and returns the record attached to the run manifest under `modes`. No `AppliedVariable` is written (rule 0 applies to introduced variables; this item introduces none, and its record says `kind: result`). No JSBSim property is written to the run's FDM: the analysis builds its own FDM from the spec (`configure_from_spec`) because linearising an executive disturbs it (measured: 223 readable properties move by 1e-10..1e-6; qdot 1.2e-10 -> -8.8e-6 rad/s^2). The flight's `output_digest` is unchanged with the block computed (measured on `examples/cameras_waypoint.yaml`: equal digests before and after, 280 samples).

**Method record** (`modes.linearization`): `method: "jsbsim.FGLinearization"`, `step: 1e-4`, `scheme`: four-point central difference `(8(f(h)-f(-h)) - (f(2h)-f(-2h)))/(12h)` at `h = 1e-4` in each state's own unit (`FGStateSpace::linearize`, read from the jsbsim-1.2.4 sdist; not settable from Python). JSBSim's state: `Vt, Alpha, Theta, Q` (+ one `Rpm` per propeller engine, none for a turbine), `Beta, Phi, P, Psi, R, Latitude, Longitude, Alt`; inputs `ThtlCmd, DaCmd, DeCmd, DrCmd`. `full` carries JSBSim's `A`, `B`, `x0`, `u0`, names and units as given (ft/s, rad, rad/s, rev/min, ft).

**Classical blocks (SI).** `states.longitudinal = [Vt, Alpha, Theta, Q]`, `states.lateral = [Beta, Phi, P, R]`, `units` (Vt m/s; angles rad; rates rad/s). `A_longitudinal`, `A_lateral`: 4x4, the rows and columns of the full matrix under the similarity transform `T A T^-1`, `T = diag(0.3048, 1, 1, 1)`; eigenvalues therefore equal JSBSim's exactly. The engine, altitude, heading and position couplings are dropped from the blocks and kept in `full` (stated).

**Residual** (`linearization.residual`): the eight classical states perturbed again by this module through `ic/` + `run_ic()` with the same restoration FGStateSpace applies (alpha alone: beta, psi, theta put back; theta through gamma with alpha kept; beta with psi kept), derivatives read from the property tree (`accelerations/udot-ft_sec2`/`vdot`/`wdot` with Vt-dot = `(u udot + v vdot + w wdot)/Vt`, `aero/alphadot-rad_sec`, `velocities/thetadot-rad_sec`, `accelerations/qdot-rad_sec2`, `aero/betadot-rad_sec`, `velocities/phidot-rad_sec`, `accelerations/pdot-rad_sec2`, `accelerations/rdot-rad_sec2`), two-point central difference at `step = 1e-4` (`RESIDUAL_STEP`), metric `||A_measured - A_jsbsim||_F / ||A_jsbsim||_F` per block in JSBSim units, keys `longitudinal`, `lateral`, `max_abs`, `max_abs_entry`, `bound = 1e-2` (`RESIDUAL_BOUND`), `ok`. Above the bound: refusal `modes.residual`. `linearization.linear_range`: the same residual at `1e-3`, reported, not bounded. `linearization.disturbance.max_abs_xdot_change`: what linearising and restoring left in the analysis executive's derivatives. One-sided differences are not used (the trim point is not an exact equilibrium: c172p pdot = -0.27 rad/s^2 after a longitudinal trim, measured; central differences cancel it).

**Modes** (`modes.{short_period, phugoid, dutch_roll, roll, spiral}`): each `{oscillatory, eigenvalues: [[re, im], ...], stable}` plus, for a pair, `omega_n_rad_s`, `zeta`, `period_s`, `time_to_half_s` or `time_to_double_s`; for a real root, `time_constant_s` (stable) and `time_to_half_s`, or `time_to_double_s`; roll and spiral carry `coupled` (a second lateral pair is a coupled roll-spiral and is reported as such). Mapping, stated and guarded: longitudinal pairs sorted by natural frequency descending, first = short period, second = phugoid; one pair + two reals: the pair is the short period when its natural frequency exceeds the larger real root, else the phugoid; four reals: two largest = short period, two smallest = phugoid. Lateral: the fastest pair = Dutch roll; of the reals the largest magnitude = roll, the smallest = spiral. `eigenvalues.{longitudinal, lateral, full}` as `[re, im]` lists. `n_alpha_g_per_rad = -V A[alpha,alpha]/g` (the alpha-dot and pitch-rate lift terms neglected, stated).

**Class and category.** `airframe_class` from `AIRFRAME_CLASS` in `core/fdm/modes.py` (c172p I, DHC6 II (land), A320 III, B747 III, p51d IV, f16 IV; each with its MIL-F-8785C 3.1.1 source, all marked unverified here), `airframe_class_source`; an airframe with no entry refuses `modes.airframe_class` (never guessed). `flight_phase_category` defaults to `B` (cruise); the CLI takes `--category A|B|C`.

**Bands** (`bands`, per class and category, and `BANDS` in code): short-period damping (MIL-F-8785C 3.2.2.1.2, Table IV: Cat A/C Level 1 0.35-1.30, 2 0.25-2.00, 3 >= 0.15; Cat B 0.30-2.00, 0.20-2.00, >= 0.15), short-period frequency (3.2.2.1.1, Figures 1-3, as CAP = omega_sp^2/(n/alpha) with an omega floor: Cat A 0.28-3.6 & >= 1.0, 0.16-10 & >= 0.6, >= 0.16; Cat B 0.085-3.6, 0.038-10, >= 0.038; Cat C 0.16-3.6 & >= 0.7, 0.096-10 & >= 0.4, >= 0.096), phugoid (3.2.1.2: zeta >= 0.04, >= 0, T2 >= 55 s), Dutch roll (3.3.1.1, Table VI general rows: min zeta / min zeta*omega / min omega; Level 1 Cat A Class I,IV 0.19/0.35/1.0, Class II,III 0.19/0.35/0.4; Cat B 0.08/0.15/0.4; Cat C Class I,IV 0.08/0.15/1.0, Class II,III 0.08/0.10/0.4; Level 2 0.02/0.05/0.4; Level 3 0/-/0.4), roll (3.3.1.2, Table VII: Level 1 Cat A and C Class I,IV 1.0 s, II,III 1.4 s, Cat B 1.4 s; Level 2 1.4 / 3.0 / 3.0; Level 3 10 s), spiral (3.3.1.3, Table VIII, min time to double: Level 1 A 12, B 20, C 12 s; Level 2 8 s; Level 3 4 s; a stable spiral meets every level). Every table carries `reference`, `confidence` (`high`, or `moderate` for the CAP figure bounds) and `verification: "unverified here: encoded from memory; the specification is not reachable from this container"`. The Table VI CO/GA row is not applied.

**Levels** (`levels.{short_period_damping, short_period_frequency, phugoid, dutch_roll, roll, spiral}`): each `{level: 1|2|3|"below 3"|null, value, band, reference, confidence, verification}`; `overall_level` = the worst. A level is a statement about the JSBSim model (no validated data), never about the aeroplane; `not_claimed` in the record says so.

**Record keys.** `modes_version: 1` (its own key; MANIFEST_VERSION not bumped, the block is optional and absent-canonical), `kind: "result"`, `kind_note`, `attempted`, `aircraft`, `airframe_class`, `airframe_class_source`, `flight_phase_category`, `trim {vt_mps, alpha_rad, theta_rad, altitude_m}`, `linearization`, `eigenvalues`, `modes`, `n_alpha_g_per_rad`, `levels`, `overall_level`, `bands`, `references`, `refusals` (`["modes.residual"]` when the bound is exceeded, else `[]`), `not_claimed`. A refused analysis in the runner is `{modes_version, kind: "result", attempted: false, refusal: <name>, reason, aircraft}` -- a run is never aborted by a result about it.

**Refusal names.** `modes.untrimmed`, `modes.linearization`, `modes.residual`, `modes.airframe_class` (all `ModesError`, `.constraint`); the CLI also prints `spec.read` and `trim` on their existing names.

**CLI.** `python -m flightsim.modes <spec.yaml> [--json out] [--category B]`: one ASCII table (mode, omega_n, zeta, period, time constant / time to half or double, level; the CAP line; the residual line; the overall level with the unverified-here note), exit 0, or `REFUSED -- <name>: ...` and exit 1.

**Not claimed.** A handling-qualities statement about any aeroplane; the band numbers as re-checked against MIL-F-8785C or MIL-STD-1797A; the pilot-in-the-loop criteria (bandwidth, time delay, PIO); the CO/GA Dutch-roll row; the DHC6 and p51d (they do not load here); a linearisation about an untrimmed state; anything on Windows or an engine.

## I5. The DIS entity-state feed (gap I1)

Files: `core/interop/geodesy.py` (WGS 84 geodetic <-> ECEF, NED and body
frames in ECEF, the DIS Euler convention, own implementation, imports only
`math`), `core/interop/dis.py` (the PDU, the stream, the run reader, the
sidecar, the record), `flightsim/dis.py` (the CLI), `tests/test_dis.py`.
No spec change, no version bump: the feed reads a run directory after the
fact and writes beside it or wherever `--out` says.

### I5.1 The stream

`python -m flightsim.dis RUN_DIR --out FILE [--site N --application N
--entity N] [--exercise N]` writes IEEE 1278.1-2012 Entity State PDUs
(protocol version 7, PDU type 1, protocol family 1), **one per telemetry
sample in sample order**, back to back with no framing; every PDU is 144
bytes (zero variable parameter records) and its header `length` says so,
so a reader walks the file by the header. Every field is big-endian. The
byte layout, by offset (the test's independent decoder is written against
this table, not against the module):

| offset | type | field |
|---|---|---|
| 0 / 1 / 2 / 3 | u8 | protocol version 7 / exercise id / PDU type 1 / family 1 |
| 4 | u32 | timestamp: 31 bits of units past the hour, LSB 1 absolute, 0 relative |
| 8 / 10 / 11 | u16 / u8 / u8 | length 144 / PDU status 0 / padding |
| 12 / 14 / 16 | u16 | entity id: site / application / entity |
| 18 / 19 | u8 | force id (0 Other) / number of variable parameters (0) |
| 20 | u8 u8 u16 u8 u8 u8 u8 | entity type: kind, domain, country, category, subcategory, specific, extra |
| 28 | same | alternative entity type (all zero) |
| 36 | f32 x3 | linear velocity, ECEF m/s |
| 48 | f64 x3 | location, ECEF m |
| 72 | f32 x3 | orientation psi, theta, phi, radians |
| 84 | u32 | appearance (0) |
| 88 / 89 | u8 / 15 bytes | dead reckoning algorithm 4 (DRM_RVW) / other parameters (zero) |
| 104 / 116 | f32 x3 | linear acceleration ECEF m/s^2 / angular velocity body rad/s |
| 128 / 129 | u8 / 11 bytes | marking character set 1 (ASCII) / marking: the airframe name, NUL padded |
| 140 | u32 | capabilities (0) |

Where each value comes from: location = the telemetry's `lat_deg`,
`lon_deg` and `altitude_m` made ellipsoidal by the run's datum (I5.3)
through `geodesy.geodetic_to_ecef`; velocity = `v_north_mps`, `v_east_mps`,
`v_down_mps` rotated into ECEF at the sample's place; orientation = the
recorded `heading_deg`, `pitch_deg`, `roll_deg` and the place through
`geodesy.dis_euler_from_ned` (I5.2); timestamp = the sample's `t`, relative
(LSB 0), rounded to the nearest unit of 3600 / 2^31 s (1.676 us; measured
worst error on a real run 8.3e-7 s), wrapping every 3600 s with simulation
time 0 at the top of the hour; dead reckoning = DERIVED by forward
differences between consecutive samples (acceleration from the ECEF
velocities; angular velocity as the rotation between the two body-from-ECEF
matrices over the interval, in the first body frame), the last sample
repeating the previous interval, a lone sample carrying zeros -- the
telemetry records roll and pitch rates but no yaw rate and no acceleration,
so none of the three is read from JSBSim, and the sidecar says so.

### I5.2 The orientation convention

DIS `(psi, theta, phi)` are the angles that carry the ECEF axes onto the
body axes (x forward, y right, z down) by a yaw about Z, a pitch about the
new Y and a roll about the new X, so `body_from_ecef = Rx(phi) . Ry(theta)
. Rz(psi)` (passive rotations). The feed forms `body_from_ecef =
body_from_ned(heading, pitch, roll) . ned_from_ecef(lat, lon)` and reads
the three angles off the product (`theta = asin(-R[0][2])`, `psi =
atan2(R[0][1], R[0][0])`, `phi = atan2(R[1][2], R[2][2])`); the inverse
`ned_from_dis_euler` recovers heading, pitch, roll. The contract is tested
by reconstruction: the body axes in ECEF from the NED route and from the
DIS angles alone agree to 1e-9 over 2000 random cases (measured worst
1.5e-14), and one case is derived by hand in the test (level, heading east
at 45 N 10 E: psi = 100 deg, theta = 0, phi = -135 deg).

### I5.3 The datum

ECEF needs an ellipsoidal height. `datum_for_run` reads `datum.undulation_m`
from `capture_manifest.json`, else `card.json`, and handles three cases,
each named in the sidecar's `datum.handling`:

* numeric N: `ellipsoidal = altitude_m + N`
  ("datum: ellipsoidal height = JSBSim altitude + datum.undulation_m (+52.520 m, <model>)");
* the block is present with `undulation_m` null (a flat or synthesised
  scene): N = 0, because JSBSim's altitude is above the ellipsoid by
  definition and no geoid applies ("datum: the run's datum block carries no
  undulation ...");
* no block at all: N = 0 and the record says
  "datum: orthometric treated as ellipsoidal (no geoid block in this run)".

Absence is never read as zero silently: the sidecar carries `undulation_m`,
`source_file` (which file the block came from, or null), `geoid_model` and
`vertical_datum_of_heights` beside the handling sentence.

### I5.4 The entity type

A small table, `ENTITY_TYPES`, for c172p, A320, B747, DHC6, p51d and f16
(kind, domain, country, category, subcategory, specific, extra), each row
with a `basis` per field: kind 1 Platform and domain 2 Air are marked
`verified` (the standard's own); country, category and subcategory are
marked `unverified here` (SISO-REF-010 could not be fetched in this
container; values written from memory: c172p 225/84/1, A320 71/86/6, B747
225/86/8, DHC6 39/85/4, p51d 225/1/0, f16 225/1/5) and a subcategory not
known is 0, the enumeration's own "unspecified", never a guess. An
airframe outside the table refuses `interop.dis.airframe`.

### I5.5 The sidecar `dis_manifest.json` (`dis_manifest_version` 1)

Keys: `format`, `stream_file`, `stream_sha256`, `stream_bytes`,
`pdu_count`, `pdu_length_bytes` (144), `samples`, `one_pdu_per_sample`,
`run_dir`, `telemetry_sha256`, `telemetry_columns_used`, `aircraft`,
`marking`, `exercise_id`, `entity_id {site, application, entity}`,
`force_id`, `entity_type`, `entity_type_basis`, `alternative_entity_type`,
`appearance`, `capabilities`, `timestamp {kind, units_per_hour,
resolution_s, epoch, first_pdu_time_past_hour_s, first_sample_t_s}`,
`datum` (I5.3), `orientation`, `velocity`, `dead_reckoning {algorithm,
name, note}`, `field_offsets`, `position_check {reference,
first_sample_geodetic, reference_ecef_m, decoded_ecef_m, residual_m,
tolerance_m 1e-3, ok, untransformed_residual_m}`, `applied_variables`
(rule 0: `records_block` over one record), `not_claimed`.

### I5.6 The record `interop.dis` (core/records.py, record_version 1)

value = the PDU count, unit `PDU`, source `derived`, model
`IEEE 1278.1-2012 ESPDU`; parameters carry the protocol constants, the
timestamp units, the datum block as handled, the entity type with its
basis, the dead-reckoning derivation note and the telemetry columns READ
(the feed records no telemetry column and no frame key, so those tuples
are empty); references cite IEEE 1278.1-2012 (from memory), SISO-REF-010
(unverified here) and WGS 84. Null test: `with` = the distance between the
decoded first PDU's ECEF location and pyproj's EPSG:4979 -> EPSG:4978 of
the telemetry's first geodetic sample at the ellipsoidal height (asserted
0 within the 1e-3 m tolerance; `position_check.ok`), `without` = the
residual a consumer carried before the feed, reading the telemetry's own
(lat, lon, alt) numbers as ECEF metres (the branch spoke no ECEF at all;
6.38e6 m on the demonstration run), threshold 1e-3 m.

### I5.7 Refusals by name

`interop.dis.run` (no telemetry.json, or unreadable), `interop.dis.channels`
(telemetry without `t`, `lat_deg`, `lon_deg`, `altitude_m`, `heading_deg`,
`pitch_deg`, `roll_deg`, `v_north_mps`, `v_east_mps`, `v_down_mps`, or
columns of unequal length), `interop.dis.airframe`, `interop.dis.entity_id`
(site/application/entity outside 0..65535, exercise outside 0..255),
`interop.dis.stream` (a file that is not whole version-7 Entity State PDUs
of 144 bytes with zero variable parameters, a truncated stream, an absent
file), `interop.dis.arguments` (the CLI given neither a run and `--out`
nor `--decode`). The CLI prints `REFUSED -- <name>: <sentence>` and exits
2; a stream whose position check fails exits 1.

### I5.8 Not claimed

No PDU is sent on any network (no socket, no multicast, no exercise
management, no heartbeat or dead-reckoning threshold logic, no other PDU
kind); HLA, CIGI and CDB are out of scope. No DIS consumer has read the
stream here. Entity-type country/category/subcategory are unverified here.
Appearance and capabilities are 0 and say nothing about the airframe.
Dead-reckoning vectors are finite differences at the 10 Hz sample rate,
not the FDM's own accelerations and rates. The ellipsoidal height is only
as good as the run's datum block (EGM96 bilinear, its stated bounds); a
run without one is orthometric treated as ellipsoidal, and says so.
Absolute timestamps are decodable, never written. No gimbal-lock handling
beyond `atan2` at |theta| = 90 deg exactly.

## I6. Normals, motion-vector and albedo ground-truth passes (gap S3)

**Engine side (uncompiled here; pinned by source-reading tests in `tests/test_gate6_visual.py`).**
`-passes=normal,velocity,albedo` (each word optional, none by default; an argument list without it is byte-identical to before) adds three AA-free captures to the `-labels` bundle, each through `ConfigureLabelCapture` (the ID pass's route: no AA/TAA, screen percentage 100, no fog/atmosphere/volumetric fog/cloud/bloom/motion blur/DOF/lens flares/translucency), `SCS_FinalColorHDR`, with one post-process material replacing the tonemapper. The materials are built by `scripts/ue_create_materials.py` on the `M_CustomStencilID` pattern (`MD_PostProcess`, `BL_ReplacingTonemapper`, one `SceneTexture` node into emissive):

| pass | material | UE 5.7 `ESceneTextureId` | target | file |
|---|---|---|---|---|
| normal | `/Game/FlightSim/M_WorldNormalPass` | `PPI_WorldNormal` (Python `PPI_WORLD_NORMAL`) | RGBA16f | `frame_NNNN_normal.png` |
| velocity | `/Game/FlightSim/M_VelocityPass` | `PPI_Velocity` (`PPI_VELOCITY`) | RGBA32f | `frame_NNNN_flow.f32` |
| albedo | `/Game/FlightSim/M_BaseColorPass` | `PPI_BaseColor` (`PPI_BASE_COLOR`) | RGBA16f | `frame_NNNN_albedo.png` |

The two signed textures are offset in the material (`value * SIGNED_SCALE + SIGNED_OFFSET`, 0.5/0.5, = the commandlet's `RenderPassSignedScale/Offset`, pinned equal by test) and decoded in the commandlet, because a negative emissive surviving the tonemapper-replacing chain is not established. The velocity target is RGBA32f because the offset encoding puts a one-pixel motion at 0.5 + 0.0016 (1280 px wide), where a half float's step is 4.9e-4 = 0.31 px against the verifier's 2 px. The velocity capture alone keeps `bAlwaysPersistRenderingState = true` (its value is a difference against the previous frame), sets `r.Velocity.ForceOutput = 1` (read back under `render_settings.console`), and renders FIRST after the physics step, before the beauty capture (engine source reading: a primitive's previous transform survives only the first scene render after it changed).

**Files per frame** (bundle addition; no version bump; every key optional and absent-canonical):
* `frame_NNNN_normal.png`: 16-bit RGBA PNG; R,G,B = `(n * 0.5 + 0.5) * 65535` for the unit normal `n` in the SCENE frame (north, east, up) -- converted from engine axes per frame with `GetENUVectorsAtEngineLocation` at the camera; A = 65535 (UE's PNG wrapper writes no RGB; readers take the first three channels).
* `frame_NNNN_flow.f32`: little-endian float32 pairs (dx, dy), row-major, width*height pairs, PIXELS, screen +x right, +y down: the displacement of the surface at this pixel from the previous captured frame of this pass to this one (decoded clip-space delta, x right / y up, times (W/2, -H/2)). The first frame of a camera is all zeros and its record says `flow_first_frame: true`.
* `frame_NNNN_albedo.png`: 16-bit RGBA PNG; R,G,B = linear base colour in [0, 1] * 65535; A = 65535.

**render.json**: frame records gain `normal_png`, `flow_f32`, `albedo_png` (the file name, or `null` when the pass is off), `normal_unit_pixels`, `flow_first_frame`, `flow_moving_pixels`, `albedo_clamped_pixels`; the root gains `passes` (`{normal|velocity|albedo: {file, encoding, frame, material, scene_texture, anti_aliasing: "none", not_claimed}}`) and `render_settings.console["r.Velocity.ForceOutput"]`.

**Refusals by name** (commandlet): `labels.pass_material` (a pass asset absent), `labels.pass_unknown` (a word other than normal/velocity/albedo), `labels.pass_needs_labels` (`-passes` without `-labels`); all after `Fail` exists and before any pass is built. The builder (`core/render/flags.py passes_flag`) refuses an unknown word itself (ValueError).

**Python side (measured here).** `core/render/flags.py`: `render_flags(..., passes=())` emits `-passes=<words in PASS_NAMES order>` after the opt-in switches only when asked. `core/capture/labels.py`: `read_rgb16_png`, `write_rgb16_png`, `encode_normals`, `read_normal_png`, `read_flow_f32` (refuses a wrong size), `read_albedo_png`, `passes_declared`, `passes_record`; `attach_engine_labels` records `labels.passes = {normal, velocity, albedo: file|null}` per frame and the `render.passes` AppliedVariable under the capture manifest's `applied_variables` (replacing a same-named record on re-run). Readers go through rasterio: Pillow returns a 16-bit RGB PNG as 8-bit (measured).

**Verifier** (`core/capture/verify.py`, own readers, no producer import), each NOT RUN without its file, never a pass on absence:
* `normals_vs_depth`: camera-space normals from the float32 depth by central differences through the record's pinhole, oriented toward the camera, vs the pass's scene normal rotated by the record's quaternion; median angle over smooth pixels (finite depth at the pixel and its four neighbours, neighbours within `SMOOTH_DEPTH_FRACTION` 0.02 of the depth, at least `NORMAL_MIN_SMOOTH_PIXELS` 100) `< NORMAL_ANGLE_TOL_DEG` 10. FAIL `annotation.normals`. NOT RUN with only the 16-bit depth PNG.
* `flow_vs_motion`: per camera, consecutive labelled frames in `t_s` order; each airframe keypoint placed by the two aircraft states and projected through the two records with the verifier's own rotation and pinhole; predicted (du, dv) vs the flow at the pixel containing the keypoint, for keypoints inside the image whose pixel carries the primary's int_id; median |error| `< FLOW_TOL_PX` 2 over at least `FLOW_MIN_KEYPOINTS` 3 samples; a `flow_first_frame` file must be zeros. FAIL `annotation.flow`. NOT RUN with one frame per camera.
* `albedo_range`: 16-bit three-channel at the record's size, finite, in [0, 1], and unlike the beauty frame (as 8-bit, `> ALBEDO_DIFFERENT_COUNTS` 2 on `>= ALBEDO_MIN_DIFFERENT_FRACTION` 1 % of pixels); mean albedo over sky pixels reported, not graded. FAIL `annotation.albedo`. Sun invariance is Gate 6's clause.

**Gate 6** (`experiments/gate6_visual.py`, Windows only): look clause "albedo sun invariance" from `LOOK_RUNS` `albedo_sun_high` / `albedo_sun_low` (`-labels -passes=albedo`, sun 60 vs 15 deg, all else equal): the beauty frames must differ on `>= 2000` terrain-band pixels (control) and the albedo images on `<= 0.1 %` of pixels beyond 257 counts of 65535; a record naming no albedo fails by the record.

**Not claimed**: that any engine wrote a file (uncompiled here); the `PPI_Velocity` decoding and the (W/2, -H/2) pixel conversion; that the vector's time base is the previous captured frame rather than the previous scene render; that the beauty digest with `-passes=velocity` equals the digest without it (Gate 10-R compares like with like); the sky pixels of the normal image; `GetENUVectorsAtEngineLocation` and the sign of north in the engine frame (a horizontal plane cannot show a north flip; Gate 6's 30 deg RMS slopes can); flow at keypoints the airframe itself occludes beyond the 2 px tolerance; flow on static geometry when `r.Velocity.ForceOutput` is absent from the build.

**New keys for the integrator's one bump**: render.json frame `normal_png`, `flow_f32`, `albedo_png`, `normal_unit_pixels`, `flow_first_frame`, `flow_moving_pixels`, `albedo_clamped_pixels`; render.json root `passes`; capture manifest frame `labels.passes`; `applied_variables` record `render.passes`.

## I7 -- land cover from ESA WorldCover (gap S5, the data half)

**Owner files.** `core/terrain/landcover.py` (new), `scripts/bake_landcover.py`
(new), `tests/test_landcover.py` (new). Nothing engine-side reads the output yet;
the engine half of S5 (a landscape material or PCG biome consuming the weightmaps)
is a later item and nothing here claims it.

**The source, measured.** ESA WorldCover 10 m 2021 v200: 3x3 degree COGs, EPSG:4326,
one uint8 band, pixel exactly 1/12000 degree (nominally 10 m), nodata 0, from the
public bucket `https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/
ESA_WorldCover_10m_2021_v200_<N36W120>_Map.tif` (stem = south-west corner). Licence
**CC BY 4.0**; attribution and citation as the product user manual states them
(`v200/2021/docs/WorldCover_PUM_V2.0.pdf` in the bucket, 4,102,952 bytes, sha256
`4301a3d95260d88bd4315f43ccf2a12ef74ad391109b9f36e22b6e51d8490107`, sections 5.1
and 5.2, Table 3, section 6). The DOI `10.5281/zenodo.7254221` is in the manual's
citation text; zenodo.org and doi.org are blocked by this container's proxy, so
the DOI itself is unverified here and the record says so. Reachability: a ranged
GET returned 206; rasterio `/vsicurl/` opened the 115 MB N36W120 tile and read the
Yosemite window (4800 x 3000 px) in 2.7 s with NO GDAL proxy options set (GDAL's
curl reads `https_proxy` and `CURL_CA_BUNDLE` from the environment; the module
still passes `GDAL_HTTP_PROXY` / `CURL_CA_BUNDLE` from the environment when present,
plus `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR`). So only the scene window is read;
no whole tile is downloaded. A whole tile already in the cache dir under its bucket
name is read locally instead.

**The legend** (`LEGEND`, code -> key): 10 tree_cover, 20 shrubland, 30 grassland,
40 cropland, 50 built_up, 60 bare_sparse, 70 snow_ice, 80 permanent_water,
90 herbaceous_wetland, 95 mangroves, 100 moss_lichen; plus `nodata` (0).
`WEIGHT_KEYS` = the 11 keys + `nodata`, in that order.

**`fetch(location, cache_dir, bbox=None) -> dict`.** Windows of every tile the bbox
touches (`tiles_for_bbox`: a maximum edge exactly on a boundary belongs to the tile
below it -- Everest's 87.00 E stays in N27E084; the Grand Canyon crop crosses 36 N
and mosaics N33W114 + N36W114), mosaicked on the product's global grid, every value
checked against the legend, written to
`<cache>/ESA_WorldCover_10m_2021_v200_<key>_crop_4326.tif` + `.json`. Returned and
written provenance: `{dataset, product_version, year, bucket, posting_deg,
posting_m_nominal, license, license_url, license_note, attribution, citation,
location, bbox_deg, tiles: {stem: {url, read: "vsicurl window" | "cached whole
tile", window: {col_off, row_off, width, height}, etag, content_length,
last_modified | sha256 (cached tile)}}, crop: {file, width, height, origin_lon_deg,
origin_lat_deg}, sha256 (of the crop), path}`. A cached crop whose recorded sha256
still matches and whose bbox is the same is returned without the network.

**`read_grid(bake_path) -> BakeGrid`.** From the bake's `.json` sidecar only
(`georeference.{crs, origin_x_m, origin_y_m, pixel_size_m}`, `width`, `height`,
`sha256`, `name`); refuses `terrain.landcover_grid` when the sidecar is absent,
unreadable, or lacks any of those keys.

**`rasterise(location_or_bake, cache_dir, out_dir, bake_path=None, source_4326=None,
texels_per_cell=3) -> (scene_dir, document)`.** `location_or_bake` is a curated
`Location` (bake = `out_dir/<key>.r16` unless `bake_path`) or a bake path (the bbox
is then derived from the grid's own corners and edge midpoints, padded 5 source
cells). The fine grid is the bake's CRS/origin/extent subdivided k x k (k = 3 for a
30 m bake, dropped while an edge would exceed 8192 as the imagery drape does);
classes are reprojected nearest-neighbour; per bake cell the count of fine cells per
class becomes a weight `255 * count / k^2` rounded by the largest remainder so the
sum over the 12 maps is exactly 255 in every cell. Written to
`out_dir/<bake stem>_landcover/`: `<key>_weight.png` x 12 (8-bit L), `class_map.png`
(majority legend code, 0 = nodata), `landcover.json`:

    dataset, product_version, year, model ("ESA WorldCover v200 2021 majority/fraction")
    posting_deg (1/12000), posting_m_nominal (10.0)
    license ("CC BY 4.0"), license_url, license_note, attribution, citation
    source {dataset, bucket, location, bbox_deg, tiles, crop, path}
    sha256                       the source crop's digest
    classes [{code, key, title, rgb, file, fraction}] x 11
    fractions {key: fraction over the bake grid, nodata counted in the total}
    nodata_fraction, coverage, dominant_class
    grid {crs, origin_x_m, origin_y_m, cell_size_m, width, height, bake_sha256,
          aligned_to_bake, texels_per_cell, texel_size_m, fine_width, fine_height}
    weightmaps {key: {file, sha256}}, class_map {file, sha256, encoding}
    weight_sum_per_cell {min, max, expected: 255}
    verification_vs_source {samples, agreement, ok}
    applied_variables            records_block([scene.landcover]), record_version 1
    not_claimed

Verification before anything is written: 400 random fine texels pushed
projected -> geographic -> source pixel, class for class; `ok` needs >= 90 % of the
samples inside the source and agreement >= 0.9 (measured: 100.0 % Yosemite, 99.2 %
Grand Canyon; a row flip scores < 0.6 and is refused).

**Refusals by name.** `terrain.landcover` (`LandcoverError.constraint`; `reason` =
`unreachable` | `corrupt` | `unverified`): a tile unreachable or unreadable, a file
whose CRS is not 4326, whose pixel is not 1/12000 degree north-up, whose origin is
not the stem's corner, or with more than one uint8 band, values outside the legend,
or a rasterisation that disagrees with its source. `terrain.landcover_grid`
(`LandcoverGridError.constraint`): sidecar absent or without the grid keys. The
script prints `REFUSED -- <name>: ...` once and exits 1.

**The record** (`landcover_variable`, `scene.landcover`): value = the dominant
legend key, unit "WorldCover legend class (dominant); fractions in parameters",
source `derived`, model `ESA WorldCover v200 2021 majority/fraction`, parameters
{fractions, nodata_fraction, dominant_class, license, attribution, posting_deg,
posting_m_nominal, texels_per_cell, grid, source_sha256, verification_vs_source,
weight_encoding}, references (the Zanaga et al. 2022 citation; the manual with its
sha256), no properties written, no telemetry columns, no frame keys; null test =
the dominant class's fraction (with) against the uniform prior 1/11 (without),
threshold 0.05 (Yosemite: 0.6866 vs 0.0909, difference 0.5957, ok). The licence and
attribution ride inside the record's parameters so a manifest that lifts the record
carries them. `landcover_records(bake_path)` re-types the JSON's record for a
manifest's `records_block` and returns `[]` for a bake without land cover
(absent-canonical, never a zero record); `scene_dir_for(bake_path)` is the lookup
rule (`<bake stem>_landcover/` beside the bake).

**Licence-clean distribution.** CC BY 4.0 permits redistribution with attribution;
`license_note` in every `landcover.json` states the requirement and `attribution`
carries the line `(c) ESA WorldCover project 2021 / Contains modified Copernicus
Sentinel data (2021) processed by ESA WorldCover consortium`. A dataset card built
from a scene that carries land cover must lift that line (open issue for the export
integrator).

**Not claimed.** Nothing in the engine reads the weightmaps: no landscape layer,
material or PCG biome consumes them, no vegetation or structure is placed, no
rendered pixel changes. The classes are the product's estimate (global overall
accuracy 76.7 +/- 0.5 %, North America 74.6 +/- 1.2 %, per its manual) and are not
re-validated here. 2021 classes are not temporally aligned with the 2016-2017
imagery drape or the 2010-2015 GLO-30 heights. A weight is a fraction of 10 m cells
in a bake cell, not of area; the 10 m posting is nominal. A cached whole tile's
size is not checked (only its CRS, posting, origin and band). No version was
bumped: `landcover.json`, `scene_dir_for` and `landcover_records` are optional and
absent-canonical.
