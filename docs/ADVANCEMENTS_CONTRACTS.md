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

## I8 -- the record every variable returns, made checkable (gap section 5.2 item 2; blueprint section 2, R1)

**Owner files.** `core/records.py` (record 2 SHAPE under `RECORD_VERSION` 1), `core/registry.py` (new), `core/record_null.py` (new), `core/uncertainty.py` (new), `core/capture/manifest.py` (the suffix table, the registry-first unit lookup, the optional `uncertainty` block), the four record-1 producers (`core/terrain/geoid.py`, `core/telemetry/limits.py`, `core/telemetry/instruments.py`, `core/terrain/landcover.py`) emitting the record-2 fields they can, `tests/test_records.py`, `tests/test_registry.py`, `tests/test_record_null.py`, `tests/test_uncertainty.py`.

**Record 2 under version 1.** `AppliedVariable` gains, each OPTIONAL with a default and emitted ONLY when set: `from` (the provenance text), `std` (the citation), `readback` `{property, value, written, agrees, tolerance, tolerance_kind, basis}` (`agrees` = |value - written| <= tolerance, absolute in the property's unit or relative to |written|), `jsbsim_writes` `[{property, when}]` (every property named must be in `properties_written`, else ValueError), `model_block` `{name, standard, version, parameters, references}` (the string `model` stays as it was), `uncertainty` `{u_input{value, unit, rule, sensitivity}, u_num{srq, value, basis}}` (shape-checked; an unknown key is a ValueError). `NullTest.kind` in `{reached, bounded}`: `ok` = |difference| >= threshold for `reached`, <= threshold for `bounded` (an invariance -- "the datum moves no pixel" -- which record 1 could not express); `kind` is emitted on every null test (record-1 producers mean `reached`, which is the default and what `from_dict` reads for a dict without it). `AppliedVariable.from_dict` / `NullTest.from_dict` / `Readback.from_dict` read record 1 or record 2. A record-1 producer's dict is unchanged except for `null_test.kind` (measured: the key set of a record that sets no record-2 field is the twelve record-1 keys). `RECORD_VERSION` stays 1 (the integrator bumps); at the bump the blueprint's final spelling is `model` = the block, `model_name` = the string -- today the block rides beside the string as `model_block`, stated in the module docstring.

**The registry** (`core/registry.py`, `REGISTRY`). One `VariableRecord` per introduced variable: `name`, `spec_path` (`section.leaf`, or None for an observer / derived quantity), `unit`, `jsbsim_writes`, `effect_channels` (each with its unit), `null_value` (a value; `None` = the field unstated, `value: null` in the block's dict -- a removed key is not a spec; `NO_NULL` = no spec null, allowed only with `spec_path` None), `null_basis`, `readback_tolerance` `{value, kind, reason}` (required when anything is written), `u_input_rule` `{bin_width, declared_spread, note}`, `host_channels`. Populated: `scene.geoid_undulation_m`, `limits.monitor` (effect channels the six flag columns, unit `1`), `instruments.profile`, `scene.landcover` (no spec field, no write, producer-measured null tests), and the physics wave: `atmosphere.temperature_deviation_c` (writes `atmosphere/delta-T` before trim and every step; readback 0 absolute; effect `density_altitude_m` m, `temperature_k` K, `tas_kt` kt; null 0; b = 10 degC), `atmosphere.sea_level_pressure_hpa` (`atmosphere/P-sl-psf`, hPa x `HPA_TO_PSF` = 2.08854342; readback 0 absolute; effect `pressure_altitude_m`, `density_altitude_m`, `pressure_hpa`; null 1013.25; no vocabulary bin), `atmosphere.dew_point_c` (`atmosphere/dew-point-R`; null = absent = dry; readback 1e-6 relative, STATED not measured), `atmosphere.relative_humidity_pct` (`atmosphere/RH`; readback 1e-6 relative with the measured reason; null 0; b = 20 %), and `atmosphere.day` (unit `word`; no write of its own -- the provider expands the word into the numeric fields, whose records carry the writes; effect `density_altitude_m`, `temperature_k`, `rh_pct`; null `isa`; no bin: the prompt route infers a numeric field, never the word). Every effect channel a spec-field entry names is a recorded column (the first population named `sigma`, which no recorder writes; corrected at integration and pinned). Readbacks measured here on a trimmed c172p after three steps: delta-T 36 -> 36.0 exact, P-sl 2000 -> 2000.0 exact, `pointmass-weight-lbs[1]` 300 -> 300.0 exact, RH 0.5 -> 0.5000000000505 (1.0e-10 relative; the research session read 6.6e-8), so 1e-6 covers both with margin. `Registry.channel_units()` feeds `core.capture.manifest.channel_unit`, which consults it BEFORE the suffix table; the suffix table gains `_kgm3` kg/m^3, `_mps2` m/s^2, `_rads` rad/s, `_flag` 1, `_hpa` hPa, `_pct` %, `_ut` uT, `_k` K (longest first; measured: no old suffix shadowed). `unregistered_fields(spec_dict)` returns every `section.leaf` under a claimed section (today `atmosphere`) that no entry claims; `require_registered` refuses by name; `stated_variables` gives the provenanced mappings the spec states. The committed spec-8 examples state no claimed section: their digests are pinned (eight sha256s, equal to HEAD's own, measured from a `git archive` of HEAD) and `unregistered_fields` is empty for each.

**Refusals by name** (`RecordError.constraint`): `record.unregistered` (an unknown name in `get`; a spec field under a claimed section no entry claims), `record.null_value` (a spec-field entry registered with `NO_NULL`; a null pair for a variable with no spec field, a field the spec does not state, or a stated value that IS the null), `record.effect_channel` (a pair for a variable with no effect channel, or a registered channel the run did not record), `record.effect_channel_unit` (a channel with no unit, or a unit its name contradicts). A duplicate name or spec path, a write without a readback tolerance, a tolerance without a reason, a null value without a basis: ValueError (programming errors).

**The null pair** (`core/record_null.py`, `run_null_pair(spec, name, runner=run_spec, registry=REGISTRY)`). The spec's dict with the one field at the registry's null value (`source: derived`, `from` naming the pair; removed when the null is `None`), re-read as a `ScenarioSpec`; both flown; per effect channel `{peak_abs, rms, unit, floor, reached, samples, peak_index, with_at_peak, without_at_peak}` (a `deg` difference wrapped to +-180; unequal lengths compared over the shorter and noted); both spec and output digests and `differ`; verdict `reached` | `silent` | `ungraded`; `null_test()` = a `reached` NullTest on the strongest channel (with/without at the sample of peak difference, threshold = floor). Floors: `NULL_FLOOR_ALTITUDE_M` 0.5, `NULL_FLOOR_ANGLE_DEG` 0.05, `NULL_FLOOR_SPEED_KT` 0.1 (m/s = 0.1 kt), with `NULL_FLOOR_REFERENCE` citing VV_REPORT row V9 (0.098 m at 1/60 vs 1/120, 0.048 m at 1/120 vs 1/240, p = 1.03); a unit without a floor is reported, not graded. `null_pairs_for_spec` runs one pair per registered spec field stated off its null (empty on every committed example today); `null_pairs_block`, `attach_null_pair` (writes the null test with `null_value`, `digests`, `effect`, `verdict`, `basis` into the variable's record when the block has one; returns False otherwise).

**Uncertainty** (`core/uncertainty.py`). `u_num_twin`: the dt/2 twin (rate x 2, turbulence `none`, both stated in the twin's provenance text), per SRQ (`altitude_m`, `north_m`, `east_m` from lat/lon by the WGS 84 radii at the first sample, `tas_kt`, `pitch_deg`, `roll_deg`, `heading_deg` unwrapped) the peak |S_dt - S_dt/2| with the twin interpolated onto the coarse sample times, e = diff / (2^p - 1), u_num = Fs x e: p = 1 assumed with Fs = 3, or the `three_rate_study` observed p with Fs = 1.25 (Roache 1994); `basis` states which. `u_x` by source rank: user 0 unless `tolerance` is stated with the value; inferred (b/2)/sqrt(3) with b the registry's bin width (refuses to guess without one); sampled 0; model/default/derived the declared spread. `central_sensitivity`: x +- u_x, c_i = (S+ - S-)/(2 u_x) with S the SRQ at the final common sample (a secant, stated). `u_input_for` runs the pair only when u_x > 0. `u_val` per SRQ = sqrt(u_num^2 + sum (c_i u_x_i)^2), each term listed. `uncertainty_block` = `{u_num, u_input, u_val, form: "ASME V&V 20; u_D absent per run", not_claimed}`; `uncertainty_for_run` builds it for a run; `record_u_num` gives the record-level `{srq, value, basis}`.

**Capture / manifest.** `build_capture_manifest(..., uncertainty=None)`: the top-level `uncertainty` key is written only when a block is given (absent-canonical; measured: the v6 schema validates and `flightsim.verify` passes with it present); `SIDECAR_CONTEXT_KEYS` += `uncertainty`. The `--null-tests` / `--uncertainty` options (off by default) and the `validate_registry` call are integration patches, not landed.

**Not claimed.** A null pair is connectivity and one-sided sensitivity, not correctness; the floors grade against the integrator's noise at the stock rates. u_num is one dt/2 twin with an assumed order unless the three-rate study ran; u_input is first order with a secant sensitivity; u_D is absent, so the block is the run's own uncertainty, not a validation. The readback grades JSBSim's property store, not the physics. The dew-point readback tolerance is stated, not measured. The four record-1 producers write no JSBSim property, so they carry no readback and no `jsbsim_writes` (an honest absence). Nothing engine-side reads any of it; `host_channels` is a contract for the C++ recorder, unverified here. No version was bumped.

## P1 -- the non-standard atmosphere and humidity (gap P1)

**The fact.** `atmosphere/delta-T` was never written and no humidity was ever set (PHASE3_GAP_ANALYSIS P1). The installed JSBSim 1.2.4 `FGStandardAtmosphere` (source fetched and read) applies `delta-T` as a bias in Rankine at every altitude (`GetTemperature`; the graded route `SL-graded-delta-T` is NOT used and is said so), `P-sl-psf` as an off-standard sea-level pressure with the layer breakpoints rebuilt from the BIASED base temperatures (`CalculatePressureBreakpoints`, `GetPressure`), and `dew-point-R` through the Magnus form `e = a exp(b t/(c+t))`, a = 611.2 Pa (over JSBSim's own 47.88 psf-to-Pa), b = 17.62, c = 243.12 degC (Sonntag as the source cites it), the vapour mass fraction `f = R_dry e/(R_water (P - e))`, a moist gas constant `R = (f R_water + R_dry)/(1 + f)`, and `rho = P/(R T)`; density and pressure altitude by inverting the standard layer formulas (`CalculateDensityAltitude`, `CalculatePressureAltitude`). Measured here: dew point 518.67 R at ISA sea level -> RH 100 %, rho -0.63 %, DA +66.29 m (217.5 ft); delta-T +36 R with P-sl 2000 psf -> T 554.67 R, rho 0.002101 slug/ft3, DA 4164.1 ft, PA 1555.2 ft; `delta-T` survives 200 unrewritten steps; JSBSim's `atmosphere/sigma` divides by the DAY's sea-level density (1.0 at sea level on a hot day), so the item's `sigma` is the ISA ratio and is compared through density, never through that property.

**Two silent caps, refused instead (docs/JSBSIM_CORRECTIONS.md 14).** A dew point above the saturation of the LAST computed temperature is capped to it (dew-point-R 540 at ISA sea level reads 518.67, a line printed to C++ stderr); a vapour mass fraction above a per-altitude record-high table (35000 ppm at sea level .. 38 ppm at 16 km, looked up at the PRESSURE altitude on the write and the geometric altitude every step) is capped (500 R at 5000 ft reads 499.63 R). The validator refuses both at the scene's initial altitude by name; the provider never writes into them along the flight.

**Owner files.** `core/environment/atmosphere.py` (new), `core/environment/stack.py`, `core/scenario/blocks.py`, `core/scenario/spec.py`, `core/scenario/validate.py`, `core/scenario/runner.py`, `core/scenario/card.py`, `core/fdm/state.py`, `core/telemetry/recorder.py`, `tests/test_atmosphere.py`.

**The block** (`atmosphere`, a ProvenancedBlock; still spec 8, absent-canonical: the ISA day is the default and is omitted, pinned against every committed spec example's digest):

```
atmosphere:
  temperature_deviation_c:  Quantity, default 0.0 degC       (-60..+45)
  sea_level_pressure_hpa:   Quantity, default 1013.25 hPa    (870..1085)
  dew_point_c:              Quantity, default None (dry)      (-90..60, <= T at the scene, under the vapour cap)
  relative_humidity_pct:    Quantity, default None (dry)      (0..100; 0 is dry air and writes nothing)
  day:                      Quantity, default "isa"
```
Every field is behind `spec.set("atmosphere.<field>")` / `plan()` with the spec's own doctrine. `day` words (STATED choices, each with its `std`): `isa` (nothing), `isa_plus_15`, `isa_plus_20`, `hot_day` (+30 degC, a value inside MIL-HDBK-310's 1 % hot column as remembered, unverified here, not the handbook's profile), `cold_day` (-40 degC), `humid` (RH 90 % at the scene). `AtmosphereSpec.resolved()`: a word fills a numeric field only while it is at its default (`inferred`, from "day: <word>"); a stated number always wins; a word's humidity fills nothing when either humidity field is stated. `mil_hdbk_310_hot|cold|humid|high_altitude` are recognised and refused `atmosphere.profile` until transcribed with provenance; any other word is `atmosphere.profile` too.

**Refusals by name** (`AtmosphereError.constraint` in the provider; the SAME list as `Violation`s from `validate_atmosphere`, produced by one function `atmosphere.problems`): `atmosphere.temperature_deviation`, `atmosphere.sea_level_pressure`, `atmosphere.dew_point` (RH outside 0..100, dew point outside -90..60, above the modelled temperature at the scene's initial altitude, or beyond the vapour cap there; a non-number in either humidity field), `atmosphere.humidity_conflict` (both stated), `atmosphere.profile`.

**The provider** `NonStandardAtmosphere(AtmosphereProvider)`, `from_spec(spec)` (None for the default block: nothing applied, nothing recorded). It writes ONLY the stated variables: `atmosphere/delta-T` = deviation x 1.8 R, `atmosphere/P-sl-psf` = hPa x 100 / 47.880258980336, `atmosphere/dew-point-R` = the stated dew point, or the one the stated RH implies at the scene's initial altitude on the modelled temperature (inverse Magnus). Along the flight the dew point written is the LEAST of the stated dew point, the modelled temperature at the aircraft's altitude, the temperature JSBSim currently holds (`SetDewPoint` checks saturation against the last computed state) and the cap's dew point there; the limited steps are counted. `stack.prepare(fdm)` (new; called by `configure_from_spec` between `set_initial_conditions` and `trim`, also on the validator's feasibility probe) writes each variable in the order delta-T, P-sl-psf, dew-point-R with a re-latch of the initial conditions after each (`run_ic`: recomputes the atmosphere at the ICs without advancing time; the wrapper's executive is used until a public `relatch_initial_conditions` exists), reading density/temperature/pressure/DA/PA/RH/e before and after each write -- the per-variable null pair -- and the exact read-back of every property. `stack.apply` calls `observe(fdm)` at the top of every step (the previous step's writes read back BEFORE this step's write) and then writes the properties every step as before.

**Read-back, measured.** Before the trim: delta-T, P-sl-psf and dew-point-R read back with 0.0 error (tolerance 0, 0, 1e-9 relative). After a step: delta-T and P-sl-psf 0.0; the dew point moves with ONE step's pressure change because JSBSim conserves the vapour mass fraction and recomputes the dew point at the new pressure (1.5e-6 R over 360 steps on the c172p, 2.3e-7 R over 600 on the A320 autopilot flight; tolerance 1e-6 relative, basis stated in the record).

**The records** (`applied_variables`, record_version 1, one per STATED variable, attached by `run_spec` through `attach_record`): `atmosphere.temperature_deviation_c` (degC), `atmosphere.sea_level_pressure_hpa` (hPa), `atmosphere.dew_point_c` (degC) or `atmosphere.relative_humidity_pct` (%); `source` is the spec Quantity's (inferred for a day word, user for a set()); model "JSBSim 1.2.4 FGStandardAtmosphere: temperature bias ..."; parameters {property, written, reference_altitude_m, readback {written, read, abs_error, tolerance_relative, agrees}, per_step_readback {steps_checked, max_abs_error, tolerance_relative, agrees, basis, steps_written, dew_point_limited_steps}, predicted (the closed form at the scene), delivered (JSBSim after the writes), route "bias", dew_point_c for RH}; references (the source functions; US Standard Atmosphere 1976 and Sonntag as the source cites them, unverified here; MIL-HDBK-310 for the word); properties_written = the one property (empty for RH 0); telemetry_columns = frame_keys = the six channels; null_test = air density at the initial altitude before against after THAT variable's write, threshold 0.1 % of the reference density (kind "reached"; a stated zero deviation measures 0 and is honestly not ok); not_claimed (below).

**The channels** (recorded, NOT graded: the Gate 5 COMPARED set is unchanged, pinned by the existing test): `density_altitude_m`, `pressure_altitude_m` (JSBSim's `atmosphere/density-altitude`, `pressure-altitude`), `rh_pct` (`atmosphere/RH`, percent), `vapour_pressure_pa` (`vapor-pressure-psf`), `temperature_k` (`T-R`), `pressure_hpa` (`P-psf`); `REQUIRED_PROPERTIES` gains the four new properties (probed on the live catalog). Per frame: `frame_state` copies them with no change to that file; units m, m, %, Pa, K, hPa once the suffix table carries `_pct`, `_k`, `_hpa` (integration patch 1).

**The card block** `atmosphere_properties` (absent for the default block), keys in this fixed order and no other: `atmosphere/delta-T`, `atmosphere/P-sl-psf`, `atmosphere/dew-point-R` (each the exact value written, null = not written), `applied` ("before the trim and every step; a null is not written"), `dew_point_rule`, `stated` {each field: {value, source, from} | null}. `atmosphere_card_block(spec)` raises if the order ever differs from `CARD_KEYS`; `write_run_card` needs no new argument (the card is a projection of the spec).

**The closed form** `closed_form(altitude_m, dT_c, p_sl_hpa, dew_point_c)` and `expected_density_ratio(dT_c, p_sl_hpa, dew_point_c, altitude_m)` transcribe the same equations (constants, the 9-row temperature table by geopotential altitude, the 10-row vapour table, both cap lookups) so the predicted side of every null test is stated; a `None` sea-level pressure means JSBSim's own 2116.228 psf (1013.25 hPa converted exactly is 2116.2166 psf, 5.4e-6 lower, and is written only when the spec states it).

**Not claimed.** MIL-HDBK-310 profiles (refused); a temperature inversion, a changed lapse rate or a humidity profile with height (the dew point is held constant along the flight and limited where the air would not admit it); that JSBSim's standard day equals the 1976 tables (taken on the source's word; not compared here); bit-identity of a run that STATES the standard day with the default run (the pre-trim measurement re-latches the initial conditions and moves every column by at most 4.0e-10 N / 3.5e-11 kg / 1.6e-13 deg, measured and pinned under 1e-8; the default block runs the unchanged path); the engine side (the card block is pinned; nothing applies it here); the prompt compiler (no atmosphere vocabulary: the block is stated through YAML or `spec.set`). No version was bumped: `atmosphere` and the records are optional and absent-canonical.

## Wave 1 integration (R1 with P1)

What the two items could not measure apart, measured together on the branch (tests/test_atmosphere.py, tests/test_registry.py, tests/test_record_null.py):

* **The block's fifth field.** The registry claimed the `atmosphere` section with four entries; the block has five fields (`day`, the word). A stated day therefore met `record.unregistered` from the validator. `atmosphere.day` is registered (above); `REGISTRY.spec_fields()` equals the block's `FIELD_ORDER`, pinned.
* **Effect channels are recorded columns.** `sigma` (named by two entries) is no recorder's column: replaced by `temperature_k` (K) and `pressure_hpa` (hPa). Pinned: every spec-field entry's channels are in a run's columns.
* **The unstated null.** A null of `None` sets `value: null` with `source: derived` and a `from` saying "unstated", instead of removing the key: every provenanced block lists all its fields, so the removed key was refused by `from_dict`. `null_pairs_for_spec` skips an unstated field (nothing was applied), so a worded spec runs the word's pair only.
* **Floors for the atmosphere's channels** (stated, said so): 0.1 K, 0.1 %, 0.1 hPa, 1 Pa.
* **Measured null pairs on the c172p, 1500 m, 3 s** (each ~2 s, both digests differ, verdict `reached`): `day: hot_day` -> density altitude 847.60 m, temperature 30.000 K, humidity 0 (below floor, graded so); `day: humid` -> 35.99 m, 90.000 %; `temperature_deviation_c: 30` -> 847.60 m, 30.000 K, TAS 0.0037 kt (below floor); `sea_level_pressure_hpa: 990` -> pressure altitude 188.85 m, density altitude 233.10 m, 19.40 hPa; `relative_humidity_pct: 60` -> 60.000 %, 532.3 Pa, 23.98 m; `dew_point_c: 5` -> 98.26 %, 871.7 Pa, 39.30 m.
* Catalogue: the nine entries landed (four `record.*`, five `atmosphere.*`); tests/test_messages.py green over every name.

## P2 -- the XML-injection pipeline: failures re-anchored, icing factors, the stall-onset shift, the rotational gust (blueprint section 1, corrections 1-3)

**Owner files.** `core/control/derive.py` (the pipeline), `core/control/systems/failures.xml.tmpl`, `icing.xml`, `icing_alpha.xml`, `gust_rotation.xml` (new; `tecs.xml` unchanged), `core/fdm/fdm.py` (`FlightDynamics.with_injections`; `with_tecs` byte-compatible), `tests/test_derive_injections.py` (new), `tests/test_control.py` (one pin added).

**The pipeline.** `Injection(name, template, rewrite, anchor_test, suffix, system_file, expand, introduces)`; `derive(base, build_dir, root_dir, injections=("tecs",))` applies the selection in the FIXED order `tecs -> failures -> icing -> icing_alpha -> gust_rotation` whatever order it was given in; each injection runs its `anchor_test` over the CURRENT text (so a later injection sees the earlier rewrites) and refuses BEFORE anything is written. Each is independently selectable; the derived name encodes the set through one token per injection (`tecs`, `fail`, `ice`, `alpha`, `gust`): `c172p-fail-ice-alpha-gust` (host) vs `c172p-tecs-fail-ice-alpha-gust` (headless), `c172p-tecs` for the default. `derive(name)` with no selection is the TECS derivation exactly as before (same name, same files, same hashes; pinned). Byte-identical on regeneration (the existing rule; the atomic no-op write kept). The stock file and the vendored systems tree are never edited: a stock model whose FCS lives in a shared `<system file=...>` (the DHC6) is refused, not patched.

**Provenance** (`DerivedAircraft.provenance()`, the manifest's `fdm.derivation`): the four original keys (`derived_from`, `base_sha256`, `tecs_template_sha256` -- null when tecs is not in the set --, `derived_sha256`, `engine_count`) plus `suffix` and `injections[]`, one record per applied injection: `{name, suffix, system_file, template_sha256 (the repository template's bytes), written_sha256 (the expanded system file's bytes), anchors (the counts the anchor test measured)}`. `verify_hashes(derived, expected_derived_sha256=None)` re-hashes the airframe and every written system file against the record and, when a manifest's hash is given, the derivation against it.

**The rewrites** (measured on the c172p, tests/test_derive_injections.py):

* `failures` -- for each of elevator, aileron, rudder the airframe's `<flight_control>` `<input>fcs/<s>-cmd-norm</input>` is RE-ANCHORED to `<input>failure/<s>/cmd-in</input>`; the injected system (loaded after TECS, before the FCS) is per surface `failure/<s>/authority` (1.0), `failure/<s>/cmd-in` (0), a `<pure_gain>` reading the host's untouched `fcs/<s>-cmd-norm` with the authority property as its gain, and `<actuator name="failure/<s>/actuator">` with `<clipto>` -1..1 writing `failure/<s>/cmd-in`, carrying JSBSim's own `failure/<s>/actuator/malfunction/fail_stuck | fail_zero | fail_hardover`. The blueprint's phrase "whose output is fcs/<s>-cmd-norm" is NOT followed: that is the pass-through loop correction 1 refutes, re-measured here (authority 0.5, command -0.3 written once: -0.15, -0.075, -0.0375, -0.01875 ... 7e-5 by step 12); the chain writes the new property and the FCS reads it, so the command holds (-0.15 on all 100 steps).
* `icing` -- every `<function>` of the six axes (LIFT, DRAG, SIDE, ROLL, PITCH, YAW; c172p 5/5/5/5/6/5 = 31) is wrapped in `<product><property>icing/<axis>-factor</property> EXPR </product>`; `icing.xml` declares the six factors (1.0) and `icing/eta` (0; declared for P5, read by nothing here).
* `icing_alpha` -- `icing_alpha.xml` declares `icing/alpha-shift-rad` (0); the sum `icing/alpha-effective-rad = aero/alpha-rad + shift` is injected as a PRE-AXIS `<function>` at the top of `<aerodynamics>`, NOT as a system: a `<system>` runs before FGAuxiliary in the 1.2.4 schedule and reads the PREVIOUS step's alpha (measured: a system copy lags 5.3e-4 .. 1.5e-3 rad over six steps of an elevator step; the aerodynamics function differs by 0.0). The LIFT axis's one `<independentVar>aero/alpha-rad</independentVar>` table is re-pointed at the effective alpha.
* `gust_rotation` -- `gust_rotation.xml` declares `gust/p-equivalent-rad_sec` (0); the ROLL axis's one `<property>velocities/p-aero-rad_sec</property>` becomes `<sum>` of it and the gust property.

**Refusals by name** (`DerivationError.constraint`): `derivation.anchor_missing` -- no `<flight_control>`, a surface's command not read through any `<input>` (DHC6: FCS in a shared system file), read anywhere else in the FCS too (f16: `<test value="fcs/aileron-cmd-norm">`), no `<aerodynamics>`, an axis name outside the six, a nested function, the LIFT axis with zero (p51d: alpha in degrees) or several (f16: five) alpha-rad tables, the ROLL axis with other than one roll-rate term (a fabricated double term); the old "could not find <flight_control>, <autopilot> or <ground_reactions>" message now carries this name. `derivation.injection_conflict` -- an unknown, repeated or empty selection; a base that already declares an injection's properties or system line (deriving `c172p-fail-ice-alpha-gust` again); a record asked for an injection the airframe was not derived with. `derivation.hash_mismatch` -- a built file whose bytes no longer hash as recorded (airframe or system file), or a derivation whose hash is not the caller's expected one; `FlightDynamics.with_injections(base, injections, ..., expected_derived_sha256=None)` calls `verify_hashes` before JSBSim reads anything. A programming-level failure (no engines for TECS, a template without its placeholder) carries an empty constraint, as before.

**Neutral values are bit-identical** (V18, per injection and all four together): 8 s of a trimmed elevator step (-0.3 at 1 s, 120 Hz, 960 steps), fifteen properties per step (position, attitude, u/w, p/q, alpha, the three aero forces and moments, elevator): worst |derived - stock| 0.0. IEEE 754 exactness of x * 1.0, x + 0.0 and a unit gain is the mechanism; the test measures it, the docstrings do not assume it.

**Driven, measured** (each a `reached` null test in an `AppliedVariable` built by `derive.injection_variable`): authority 0.5 holds `failure/elevator/cmd-in` = -0.15 on all 100 steps for -0.3 written once, and the elevator sits where the stock airframe puts it for -0.15 (0.01495360487503992 rad, equal to the bit); `fail_stuck` holds -0.15 for six steps of a +0.8 command, `fail_zero` writes 0 (elevator 0.07515610487503992 rad), `fail_hardover` writes +1 for a positive command (0.40135 rad = +23 deg) and -1 for a negative one (-0.39710561145647316 rad); lift factor 0.8 on the trimmed c172p (1500 m, 100 kt CAS): 1872.5287 -> 1498.0230 lbf on the next step, 0.8 x to 1e-12 relative (the research's 2772 -> 2322 was another state and only a partial wrap: the whole axis scales here); alpha shift 2 deg (0.0349066 rad): the static 8..22 deg sweep's lift peak moves 16.25 -> 14.25 deg requested (CL 1.4490 / 1.4497), -2.0 deg; gust p-equivalent 0.3 rad/s for 2 s from the longitudinal trim: roll -30.2129 deg against -3.6706 deg at 0 (the research read -30.3 vs -2.7). Every injected property reads back exactly (12 writes, before and after three steps).

**The record.** `derive.INJECTION_VARIABLES` names twelve variables (`failures.{elevator,aileron,rudder}_authority` unit 1, neutral 1.0; `icing.{lift,drag,side,roll,pitch,yaw}_factor` unit 1, neutral 1.0; `icing.eta` unit 1, neutral 0; `icing.alpha_shift_rad` rad, 0; `gust.p_equivalent_rad_s` rad/s, 0); `injection_variable(name, value, derived, readback_value, null_test, telemetry_columns, source, frm)` returns the record-2 `AppliedVariable`: `properties_written` = the property, `jsbsim_writes` "after load; held by the property store every step", `readback` tolerance 0 absolute with the measured basis, `model_block` {name "XML injection '<x>'", version = the template sha256's first 12, parameters {property, neutral_value, derived_sha256}}, parameters carrying the injection's template / written / derived hashes and the anchors, the blueprint and JSBSim references, `not_claimed`. The registry entries (spec_path None: no spec block lands with P2) are returned as an integration patch; the spec blocks, the vocabulary and the run-manifest attachment belong to P3 (failures), P5 (icing) and P6/P7 (gust).

**Not claimed.** No engine has loaded a derived airframe (the aircraft root is hard-coded in the vendored plugin; correction 2's fifth local patch is the named next step and `ue/` is untouched). The rewrites are textual against the stock files' spelling of the anchors: the c172p, A320, B747 derive with all four, the p51d with three (its lift is in degrees), the DHC6 refuses failures, the f16 refuses failures and icing_alpha. No physics is validated: a factor scales a whole axis, the alpha shift moves the LIFT table only (drag, moments and the other axes keep the true alpha), the gust sum reaches the roll-damping term only (no yaw or pitch moment, no Clr coupling), the failure chain has no rate limit, lag or hydraulic topology and clips a command beyond -1..1 before the trim summer (the host never writes one). `icing/eta` is declared and maps to nothing until P5. The pre-existing `tecs.xml` keeps its non-ASCII comment lines (not this item's; every file this item writes is ASCII and parses). No version bumped: `injections[]`, `suffix` and the records are optional and absent-canonical; the default derivation's hash is unchanged.

## D1 -- the EGM2008 datum extension and the datum blocks (gap P10; blueprint section 5)

**Owner files.** `core/terrain/geoid.py` (extended in place; every in-tree name kept), `core/terrain/glo30.py` (the bake), `core/scenario/blocks.py` + `core/scenario/spec.py` (the `datum` block only), `core/scenario/runner.py` (the channels and the record), `experiments/datum_null_test.py` (new), `tests/test_geoid.py` (extended), `tests/test_datum_block.py` (new). The DIS parts are D2's.

**The two grids.** The committed EGM96 grid stays as landed (I1). The EGM2008 5-minute grid is the bake cache's (`data/geoid/egm2008-5.pgm`, gitignored, 18,671,444 bytes, sha256 `96d55e88...`, 4320 x 2161, header MaxBilinearError 0.478 / MaxCubicError 0.294), fetched by `fetch_egm2008` from the recorded tarball (`egm2008-5.tar.bz2`, 10,414,793 bytes, sha256 `9a57c143...`, member `geoids/egm2008-5.pgm`): the tarball's digest is checked before extraction and the grid's after; `load_egm2008` refuses **`geoid.grid_missing`** (absent) and **`geoid.grid_digest`** (another digest, or a header that does not name EGM2008). `grid_for_model("auto" | "EGM2008" | "EGM96")`: auto is EGM2008 when cached, else EGM96 with the difference stated. `parse_pgm` reads the header's values as data (offset, scale, both bounds, the description, hence the model key).

**Interpolation.** `GeoidGrid.undulation` is bilinear (kept, guarded). `GeoidGrid.undulation_cubic` is GeographicLib's default: the 12-point least-squares cubic of `Geoid::height` (`cubic = true`), the three transfer matrices (`c3`/240 interior, `c3n`/372 north-pole row, `c3s`/372 south-pole row) transcribed from GeographicLib 2.3 `Geoid.cpp` fetched here (tarball sha256 `31148478...`) and RE-DERIVED in `tests/test_geoid.py` in exact rational arithmetic from the stencil and weights (C3 = the weighted fit; C3N = the fit without x, x^2, x^3; C3S = C3N under y -> 1 - y); rows beyond a pole reflect with longitude + 180 (`rawval`), columns wrap. EGM2008 blocks are cubic (bound MaxCubicError 0.294 m); EGM96 blocks stay bilinear (the in-tree verifier clause re-evaluates them). Measured: (0, 0) = 17.226 / 17.225 m (EGM2008 bilinear / cubic), 17.163 / 17.161 (EGM96); the six origins (EGM2008 cubic, bilinear): matterhorn +54.780 / +54.756, yosemite -25.431 / -25.432, fuji +42.421 / +42.413, everest -28.897 / -28.968, grand_canyon -23.435 / -23.419, flint_hills -30.305 / -30.304; the polar rows give N independent of longitude at both poles.

**The `.gtx` crop.** `write_gtx(grid, bbox, path, margin_nodes=1)`: floor / ceil of the scene bbox in whole nodes of the grid's posting plus one node each side (`gtx_crop_nodes`; a crop that would reach beyond a pole refuses **`datum.outside_grid`**), the nodes verbatim (offset + scale x sample, NOT interpolated) as a NOAA gtx (big-endian: 4 float64 south lat, west lon, dlat, dlon; 2 int32 rows, cols; float32 rows from the south row northward). It holds +N; PROJ's forward `vgridshift` subtracts the grid, so an evaluator uses `+inv +proj=vgridshift +grids=<file>`. The record: file, sha256, bytes, posting, rows x cols, the four bounds, `alignment` (the corner's node indices; `node_aligned: true`), the raw node min/max, the evaluator string. `read_gtx` -> `GtxCrop` (bilinear on the nodes; **`datum.outside_grid`** beyond them). `write_geoid_samples` writes `<key>_geoid.json`: the origin's N both ways and 100 interior points (seed 20260928, uniform a quarter node inside the crop) from the FULL grid. `write_gtx_bundle` writes both beside the raster (`<key>_geoid.gtx`, `<key>_geoid.json`) and returns the crop record with `samples_file` / `samples_sha256` / `samples_count`.

**The datum block** (bake sidecar `provenance.datum`, run card `datum`, run manifest `datum`, capture manifest `datum`, frame sidecar `context.datum`): every I1 key kept (`vertical_datum_of_heights`, `geoid_model`, `origin_lat_deg`, `origin_lon_deg`, `undulation_m`, `undulation_source`, `bilinear_error_bound_m`, `model_difference_bound_m`, `model_difference_basis`, `model_difference_at_origin_m`, `orthometric_height_of_origin_m`, `ellipsoidal_height_of_origin_m`, `note`) plus:

    geoid_model_key              "EGM2008" | "EGM96" (null on a flat / synthesised scene)
    grid_sha256                  the grid's (also undulation_source.sha256)
    interpolation                "cubic" (EGM2008) | "bilinear" (EGM96)
    interpolation_error_bound_m  the header's bound for that interpolation (0.294 / 1.152)
    cubic_error_bound_m          the header's MaxCubicError
    undulation_bilinear_m        N bilinear, always (what a crop evaluator reproduces)
    egm2008_minus_egm96_at_origin_m  live, bilinear on both, when both grids are present; else null
    bounds                       {scene_bbox_deg, lattice_step_deg (a quarter node), samples,
                                  undulation_min_m, undulation_max_m, undulation_range_m, note}
    gtx                          the crop record above (null for a block without one)
    u_model_m, u_model_basis     0.10 m EGM2008 (Pavlis et al. 2012's 5-10 cm, declared, unverified here);
                                 13.7 m EGM96 (the model-difference bound is the binding term)
    tide_system                  "not verified here"
    physics_frame                {frame: "orthometric", jsbsim_h_sl, jsbsim_ecef, export, atmosphere,
                                  ellipsoid_frame (refused by name), note}

For an EGM2008 block `model_difference_bound_m` and `model_difference_at_origin_m` are 0.0 with the basis saying the model is the bakes' own; for an EGM96 block they stay the I1 numbers (13.7; the curated table at the six keys, null elsewhere, never the live value). `undulation_source` gains `model`, `posting_deg`, `max_bilinear_error_m`, `max_cubic_error_m` and names each grid's own tarball. `flat_datum_block` gains `geoid_model_key: null` and `physics_frame`; `undulation_m` stays null, never 0.

**The bake** (`glo30.bake(..., geoid_model="auto")`): the grid is chosen -- and refused by name -- BEFORE any tile is fetched (measured: the fetch is never called); after the I1 line writes the block from the provenance origin, `bake_datum` re-evaluates it with the chosen grid, the scene bbox and the crop record (`write_gtx_bundle`); `provenance.geoid_files` names the two files with their sha256; `provenance.dted` is `dted_block` (MIL-PRF-89020B DSI/ACC-style fields, names from memory and marked `[unverified here]`, values from the bake: corners, lines / samples, posting, source interval, datum strings, the GLO-30 accuracies as declared u_D -- vertical LE90 4 m (sigma 2.43 m), horizontal CE90 6 m, relative 2 / 4 m by slope -- with the bake's own verification beside them; refuses **`dted.metadata_incomplete`** when the provenance lacks origin, bbox, tiles, verification or vertical datum); `provenance.cdb_descriptor` is documentation only (`datastore_written: false`).

**The spec block** `datum` (`DatumSpec`, absent-canonical, still spec 8):

    datum:
      vertical:       Quantity, default "orthometric"   ("ellipsoidal" recognised and refused)
      physics_frame:  Quantity, default "orthometric"   ("ellipsoid" recognised and refused)
      geoid_model:    Quantity, default None            ("EGM2008" | "EGM96"; null = the bake's own)

Behind `spec.set("datum.<field>")` / `plan()`; every committed example keeps its digest (pinned). `datum_spec_problems(block)` is the one list: **`datum.physics_frame_unsupported`** for a vertical other than orthometric or a frame other than orthometric, **`datum.model_mismatch`** for a model word this build does not carry. The runner raises the first at its top (`refuse_datum_spec`, before any flight, whether or not the validator ran); `validate_datum` (integration patch) lists them all.

**The runner.** `scene_datum_for(spec, terrain_ground)` BEFORE the flight: the bake's recorded block over a georeferenced heightfield (a sidecar with an origin and no block refuses **`datum.sidecar_without_datum`**: re-bake; `datum_for_heightfield(..., require_block=True)`), the synthesised block over a ridge, the flat block otherwise; `check_model_declared` refuses **`datum.model_mismatch`** when the declared model is not the block's or the scene carries none. AFTER `output_digest` and before the limit monitor, `datum_run` annotates two DERIVED columns: `undulation_m` (N at the scene origin, constant; 0.0 where no geoid applies -- the frame's definition, as I5.3 handles it; the block keeps null) and `hae_m` = `altitude_m + undulation_m`; reads the appended column back (`Readback`, property `telemetry.hae_m[0]`, tolerance 0, the recorder's store, not JSBSim's); re-digests the recorded (non-derived) columns and records the equality as a `bounded` invariance. The manifest gains `datum` and the record `scene.geoid_undulation_m` (after the limits and atmosphere records). Per frame `frame_state` carries both columns (`state.undulation_m`, `state.hae_m`, unit m by the suffix table).

**The record** `scene.geoid_undulation_m` (extended; `undulation_variable(datum, run=None)`): model `"<EGM2008|EGM96> <cubic|bilinear>"` (`model_block` standard EGM2008 Pavlis 2012 / EGM96 Lemoine 1998); parameters gain `model`, `interpolation_error_bound_m`, `undulation_bilinear_m`, `bounds`, `gtx_file`, `gtx_sha256`, `physics_frame`, `u_model_m`, `tide_system`, `channels`, and from a run `invariance`, `spec_datum` (each field's value / source / from), `declared_model`, `applied`, `samples`; `telemetry_columns` = [undulation_m, hae_m], `frame_keys` = [state.undulation_m, state.hae_m] (always: the runner appends them on every run); `readback` from a run; `uncertainty.u_input` = {value: u_model_m, unit m, rule: the declared spread, sensitivity {hae_m: 1.0}}, `u_num` null; the null test is the I1 `reached` N-against-0 with the model's interpolation bound as threshold (kept, guarded) and the `bounded` invariance rides under `parameters.invariance`; a flat scene: value null, no null test, the channel's 0 explained in `not_claimed`.

**The null test** (`experiments/datum_null_test.py`): the synthetic peak through the real bake path, the same c172p flight with the block stated (vertical, physics frame, the bake's model declared) and without: `output_digest` identical (bounded: 0 recorded columns differ), and the ECEF radial distance of the exported position (`hae_m`) minus that of JSBSim's altitude taken as ellipsoidal = N0 within 0.5 m at every sample (reached against N0 - 0.5, and bounded against N0 at the worst sample); written to `runs/datum_null_test/datum_null_test.json` with the run's record.

**Verifier (patch text pinned in `tests/test_geoid.py::VERIFY_DATUM_PATCH`).** `verify_datum` extended: a block's model from its key (or name); an EGM2008 block re-evaluated from `data/geoid/egm2008-5.pgm` when the checker's cache has it, else NOT RUN (the grid is not committed); the block's grid sha256 must be the checker's; the BILINEAR value (`undulation_bilinear_m` for a cubic block) within 0.01 m of the checker's own bilinear read; a cubic value within the header's two bounds of it; ellipsoidal = orthometric + N. New check **`datum_independent`** (FAIL `scene.datum`): finds `<scene.terrain>_geoid.gtx` and `.json` beside the bake, checks both sha256s, the header's steps equal the recorded posting and its corner sits on whole nodes, then PROJ `+inv +proj=vgridshift` at the origin against `undulation_bilinear_m` and at the 100 recorded interior points against the producer's full-grid values, each within `DATUM_INDEPENDENT_TOL_M` 0.01 m, and inf one node north and one node west of the crop; NOT RUN without a georeferenced block, a `gtx` sub-block, `scene.terrain` or pyproj. Independent of the producer's interpolation CODE, not its DATA (stated). The checker imports nothing from `core.terrain`.

**Refusal names.** `terrain.geoid`, `scene.datum` (in tree); new: `geoid.grid_missing`, `geoid.grid_digest`, `datum.outside_grid`, `datum.sidecar_without_datum`, `datum.model_mismatch`, `datum.physics_frame_unsupported`, `dted.metadata_incomplete` (all `DatumError.constraint`); check `check.datum_independent`.

**Not claimed.** No height inside the simulation is converted (JSBSim's h-sl and its own ECEF stay as they were; `hae_m` is the export); N is the origin's for the whole flight (the bbox range bounds that choice, 0.60-3.39 m at the six curated scenes); the model uncertainty is declared, not measured; the tide system is not verified; the DTED / CDB blocks are documentation (no cell, no tile); the MIL-PRF-89020B and OGC CDB field names are from memory; no real GLO-30 bake was made here (synthetic tiles through the real bake path); the host recorder's `undulation_m` / `hae_m` are a contract for the C++ recorder; the ellipsoid physics frame is documented and refused. No version was bumped: the `datum` block, the new block keys, the channels and the record fields are optional and absent-canonical (the eight committed examples' digests are pinned unchanged).

## Wave 2 integration (P2 with D1)

Measured together on the branch (tests/test_registry.py, tests/test_limits.py, tests/test_atmosphere.py, tests/test_mutation_targets.py, tests/test_geoid.py, tests/test_datum_block.py, tests/test_derive_injections.py):

* **The registry now holds three populations**: the spec-field entries (atmosphere, datum -- `REGISTRY.sections()` is `("atmosphere", "datum")`, and `spec_fields()` equals the two blocks' field orders, pinned), the batch-1 observers, and P2's twelve injected properties (`spec_path` None, `NO_NULL`, a JSBSim write after load with an exact read-back; the neutral value's basis stated). tests/test_registry.py enumerates all four groups.
* **The verifier's datum block** is the text tests/test_geoid.py pins (`VERIFY_DATUM_PATCH`, now the P10 / D1 block with `datum_independent`): the batch-1 block was replaced by that text and the independent crop check runs after the datum clause.
* **Enumerations extended**: tests/test_limits.py's derived-column set gains `undulation_m` and `hae_m` and its per-run record list gains `scene.geoid_undulation_m` (every run manifest now carries the datum record beside the limits record); the capture manifest's `scene.geoid_undulation_m` record is the headless flight's.
* **Guard form**: a guard's last line is `    || failures=$((failures+1))` and nothing else -- 21 of D1's guards carried a trailing `# fires: yes` comment that the parser's line-end anchor does not read; the comments were removed (the measurement lives in the report). The script's diff against the previous commit is insert-only.
* docs/JSBSIM_CORRECTIONS.md gains **section 15** (P2's measured alpha lag of a `<system>` copy); P6's three facts will be 16-18.
* Floors for the injections' effect channels (N, deg/s) joined `FLOORS_BY_UNIT`, stated as such.
