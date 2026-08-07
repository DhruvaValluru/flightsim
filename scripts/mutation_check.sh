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
    '        self.signs = measure(base)' \
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
    '    first_a = at[1] if len(at) > 1 else at[0]
    first_b = bt[1] if len(bt) > 1 else bt[0]' \
    '    first_a = at[0]  # MUTATED: the trim snapshot is graded as flight
    first_b = bt[0]' \
    "trim snapshot exempt, flight graded" tests/test_host_parity.py \
    || failures=$((failures+1))

mutate experiments/gate5_ue_parity.py \
    '    first_a = at[1] if len(at) > 1 else at[0]
    first_b = bt[1] if len(bt) > 1 else bt[0]' \
    '    first_a = at[5] if len(at) > 5 else at[0]  # MUTATED: shave five samples
    first_b = bt[5] if len(bt) > 5 else bt[0]' \
    "exactly one sample is exempt" tests/test_host_parity.py \
    || failures=$((failures+1))

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
                        and report["p95_abs_m"] < 30.0)' \
    '    report["ok"] = True  # MUTATED: every bake verifies' \
    "a bake must match its source DEM" tests/test_phase6b.py \
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

mutate experiments/gate5_ue_parity.py \
    '    if str(spec.turbulence.value) != "none":' \
    '    if False:  # MUTATED: turbulent cards carry no provider writes' \
    "turbulent cards carry the provider's exact writes" tests/test_phase6b.py \
    || failures=$((failures+1))

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
