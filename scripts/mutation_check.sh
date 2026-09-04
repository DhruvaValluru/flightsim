#!/usr/bin/env bash
# Disable a guard, confirm the corresponding test fails, restore, confirm green.
#
# A test that passes when its guard is removed is not a test, and §1.7 is the
# reason this script exists: the previous build's suite reported 34/34 while a
# broken run shipped.
#
# Why the cache purge matters
# ---------------------------
# macOS system Python sets sys.pycache_prefix, so bytecode is written to
# ~/Library/Caches/com.apple.python/<abs-path-to-repo>/ and NOT to __pycache__
# inside the tree. A `find . -name __pycache__` therefore purges nothing.
#
# That is not academic. A mutation that swaps two digits leaves the file size
# unchanged, and this repo hit a case where the restored source was shadowed by
# stale bytecode compiled from the mutated version -- so a correct fix appeared
# to fail and a mutation appeared not to take. Every invalidation below is
# belt-and-braces on purpose.
set -uo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
PYTEST=.venv/bin/pytest

purge_cache() {
    find . -name __pycache__ -type d -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null
    local prefix
    prefix=$($PY -c 'import sys; print(sys.pycache_prefix or "")')
    if [ -n "$prefix" ]; then
        rm -rf "${prefix}${PWD}" 2>/dev/null
    fi
}

# mutate <file> <python-repr-of-old> <python-repr-of-new> <label> <tests...>
mutate() {
    local file="$1" old="$2" new="$3" label="$4"; shift 4
    local backup; backup=$(mktemp)
    cp "$file" "$backup"

    if ! $PY - "$file" "$old" "$new" <<'EOF'
import sys
path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(path).read()
if old not in src:
    sys.exit(f"  mutation target not found in {path}: {old!r}")
open(path, "w").write(src.replace(old, new, 1))
EOF
    then
        echo "  SKIP  $label -- could not apply mutation"
        cp "$backup" "$file"; rm -f "$backup"; return 1
    fi

    purge_cache
    if $PYTEST "$@" -q >/dev/null 2>&1; then
        echo "  WEAK  $label -- tests still pass with the guard removed"
        local result=1
    else
        echo "  ok    $label -- tests fail with the guard removed"
        local result=0
    fi
    cp "$backup" "$file"; rm -f "$backup"; purge_cache
    return $result
}

echo "Baseline:"
purge_cache
if $PYTEST -q >/dev/null 2>&1; then echo "  ok    suite is green"; else
    echo "  ABORT suite is not green before mutating"; exit 1; fi

echo
echo "Mutations (each must make its test fail):"
failures=0

mutate core/fdm/properties.py \
    'if flag is None:
            raise UnknownPropertyError(
                f"{name!r} is not in the loaded model'"'"'s property catalog "
                f"({len(self._access)} entries). JSBSim would silently create "' \
    'if False:
            raise UnknownPropertyError(
                f"{name!r} is not in the loaded model'"'"'s property catalog "
                f"({len(self._access)} entries). JSBSim would silently create "' \
    "property-name validation" tests/test_properties.py || failures=$((failures+1))

mutate core/fdm/fdm.py \
    '    return _IC_PRIORITY.get(name, _IC_DEFAULT_RANK)' \
    '    return 0  # MUTATED' \
    "initial-condition ordering" tests/test_initial_conditions.py || failures=$((failures+1))

mutate core/fdm/fdm.py \
    '        self._verify_initial_conditions(ordered, tolerance)' \
    '        pass  # MUTATED' \
    "initial-condition verification" tests/test_initial_conditions.py || failures=$((failures+1))

mutate core/fdm/fdm.py \
    '        if mode is not TrimMode.GROUND and not self.engines_running:' \
    '        if False:' \
    "engines-stopped trim guard" tests/test_trim_and_engines.py || failures=$((failures+1))

mutate core/nl/compiler.py \
    '    text = _strip_terrain_phrase(text)' \
    '    pass  # MUTATED' \
    "terrain-clause stripping" tests/test_nl_compiler.py || failures=$((failures+1))

mutate core/scenario/runner.py \
    '    except ValueError as exc:
        raise UnimplementedConditionError(' \
    '    except ValueError as exc:
        stack.add(DrydenTurbulence("moderate"))  # MUTATED: silently substitute
        _unused = UnimplementedConditionError(' \
    "unimplemented-condition guard" tests/test_validation_and_run.py || failures=$((failures+1))

mutate core/control/autopilot.py \
    '        self.signs = measure(base, altitude_m=here.altitude_m,
                             cas_kt=here.cas_kt)' \
    '        from .signs import ControlSigns
        self.signs = ControlSigns(base, 1.0, 1.0, 1.0)  # MUTATED: assume signs' \
    "measured control signs" tests/test_control.py || failures=$((failures+1))

mutate core/control/systems/tecs.xml \
    '        <lt><property>ap/enable</property><value>0.5</value></lt>
        <value>-1.0</value>
        <property>ap/tecs/pitch-saturated</property>' \
    '        <lt><property>ap/enable</property><value>0.5</value></lt>
        <value>0.0</value>
        <property>ap/tecs/pitch-saturated</property>' \
    "integrator reset while disengaged" tests/test_control.py || failures=$((failures+1))

mutate core/control/derive.py \
    '    lines = []
    for i in range(engine_count):' \
    '    lines = []
    for i in range(min(engine_count, 1)):  # MUTATED: only engine 0' \
    "throttle drives every engine" tests/test_control.py || failures=$((failures+1))

mutate core/environment/stack.py \
    '        for provider in self.turbulence:
            writes.update(provider.configure())' \
    '        for provider in []:  # MUTATED: turbulence never configured
            writes.update(provider.configure())' \
    "turbulence reaches the FDM" tests/test_environment.py || failures=$((failures+1))

mutate core/environment/downburst.py \
    '        ratio_sq = (r_m / self.core_radius_m) ** 2
        integral = self.outflow_height_m * _shaping_integral(zeta)
        return -self._lambda * (1.0 - ratio_sq) * math.exp(-ratio_sq) * integral' \
    '        ratio_sq = (r_m / self.core_radius_m) ** 2
        integral = self.outflow_height_m * _shaping_integral(zeta)
        return -self._lambda * math.exp(-ratio_sq) * integral  # MUTATED: continuity factor dropped' \
    "downburst vertical velocity obeys continuity" tests/test_downburst.py || failures=$((failures+1))

mutate core/environment/stack.py \
    '        wind = self.wind_at(position, time_s)' \
    '        from .base import WindNED
        wind = WindNED()  # MUTATED: wind never applied' \
    "wind reaches the FDM" tests/test_environment.py || failures=$((failures+1))

mutate core/environment/terrain_field.py \
    '        w_up = (updraught - sink) * self.decay(position.agl_m)' \
    '        w_up = 0.0  # MUTATED: orographic lift never applied' \
    "orographic lift reaches the FDM" tests/test_environment.py || failures=$((failures+1))

mutate core/control/autopilot.py \
    '            sin_mean = sum(math.sin(math.radians(h)) for h in settled_headings) / n
            cos_mean = sum(math.cos(math.radians(h)) for h in settled_headings) / n
            achieved_hdg = math.degrees(math.atan2(sin_mean, cos_mean)) % 360.0' \
    '            achieved_hdg = sum(settled_headings) / n  # MUTATED: arithmetic mean' \
    "circular mean for heading" tests/test_control.py || failures=$((failures+1))

mutate core/terrain/dem.py \
    '    if crop_to_valid and mask.any():' \
    '    if False:  # MUTATED: keep fabricated reprojection corners' \
    "DEM cropped to real data" tests/test_terrain.py || failures=$((failures+1))

mutate core/terrain/landscape.py \
    '        scale_y=pixel_y_m * UE_CM_PER_M,' \
    '        scale_y=pixel_x_m * UE_CM_PER_M,  # MUTATED: one scale for both axes' \
    "per-axis Landscape scale" tests/test_terrain.py || failures=$((failures+1))

mutate core/terrain/landscape.py \
    '    return relief_m * UE_CM_PER_M * UE_HEIGHT_UNIT' \
    '    return relief_m * UE_CM_PER_M  # MUTATED: dropped the 1/512 constant' \
    "Landscape Z-scale constant" tests/test_terrain.py || failures=$((failures+1))

mutate core/terrain/heightfield.py \
    '        if field.digest() != meta["sha256"]:' \
    '        if False:  # MUTATED: no integrity check' \
    "heightfield integrity check" tests/test_terrain.py || failures=$((failures+1))

mutate core/fdm/fdm.py \
    '            if name in IC_WRAPPED_360:' \
    '            if False:  # MUTATED: no angular wrap' \
    "wrap-aware heading IC check" tests/test_terrain.py || failures=$((failures+1))

mutate core/experiments/seeds.py \
    '        seeds[name] = 1 + (raw % MAX_SEED)' \
    '        seeds[name] = raw >> 1  # MUTATED: seeds saturate at INT_MAX' \
    "seeds stay inside JSBSim's range" tests/test_experiments.py || failures=$((failures+1))

mutate core/experiments/sweep.py \
    '        log.truncate()' \
    '        pass  # MUTATED: stale rows accumulate' \
    "non-resumed sweep starts fresh" tests/test_experiments.py || failures=$((failures+1))

mutate core/experiments/sweep.py \
    '            record["ok"] = False' \
    '            return  # MUTATED: drop failed cases' \
    "failed cases are recorded" tests/test_experiments.py || failures=$((failures+1))

mutate core/scenario/envelope.py \
    '        lift_lbs = fdm.props.get("forces/fwz-aero-lbs")' \
    '        lift_lbs = -fdm.props.get("forces/fwz-aero-lbs")' \
    "lift-curve sign" tests/test_validation_and_run.py || failures=$((failures+1))

mutate experiments/gate5_ue_parity.py \
    '            worst = max(
                (abs(_interpolate(at, a[channel], t) - _interpolate(bt, b[channel], t))
                 for t in grid),
                default=math.inf,
            )' \
    '            worst = max(  # MUTATED: back to comparing by sample index
                (abs(a[channel][i] - b[channel][i])
                 for i in range(min(len(a[channel]), len(b[channel])))),
                default=math.inf,
            )' \
    "host parity compared on the recorded clock" tests/test_host_parity.py \
    || failures=$((failures+1))

mutate experiments/gate5_ue_parity.py \
    '        return self.fraction >= MIN_OVERLAP_FRACTION' \
    '        return True  # MUTATED: a partial UE run counts as a full one' \
    "UE run must cover the scenario" tests/test_host_parity.py || failures=$((failures+1))

mutate experiments/gate5_ue_parity.py \
    '    spec.set("hold_state", False, frm="open loop in both hosts")' \
    '    pass  # MUTATED: headless flies closed loop, UE flies open loop' \
    "both hosts fly open loop" tests/test_host_parity.py || failures=$((failures+1))

mutate experiments/gate5_ue_parity.py \
    '            raise ValueError(
                f"the {name} trajectory has no '"'"'t'"'"' column, so the two runs "' \
    '            columns["t"] = list(range(len(next(iter(columns.values())))))  # MUTATED
            _unused = (
                f"the {name} trajectory has no '"'"'t'"'"' column, so the two runs "' \
    "a trajectory with no clock is refused" tests/test_host_parity.py \
    || failures=$((failures+1))

mutate experiments/gate5_ue_parity.py \
    '    return math.degrees(0.5 * math.atan2(2.0 * cxy, cxx - cyy)), fraction' \
    '    return 0.0, fraction  # MUTATED: the pixels are never measured' \
    "apparent bank measured from the pixels" tests/test_on_screen.py \
    || failures=$((failures+1))

mutate experiments/gate5_ue_parity.py \
    '        correlation >= ON_SCREEN["min_bank_correlation"],' \
    '        True,  # MUTATED: any pixels count as a visible roll' \
    "image bank must track FDM roll" tests/test_on_screen.py \
    || failures=$((failures+1))

mutate experiments/gate5_ue_parity.py \
    '        camera_roll <= ON_SCREEN["max_camera_roll_deg"],' \
    '        True,  # MUTATED: a camera welded to the airframe passes' \
    "camera never inherits roll" tests/test_on_screen.py || failures=$((failures+1))

mutate experiments/gate5_ue_parity.py \
    '        len(moving) >= ON_SCREEN["min_moving_surfaces"],' \
    '        True,  # MUTATED: surfaces that never moved count as articulating' \
    "surfaces must actually move geometry" tests/test_on_screen.py \
    || failures=$((failures+1))

mutate experiments/gate5_ue_parity.py \
    '        bool(records) and worst >= ON_SCREEN["min_lit_fraction"],' \
    '        True,  # MUTATED: a blank frame counts as a frame' \
    "a blank frame is not evidence" tests/test_on_screen.py || failures=$((failures+1))

mutate experiments/host_parity_matrix.py \
    '    if achieved != wanted:' \
    '    if False:  # MUTATED: the row may name a condition it did not run' \
    "matrix rows run what they claim" tests/test_parity_matrix.py \
    || failures=$((failures+1))

mutate experiments/host_parity_matrix.py \
    '        elif _sha256(source) != _sha256(target):' \
    '        elif False:  # MUTATED: the hosts may load different aircraft files' \
    "both hosts load identical model XML" tests/test_parity_matrix.py \
    || failures=$((failures+1))

mutate experiments/host_parity_matrix.py \
    '    return passed == len(compared) and bool(compared)' \
    '    return passed == len(compared)  # MUTATED: an empty matrix passes' \
    "an empty matrix is not a pass" tests/test_parity_matrix.py \
    || failures=$((failures+1))

mutate experiments/gate5_ue_parity.py \
    '            series_a = _unwrap_degrees(a[channel])
            series_b = _unwrap_degrees(b[channel])' \
    '            series_a = list(a[channel])  # MUTATED: raw wrapped series
            series_b = list(b[channel])' \
    "heading compared on the circle" tests/test_host_parity.py \
    || failures=$((failures+1))

mutate experiments/gate5_ue_parity.py \
    '    start, end = max(at[0], bt[0]), min(at[-1], bt[-1])' \
    '    start, end = max(at[4], bt[4]), min(at[-1], bt[-1])  # MUTATED: skip a leading window' \
    "no leading window of the flight is skipped (Package A replaced the one-sample exemption)" \
    tests/test_host_parity.py || failures=$((failures+1))

mutate experiments/gate5_ue_parity.py \
    '    grid = [t for t in at if start <= t <= end]' \
    '    grid = [t for t in at if start <= t <= end][1:]  # MUTATED: the trim snapshot is exempt again' \
    "no sample is exempt: the trim snapshot is graded (Package A retired the one-sample exemption)" \
    tests/test_host_parity.py || failures=$((failures+1))

mutate experiments/gate6_visual.py \
    '        ratio <= THRESHOLDS["max_extinction_ratio"],' \
    '        True,  # MUTATED: a crisp far ridge counts as extinction' \
    "extinction must fade the far ridge" tests/test_gate6_visual.py \
    || failures=$((failures+1))

mutate experiments/gate6_visual.py \
    '        area >= THRESHOLDS["min_valley_shadow_px"],
        f"{area} px of the terrain band darken when cast shadows are on "' \
    '        True,  # MUTATED: any sliver of shadow shadows the valley
        f"{area} px of the terrain band darken when cast shadows are on "' \
    "valley shadow needs real area" tests/test_gate6_visual.py \
    || failures=$((failures+1))

mutate experiments/gate6_visual.py \
    '    area = int((darkened & ~body).sum())' \
    '    area = int(darkened.sum())  # MUTATED: the dark body counts as its shadow' \
    "aircraft body is not its shadow" tests/test_gate6_visual.py \
    || failures=$((failures+1))

mutate experiments/gate6_visual.py \
    '        excursion >= THRESHOLDS["min_control_excursion"],' \
    '        True,  # MUTATED: a metric nothing can trip still validates' \
    "exposure control must trip the metric" tests/test_gate6_visual.py \
    || failures=$((failures+1))

# -- Phase 6B guards ------------------------------------------------------

mutate assets_pipeline/convert.py \
    '    if fdm_name not in config["fdm_match"]:' \
    '    if False:  # MUTATED: any mesh may fly any FDM' \
    "a mesh must match the FDM it flies (1.4)" tests/test_phase6b.py \
    || failures=$((failures+1))

mutate assets_pipeline/convert.py \
    '                    if uv_area < 1e-9:' \
    '                    if False:  # MUTATED: degenerate UVs pass through' \
    "degenerate UVs corrupt the mesh build" tests/test_phase6b.py \
    || failures=$((failures+1))

mutate core/terrain/glo30.py \
    '    report["ok"] = bool(report["samples"] >= samples * 0.9
                        and abs(report["mean_m"]) < 5.0
                        and report["p95_excess_m"] < 30.0)' \
    '    report["ok"] = True  # MUTATED: every bake verifies' \
    "a bake must match its source DEM" tests/test_phase6b.py tests/test_terrain.py \
    || failures=$((failures+1))

mutate core/terrain/glo30.py \
    '            "ok": bool(abs(best - surveyed) < 250.0),' \
    '            "ok": True,  # MUTATED: any raster is the named mountain' \
    "a named summit must be where the raster says" tests/test_phase6b.py \
    || failures=$((failures+1))

mutate experiments/turbulence_ue.py \
    '        "ok": bool(turbulent_rms >= NULL_TEST["min_turbulent_rms"]
                   and ratio >= NULL_TEST["min_rms_ratio"]),' \
    '        "ok": True,  # MUTATED: still air counts as turbulence' \
    "UE turbulence must reach the FDM" tests/test_phase6b.py \
    || failures=$((failures+1))

mutate experiments/orographic_ue.py \
    '        "ok": bool(worst <= THRESHOLDS["max_port_difference_mps"]),' \
    '        "ok": True,  # MUTATED: a drifted port still verifies' \
    "the orographic port must match the original" tests/test_phase6b.py \
    || failures=$((failures+1))

mutate core/scenario/card.py \
    '    elif str(spec.turbulence.value) != "none":' \
    '    elif False:  # MUTATED: turbulent cards carry no provider writes' \
    "turbulent cards carry the provider's exact writes" tests/test_phase6b.py \
    || failures=$((failures+1))

# -- imagery drape: verification and license pin -------------------------

mutate core/terrain/imagery.py \
    '    report["ok"] = bool(report["samples"] >= samples * 0.9
                        and report["mean_abs_counts"] < 8.0
                        and report["p95_abs_counts"] < 30.0)' \
    '    report["ok"] = True  # MUTATED: every drape verifies' \
    "a draped texture must match its source imagery" tests/test_imagery.py \
    || failures=$((failures+1))

mutate core/terrain/imagery.py \
    'LAYER = "s2cloudless"' \
    'LAYER = "s2cloudless-2018"  # MUTATED: the NC-licensed layer' \
    "only the CC-BY-SA 2016 layer may be fetched" tests/test_imagery.py \
    || failures=$((failures+1))

# -- log-profile surface layer (Phase 7) ---------------------------------

mutate core/environment/wind.py \
    '        return (self.reference_speed_mps
                * math.log(z / self.z0_m)
                / math.log(self.reference_height_m / self.z0_m))' \
    '        return (self.reference_speed_mps
                * (z / self.z0_m)
                / (self.reference_height_m / self.z0_m))  # MUTATED: linear' \
    "the log profile must actually be the log law" tests/test_environment.py \
    || failures=$((failures+1))

mutate core/environment/wind.py \
    '        z = min(max(agl_m, 0.0), self.SURFACE_LAYER_TOP_M)' \
    '        z = max(agl_m, 0.0)  # MUTATED: extended past its derivation' \
    "the log law must be held at the surface-layer top" tests/test_environment.py \
    || failures=$((failures+1))

# -- Allen thermals (Phase 7) --------------------------------------------

mutate core/environment/thermals.py \
    '        we = min(-(at * w_bar * (1.0 - swd)) / (area - at), 0.0)' \
    '        we = 0.0  # MUTATED: no environment sink, mass not conserved' \
    "the environment sink must balance the updraft flux" tests/test_thermals.py \
    || failures=$((failures+1))

mutate core/environment/thermals.py \
    '        return self.wstar_mps * zzi ** (1.0 / 3.0) * (1.0 - 1.1 * zzi)' \
    '        return self.wstar_mps * zzi ** (1.0 / 3.0) * (1.0 - 0.1 * zzi)  # MUTATED' \
    "eq 11 profile must match the TM check case" tests/test_thermals.py \
    || failures=$((failures+1))

mutate core/scenario/card.py \
    '        try:
            fdm.do_trim(1)
        except jsbsim.TrimFailureError:
            return None' \
    '        try:
            fdm.do_trim(1)
        except jsbsim.TrimFailureError:
            pass  # MUTATED: a glider trim is accepted' \
    "the mixture discovery must refuse a failed trim" tests/test_trim_and_engines.py \
    || failures=$((failures+1))

# -- the evolving-conditions schedule (Phase 7 3.1) ----------------------

mutate core/environment/turbulence.py \
    '    #: Severity pin: nonzero constant, written once (see class docstring).
    PINNED_SEVERITY = 1.0' \
    '    #: Severity pin: nonzero constant, written once (see class docstring).
    PINNED_SEVERITY = 0.0  # MUTATED: the measured master off-switch' \
    "the schedule's severity pin must be nonzero" tests/test_environment.py \
    || failures=$((failures+1))

# -- lee-rotor turbulence: the §13 contract ------------------------------

mutate core/environment/rotor.py \
    '            "atmosphere/turbulence/milspec/severity": PINNED_SEVERITY,' \
    '            "atmosphere/turbulence/milspec/severity": 0.0,  # MUTATED' \
    "rotor severity pin must be nonzero (0 is a master off-switch)" \
    tests/test_rotor.py || failures=$((failures+1))

mutate core/environment/rotor.py \
    '        return {W20_PROP: u.kt_to_fps(w20_kt)}' \
    '        return {W20_PROP: u.kt_to_fps(w20_kt), "atmosphere/randomseed": float(self.seed)}  # MUTATED' \
    "rotor per-step writes must never touch the seed" \
    tests/test_rotor.py || failures=$((failures+1))

mutate core/environment/rotor.py \
    '        return min(max(self.background_w20_kt, rotor_w20_kt), W20_CAP_KT)' \
    '        return max(self.background_w20_kt, rotor_w20_kt)  # MUTATED: uncapped' \
    "rotor W20 must stay on the measured ladder (severe cap)" \
    tests/test_rotor.py || failures=$((failures+1))

mutate core/environment/rotor.py \
    'ROTOR_SIGMA_GAIN = 1.0' \
    'ROTOR_SIGMA_GAIN = 0.0  # MUTATED: rotor decoupled' \
    "rotor sigma must couple to the lee-sink field" \
    tests/test_rotor.py || failures=$((failures+1))

mutate core/environment/stack.py \
    '        for provider in self.turbulence:
            writes.update(provider.step_writes(position, time_s))' \
    '        pass  # MUTATED: per-step intensity writes never reach the FDM' \
    "the stack must deliver per-step turbulence intensity writes" \
    tests/test_rotor.py || failures=$((failures+1))

# -- Phase 8: the LLM compiler and the web front door --------------------

mutate core/nl/llm_compiler.py \
    '        if entry["source"] not in ("user", "inferred", "model"):' \
    '        if False:  # MUTATED: a model may claim default provenance' \
    "the model cannot claim provenance it does not have" \
    tests/test_llm_compiler.py || failures=$((failures+1))

mutate core/nl/llm_compiler.py \
    '        elif "enum" in value_schema and value not in value_schema["enum"]:' \
    '        elif False:  # MUTATED: out-of-vocabulary values accepted' \
    "out-of-vocabulary values are refused, never patched" \
    tests/test_llm_compiler.py || failures=$((failures+1))

mutate webapp/runs.py \
    '            if editor_running():' \
    '            if False:  # MUTATED: concurrent editor runs allowed' \
    "the web app enforces the single-editor lock" \
    tests/test_webapp.py || failures=$((failures+1))

mutate webapp/server.py \
    '    if not verdict["ok"]:' \
    '    if False:  # MUTATED: an invalid edited spec runs anyway' \
    "the run endpoint re-validates whatever the page hands it" \
    tests/test_webapp.py || failures=$((failures+1))

mutate webapp/runs.py \
    '    if float(spec.airspeed.value) < speeds.vs_kt * STALL_MARGIN:' \
    '    if False:  # MUTATED: defaulted airspeed never planned' \
    "a defaulted airspeed is planned to the measured envelope" \
    tests/test_webapp.py || failures=$((failures+1))

# -- the scene director's rails (2026-08-13) ------------------------------

mutate core/nl/llm_compiler.py \
    '        if not (isinstance(entry["from"], str) and entry["from"].strip()):' \
    '        if False:  # MUTATED: undeclared guesses accepted' \
    "a model guess with no declared reason is refused" \
    tests/test_llm_compiler.py || failures=$((failures+1))

mutate webapp/runs.py \
    'PLANNABLE_SOURCES = ("default", "model", "derived")' \
    'PLANNABLE_SOURCES = ("default", "model", "derived", "user", "inferred")  # MUTATED' \
    "planners never move a user-stated value" \
    tests/test_webapp.py || failures=$((failures+1))

mutate webapp/runs.py \
    '            "wind_direction", float(round((axis + 90.0) % 360.0)),' \
    '            "wind_direction", 0.0,  # MUTATED: ridge axis ignored' \
    "the planned wind blows across the computed ridge axis" \
    tests/test_webapp.py || failures=$((failures+1))

# -- Phase 8 LLM compiler v2: questions, cap, provenance, geography ------

mutate core/nl/llm_compiler.py \
    '    if questions and not allow_questions:' \
    '    if False:  # MUTATED: a second question round is accepted' \
    "the answer round rejects further questions (one round only)" \
    tests/test_llm_compiler.py || failures=$((failures+1))

mutate core/nl/llm_compiler.py \
    '    if len(questions) > MAX_QUESTIONS:' \
    '    if False:  # MUTATED: unlimited questions accepted' \
    "the 3-question cap is enforced in parsing, not just requested" \
    tests/test_llm_compiler.py || failures=$((failures+1))

mutate core/nl/llm_compiler.py \
    '        if entry["from"].strip().startswith("answer to") and entry["source"] != "user":' \
    '        if False:  # MUTATED: answered fields may claim any source' \
    "a field decided by an answer is the user speaking (source user)" \
    tests/test_llm_compiler.py || failures=$((failures+1))

mutate core/nl/llm_compiler.py \
    '    missing = set(location_keys) - set(table)' \
    '    missing = set()  # MUTATED: bake coverage never checked' \
    "a bake missing from the locations block fails at import" \
    tests/test_llm_compiler.py || failures=$((failures+1))

# -- Phase 8 aero panel: property selftest + frozen graded channels ------

mutate ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimInteractiveMode.cpp \
    '		if (!Recorder->SelftestProperties(Error)) { return false; }' \
    '		if (false) { return false; }  // MUTATED: selftest skipped' \
    "the interactive host refuses a run whose channels cannot be read" \
    tests/test_aero_channels.py || failures=$((failures+1))

mutate experiments/gate5_ue_parity.py \
    '    "lon_deg": 1e-4,' \
    '    "lon_deg": 1e-4, "alpha_deg": 1.0,  # MUTATED: graded set grew' \
    "the Gate 5 graded channel set does not grow by drive-by" \
    tests/test_aero_channels.py || failures=$((failures+1))

# -- Phase 8B airframe contact + terrain-driven airflow ------------------

mutate core/terrain/contact.py \
    '            if station_altitude_m < terrain_m:' \
    '            if False:  # MUTATED: wings never feel the terrain' \
    "a wingtip below the surface is an impact, not a fly-through" \
    tests/test_terrain_contact.py || failures=$((failures+1))

mutate ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimScenarioWorld.cpp \
    '	return !Crashed(TimeSeconds, Error) && !AirframeImpact(TimeSeconds, Error);' \
    '	return !Crashed(TimeSeconds, Error);  // MUTATED: wings ignored' \
    "the UE step refuses on airframe impact, not just on crash" \
    tests/test_terrain_contact.py || failures=$((failures+1))

mutate webapp/runs.py \
    '            turbulence_provider=rotor_provider,' \
    '            turbulence_provider=None,  # MUTATED: rotor word dropped' \
    "the rotor card word travels with its pinned turbulence writes" \
    tests/test_webapp.py || failures=$((failures+1))

mutate webapp/runs.py \
    '                clearance = min(' \
    '                clearance = max(  # MUTATED: tips never tighten the plan' \
    "the clearance plan is the minimum over span stations" \
    tests/test_webapp.py || failures=$((failures+1))

mutate webapp/runs.py \
    '            fdm.props.set("atmosphere/wind-down-fps", -w_up / 0.3048)' \
    '            pass  # MUTATED: orographic sink never reaches the plan' \
    "the pre-flight flies through the orographic field" \
    tests/test_webapp.py || failures=$((failures+1))

# -- Phase 9.1 surface classes -------------------------------------------

mutate core/scenario/validate.py \
    '        surface_class(str(spec.surface.value))' \
    '        pass  # MUTATED: unmodelled ground cover runs anyway' \
    "an unmodelled surface word refuses by name" \
    tests/test_surface.py || failures=$((failures+1))

mutate ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimScenarioWorld.cpp \
    '				NorthFps = SpeedMps * LogProfileCard.NorthUnit / 0.3048;' \
    '				NorthFps += SpeedMps * LogProfileCard.NorthUnit / 0.3048;  // MUTATED: double-counted' \
    "carries_base replaces the base wind instead of double-counting" \
    tests/test_surface.py || failures=$((failures+1))

mutate core/scenario/runner.py \
    '    if surface is not None and wind_speed > 0.0:' \
    '    if False:  # MUTATED: surface shear never attaches' \
    "a surface class attaches its roughness shear" \
    tests/test_surface.py || failures=$((failures+1))

# -- Phase 9 dynamic terrain + historical weather ------------------------

mutate webapp/server.py \
    '    unbaked = needs_dynamic_bake(spec)' \
    '    unbaked = None  # MUTATED: stated places run on a flat slab' \
    "stated coordinates without a bake refuse instead of faking a slab" \
    tests/test_webapp.py || failures=$((failures+1))

mutate webapp/runs.py \
    '    if (str(spec.wind_speed.source) == "user"' \
    '    if False and (str(spec.wind_speed.source) == "user"' \
    "a stated wind is never overwritten by reanalysis" \
    tests/test_webapp.py || failures=$((failures+1))

# -- Phase 9.2/9.3 storm + tornado ---------------------------------------

mutate core/environment/tornado.py \
    '            v_t = self.v_max_mps * (self.r_core_m / r)' \
    '            v_t = self.v_max_mps  # MUTATED: no 1/r decay outside the core' \
    "the vortex decays as 1/r outside the core" \
    tests/test_weather_events.py || failures=$((failures+1))

mutate webapp/runs.py \
    '    if (str(spec.weather_event.value) == "thunderstorm"
            and str(spec.turbulence.source) in PLANNABLE_SOURCES):' \
    '    if str(spec.weather_event.value) == "thunderstorm":  # MUTATED: stated words moved' \
    "the thunderstorm composition never moves a stated turbulence word" \
    tests/test_weather_events.py || failures=$((failures+1))

# -- Camera Phase 1 ------------------------------------------------------

mutate core/scenario/spec.py \
    '        version = data.get("spec_version")
        if version != SPEC_VERSION:' \
    '        version = data.get("spec_version")
        if False:  # MUTATED: old spec versions load anyway' \
    "a wrong spec_version refuses by name" \
    tests/test_camera_spec.py tests/test_scenario_spec.py \
    || failures=$((failures+1))

mutate core/scenario/camera.py \
    '        if current.source not in (Source.DEFAULT, Source.DERIVED,
                                  Source.MODEL):' \
    '        if False:  # MUTATED: stated camera fields silently move' \
    "a stated camera field is never silently moved" \
    tests/test_camera_spec.py || failures=$((failures+1))

mutate core/capture/poses.py \
    '            roll.append(0.0)                       # never inherit roll' \
    '            roll.append(air_roll[i])  # MUTATED: chase inherits roll' \
    "only the cockpit preset inherits roll" \
    tests/test_camera_poses.py || failures=$((failures+1))

mutate core/capture/poses.py \
    'def _heading_only(heading_deg, forward, right, up):
    """Rotate an offset in the heading-only frame (yaw applied, pitch
    and roll DISCARDED -- the §1.5 rule)."""
    y = math.radians(heading_deg)' \
    'def _heading_only(heading_deg, forward, right, up):
    """MUTATED: tilted frame."""
    heading_deg = heading_deg + 0.0
    up = up + forward * 0.26  # MUTATED: pitch leaks into the offset
    y = math.radians(heading_deg)' \
    "chase offsets live in the heading-only frame" \
    tests/test_camera_poses.py || failures=$((failures+1))

mutate core/capture/schedule.py \
    '        if count > n:' \
    '        if False:  # MUTATED: unreachable counts schedule anyway' \
    "an unreachable capture count refuses by name" \
    tests/test_camera_schedule.py || failures=$((failures+1))

mutate core/capture/schedule.py \
    '    if trigger != "interval" and count > 0 and len(indices) != count:' \
    '    if False:  # MUTATED: the count contract is not enforced' \
    "a stated capture count is a contract, not a hint" \
    tests/test_camera_schedule.py || failures=$((failures+1))

mutate core/capture/schedule.py \
    '        if last is None or t[i] - last >= refractory:' \
    '        if True:  # MUTATED: refractory ignored, one capture per sample' \
    "the refractory period collapses bursts" \
    tests/test_camera_schedule.py || failures=$((failures+1))

mutate core/capture/validate.py \
    '    if not 0.0 < focal <= MAX_FOCAL_MM:' \
    '    if False:  # MUTATED: non-physical lenses pass' \
    "a non-physical focal length refuses" \
    tests/test_camera_validate.py || failures=$((failures+1))

mutate core/capture/validate.py \
    '        if worst is not None and worst < CAMERA_MIN_CLEARANCE_M:
            out.append(Violation(
                "camera.terrain_clearance",
                f"{who}: the solved pose track descends' \
    '        if False:  # MUTATED: buried track cameras pass
            out.append(Violation(
                "camera.terrain_clearance",
                f"{who}: the solved pose track descends' \
    "the solved track is clearance-checked against the raster" \
    tests/test_camera_validate.py || failures=$((failures+1))

mutate core/capture/validate.py \
    '        if outside:
            out.append(Violation(
                "camera.scene_bounds",
                f"{who}: {outside} of {len(track)} solved poses fall' \
    '        if False:  # MUTATED: off-raster poses pass
            out.append(Violation(
                "camera.scene_bounds",
                f"{who}: {outside} of {len(track)} solved poses fall' \
    "poses off the scene raster refuse" \
    tests/test_camera_validate.py || failures=$((failures+1))

mutate core/capture/validate.py \
    '        if inside:
            out.append(Violation(
                "camera.hazard_intersection",' \
    '        if False:  # MUTATED: cameras inside the vortex pass
            out.append(Violation(
                "camera.hazard_intersection",' \
    "poses inside the tornado core refuse" \
    tests/test_camera_validate.py || failures=$((failures+1))

mutate core/scenario/validate.py \
    '    report.violations.extend(validate_cameras(spec))' \
    '    pass  # MUTATED: camera checks never reach the verdict' \
    "camera refusals ride the core validation surface" \
    tests/test_camera_validate.py || failures=$((failures+1))

mutate core/nl/llm_compiler.py \
    '            if name not in CAMERA_FIELD_VALUE_SCHEMAS:' \
    '            if False:  # MUTATED: unknown camera fields patched in' \
    "unknown LLM camera fields refuse loudly" \
    tests/test_llm_compiler.py || failures=$((failures+1))

mutate core/nl/llm_compiler.py \
    '    if len(cameras) > MAX_CAMERAS:' \
    '    if False:  # MUTATED: unbounded camera lists' \
    "the LLM camera list is bounded" \
    tests/test_llm_compiler.py || failures=$((failures+1))

mutate core/nl/compiler.py \
    '    if count is not None:
        camera.capture_count = Quantity(' \
    '    if False:  # MUTATED: image counts silently dropped
        camera.capture_count = Quantity(' \
    "a stated image count reaches the camera spec" \
    tests/test_nl_compiler.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if not (0.0 <= u_q <= record["width_px"]' \
    '            if False and not (0.0 <= u_q <= record["width_px"]' \
    "an aimed camera that cannot see the aircraft fails verification" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        "cross_view_consistency", worst <= tol_m,' \
    '        "cross_view_consistency", True,  # MUTATED' \
    "two-view triangulation errors fail verification" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        if indices != list(range(declared)):' \
    '        if False:  # MUTATED: dropped frames pass' \
    "a dropped frame fails the count-exactness check" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        if worst > tol_s:' \
    '        if False:  # MUTATED: diverging capture times pass' \
    "diverging capture times fail the alignment check" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate webapp/runs.py \
    '        and str(camera.position_alt_m.source) in PLANNABLE_SOURCES]' \
    '        and True]  # MUTATED: stated camera placements re-planned' \
    "the camera planner never moves a stated placement" \
    tests/test_camera_spec.py || failures=$((failures+1))

# -- Aircraft fail-safe guards --------------------------------------------

mutate assets_pipeline/importer.py \
    '    if reason:' \
    '    if False:  # MUTATED: an unlicensable airframe is fetched anyway' \
    "an airframe with no upstream license is never fetched (3.3)" \
    tests/test_aircraft_assets.py || failures=$((failures+1))

mutate assets_pipeline/importer.py \
    '    if missing:' \
    '    if False:  # MUTATED: trust the editor exit code' \
    "an import is verified by the assets, not the editor exit code" \
    tests/test_aircraft_assets.py || failures=$((failures+1))

mutate webapp/runs.py \
    '    if aircraft not in buildable:' \
    '    if False:  # MUTATED: an airframe with no config renders anyway' \
    "an airframe with no model config still refuses by name" \
    tests/test_aircraft_assets.py tests/test_webapp.py \
    || failures=$((failures+1))

mutate webapp/runs.py \
    '                       if not unavailable_reason(n))' \
    '                       if True)  # MUTATED: offer unbuildable airframes' \
    "the refusal never points at an airframe that cannot be built" \
    tests/test_aircraft_assets.py || failures=$((failures+1))

mutate webapp/runs.py \
    '    if is_imported(aircraft):' \
    '    if False:  # MUTATED: rebuild the model on every render' \
    "the aircraft fail-safe builds once, not once per render" \
    tests/test_aircraft_assets.py || failures=$((failures+1))

mutate webapp/runs.py \
    '        except AircraftAssetError as exc:
            run.push("failed", f"[{exc.constraint}] {exc.message}")' \
    '        except AircraftAssetError as exc:
            pass  # MUTATED: a failed model build is not named' \
    "a failed model build fails the run BY NAME" \
    tests/test_aircraft_assets.py || failures=$((failures+1))

# -- Capture-on-the-page guards -------------------------------------------

mutate webapp/server.py \
    '    if not run_id.isalnum() or name not in _artifact_paths(run_id):' \
    '    if False:  # MUTATED: serve any path the request names' \
    "a run serves only the files it actually wrote" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/server.py \
    '    spec, refusal = _prepare_run_spec(request)
    if refusal is not None:
        return refusal
    outcome = manager.start_capture(spec, provenance={' \
    '    spec, refusal = _prepare_run_spec(request)
    if False:  # MUTATED: capture skips the shared validation
        return refusal
    outcome = manager.start_capture(spec, provenance={' \
    "the capture endpoint never bypasses the shared validation" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '            run.push("capture", f"[{exc.constraint}] {exc.message}")
            return False' \
    '            run.push("capture", f"[{exc.constraint}] {exc.message}")
            return True  # MUTATED: a refused capture reports success' \
    "a refused capture never reports a successful run" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/capture.py \
    '    if refusals:' \
    '    if False:  # MUTATED: build a manifest for refused geometry' \
    "a scene-refused pose track writes no manifest" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Package A guards: the aircraft is trimmed IN the wind ------------------

mutate core/scenario/runner.py \
    '        fdm.set_wind_initial_conditions(north_fps, east_fps, 0.0)' \
    '        pass  # MUTATED: wind written nowhere; trim in calm air' \
    "the runner places the spec wind in the initial conditions" \
    tests/test_trim_in_wind.py || failures=$((failures+1))

mutate core/scenario/runner.py \
    '    fdm.verify_wind_state(north_fps, east_fps, float(spec.airspeed.value))' \
    '    pass  # MUTATED: a calm trim in a wind spec is not refused' \
    "a trim that lost the wind refuses by name (wind.trim_state)" \
    tests/test_trim_in_wind.py || failures=$((failures+1))

mutate core/fdm/fdm.py \
    '        else:
            raise TrimStateError(
                f"{self.model.name!r}: could not place a {mag / 1.6878:.1f} kt "' \
    '        else:
            pass  # MUTATED: an unconverged fixed point is handed to trim
            _unused = (
                f"{self.model.name!r}: could not place a {mag / 1.6878:.1f} kt "' \
    "an unconverged wind fixed point refuses rather than approximates" \
    tests/test_trim_in_wind.py || failures=$((failures+1))

mutate experiments/gate5_ue_parity.py \
    '    start, end = max(at[0], bt[0]), min(at[-1], bt[-1])' \
    '    start, end = max(at[1], bt[1]), min(at[-1], bt[-1])  # MUTATED: exemption back' \
    "host parity grades the trim snapshot (no first-sample exemption)" \
    tests/test_host_parity.py || failures=$((failures+1))

# -- Package B guard: the sign probe flies the aircraft's own state -----------

mutate core/control/autopilot.py \
    '        self.signs = measure(base, altitude_m=here.altitude_m,
                             cas_kt=here.cas_kt)' \
    '        self.signs = measure(base)  # MUTATED: hardcoded transport probe' \
    "the sign probe flies the engaging aircraft's own trimmed state" \
    tests/test_control_signs.py || failures=$((failures+1))

# -- Package C guard: a failed closure fails the run ---------------------------

mutate webapp/runs.py \
    '        if not run.capture["closure"]["ok"]:' \
    '        if False:  # MUTATED: a failed closure is a note, not a failure' \
    "a failed closure fails the run by name (closure.<check>)" \
    tests/test_closure_pair.py || failures=$((failures+1))

# -- Package D guards: the throttle loop knows how much aircraft it flies ----

mutate core/control/autopilot.py \
    '        props.set_many(self.performance.as_properties())' \
    '        pass  # MUTATED: thr-per-ste stays at the template constant 1.0' \
    "the TECS throttle normalisation is written from a measurement, not a constant" \
    tests/test_performance.py || failures=$((failures+1))

mutate core/performance.py \
    '    if thrust_max_n <= thrust_trim_n or thrust_up_n <= thrust_down_n:' \
    '    if False:  # MUTATED: an airframe with no excess power is measured anyway' \
    "a performance probe with no excess power refuses by name" \
    tests/test_performance.py || failures=$((failures+1))

# -- Package E guard: the terrain ahead is looked at ------------------------

mutate core/terrain/lookahead.py \
    'HORIZON_S = 90.0' \
    'HORIZON_S = 0.0  # MUTATED: the look-ahead sees nothing ahead' \
    "the altitude setpoint is raised ahead of terrain the aircraft can clear, and the run refuses by name ahead of terrain it cannot" \
    tests/test_terrain_lookahead.py || failures=$((failures+1))

# -- Package F guard: the rotor acts or says it doesn't -----------------------

mutate core/environment/rotor.py \
    '        acts = self.delivered_sigma_w_mps() >= ROTOR_ACTS_SIGMA_W_MPS' \
    '        acts = True  # MUTATED: the rotor claims to act whatever the FDM delivered' \
    "a run carries the word lee-rotor only if the FDM delivered the turbulence" \
    tests/test_rotor.py || failures=$((failures+1))

mutate core/environment/rotor.py \
    '            return measure_poe_sigma_w_mps(msl_m, agl_m, PINNED_SEVERITY)' \
    '            return 0.544  # MUTATED: the old constant POE index-1 floor claim' \
    "the sigma_w claimed above the ceiling is measured at the planned MSL, not a constant" \
    tests/test_rotor.py || failures=$((failures+1))

# -- Package G guard: the turn is coordinated from a measured gain --------------

mutate core/control/autopilot.py \
    '            props.set_many(self.yaw_authority.as_properties())' \
    '            pass  # MUTATED: the sideslip loop stays at the template gain 0' \
    "the sideslip-to-rudder gains are written from a measurement, not left at zero" \
    tests/test_turn_coordination.py || failures=$((failures+1))

mutate core/terrain/lookahead.py \
    '            horizon = min(horizon, max(0.0, float(remaining_s)))' \
    '            pass  # MUTATED: terrain past the end of the run is graded anyway' \
    "the look-ahead horizon never reaches past the end of the run" \
    tests/test_terrain_lookahead.py || failures=$((failures+1))

mutate webapp/capture.py \
    '    seconds = min(float(pair.duration.value), CLIP_SECONDS)' \
    '    seconds = float(pair.duration.value)  # MUTATED: the pair flies past the clip' \
    "the closure pair grades the clip's own window" \
    tests/test_closure_pair.py || failures=$((failures+1))

# -- Camera Phase 1 finished: engine parity on rendered frames -------------

mutate core/capture/verify.py \
    '            if gap_pos > pos_tol_m:' \
    '            if False:  # MUTATED: an applied position off the solved pose passes' \
    "an applied camera position off the solved pose fails engine parity" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if gap_ang > ang_tol_deg:' \
    '            if False:  # MUTATED: an applied orientation off the solved pose passes' \
    "an applied camera orientation off the solved pose fails engine parity" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if gap_t > tol_t:' \
    '            if False:  # MUTATED: a capture off its scheduled instant passes' \
    "a capture off its scheduled instant fails engine parity" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                if size is not None and size != expected:' \
    '                if False:  # MUTATED: a PNG of the wrong size passes' \
    "a rendered PNG of the wrong size fails engine parity" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                if gap_px > px_tol:' \
    '                if False:  # MUTATED: reprojection through the applied pose unchecked' \
    "the aircraft must reproject through the applied pose to the manifest pixel" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        if captured != scheduled or declared != scheduled:' \
    '        if False:  # MUTATED: engine frame counts unchecked' \
    "the engine's frame count must equal the schedule's for engine parity" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            ENGINE_PARITY_CHECK, None,' \
    '            ENGINE_PARITY_CHECK, True,  # MUTATED: awaiting reported as passed' \
    "awaiting engine frames is never reported as a pass" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        return all(c.ok is not False for c in self.checks)' \
    '        return True  # MUTATED: a failed check never fails the report' \
    "a failed check fails the verification report" \
    tests/test_camera_verify.py || failures=$((failures+1))

# -- Camera Phase 1, frames round 3: engine parity judges the pixels ------

mutate core/capture/verify.py \
    '    if gap_e > tol_px_d:' \
    '    if False:  # MUTATED: the engine-measured aircraft pixel is never graded' \
    "the engine-measured aircraft pixel must sit at the labelled pixel" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if gap_model > px_tol:' \
    '    if False:  # MUTATED: an engine lens that is not the card lens passes' \
    "the engine's own projection must agree with the manifest's lens model" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if not e_visible:' \
    '    if False:  # MUTATED: an aircraft the engine calls invisible passes' \
    "an aircraft the engine reports not visible fails a labelled frame" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if stats["contrast"] < contrast_min:' \
    '    if False:  # MUTATED: a flat frame passes the pixel-content clause' \
    "a frame with nothing drawn at the label window fails engine parity" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                        if png_readable:
                            frame_ok &= _pixel_content_clause(' \
    '                        if False:  # MUTATED: the pixels are never read
                            frame_ok &= _pixel_content_clause(' \
    "engine parity reads the PNG's pixels at the label window" \
    tests/test_camera_verify.py || failures=$((failures+1))

# -- Camera Phase 1, frames round 3: one coherent parity contract ---------

mutate core/capture/verify.py \
    '            elif abs(float(step) - 1.0 / rate_hz) > ENGINE_STEP_TOL_S:' \
    '            elif False:  # MUTATED: the engine step is never checked against the spec rate' \
    "render.json's step_s is checked against the manifest's rate_hz" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        tol_t = time_tol_s
        # The engine'"'"'s step is a FACT to check against the spec'"'"'s rate,' \
    '        tol_t = float(render.get("step_s", time_tol_s))  # MUTATED: the judged file declares its own tolerance
        # The engine'"'"'s step is a FACT to check against the spec'"'"'s rate,' \
    "the capture-time tolerance never comes from the file being judged" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                    budget = drawn_aircraft_budget_m(speed, rate_hz)' \
    '                    budget = {"budget_m": 2.5, "steps": 1.5, "step_m": 1.667, "speed_mps": 200.0, "rate_hz": 120.0}  # MUTATED: a constant budget' \
    "the drawn-aircraft budget is computed from the run's own speed and rate" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/schedule.py \
    '        off = off_grid_instants(times, rate_hz)
        if off:' \
    '        off = off_grid_instants(times, rate_hz)
        if False:  # MUTATED: an off-grid instant is scheduled anyway' \
    "a capture instant off the fixed-step grid is refused by name" \
    tests/test_camera_schedule.py || failures=$((failures+1))

mutate core/capture/manifest.py \
    '        if off:
            raise ValueError(' \
    '        if False:  # MUTATED: an off-grid schedule reaches the manifest
            raise ValueError(' \
    "the manifest refuses a schedule off the fixed-step grid" \
    tests/test_camera_manifest.py || failures=$((failures+1))

mutate core/capture/poses.py \
    '    if TAS_CHANNEL in columns and len(columns[TAS_CHANNEL]) == n:' \
    '    if False:  # MUTATED: the recorded airspeed is ignored' \
    "the manifest's aircraft speed is the recorded true airspeed when present" \
    tests/test_camera_manifest.py || failures=$((failures+1))

# -- Camera Phase 1 finished: the web run renders frames, not a clip ------

mutate core/capture/render_pass.py \
    '    if captured != scheduled or declared != scheduled:' \
    '    if False:  # MUTATED: a short engine pass counts as a frame set' \
    "an engine pass short of the schedule fails the run by name" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate core/capture/render_pass.py \
    '    if missing:' \
    '    if False:  # MUTATED: a scheduled PNG missing from disk passes' \
    "a scheduled PNG missing from disk fails the pass by name" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '            if problem is not None:' \
    '            if False:  # MUTATED: a failed engine pass never stops the run' \
    "a failed engine pass stops the frames run before any clip" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '            cameras=outcome.card_blocks() if outcome else None,' \
    '            cameras=None,  # MUTATED: the card carries no solved tracks' \
    "the frames run's card carries the solved pose tracks" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '        if engine is None or engine["ok"] is not True:' \
    '        if False:  # MUTATED: engine parity never fails a frames run' \
    "a frames run is done only when engine parity passed" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/capture.py \
    '            "rendered": int(per.get("rendered", 0)),' \
    '            "rendered": len(schedule),  # MUTATED: scheduled counted as rendered' \
    "a scheduled frame is never counted as rendered" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Camera Phase 1 finished: the render choice ----------------------------

mutate webapp/server.py \
    '    if not ue_available():
        return JSONResponse({"refused": UE_PLATFORM_REFUSAL,
                             "constraint": "ue.platform",
                             "reason": ue_unavailable_reason(),
                             "render": render}, status_code=409)' \
    '    if False:  # MUTATED: an engine choice with no engine is not refused
        return JSONResponse({"refused": UE_PLATFORM_REFUSAL,
                             "constraint": "ue.platform",
                             "reason": ue_unavailable_reason(),
                             "render": render}, status_code=409)' \
    "an engine render choice is refused ue.platform before the mesh rule" \
    tests/test_webapp.py || failures=$((failures+1))

mutate webapp/server.py \
    '    if render == "none":
        outcome = manager.start_capture(spec, provenance=provenance)' \
    '    if False:  # MUTATED: render=none goes through the engine gate
        outcome = manager.start_capture(spec, provenance=provenance)' \
    "render=none is the headless flow with no platform gate" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/server.py \
    '                         "render_default": render_choice_default()})' \
    '                         "render_default": "frames"})  # MUTATED: engine option defaulted without an engine' \
    "the default render choice is the richest the machine supports" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '<option value="frames">Render frames and clip</option>' \
    '<option value="frames">Render</option>' \
    "the run form carries the render choice in the stated words" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate core/util/platform.py \
    '        if not ue_bridge_binary(repo).is_file():
            return ("FlightSimBridge not built' \
    '        if False:  # MUTATED: an unbuilt bridge reports no reason
            return ("FlightSimBridge not built' \
    "an unbuilt bridge is named as the reason the engine is unavailable" \
    tests/test_platform.py || failures=$((failures+1))

# -- Camera Phase 1 finished: the CLI's --render switch ----------------------

mutate flightsim/capture.py \
    '    if render != "none" and not ue_available():' \
    '    if False:  # MUTATED: an engine choice without an engine runs headless' \
    "the CLI refuses an engine render choice by name without an engine" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '        if problem is not None:
            print(f"FAILED {RENDER_FRAMES_CONSTRAINT}: camera' \
    '        if False:  # MUTATED: a short engine pass is reported as frames
            print(f"FAILED {RENDER_FRAMES_CONSTRAINT}: camera' \
    "the CLI fails a short engine pass by name" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/render_pass.py \
    '    return "frames" if ue_available() else "none"' \
    '    return "frames"  # MUTATED: an engine default on a machine without one' \
    "the default render choice is the richest the machine supports (CLI)" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/render_pass.py \
    '    if camera_index is not None:
        inline, trailing = [f"-camera-index={int(camera_index)}"], []' \
    '    if False:  # MUTATED: the consume-poses pass never gets its index
        inline, trailing = [f"-camera-index={int(camera_index)}"], []' \
    "the per-camera pass carries -camera-index=N" \
    tests/test_camera_cli.py || failures=$((failures+1))

# -- Round 2: engine parity judges the aircraft the engine DREW ------------

mutate core/capture/verify.py \
    '                    if gap_m > aircraft_tol_m or gap_px_d > tol_px_d:' \
    '                    if False:  # MUTATED: the drawn aircraft is never judged' \
    "the aircraft the engine drew must land on the manifest's labelled pixel" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                drawn = None
                frame_ok = False
                problems.append(f"{camera_id} frame {index}: engine record "
                                f"lacks the drawn aircraft ({exc}); the "' \
    '                drawn = None
                frame_ok = frame_ok  # MUTATED: a missing drawn aircraft is skipped
                _skipped = (f"{camera_id} frame {index}: engine record "
                                f"lacks the drawn aircraft ({exc}); the "' \
    "an engine record without the drawn aircraft fails engine parity" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/render_pass.py \
    '    word = str(spec.turbulence.value)
    if word != "none":' \
    '    word = str(spec.turbulence.value)
    if False:  # MUTATED: turbulence words pass the host-parity rule' \
    "a turbulence word refuses a frames pass (host parity measured and refused)" \
    tests/test_camera_cli.py tests/test_webapp_capture.py \
    || failures=$((failures+1))

mutate webapp/server.py \
    '    parity = frames_host_parity_refusal(spec) if render == "frames" else None' \
    '    parity = None  # MUTATED: /run never consults the host-parity rule' \
    "POST /run refuses frames for a turbulent spec by name" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '            parity = frames_host_parity_refusal(
                spec, rotor_attached=rotor_provider is not None)' \
    '            parity = None  # MUTATED: the flow ignores an attached rotor' \
    "a frames run with a lee rotor attached fails by name" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '        parity = frames_host_parity_refusal(spec)
        if parity is not None:
            print(f"REFUSED {HOST_PARITY_CONSTRAINT}: {parity}")' \
    '        parity = None  # MUTATED: the CLI renders frames for turbulent air
        if parity is not None:
            print(f"REFUSED {HOST_PARITY_CONSTRAINT}: {parity}")' \
    "the CLI refuses frames for a turbulent spec by name" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if gap_pose_t > ENGINE_POSE_TIME_TOL_S:' \
    '            if False:  # MUTATED: a pose taken at the clock passes' \
    "the applied pose must be taken at the scheduled instant, not the engine clock" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '    if not report.ok:
        print(f"FAILED capture.verification: the manifest just written did "' \
    '    if False:  # MUTATED: a manifest that fails its own verification is done
        print(f"FAILED capture.verification: the manifest just written did "' \
    "a manifest that fails its own verification fails the CLI run by name" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '            print(f"engine absent: {ue_unavailable_reason()}; frames not "
                  f"rendered (--render frames where the engine exists)")' \
    '            print(UE_PLATFORM_REFUSAL)  # MUTATED: a successful headless run prints a refusal' \
    "a successful headless CLI run states the engine's absence without REFUSING" \
    tests/test_camera_cli.py || failures=$((failures+1))

# -- Round 2: no hidden render default on the run form ----------------------

mutate webapp/static/index.html \
    '<select id="render" disabled>' \
    '<select id="render">' \
    "the run form's render control ships disabled until /status answers" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '<option value="none" selected>Headless</option>' \
    '<option value="none">Headless</option>' \
    "the run form's initial selection is Headless, never an engine option" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '    option.disabled = !choice.available;' \
    '    option.disabled = false;  // MUTATED: an unavailable option stays selectable' \
    "an unavailable render option is disabled on the page" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '  select.disabled = !status.render_default;' \
    '  select.disabled = false;  // MUTATED: enabled without a server default' \
    "the render control is enabled only once the server has said the default" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Round 2: what a frames pass costs, and the by-product clip, recorded ---

mutate core/capture/render_pass.py \
    '            "-i", str(playlist), "-vsync", "vfr",' \
    '            "-i", str(playlist),  # MUTATED: constant frame rate, instants lost' \
    "the by-product clip keeps every frame at its scheduled instant (-vsync vfr)" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate core/capture/render_pass.py \
    '    if lead > 0.0:
        from PIL import Image' \
    '    if False:  # MUTATED: no black lead-in; clip time is not simulation time
        from PIL import Image' \
    "the by-product clip leads in black to the first instant" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '        _note_frames_provenance(out, passes, encoded, clip_seconds)' \
    '        pass  # MUTATED: the passes and the clip are not recorded' \
    "a frames run records its passes and its clip in provenance" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '    record.update({"render_passes": passes, "clip_encoded": bool(encoded),
                   "clip_seconds": float(clip_seconds)})' \
    '    pass  # MUTATED: the CLI does not record its passes or its clip' \
    "the CLI records its passes and its clip beside the run's digests" \
    tests/test_camera_cli.py || failures=$((failures+1))

echo
purge_cache
if $PYTEST -q >/dev/null 2>&1; then echo "Restored: suite is green"; else
    echo "Restored: SUITE IS NOT GREEN -- a restore failed"; exit 1; fi

echo
if [ "$failures" -eq 0 ]; then
    echo "All guards are load-bearing."
else
    echo "$failures guard(s) are not covered by a failing test."
fi
exit "$failures"
