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

# --only <regex>: run only the guards whose LABEL matches the extended
# regex (bash =~), e.g. --only 'geometry preview|preview round 2'; the
# others are not run and not counted. The baseline and the final
# restore check still run the whole suite (a mutation must be judged
# against a green tree), so a subset costs two suite runs plus its
# guards. The selected guards are listed and counted in the summary.
ONLY=""
while [ $# -gt 0 ]; do
    case "$1" in
        --only) ONLY="$2"; shift 2 ;;
        *) echo "usage: $0 [--only <label regex>]"; exit 2 ;;
    esac
done
selected=0

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
    if [ -n "$ONLY" ] && ! [[ "$label" =~ $ONLY ]]; then return 0; fi
    selected=$((selected+1))
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
    '    with manager.planning_console():
        spec, refusal = _prepare_run_spec(request)
    if refusal is not None:
        return refusal
    refusal = _scale_divides_or_refusal(preview_scale, spec)
    if refusal is not None:
        return refusal
    outcome = manager.start_capture(spec, provenance={' \
    '    with manager.planning_console():
        spec, refusal = _prepare_run_spec(request)
    if False:  # MUTATED: capture skips the shared validation
        return refusal
    refusal = _scale_divides_or_refusal(preview_scale, spec)
    if refusal is not None:
        return refusal
    outcome = manager.start_capture(spec, provenance={' \
    "the capture endpoint never bypasses the shared validation" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '            run.push("capture", exc.render())
            return False' \
    '            run.push("capture", exc.render())
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

# -- Camera Phase 1, frames round 3: the CLI's record agrees with the page --

mutate flightsim/capture.py \
    '        "render": {"choice": render, "label": RENDER_WORDS[render],' \
    '        "render_": {"choice": render, "label": RENDER_WORDS[render],  # MUTATED: the choice is not recorded' \
    "the CLI records its render choice in run.json" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '    (Path(out) / "verify.json").write_text(' \
    '    (Path(out) / "verify_.json").write_text(  # MUTATED: no verify.json beside the manifest' \
    "the CLI writes the verifier's report as verify.json in every mode" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate webapp/server.py \
    '    render = request.render or render_choice_default()' \
    '    render = request.render or "clip"  # MUTATED: a second, hidden default' \
    "an omitted render field resolves through the one default rule" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate core/util/platform.py \
    '    editor = ue_editor_path()
    if editor is None or not editor.is_file():
        return (f"no engine on this machine: set UE_ROOT to the Unreal "' \
    '    editor = ue_editor_path()
    if False:  # MUTATED: a missing engine install is not a reason
        return (f"no engine on this machine: set UE_ROOT to the Unreal "' \
    "a mac or Windows machine without the engine install is refused by name" \
    tests/test_platform.py || failures=$((failures+1))

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
        outcome = manager.start_capture(spec, provenance=provenance,
                                        **_scale_kwargs(preview_scale))' \
    '    if render == "none":
        render = "clip"  # MUTATED: render=none is degraded to the engine flow and its gate
    if False:
        outcome = manager.start_capture(spec, provenance=provenance,
                                        **_scale_kwargs(preview_scale))' \
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
    '    if not ue_bridge_binary(repo).is_file():
        return ("FlightSimBridge not built: run "' \
    '    if False:  # MUTATED: an unbuilt bridge reports no reason
        return ("FlightSimBridge not built: run "' \
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
    '                    if gap_m > tol_m or gap_px_d > tol_px_d:' \
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
            spec_header()
            print(f"REFUSED {HOST_PARITY_CONSTRAINT}: {parity}")' \
    '        parity = None  # MUTATED: the CLI renders frames for turbulent air
        if parity is not None:
            spec_header()
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
                   "clip_seconds": float(clip_seconds),' \
    '    ({"render_passes": passes, "clip_encoded": bool(encoded),  # MUTATED: not recorded
                   "clip_seconds": float(clip_seconds),' \
    "the CLI records its passes and its clip beside the run's digests" \
    tests/test_camera_cli.py || failures=$((failures+1))

# -- Camera Phase 1, package I done properly: the geometry preview ----------

mutate core/capture/preview.py \
    '    horizon = horizon_segment(record, axis_scale)' \
    '    horizon = None  # MUTATED: no horizon is computed or drawn' \
    "the preview draws the horizon at the camera's pitch and roll" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '        "left_tip": P - r * S / 2, "right_tip": P + r * S / 2,' \
    '        "left_tip": P - r * S / 4, "right_tip": P + r * S / 4,  # MUTATED' \
    "the aircraft body is scaled by the FDM's span at the frame's range" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    keep = (za > near) | (zb > near)' \
    '    keep = np.ones(len(za), dtype=bool)  # MUTATED: geometry behind the camera is drawn mirrored' \
    "a segment behind the camera is never drawn" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    'PREVIEW_SCALE_DEFAULT = 1' \
    'PREVIEW_SCALE_DEFAULT = 2  # MUTATED: half scale by default' \
    "previews default to the record's full resolution" \
    tests/test_camera_preview.py tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    if value is None or value < 1 or float(scale) != float(value):' \
    '    if False:  # MUTATED: any scale is accepted and rounded' \
    "a preview scale that is not a positive integer refuses by name" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    return np.clip(32.0 + 208.0 * (1.0 - frac), 32.0, 240.0)' \
    '    return np.full_like(frac, 120.0)  # MUTATED: no depth shading' \
    "the ground is depth-shaded, near bright and far dim" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    lines = header_lines(record, manifest, scale, tag, ground=ground, plan=plan,
                         terrain_elevation_m=terrain_elevation_m,
                         track_words=track_words, drawn=info["segments"],
                         arrow=info["north_arrow_state"])' \
    '    lines = [record["camera_id"]]  # MUTATED: the header names only the camera' \
    "the header states position, look direction and focal length" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    if contact_sheets:' \
    '    if False:  # MUTATED: no contact sheet' \
    "every camera gets a contact sheet of its previews" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    written.seconds_per_frame = elapsed / len(written) if written else 0.0
    if contact_sheets:' \
    '    written.seconds_per_frame = 0.0  # MUTATED: the render time is not measured
    if contact_sheets:' \
    "the preview render time is measured per frame and recorded" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate core/scenario/runner.py \
    '        "aircraft_metrics": aircraft_metrics(fdm),' \
    '        "aircraft_metrics": None,  # MUTATED: the FDM span is not read' \
    "the run manifest carries the airframe metrics read from the FDM" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '        aircraft_metrics=result.manifest.get("aircraft_metrics"))' \
    '        aircraft_metrics=None)  # MUTATED: the capture manifest drops the metrics' \
    "the capture manifest carries the airframe metrics the body is scaled by" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '    overlays = overlay() if overlay is not None else []' \
    '    overlays = []  # MUTATED: no overlay over the rendered frames' \
    "a frames run overlays the reprojected geometry on every rendered frame (CLI)" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate webapp/capture.py \
    '    if outcome.manifest is not None:
        overlays = render_overlays(' \
    '    if False:  # MUTATED: no overlay over the rendered frames
        overlays = render_overlays(' \
    "a frames run overlays the reprojected geometry on every rendered frame (page)" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/capture.py \
    '    overlays_root = out_dir / "capture" / "overlays"
    if overlays_root.is_dir():' \
    '    overlays_root = out_dir / "capture" / "overlays"
    if False:  # MUTATED: overlays are not listed' \
    "the page lists the overlays as their own artefact class" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/server.py \
    '        return validated_scale(1 if request.preview_scale is None
                               else request.preview_scale), None' \
    '        return 1, None  # MUTATED: the page field is ignored' \
    "the page's preview scale is honoured or refused by name" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Camera Phase 1, package I, preview round 2: depth order, telemetry
# -- track, rings from the camera, compass + arrow, overlays at the
# -- frame's size, the terrain header, the length caveat, numbering -----

mutate core/capture/preview.py \
    '    order = np.argsort(-segments[:, 4], kind="stable")' \
    '    order = np.arange(len(segments))  # MUTATED: raster order, far over near' \
    "preview round 2: segments are drawn far to near (painter's order)" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    visible_s = v_s <= prev_v + tolerance_px' \
    '    visible_s = np.ones(len(v_s), dtype=bool)  # MUTATED: nothing is hidden behind a ridge' \
    "preview round 2: ground behind a nearer ridge is hidden by the skyline" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    if telemetry is not None:
        frame = scene_frame' \
    '    if False:  # MUTATED: the track is always the schedule'"'"'s chords
        frame = scene_frame' \
    "preview round 2: the flown track is the telemetry, not the schedule's chords" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    interval = float(np.median(np.diff(t)))' \
    '    interval = (t[-1] - t[0]) / (n - 1)  # MUTATED: the mean step, skewed by the first sample' \
    "preview round 2: the telemetry rate is the recorder's median step" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '            past = when[1:] <= now + 1e-9' \
    '            past = np.ones(len(when) - 1, dtype=bool)  # MUTATED: everything is past' \
    "preview round 2: the past/future split is at the frame's instant" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '            "camera_north_m": cam_n, "camera_east_m": cam_e,' \
    '            "camera_north_m": centre_n, "camera_east_m": centre_e,  # MUTATED: rings on the snapped origin' \
    "preview round 2: distance rings are centred on the camera's exact ground point" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '        angle = (offset - yaw) % 360.0' \
    '        angle = (offset + yaw) % 360.0  # MUTATED: the compass turns the wrong way' \
    "preview round 2: the compass puts north at minus the camera's yaw" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    if arrow_base is not None:
        arrow = north_arrow_points(record, arrow_base, axes)' \
    '    if False:  # MUTATED: no north arrow in any scene
        arrow = north_arrow_points(record, arrow_base, axes)' \
    "preview round 2: the north arrow is drawn in every scene" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '        length = min(NORTH_ARROW_PX / per_metre, cap)
        for _ in range(3):' \
    '        length = cap  # MUTATED: a world length, whatever it projects to
        for _ in range(0):' \
    "preview round 2: the arrow's world length is set by its projected size" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '        axis_scale = (float(record["width_px"]) / w, float(record["height_px"]) / h)' \
    '        axis_scale = (1.0, 1.0)  # MUTATED: the record'"'"'s intrinsics on a frame of another size' \
    "preview round 2: overlays scale the intrinsics per axis to the frame's own size" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    band_alpha = 255 if not overlay else min(alpha, OVERLAY_BAND_ALPHA)' \
    '    band_alpha = 255 if not overlay else min(alpha, 150)  # MUTATED: the old dark band' \
    "preview round 2: the overlay's header band darkens the frame by at most 96/255" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '        if _text_width(draw, line, font) <= max_width:
            out.append(line)
            continue' \
    '        if True:  # MUTATED: no wrapping, the line runs off the frame
            out.append(line)
            continue' \
    "preview round 2: header lines wider than the image are wrapped" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '            words = (f"terrain {tp['"'"'name'"'"']} {tp['"'"'width_px'"'"']}x{tp['"'"'height_px'"'"']} @ "' \
    '            words = ("terrain: raster wireframe"  # MUTATED: the raster is not named
                     f"{tp['"'"'name'"'"'][:0]}{tp['"'"'width_px'"'"'] * 0}{tp['"'"'height_px'"'"'] * 0}"' \
    "preview round 2: the header names the raster, its resolution and the wireframe spacing" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    if fine >= stride:
        return np.zeros((0, 3)), np.zeros((0, 3))' \
    '    if True:  # MUTATED: no fine lattice near the camera
        return np.zeros((0, 3)), np.zeros((0, 3))' \
    "preview round 2: the fine lattice densifies the ground near the camera" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '        if radius > far_m:
            continue' \
    '        if True:  # MUTATED: no rings on the terrain
            continue' \
    "preview round 2: distance rings are draped on the raster in terrain scenes" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/scenario/runner.py \
    '    if stations_m >= arm_chord_m:' \
    '    if False:  # MUTATED: always arm + chord, the shorter bound' \
    "preview round 2: the body length is the larger stated station extent, named" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    caveat = metrics.get("length_caveat")' \
    '    caveat = None  # MUTATED: the picture drops the length caveat' \
    "preview round 2: the body line carries the length caveat" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    return f"frame index {index} ({int(index) + 1} of {count})"' \
    '    return f"frame index {index} ({int(index)} of {count})"  # MUTATED: index over count again' \
    "preview round 2: the header numbers frames by index AND count" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    words = f"#{index} ({int(index) + 1}/{total})"' \
    '    words = f"#{index}"  # MUTATED: the contact sheet drops the count' \
    "preview round 2: the contact sheet label carries index and count" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '                               scale=preview_scale, telemetry=columns)' \
    '                               scale=preview_scale)  # MUTATED: the CLI keeps its telemetry to itself' \
    "preview round 2: the CLI passes the run's telemetry to the previews" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate webapp/capture.py \
    '                               max_frames=MAX_PREVIEWS, scale=preview_scale,
                               telemetry=columns)' \
    '                               max_frames=MAX_PREVIEWS, scale=preview_scale)  # MUTATED: no telemetry to the page'"'"'s previews' \
    "preview round 2: the page passes the run's telemetry to the previews" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Camera Phase 1, package I, preview round 3: readable contact sheets,
# -- header wrapping exercised, label placement, the horizon behind the
# -- skyline, overlay text backing, divisor scales, header truth, the
# -- terrain and overlay render budget ---------------------------------

mutate core/capture/preview.py \
    '            tile, tile_info = draw_preview(record, manifest, ground, size=(tw, th),
                                           style="thumbnail", track_points=track_points,' \
    '            tile, tile_info = draw_preview(record, manifest, ground, size=(tw, th),
                                           style="full", track_points=track_points,  # MUTATED: the tile carries the header, legend and labels' \
    "preview round 3: contact-sheet tiles are drawn for the tile, without text" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    line_px = THUMBNAIL_LINE_PX if thumbnail else 1' \
    '    line_px = 1  # MUTATED: one-pixel lines in the tile' \
    "preview round 3: tile lines are drawn at THUMBNAIL_LINE_PX" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '        if distance > req["gap"] + LABEL_LEADER_LINE_HEIGHTS * th:' \
    '        if False:  # MUTATED: a label far from its anchor gets no leader' \
    "preview round 3: a label placed far from its anchor gets a leader line" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '        out = [(side[k], k, 0) for k in prefer]' \
    '        out = [(side[prefer[-1]], prefer[-1], 0)]  # MUTATED: one side only, the old shift-down' \
    "preview round 3: labels try right, left, above and below their anchor" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '                if any(_near(box, zone, 2.0) for zone in self.reserved):
                    continue' \
    '                if False:  # MUTATED: labels may land on the band, legend or compass
                    continue' \
    "preview round 3: labels keep clear of the header band, legend and compass" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    for offset in (step, -step, 0.0):' \
    '    for offset in (0.0,):  # MUTATED: ring labels back on the arrow'"'"'s column' \
    "preview round 3: ring labels are anchored off the arrow's column" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    hidden = sky[idx] < v_h - tolerance_px' \
    '    hidden = np.zeros(len(cols), dtype=bool)  # MUTATED: the horizon is painted through the ridge' \
    "preview round 3: the horizon is hidden where the skyline rises above it" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '                    draw.line([at(u), at(min(u + on, b))], fill=rgba(HORIZON_HIDDEN_RGB),' \
    '                    draw.line([at(u), at(min(u + on, b))], fill=rgba(HORIZON_RGB),  # MUTATED: hidden dashes in the seen colour' \
    "preview round 3: the hidden horizon is dashed in its own colour" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '    stroke = TEXT_STROKE_PX if overlay else 0' \
    '    stroke = 0  # MUTATED: bare overlay text over bright pixels' \
    "preview round 3: overlay text carries a dark stroke" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '        if overlay:
            # The compass on its own small band, like the header.' \
    '        if False:  # MUTATED: no band under the compass
            # The compass on its own small band, like the header.' \
    "preview round 3: the overlay's compass sits on its own band" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '        if w % value or h % value:' \
    '        if False:  # MUTATED: a non-divisor scale is floored (426x240 for 3)' \
    "preview round 3: a scale that does not divide the resolution is refused by name" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '    if scale_refusal is not None:
        spec_header()
        print(f"REFUSED -- {scale_refusal}")
        return 2' \
    '    if False:  # MUTATED: the CLI flies first and floors the previews
        spec_header()
        print(f"REFUSED -- {scale_refusal}")
        return 2' \
    "preview round 3: the CLI refuses a non-divisor preview scale before the flight" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate webapp/server.py \
    '    refusal = scale_refusal_for_cameras(preview_scale,
                                        spec.cameras or default_cameras(spec))
    if refusal is None:
        return None' \
    '    refusal = scale_refusal_for_cameras(preview_scale,
                                        spec.cameras or default_cameras(spec))
    if True:  # MUTATED: the page starts the run at a scale it cannot draw
        return None' \
    "preview round 3: the page refuses a non-divisor preview scale before the run" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '        if drawn is not None and drawn.get("grid", 0) == 0:
            words += " (out of frame)"' \
    '        if False:  # MUTATED: the header describes a lattice the picture does not carry
            words += " (out of frame)"' \
    "preview round 3: the ground line says (out of frame) when no ground segment survived" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '                         arrow=info["north_arrow_state"])' \
    '                         arrow=None)  # MUTATED: the header is silent about the arrow' \
    "preview round 3: the header states the north arrow's state" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '            info["segments"][f"{name}_hidden"] = n_in_frame - seen' \
    '            info["segments"][f"{name}_hidden"] = int(len(clipped) - len(visible))  # MUTATED: the old cross-kind total' \
    "preview round 3: hidden counts are per kind and reconcile with the segments in frame" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '            if zone[0] <= ax <= zone[2] and zone[1] <= ay <= zone[3]:' \
    '            if False:  # MUTATED: no candidate below a zone the anchor lies in' \
    "preview round 3: a label anchored inside a reserved zone is offered the rows beside it" \
    tests/test_camera_preview.py || failures=$((failures+1))

mutate core/capture/preview.py \
    '        written.sizes[path] = image.size
    elapsed = time.perf_counter() - started
    written.seconds_per_frame = elapsed / len(written) if written else 0.0' \
    '        written.sizes[path] = image.size
    elapsed = time.perf_counter() - started
    written.seconds_per_frame = RENDER_BUDGET_S_PER_FRAME  # MUTATED: the overlay time is not measured' \
    "preview round 3: the overlay render time is measured per frame and graded" \
    tests/test_camera_preview.py || failures=$((failures+1))

# -- Camera Phase 1, package I, commands round 1: the verifier as a table
# -- with a number, a tolerance and a WHERE per check; SKIPPED is neither
# -- passed nor ran; the JSBSim console is routed, counted, never lost --

mutate core/capture/verify.py \
    '        return Check("cross_view_consistency", None,' \
    '        return Check("cross_view_consistency", True,  # MUTATED: nothing to grade counted as a pass' \
    "commands round 1: a single-camera cross-view check is SKIPPED, never a pass" \
    tests/test_camera_verify.py tests/test_webapp_capture.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        return len(self.checks) - len(self.awaiting) - len(self.skipped)' \
    '        return len(self.checks) - len(self.awaiting)  # MUTATED: a skipped check counted as ran' \
    "commands round 1: a skipped check is counted in neither passed nor ran" \
    tests/test_camera_verify.py tests/test_webapp_capture.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if worst_at is None or gap > worst_gap:' \
    '            if worst_at is None:  # MUTATED: the worst frame is never tracked' \
    "commands round 1: geometry recovery names the worst frame by camera, index and instant" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        if worst_at is None or error > worst:' \
    '        if worst_at is None:  # MUTATED: the worst two-view instant is never tracked' \
    "commands round 1: cross-view consistency names the worst sample and its two frames" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        only_b = sorted(set(times_b) - set(times_a))' \
    '        only_b = []  # MUTATED: the run with the extra instant is not named' \
    "commands round 1: temporal alignment names the run holding the extra instant" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/fdm/fdm.py \
    '        with captured_console(f"FlightDynamics({self.model.name})"):
            self._exec = jsbsim.FGFDMExec(root_dir=str(self.model.root_dir))' \
    '        if True:  # MUTATED: the banner goes to stdout
            self._exec = jsbsim.FGFDMExec(root_dir=str(self.model.root_dir))' \
    "commands round 1: JSBSim's startup banner is routed to the run's log, not stdout" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate core/fdm/console.py \
    '    sink.loads += 1' \
    '    sink.loads += 0  # MUTATED: model loads are not counted' \
    "commands round 1: the JSBSim line's model-load count is the sink's own count" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate core/fdm/console.py \
    '    log_fd = os.open(str(sink.path), os.O_WRONLY | os.O_CREAT | os.O_APPEND,' \
    '    log_fd = os.open(os.devnull, os.O_WRONLY | os.O_CREAT | os.O_APPEND,  # MUTATED: the banner is dropped' \
    "commands round 1: the routed JSBSim console is written to the log, never dropped" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '        "jsbsim_log": str(out / "jsbsim.log"),' \
    '        "jsbsim_log_": str(out / "jsbsim.log"),  # MUTATED: run.json does not record the log' \
    "commands round 1: run.json records the JSBSim log path" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/report.py \
    '    for c in cameras:
        fx = f"fx {c['"'"'fx_px'"'"']:.1f} px" if c["fx_px"] is not None else "fx -"' \
    '    for c in cameras[:1]:  # MUTATED: the header lists one camera
        fx = f"fx {c['"'"'fx_px'"'"']:.1f} px" if c["fx_px"] is not None else "fx -"' \
    "commands round 1: the header carries one line per camera" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/report.py \
    '        for r in records:
            if r["aircraft_u_px"] is None:' \
    '        for r in records[:1]:  # MUTATED: the schedule table stops after one row
            if r["aircraft_u_px"] is None:' \
    "commands round 1: the schedule table lists every scheduled instant" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/report.py \
    '            elif len(times) > 1:
                gaps = [b - a for a, b in zip(times, times[1:])]' \
    '            elif False:  # MUTATED: a sample-snapped schedule is reported as uniform
                gaps = [b - a for a, b in zip(times, times[1:])]' \
    "commands round 1: --brief never claims a period the schedule does not have" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/verify.py \
    '        target["quaternion_wxyz"][2] = before[2] + 0.05' \
    '        target["quaternion_wxyz"][2] = before[2] + 0.0  # MUTATED: the corruption is a no-op' \
    "commands round 1: --corrupt quaternion really corrupts, and the verifier catches it" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/verify.py \
    '                record["aircraft"]["north_m"] += 5.0' \
    '                record["aircraft"]["north_m"] += 0.0  # MUTATED: the corruption is a no-op' \
    "commands round 1: --corrupt aircraft really corrupts, and the verifier catches it" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/verify.py \
    '        target["t_s"] = before + step' \
    '        target["t_s"] = before  # MUTATED: the corruption is a no-op' \
    "commands round 1: --corrupt time really corrupts, and the verifier catches it" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/verify.py \
    '        manifest["frames"] = [r for r in frames if r is not last]' \
    '        manifest["frames"] = list(frames)  # MUTATED: the corruption is a no-op' \
    "commands round 1: --corrupt count really corrupts, and the verifier catches it" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/verify.py \
    '        if expected in failed:' \
    '        if True:  # MUTATED: a corruption the verifier missed is reported as caught' \
    "commands round 1: a --corrupt run the verifier does not catch is UNEXPECTED, not FAILED" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/report.py \
    '        print(f"USAGE: {exc}")
        return EXIT_USAGE' \
    '        print(f"USAGE: {exc}")
        return EXIT_REFUSED  # MUTATED: usage errors share REFUSED'"'"'s code' \
    "commands round 1: a usage error exits 3, never REFUSED's 2" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/report.py \
    '                code = EXIT_UNEXPECTED' \
    '                code = EXIT_FAILED  # MUTATED: an exception reads as a verification failure' \
    "commands round 1: an exception exits 4 by word, never as a FAILED verification" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '    doc["verification"] = report.to_dict()
    if render != "frames" or not report.ok:' \
    '    doc["verification"] = {}  # MUTATED: --json carries no verification
    if render != "frames" or not report.ok:' \
    "commands round 1: capture --json carries the verification document" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '        return EXIT_FAILED

    if render == "none":' \
    '        return EXIT_REFUSED  # MUTATED: a verification failure exits as a refusal

    if render == "none":' \
    "commands round 1: a manifest failing its own verification exits 1, the shared FAILED code" \
    tests/test_camera_cli.py || failures=$((failures+1))

# The document itself is the guarded artefact here: a stale block (one
# summary line edited) must fail the shape comparison.
mutate docs/CAMERA_PHASE1_REPORT.md \
    'verification PASSED (9/9 checks; 1 awaiting engine frames: engine_parity)
engine absent:' \
    'verification PASSED (9/9 checks)
engine absent:' \
    "commands round 1: the document's expected output cannot go stale without a test saying so" \
    tests/test_camera_cli.py || failures=$((failures+1))

# -- Camera Phase 1, package I, commands round 2: the verifier reads the
# -- flight (telemetry.json) and the spec's schedule (scenario.yaml), so a
# -- manifest that disagrees with the flight it claims to record fails its
# -- own verification with no sibling run; --corrupt clock/flight/schedule --

mutate core/capture/verify.py \
    '    if worst["position_m"] > position_tol_m:' \
    '    if False:  # MUTATED: the recorded aircraft is never graded against the telemetry' \
    "commands round 2: flight fidelity grades the recorded aircraft position against the telemetry at its sample" \
    tests/test_camera_verify.py tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if worst["time_s"] > time_tol_s:' \
    '    if False:  # MUTATED: a record'"'"'s t_s is never graded against the telemetry clock' \
    "commands round 2: flight fidelity grades every record's t_s against the telemetry's own t at its sample" \
    tests/test_camera_verify.py tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if worst["angle_deg"] > angle_tol_deg:' \
    '    if False:  # MUTATED: the recorded attitude is never graded against the telemetry' \
    "commands round 2: flight fidelity grades the recorded attitude against the telemetry" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if not digests_equal:' \
    '    if False:  # MUTATED: a telemetry.json that is not this flight passes' \
    "commands round 2: telemetry.json beside the manifest must digest to the manifest's output_digest" \
    tests/test_camera_verify.py tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if si != ai or gap > TIME_TOL_S:' \
    '            if False:  # MUTATED: the recomputed schedule is never compared instant for instant' \
    "commands round 2: schedule fidelity compares the spec's recomputed schedule with the manifest instant for instant" \
    tests/test_camera_verify.py tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    report.checks.append(verify_flight_fidelity(manifest, columns))' \
    '    report.checks.append(verify_flight_fidelity(manifest, None))  # MUTATED: the flight is never read' \
    "commands round 2: verify_run reads telemetry.json beside the manifest; flight fidelity is never skipped when it exists" \
    tests/test_camera_verify.py tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    report.checks.append(verify_schedule_fidelity(manifest, spec, columns))' \
    '    report.checks.append(verify_schedule_fidelity(manifest, None, columns))  # MUTATED: the spec is never read for the schedule' \
    "commands round 2: verify_run reads scenario.yaml beside the manifest; schedule fidelity is never skipped when it exists" \
    tests/test_camera_verify.py tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/verify.py \
    '            record["t_s"] = float(record["t_s"]) + CLOCK_SHIFT_S' \
    '            record["t_s"] = float(record["t_s"]) + 0.0  # MUTATED: the corruption is a no-op' \
    "commands round 2: --corrupt clock really shifts every instant, and the verifier catches it" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/verify.py \
    '            record["aircraft"]["north_m"] += FLIGHT_SHIFT_M' \
    '            record["aircraft"]["north_m"] += 0.0  # MUTATED: the corruption is a no-op' \
    "commands round 2: --corrupt flight really moves the aircraft in every view, and the verifier catches it" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/verify.py \
    '            record["sample_index"] = moved' \
    '            record["sample_index"] = sample  # MUTATED: the instant stays where the spec schedules it' \
    "commands round 2: --corrupt schedule really moves an instant off the spec's schedule, and the verifier catches it" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/verify.py \
    '    return run_dir.parent / f"{run_dir.name}_corrupt_{kind}"' \
    '    return run_dir / f"corrupt_{kind}"  # MUTATED: the corrupt copy lands inside the run' \
    "commands round 2: the corrupt copy is a sibling of the run, never inside it" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/verify.py \
    '    if copy_dir.resolve() == Path(run_dir).resolve() or \
            Path(run_dir).resolve() in copy_dir.resolve().parents:' \
    '    if False:  # MUTATED: a --corrupt-dir inside the run is accepted' \
    "commands round 2: a --corrupt-dir inside the run is refused as USAGE" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/report.py \
    '        flight += (f"; telemetry t {telemetry['"'"'first_s'"'"']:.3f}.."' \
    '        flight += (f"; telemetry ({telemetry['"'"'first_s'"'"']:.3f}.."  # MUTATED: the window is not stated' \
    "commands round 2: the flight line states the telemetry window the schedule lives in" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/report.py \
    '                if trigger == "distance":' \
    '                if False:  # MUTATED: a distance trigger is worded as sample-snapped' \
    "commands round 2: --brief words a distance trigger's spacing from the trigger, never as sample snapping" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '    if not Path(args.spec).is_file():' \
    '    if False:  # MUTATED: a missing spec falls through to a traceback' \
    "commands round 2: a spec path that does not exist is USAGE (exit 3), never UNEXPECTED" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        noted = [c for c in self.checks if c.ok is not True]' \
    '        noted = list(self.checks)  # MUTATED: every PASS is rendered twice' \
    "commands round 2: a PASS is rendered once, in the table, never again as a detail line" \
    tests/test_camera_verify.py tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if len(indices) != declared:
                problems.append(f"{camera_id}: {len(indices)} frames "' \
    '            if True:  # MUTATED: a wrong-index FAIL is worded as a wrong count
                problems.append(f"{camera_id}: {len(indices)} frames "' \
    "commands round 2: a count FAIL says what was found, a wrong count or the wrong indices, never 'or'" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/fdm/console.py \
    '    os.write(log_fd, stamp.encode("utf-8"))' \
    '    os.write(log_fd, b"")  # MUTATED: the loads are not stamped' \
    "commands round 2: every routed model load is stamped in the log with what was built and who asked" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate webapp/capture.py \
    '    return jsbsim_console(Path(capture_dir) / "jsbsim.log")' \
    '    return contextlib.nullcontext(JSBSimConsole(Path(capture_dir) / "jsbsim.log"))  # MUTATED: a direct capture_run is not routed' \
    "commands round 2: a direct capture_run routes JSBSim's console to capture/jsbsim.log" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '            with jsbsim_console(out / "jsbsim.log"):
                (flow or self._render_flow)(run, spec, provenance)' \
    '            if True:  # MUTATED: the page run is not routed
                (flow or self._render_flow)(run, spec, provenance)' \
    "commands round 2: a page run enters the run's own JSBSim sink, <run>/jsbsim.log, around the whole flow" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate flightsim/report.py \
    '            du = float(record["fx_px"]) * (-right) / ahead' \
    '            du = 0.0  # MUTATED: the cockpit promise ignores the lateral offset' \
    "commands round 2: the cockpit off-aim column measures against the body-axis cg pixel the header promises" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/report.py \
    '    if kind in ("aircraft-lagged", "aircraft-exact"):
        return math.hypot(u - cx, v - cy)' \
    '    if kind in ("aircraft-lagged", "aircraft-exact"):
        return 0.0  # MUTATED: an aimed camera never reports its miss' \
    "commands round 2: an aircraft-aimed camera's off-aim column is its measured distance from the centre" \
    tests/test_camera_cli.py || failures=$((failures+1))

# A stale NUMBER in the document (one measured value off by one in its
# last digit) must fail the freshness test on the platform it was
# measured on: the comparison is exact there, not a masked shape.
mutate docs/CAMERA_PHASE1_REPORT.md \
    '  geometry_recovery       FAIL      124.7076 px' \
    '  geometry_recovery       FAIL      124.7075 px' \
    "commands round 2: a stale measured number in the document fails the freshness test on the measured platform" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate scripts/examples_expected.py \
    '    if not exact:
        masked = _HEX.sub("<hex>", masked)' \
    '    if True:  # MUTATED: digests and numbers are masked on every platform
        masked = _HEX.sub("<hex>", masked)' \
    "commands round 2: the freshness comparison is exact on the measured platform, numbers and digests included" \
    tests/test_camera_cli.py || failures=$((failures+1))

# -- Camera Phase 1, package I, commands round 3: the pose is graded
# -- against the spec (pose_fidelity: the track recomputed from
# -- scenario.yaml over telemetry.json) and the cross-view rays start at
# -- the recomputed pose, never at the record under test; --corrupt
# -- pose/lens --

mutate core/capture/verify.py \
    '    if worst_pose["position_m"] > position_tol_m:' \
    '    if False:  # MUTATED: a moved camera is never graded against the spec'"'"'s track' \
    "commands round 3: pose fidelity grades every record's camera position against the track recomputed from the spec" \
    tests/test_camera_verify.py tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if worst_pose["angle_deg"] > angle_tol_deg:' \
    '    if False:  # MUTATED: a rotated camera'"'"'s Euler angles are never graded' \
    "commands round 3: pose fidelity grades every record's Euler orientation against the recomputed track" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if worst_pose["quaternion"] > quaternion_tol:' \
    '    if False:  # MUTATED: the quaternion is never graded against the recomputed track' \
    "commands round 3: pose fidelity grades every record's quaternion against the recomputed track" \
    tests/test_camera_verify.py tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if worst_pose["lens_px"] > lens_tol_px or worst_pose["focal_mm"] > lens_tol_mm:' \
    '    if False:  # MUTATED: a scaled lens is never graded against the spec camera' \
    "commands round 3: pose fidelity grades every record's fx/fy, principal point and focal length against the spec camera" \
    tests/test_camera_verify.py tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        equal = str(block.get("pose_track_digest")) == track.digest()' \
    '        equal = True  # MUTATED: the manifest'"'"'s pose_track_digest is written and never read' \
    "commands round 3: every camera block's pose_track_digest is compared verbatim with the recomputed track's" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if record.get(key) != expected[key]:' \
    '            if False:  # MUTATED: resolution, sensor and clip planes are never compared' \
    "commands round 3: a record's resolution, sensor and clip planes are compared with the spec camera's" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    report.checks.append(verify_pose_fidelity(manifest, spec, columns,
                                              recomputed))' \
    '    report.checks.append(verify_pose_fidelity(manifest, None, columns,
                                              recomputed))  # MUTATED: the spec is never read for the pose' \
    "commands round 3: verify_run reads scenario.yaml for the pose; pose fidelity is never skipped when it exists" \
    tests/test_camera_verify.py tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                cast_a, cast_b = expected_a, expected_b' \
    '                cast_a, cast_b = a, b  # MUTATED: the rays start at the record under test (circular in the pose)' \
    "commands round 3: the cross-view rays are cast from the poses recomputed from the spec, never from the record under test" \
    tests/test_camera_verify.py tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                target = (flight["north_m"], flight["east_m"],
                          flight["alt_m"])' \
    '                target = point_a  # MUTATED: the recovered point is graded against the record, not the flight' \
    "commands round 3: the cross-view recovered point is graded against the telemetry's aircraft at that sample" \
    tests/test_camera_verify.py tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/verify.py \
    '                record["position_east_m"] += POSE_SHIFT_M' \
    '                record["position_east_m"] += 0.0  # MUTATED: the corruption is a no-op' \
    "commands round 3: --corrupt pose really moves the camera, and the verifier catches it" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/verify.py \
    '                record["fx_px"] *= LENS_SCALE
                record["fy_px"] *= LENS_SCALE
                record["focal_length_mm"] *= LENS_SCALE' \
    '                record["fx_px"] *= 1.0  # MUTATED: the corruption is a no-op
                record["fy_px"] *= 1.0
                record["focal_length_mm"] *= 1.0' \
    "commands round 3: --corrupt lens really scales the lens, and the verifier catches it" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/verify.py \
    '                record[key] = pose[key]' \
    '                record[key] = record[key]  # MUTATED: the moved instant keeps the old sample'"'"'s pose' \
    "commands round 3: --corrupt schedule copies the spec's pose at the moved sample so only the schedule tells" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '    if header is not None:
        header()' \
    '    if False:  # MUTATED: a refusal prints no header
        header()' \
    "commands round 3: a refused capture prints the header from the spec alone before the violation" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/report.py \
    '            fx = focal * width / float(value("sensor_width_mm"))' \
    '            fx = None  # MUTATED: no record, no fx' \
    "commands round 3: the refusal header's fx is computed from the spec's focal length, sensor width and resolution" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/report.py \
    '    if trigger == "interval" and camera.get("period_s"):' \
    '    if False:  # MUTATED: a period schedule is worded as a count of 0' \
    "commands round 3: a spec-only camera whose count the flight decides is worded from its trigger, never as 0 captures" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if worst_gap > tol_px:
        problems.insert(0, f"the aircraft'"'"'s pixel is {worst_gap:.3f} px from "' \
    '    if False:  # MUTATED: the off-aim promise is never graded
        problems.insert(0, f"the aircraft'"'"'s pixel is {worst_gap:.3f} px from "' \
    "commands round 3: aim fidelity grades the aircraft's pixel against the pixel the preset's promise predicts" \
    tests/test_camera_verify.py tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            gain = 1.0 - math.exp(-dt / lag_s)' \
    '            gain = 1.0  # MUTATED: the promise is the aircraft itself, not the lagged aim' \
    "commands round 3: the lagged presets' promise is the AIM_LAG_S first-order lag recomputed over the telemetry" \
    tests/test_camera_verify.py tests/test_camera_cli.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                if axis_gap > axis_tol_deg:' \
    '                if False:  # MUTATED: a cockpit camera'"'"'s axes are never compared with the body axes' \
    "commands round 3: a cockpit record's axes are compared with the telemetry's body axes" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    report.checks.append(verify_aim_fidelity(manifest, columns))' \
    '    report.checks.append(verify_aim_fidelity(manifest, None))  # MUTATED: the aim is never graded from the flight' \
    "commands round 3: verify_run grades the aim promise from telemetry.json; aim fidelity is never skipped when it exists" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/verify.py \
    '                record["yaw_deg"] = (float(record["yaw_deg"])
                                     + AIM_TWIST_DEG) % 360.0' \
    '                record["yaw_deg"] = (float(record["yaw_deg"])
                                     + 0.0) % 360.0  # MUTATED: the corruption is a no-op' \
    "commands round 3: --corrupt aim really turns the camera, and the verifier catches it" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate webapp/server.py \
    '    with manager.planning_console():
        spec, refusal = _prepare_run_spec(request)
    if refusal is not None:
        return refusal
    refusal = _scale_divides_or_refusal(preview_scale, spec)
    if refusal is not None:
        return refusal
    outcome = manager.start_capture(spec, provenance={' \
    '    if True:  # MUTATED: /capture plans on the server console
        spec, refusal = _prepare_run_spec(request)
    if refusal is not None:
        return refusal
    refusal = _scale_divides_or_refusal(preview_scale, spec)
    if refusal is not None:
        return refusal
    outcome = manager.start_capture(spec, provenance={' \
    "commands round 3: /capture's own pre-run planning routes JSBSim's console to the server-level planning log" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/server.py \
    '    with manager.planning_console():
        plan_scene_setting(spec)' \
    '    if True:  # MUTATED: /compile plans on the server console
        plan_scene_setting(spec)' \
    "commands round 3: /compile's planning routes JSBSim's console to the server-level planning log" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate core/fdm/console.py \
    '_SLOT = threading.local()' \
    '_SLOT = type("Slot", (), {})()  # MUTATED: one process-wide slot shared by every thread' \
    "commands round 3: the JSBSim console sink is one slot per thread, so a request's planning and a run never share one" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '                    self.planning_loads += int(sink.loads)' \
    '                    self.planning_loads += 0  # MUTATED: the status line never counts the planning loads' \
    "commands round 3: /status counts the model loads the planning log holds" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 1: the frames zip and one download per artefact class ------

mutate webapp/server.py \
    '    refusal = frames_zip_refusal(out, files)' \
    '    refusal = None  # MUTATED: an empty frames zip is served for a headless run' \
    "page round 1: frames.zip is refused by name when no frame was rendered" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/capture.py \
    '        if not entry["name"].startswith("capture/frames/"):
            continue' \
    '        if False:  # MUTATED: every image class counts as the frame set
            continue' \
    "page round 1: the frames zip carries only capture/frames PNGs and render.json" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/capture.py \
    '    if frames:
        cameras = sorted(' \
    '    if True:  # MUTATED: frames.zip offered with no rendered frame
        cameras = sorted(' \
    "page round 1: the download strip offers frames.zip only when a rendered PNG exists" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '  const buttons = downloads.map(d =>' \
    '  const buttons = downloads.slice(0, 1).map(d =>  // MUTATED: one button, whatever the classes' \
    "page round 1: the strip offers one button per artefact class the run wrote" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 1: the gallery shows every frame; previews are the labelled fallback

mutate webapp/capture.py \
    '            if frame in on_disk:
                frames.append(' \
    '            if True:  # MUTATED: a frame is listed whether or not its PNG exists
                frames.append(' \
    "page round 1: a gallery lists a frame only when its PNG is on disk" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '      thumbsHtml(runId, gallery.camera_id, frames, "frames") + previewBlock +' \
    '      thumbsHtml(runId, gallery.camera_id, frames.slice(0, 2), "frames") + previewBlock +  // MUTATED: silently truncated' \
    "page round 1: the gallery shows every rendered frame the server listed" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '    `<span class="dim">(fallback: ${esc(fallbackWords(run))}; showing ` +' \
    '    `<span class="dim">(${esc(fallbackWords(run))}; showing ` +  // MUTATED: previews not labelled as the fallback' \
    "page round 1: previews with no rendered frame are labelled as the fallback with the reason" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '      ? `<details><summary class="dim">geometry previews (not frames): ` +' \
    '      ? `<div><summary class="dim">geometry previews (not frames): ` +  // MUTATED: previews drawn as peers of the frames' \
    "page round 1: on a frames run the previews sit behind a not-frames disclosure" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '                           engine_reason=ue_unavailable_reason())' \
    '                           engine_reason=None)  # MUTATED: the machine'"'"'s reason is not recorded' \
    "page round 1: a headless run records the machine's own no-engine reason" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 1: the verifier's table on the page, verbatim from verify.json

mutate webapp/static/index.html \
    '      `<td>${esc(row[2])}</td><td>${esc(row[3])}</td>` +' \
    '      `<td>-</td><td>-</td>` +  // MUTATED: the measured and tolerance cells dropped' \
    "page round 1: the page's verification table carries the measured and tolerance cells" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '  const tally = v.summary
    ? `<b>${esc(v.summary)}</b>`' \
    '  const tally = false
    ? `<b>${esc(v.summary)}</b>`  // MUTATED: the tally composed on the page instead of the verifier'"'"'s line' \
    "page round 1: the tally line is the verifier's own summary, verbatim" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '    const line = status === "PASS" ? "" :' \
    '    const line = true ? "" :  // MUTATED: no detail line for a row that did not PASS' \
    "page round 1: a row that did not PASS carries its detail line, as the CLI prints it" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 1: a mid-run refusal keeps its offending value -------------

mutate webapp/capture.py \
    '        raise CaptureError(first.constraint, first.message,
                           actual=first.actual, limit=first.limit,
                           unit=first.unit)' \
    '        raise CaptureError(first.constraint, first.message)  # MUTATED: the value dropped' \
    "page round 1: a track refusal carries the violation's actual, limit and unit" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '            run.capture = exc.as_dict()
            run.push("capture", exc.render())' \
    '            run.capture = {"refused": exc.constraint, "message": exc.message}  # MUTATED: value lost
            run.push("capture", f"[{exc.constraint}] {exc.message}")' \
    "page round 1: the run state and status line carry the refusal's value against its limit" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '      ? ` (measured ${r.actual}${unit}, limit ${r.limit}${unit})` : "";' \
    '      ? `` : "";  // MUTATED: the card prints the message alone' \
    "page round 1: the card prints a refusal's measured value and limit" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 1: closure rows with their unit and the graded window -----

mutate webapp/static/index.html \
    '      `${esc(c.unit)} <span class="dim">(tol ${c.tolerance} ${esc(c.unit)})</span></li>`).join("");' \
    '      `${esc(c.unit)} <span class="dim">(tol ${c.tolerance})</span></li>`).join("");  // MUTATED: no unit on the tolerance' \
    "page round 1: a closure row's tolerance carries its unit" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '  if (cl.duration_s == null) return settled;' \
    '  return settled;  // MUTATED: the graded window is never named' \
    "page round 1: the closure heading names the graded window and its length" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 1: a finished run outlives the server process ---------------

mutate webapp/runs.py \
    '        if status is None and not clip.is_file():
            return None' \
    '        if not clip.is_file():  # MUTATED: recovery keyed on the clip again
            return None' \
    "page round 1: recovery is keyed on provenance and status, not on a clip" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '        run.capture = recover_capture_summary(out)' \
    '        run.capture = None  # MUTATED: a recovered run loses its capture card' \
    "page round 1: a recovered run's capture card is rebuilt from the capture files" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/capture.py \
    '    closure = _read_json(capture_dir / "closure.json")
    if closure is not None:' \
    '    closure = _read_json(capture_dir / "closure.json")
    if False:  # MUTATED: the closure report is not read back' \
    "page round 1: the recovered card carries closure.json" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/capture.py \
    '    counts = _counts([(camera_id, lengths[camera_id]) for camera_id in order],
                     verdict)' \
    '    counts = _counts([(camera_id, lengths[camera_id]) for camera_id in order],
                     {})  # MUTATED: rendered and verified not read from verify.json' \
    "page round 1: the recovered counts come from verify.json's engine-parity data" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '        if status in ("done", "failed") and self.out_dir:
            self.write_status(Path(self.out_dir), status, detail)' \
    '        if False:  # MUTATED: status.json written only after the status shows
            self.write_status(Path(self.out_dir), status, detail)' \
    "page round 1: a terminal push writes status.json before the status is visible" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 2: a failed run is terminal for the page ---------------------

mutate webapp/static/index.html \
    '  return run.status === "done" || run.status === "failed";' \
    '  return run.status === "done";  // MUTATED: a failed run gets the status text alone' \
    "page round 2: a failed run is terminal for the page (card, strip and files drawn)" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '  if (runIsTerminal(run)) {' \
    '  if (run.status === "done") {  // MUTATED: poll bypasses the one terminal rule' \
    "page round 2: poll draws the page through the one terminal rule" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '  if (run.status !== "failed") return "";' \
    '  return "";  // MUTATED: a failed run'"'"'s card shows its counts as if it had finished' \
    "page round 2: a failed run's card names the failure beside its counts" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '  if (run.status === "failed") {
    return `<div class="dim">no clip: the run <span class="verdict-refused">` +' \
    '  if (false) {  // MUTATED: a failed engine run gets the unencoded-by-product words
    return `<div class="dim">no clip: the run <span class="verdict-refused">` +' \
    "page round 2: a failed engine run's clip words name the failure" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 2: the closure window names what was graded ------------------

mutate webapp/capture.py \
    '               "window": "full duration" if full_duration else "capped",' \
    '               "window": "full duration" if full_duration else "clip",  # MUTATED: a headless pair names a clip it never made' \
    "page round 2: closure.json's window word is capped, never a clip the run did not make" \
    tests/test_webapp_capture.py tests/test_closure_pair.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '    const what = render === "clip" ? "the clip'"'"'s window"
      : "the same window a clip would cover";' \
    '    const what = "the clip'"'"'s window";  // MUTATED: the headless heading names a clip' \
    "page round 2: the headless closure heading names the window a clip would cover, not a clip" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '    const whole = cl.spec_duration_s != null && Number(cl.spec_duration_s) > graded' \
    '    const whole = false  // MUTATED: a capped flight is not said to be capped' \
    "page round 2: a capped closure window names the whole flight it was cut from" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 2: the preview contact sheet never sits above rendered frames

mutate webapp/static/index.html \
    '      `frame(s)</span>${toggle}` +
      thumbsHtml(runId, gallery.camera_id, frames, "frames") + previewBlock +' \
    '      `frame(s)</span>${toggle}${sheet}` +  // MUTATED: the preview mosaic drawn above the rendered frames
      thumbsHtml(runId, gallery.camera_id, frames, "frames") + previewBlock +' \
    "page round 2: on a frames run the preview contact sheet sits inside the previews disclosure" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 2: the page's status log is the whole event log ------------

mutate webapp/runs.py \
    '                "started": self.started, "events": list(self.events),' \
    '                "started": self.started, "events": self.events[-20:],  # MUTATED: the first status lines dropped' \
    "page round 2: the run payload carries the whole event log, as status.json does" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 2: the verifier's table and the closure link their file ----

mutate webapp/capture.py \
    '    verification = "capture/verify.json"
    if verification in by_name:' \
    '    verification = "capture/verify.json"
    if False:  # MUTATED: no download class for the verification report' \
    "page round 2: the strip offers verify.json as its own artefact class" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '    + fileLink(run, "capture/verify.json");' \
    '    + "";  // MUTATED: the tally does not link verify.json' \
    "page round 2: the verifier's tally links the verify.json it is rendered from" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '      fileLink(run, "capture/closure.json") + `<ul>${rows}</ul>`;' \
    '      `<ul>${rows}</ul>`;  // MUTATED: the closure heading does not link closure.json' \
    "page round 2: the closure heading links the closure.json it is rendered from" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 2: the review table shows the cameras' keyframed moves -----

mutate webapp/static/index.html \
    '  const moves = cam.moves || [];
  if (!moves.length) return "";' \
    '  const moves = cam.moves || [];
  return "";  // MUTATED: the moves are dropped from the review table again' \
    "page round 2: the review table shows each camera's keyframed moves" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '    body.insertAdjacentHTML("beforeend", cameraMovesHtml(cam));' \
    '    // MUTATED: renderSpec never appends the move rows' \
    "page round 2: renderSpec appends the move rows after each camera's fields" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 3: the flight path is drawn from the file the run listed --

mutate webapp/static/index.html \
    '  if (names.has("capture/telemetry.json")) {' \
    '  if (false) {  // MUTATED: a headless run'"'"'s flight path is not drawn from capture/telemetry.json' \
    "page round 3: a headless run's flight path is drawn from the listed capture/telemetry.json" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '  if (names.has("telemetry.json")) {' \
    '  if (false) {  // MUTATED: a rendered run'"'"'s flight path never takes the rendered flight'"'"'s file' \
    "page round 3: a rendered run's flight path keeps the rendered flight's telemetry.json" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 3: the page's DOM glue is executed, not regex-pinned -------

mutate webapp/static/index.html \
    '    renderCapture(run);
    // The files listing is fetched ONCE and shared: the strip, the' \
    '    // MUTATED: poll never draws the capture card
    // The files listing is fetched ONCE and shared: the strip, the' \
    "page round 3 (DOM): poll draws the capture card on the live page" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '  if (stripHolder) stripHolder.innerHTML = strip;' \
    '  // MUTATED: the strip never lands in the card' \
    "page round 3 (DOM): the download strip lands inside the capture card" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '  if (galleries && run) {
    galleries.innerHTML = (payload.galleries || []).map(' \
    '  if (false) {  // MUTATED: the galleries never replace the count list
    galleries.innerHTML = (payload.galleries || []).map(' \
    "page round 3 (DOM): the galleries replace the card's per-camera count list" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '      img.src = on ? img.dataset.overlay : img.dataset.frame;' \
    '      img.src = img.dataset.overlay;  // MUTATED: the toggle never swaps back' \
    "page round 3 (DOM): the overlay toggle swaps every frame's src both ways" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '      if (link && link.tagName === "A") link.href = img.src;' \
    '      // MUTATED: the anchor keeps the frame while the thumbnail shows the overlay' \
    "page round 3 (DOM): the overlay toggle swaps the anchor's href with the src" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '  } else {
    setTimeout(poll, 2000);
  }' \
    '  } else {
    // MUTATED: a live run is never polled again
  }' \
    "page round 3 (DOM): a run still in flight is polled again" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 3: one refusal shape for the whole page --------------------

mutate webapp/static/index.html \
    '  const constraint = r.constraint || r.refused;' \
    '  const constraint = r.refused;  // MUTATED: the CLI paragraph stands in for the constraint' \
    "page round 3: a run refusal names its constraint once, never the CLI's paragraph" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '      `${refusalWords(payload, "requested")}</span>`;' \
    '      `${esc(payload.refused)}</span>`;  // MUTATED: the status prints the raw refused text' \
    "page round 3 (DOM): the run refusal in the status is the verdict's one shape" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '      v.violations.map(x => `<li>${refusalWords(x, "requested")}</li>`)' \
    '      v.violations.map(x => `<li>[${x.constraint}] ${x.message}</li>`)  // MUTATED: no value clause' \
    "page round 3 (DOM): the verdict's violations go through the one refusal shape" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '            "actual": render, "limit": "none (Headless)", "unit": None}' \
    '            "actual": None, "limit": None, "unit": None}  # MUTATED: the refused choice is dropped' \
    "page round 3: the platform refusal carries the refused choice against the machine's only choice" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '            "actual": f"{active.run_id} {active.status}", "limit": rule,' \
    '            "actual": None, "limit": None,  # MUTATED: the active run is not named as the value' \
    "page round 3: the busy refusal names the active run against the one-at-a-time rule" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '            "actual": aircraft,
            "limit": ", ".join(buildable),' \
    '            "actual": None,  # MUTATED: the airframe is only inside the prose
            "limit": None,' \
    "page round 3: the mesh refusal carries the airframe against the buildable list" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 3: keyframe rows carry their recorded provenance and are editable --

mutate webapp/static/index.html \
    '    : `<td class="src-default" data-src="${esc(key)}">spec data (no ` +' \
    '    : `<td class="src-user" data-src="${esc(key)}">keyframe (no ` +  // MUTATED: unrecorded painted green' \
    "page round 3: a keyframe row without a recorded source is never painted as the user's word" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '        camera.moves_source = "user";
        camera.moves_from = "edited in the web UI";' \
    '        // MUTATED: the edit leaves the list'"'"'s provenance unrecorded' \
    "page round 3 (DOM): an edited keyframe records the list's provenance as the user's edit" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '        move[input.dataset.field] = value;' \
    '        // MUTATED: the keyframe edit is never written back' \
    "page round 3 (DOM): a keyframe edit is written into dict.cameras[i].moves[k]" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate core/scenario/camera.py \
    '        return cls(moves=[dict(m) for m in moves], moves_source=source,
                   moves_from=frm, **kwargs)' \
    '        return cls(moves=[dict(m) for m in moves], **kwargs)  # MUTATED: provenance dropped on parse' \
    "page round 3: a camera's moves provenance survives the dict round trip" \
    tests/test_camera_spec.py || failures=$((failures+1))

mutate webapp/server.py \
    '            "moves_source": camera.moves_source,' \
    '            "moves_source": None,  # MUTATED: /compile hides the recorded source' \
    "page round 3: /compile sends the moves' recorded source" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 3: the gallery shows WHICH frames failed engine parity -----

mutate core/capture/verify.py \
    '                "index": index, "t_s": float(record["t_s"]), "ok": bool(ok),' \
    '                "index": index, "t_s": float(record["t_s"]), "ok": True,  # MUTATED: every frame recorded as verified' \
    "page round 3: verify.json records which frame failed engine parity" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/capture.py \
    '                               "parity": parity.get(camera_id, {}).get(index)})' \
    '                               "parity": None})  # MUTATED: the gallery never learns the verdict' \
    "page round 3: the galleries carry each rendered frame's parity verdict" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '  return !!(it.parity && it.parity.ok === false);' \
    '  return false;  // MUTATED: a rejected frame is captioned like a verified one' \
    "page round 3: a frame that failed engine parity is captioned FAIL in the gallery" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 3: the review table escapes what it interpolates ----------

mutate webapp/static/index.html \
    '         ? `<input data-name="${esc(f.name)}" value="${esc(value)}">`' \
    '         ? `<input data-name="${esc(f.name)}" value="${value}">`  // MUTATED: raw value in the attribute' \
    "page round 3: a field value is escaped into its input attribute" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '        `data-field="${esc(f.name)}" value="${esc(f.value)}">` +' \
    '        `data-field="${esc(f.name)}" value="${f.value}">` +  // MUTATED: raw camera value' \
    "page round 3: a camera field value is escaped into its input attribute" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '  if (f.source === "model") return `interpreting &ldquo;${esc(frm)}&rdquo;`;' \
    '  if (f.source === "model") return `interpreting &ldquo;${frm}&rdquo;`;  // MUTATED: the phrase is markup' \
    "page round 3: the provenance note's quoted phrase is escaped" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 3: a missing file listing is said by name ------------------

mutate webapp/static/index.html \
    '    if (!response.ok) {
      say(`files: /runs/${esc(runId)}/files answered HTTP ${response.status} ` +
          `— downloads and galleries unavailable`);
      return null;
    }' \
    '    if (!response.ok) return null;  // MUTATED: an HTTP error leaves the card bare' \
    "page round 3 (DOM): a failed /files fetch is said by name in the card" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '  } catch (error) {
    say(`files: /runs/${esc(runId)}/files could not be fetched ` +
        `(${esc(error)}) — downloads and galleries unavailable`);
    return null;
  }' \
    '  } catch (error) { return null; }  // MUTATED: a dead fetch is silent' \
    "page round 3 (DOM): a dead /files fetch is said by name in the card" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/static/index.html \
    '  if (!files.length) {
    say(`files: this run listed no files (/runs/${esc(runId)}/files answered ` +
        `an empty list) — nothing to download, no gallery to show`);
    return payload;
  }' \
    '  if (!files.length) return payload;  // MUTATED: an empty listing is silent' \
    "page round 3 (DOM): an empty file listing is said by name" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Page round 3: the headless fallback states the reason once -----------

mutate webapp/static/index.html \
    '  return run.engine_reason
    ? run.engine_reason
    : "headless run by choice; choose Render frames and clip for the frame set";' \
    '  return run.engine_reason
    ? `no engine on this machine — ${run.engine_reason}`  // MUTATED: the reason twice
    : "headless run by choice; choose Render frames and clip for the frame set";' \
    "page round 3: the headless fallback states the platform gate's reason once" \
    tests/test_webapp_capture.py || failures=$((failures+1))

echo
purge_cache
if $PYTEST -q >/dev/null 2>&1; then echo "Restored: suite is green"; else
    echo "Restored: SUITE IS NOT GREEN -- a restore failed"; exit 1; fi

echo
if [ -n "$ONLY" ]; then
    echo "Subset --only '$ONLY': $selected guard(s) run."
fi
if [ "$failures" -eq 0 ]; then
    echo "All guards are load-bearing."
else
    echo "$failures guard(s) are not covered by a failing test."
fi
exit "$failures"
