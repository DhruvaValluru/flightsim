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

# Options. The contract is the plain run: the full suite green, every guard
# applied and its test red, the full suite green again. The options exist so
# a review window can cover part of it, and so a refactor that rewrites a
# guarded line is caught in seconds rather than discovered as a SKIP forty
# minutes into a run (that happened: manifest 6 rewrote the "randomization"
# line and orphaned its guard).
#
#   --check-targets   apply nothing, run no test: report every guard whose
#                     target string is absent from its file or occurs more
#                     than once (a duplicate would mutate the wrong site);
#                     exit 1 when any guard is orphaned
#   --list            print each guard's number, label and file; run nothing
#   --from N, --to M  run guards N..M only (numbers as --list prints them)
#   --match REGEX     run only guards whose label matches REGEX (grep -E)
#   --no-suite        skip the full-suite baseline and final pass
#
# A subset run is a smoke test, not the contract, and says so at the end.
mode=run; from_n=1; to_n=""; match=""; run_suite=1
need_value() { [ $# -ge 2 ] || { echo "$1 needs a value (try --help)" >&2; exit 2; }; }
while [ $# -gt 0 ]; do
    case "$1" in
        --check-targets) mode=check; run_suite=0 ;;
        --list) mode=list; run_suite=0 ;;
        --from) need_value "$@"; from_n="$2"; shift ;;
        --to) need_value "$@"; to_n="$2"; shift ;;
        --match) need_value "$@"; match="$2"; shift ;;
        --no-suite) run_suite=0 ;;
        -h|--help) sed -n '/^# Options\./,/^mode=/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
    esac
    shift
done
case "$from_n${to_n:-1}" in *[!0-9]*) echo "--from/--to take guard numbers" >&2; exit 2 ;; esac

# Every guard is one `mutate` call at column zero, so the count is the total
# the running "[n/total]" tag is measured against.
total=$(grep -c '^mutate ' "$0")

purge_cache() {
    find . -name __pycache__ -type d -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null
    local prefix
    prefix=$($PY -c 'import sys; print(sys.pycache_prefix or "")')
    if [ -n "$prefix" ]; then
        rm -rf "${prefix}${PWD}" 2>/dev/null
    fi
}

# The source file mutated right now and its pristine copy. A run that is
# interrupted mid-guard (Ctrl-C, a `timeout` kill, a lost terminal) must put
# the file back: before this trap existed a killed run left
# core/scenario/randomization.py mutated in the working tree.
mutated_file=""; mutated_backup=""
restore_mutation() {
    if [ -n "$mutated_backup" ] && [ -f "$mutated_backup" ]; then
        cp "$mutated_backup" "$mutated_file" && rm -f "$mutated_backup"
        purge_cache
        echo "  restored $mutated_file after the run was interrupted" >&2
    fi
    mutated_file=""; mutated_backup=""
}
trap 'restore_mutation; exit 130' INT
trap 'restore_mutation; exit 143' TERM
trap 'restore_mutation' EXIT

# check_target <file> <old> <label> <tag>: the guard's target must occur in
# its file exactly once. Zero means a refactor orphaned the guard; more than
# one means the mutation would land on the first site, which may not be the
# guarded one.
check_target() {
    $PY - "$1" "$2" "$3" "$4" <<'EOF'
import sys
path, old, label, tag = sys.argv[1:5]
try:
    n = open(path).read().count(old)
except OSError as exc:
    print(f"  MISSING   {tag} {label} -- {exc}")
    sys.exit(1)
if n == 1:
    print(f"  ok        {tag} {label}")
elif n == 0:
    print(f"  MISSING   {tag} {label} -- target not found in {path}: {old!r}")
    sys.exit(1)
else:
    print(f"  AMBIGUOUS {tag} {label} -- target occurs {n} times in {path}: {old!r}")
    sys.exit(1)
EOF
}

guard_n=0; ran=0
# mutate <file> <python-repr-of-old> <python-repr-of-new> <label> <tests...>
mutate() {
    local file="$1" old="$2" new="$3" label="$4"; shift 4
    guard_n=$((guard_n+1))
    local tag="[$guard_n/$total]"
    if [ "$guard_n" -lt "$from_n" ]; then return 0; fi
    if [ -n "$to_n" ] && [ "$guard_n" -gt "$to_n" ]; then return 0; fi
    if [ -n "$match" ] && ! printf '%s\n' "$label" | grep -Eq -- "$match"; then return 0; fi
    ran=$((ran+1))
    case "$mode" in
        list) echo "  $tag $label  ($file)"; return 0 ;;
        check) check_target "$file" "$old" "$label" "$tag"; return $? ;;
    esac

    local backup; backup=$(mktemp)
    cp "$file" "$backup"
    mutated_file="$file"; mutated_backup="$backup"
    local t0=$SECONDS

    if ! $PY - "$file" "$old" "$new" <<'EOF'
import sys
path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(path).read()
if old not in src:
    sys.exit(f"  mutation target not found in {path}: {old!r}")
open(path, "w").write(src.replace(old, new, 1))
EOF
    then
        echo "  SKIP  $tag $label -- could not apply mutation"
        cp "$backup" "$file"; rm -f "$backup"
        mutated_file=""; mutated_backup=""
        return 1
    fi

    purge_cache
    if $PYTEST "$@" -q >/dev/null 2>&1; then
        echo "  WEAK  $tag $label -- tests still pass with the guard removed ($((SECONDS-t0))s)"
        local result=1
    else
        echo "  ok    $tag $label -- tests fail with the guard removed ($((SECONDS-t0))s)"
        local result=0
    fi
    cp "$backup" "$file"; rm -f "$backup"
    mutated_file=""; mutated_backup=""
    purge_cache
    return $result
}

case "$mode" in
    list) echo "Guards ($total):" ;;
    check) echo "Targets (each must occur exactly once in its file):" ;;
esac
if [ "$run_suite" -eq 1 ]; then
    echo "Baseline:"
    purge_cache
    if $PYTEST -q >/dev/null 2>&1; then echo "  ok    suite is green"; else
        echo "  ABORT suite is not green before mutating"; exit 1; fi
fi

if [ "$mode" = run ]; then
    echo
    echo "Mutations (each must make its test fail):"
fi
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
    '        elif _sha256_lf(source) != _sha256_lf(target):' \
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

# -- Phase 2 Look lane, part 2 guards ------------------------------------
# Each confirmed by hand in the build container (no engine: the C++ guards
# are source-text pins, the only measurement possible before a Windows
# build): apply, run the test file, restore byte-identical, purge caches.

mutate core/capture/exposure.py \
    '    return math.log2((n * n / t) * (100.0 / s))' \
    '    return math.log2((n * n / t) * (s / 100.0))  # MUTATED: ISO the wrong way up' \
    "EV100 puts ISO under the fraction" tests/test_exposure.py \
    || failures=$((failures+1))

mutate ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public/FlightSimCameraDirector.h \
    '	FVector ChaseOffsetMetres = FVector(-110.0f, 0.0f, 12.0f);' \
    '	FVector ChaseOffsetMetres = FVector(-60.0f, 0.0f, 12.0f);  // MUTATED: the Phase 10 default' \
    "camera director chase default is Python's" tests/test_gate6_visual.py \
    || failures=$((failures+1))

mutate ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp \
    '		// in render.json render_settings.cockpit_offset_m; a small airframe' \
    '		Director->ShoulderOffsetMetres.Z *= Scale;  // MUTATED: span scaling is back' \
    "shoulder offset is not span-scaled" tests/test_gate6_visual.py \
    || failures=$((failures+1))

mutate ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp \
    '			Label->ShowFlags.SetCloud(false);' \
    '			Label->ShowFlags.SetCloud(true);  // MUTATED: clouds in the label pass' \
    "label captures draw no cloud" tests/test_gate6_visual.py \
    || failures=$((failures+1))

mutate ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp \
    '			return Variable != nullptr ? Variable->GetString() : FString(TEXT("absent"));' \
    '			return Variable != nullptr ? Variable->GetString() : FString(TEXT("0"));  // MUTATED: a missing CVar reads as 0' \
    "render_settings records a missing CVar as absent" tests/test_gate6_visual.py \
    || failures=$((failures+1))

mutate ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp \
    '			if (CardLook->TryGetNumberField(TEXT("fog_extinction_per_m"), Value) && Value > 0.0)' \
    '			if (CardLook->TryGetNumberField(TEXT("fog_extinction"), Value) && Value > 0.0)  // MUTATED: a key the look never writes' \
    "commandlet reads the look keys weather_visuals writes" tests/test_gate6_visual.py \
    || failures=$((failures+1))

mutate experiments/gate6_visual.py \
    '    ok = (above_sky >= minimum and above_ground <= leak
          and below_ground >= minimum and below_sky <= leak)' \
    '    ok = above_sky >= minimum  # MUTATED: a layer leaking below the horizon passes' \
    "cloud base bracket needs both sides" tests/test_gate6_visual.py \
    || failures=$((failures+1))

mutate experiments/gate6_visual.py \
    '    ok = drop >= LOOK_THRESHOLDS["visibility_min_ratio_drop"]' \
    '    ok = True  # MUTATED: no order between 50 km and 10 km required' \
    "extinction must follow visibility" tests/test_gate6_visual.py \
    || failures=$((failures+1))

mutate experiments/gate6_visual.py \
    '    ok = (terrain >= LOOK_THRESHOLDS["wet_min_changed_px"]
          and sky <= LOOK_THRESHOLDS["wet_max_sky_changed_px"])' \
    '    ok = terrain >= LOOK_THRESHOLDS["wet_min_changed_px"]  # MUTATED: the sky may get wet' \
    "wet surface null test needs an unchanged sky" tests/test_gate6_visual.py \
    || failures=$((failures+1))

mutate experiments/gate6_visual.py \
    '    if mean < LOOK_THRESHOLDS["night_min_mean_luminance"]:' \
    '    if False:  # MUTATED: black frames hold their exposure' \
    "night exposure clause is vacuous on black frames" tests/test_gate6_visual.py \
    || failures=$((failures+1))

# -- engine source pins from the Phase 2 review round (cpp area) --------
# Still text pins (no engine here): the settle-in placement asks the
# director for the preset's resting pose measured from the CG, never a
# station computed from the actor origin (the datum 33.7 m ahead of the
# B747's CG opened every preset-mode chase clip 136 m behind); the
# render.json root camera_preset is the preset that flew, not a
# hard-coded "LaggedChase"; the plugin includes only the Json headers
# UE ships (Dom/JsonValues.h stopped the first Windows build). Literal
# tabs inside the targets, as the C++ is indented.
mutate ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimCameraDirector.cpp \
    '	// Rest where the presets update from: the CG, never the datum.
	const FVector RestAimPoint = TargetAimPoint(TargetTransform);' \
    '	const FVector RestAimPoint = TargetTransform.GetLocation();  // MUTATED: the datum, not the CG' \
    "resting pose measures from the CG" \
    tests/test_gate6_visual.py || failures=$((failures+1))

mutate ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp \
    '		if (!Director->PresetRestingPose(Station, Look))' \
    '		Station = Scenario.Aircraft->GetActorLocation();  // MUTATED: the datum station is back
		if (false)' \
    "settle-in placement is the director's resting pose" \
    tests/test_gate6_visual.py || failures=$((failures+1))

mutate ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp \
    '	Root->SetStringField(TEXT("camera_preset"), CameraPreset);' \
    '	Root->SetStringField(TEXT("camera_preset"), TEXT("LaggedChase"));  // MUTATED: the hard-coded lie' \
    "render.json root camera_preset is the preset that flew" \
    tests/test_gate6_visual.py || failures=$((failures+1))

mutate ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimVisualScene.cpp \
    '#include "Dom/JsonObject.h"
#include "Engine/DirectionalLight.h"' \
    '#include "Dom/JsonObject.h"
#include "Dom/JsonValues.h"  // MUTATED: a header no engine ships
#include "Engine/DirectionalLight.h"' \
    "plugin includes only the Json headers the engine ships" \
    tests/test_gate6_visual.py || failures=$((failures+1))

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
    '        return {W20_PROP: u.kt_to_fps(self.w20_kt_at(position))}' \
    '        return {W20_PROP: u.kt_to_fps(self.w20_kt_at(position)), "atmosphere/randomseed": float(self.seed)}  # MUTATED' \
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
    '            raise _fail(f"field {name!r} must carry exactly value/source/from")
        if entry["source"] not in ("user", "inferred", "model"):' \
    '            raise _fail(f"field {name!r} must carry exactly value/source/from")
        if False:  # MUTATED: a model may claim default provenance' \
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
    '        if not (isinstance(entry["from"], str) and entry["from"].strip()):
            # The load-bearing rail for guesses' \
    '        if False:  # MUTATED: undeclared guesses accepted
            # The load-bearing rail for guesses' \
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
    '    if (str(spec.wind_speed.source) not in PLANNABLE_SOURCES' \
    '    if False and (str(spec.wind_speed.source) not in PLANNABLE_SOURCES' \
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
    '        if (dn * dn + de * de) ** 0.5 <= radius:
            if last is None or t[i] - last >= refractory:' \
    '        if (dn * dn + de * de) ** 0.5 <= radius:
            if True:  # MUTATED: refractory ignored, one capture per sample' \
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
    '        if count is not None:
            camera.capture_count = Quantity(' \
    '        if False:  # MUTATED: image counts silently dropped
            camera.capture_count = Quantity(' \
    "a stated image count reaches the camera spec" \
    tests/test_nl_compiler.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if not (0.0 <= u_q <= record["width_px"]' \
    '            if False and not (0.0 <= u_q <= record["width_px"]' \
    "an aimed camera that cannot see the aircraft fails verification" \
    tests/test_camera_verify.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        if error > tol_m:' \
    '        if False:  # MUTATED: a landmark may triangulate anywhere' \
    "a landmark that does not triangulate back fails cross-view consistency" \
    tests/test_camera_engine_parity.py || failures=$((failures+1))

# -- Phase 2, package A: a keyframed move is the station the verifier
# grades against; with the keyframes ignored the documented "pull back"
# fails at 172 m against a 166 m bound (the Phase 1 defect), and the
# push-in-vs-pull-back corruption must still be caught.
mutate core/capture/verify.py \
    '                _keyframed_scalar(moves, key, t_frame,' \
    '                _keyframed_scalar([], key, t_frame,  # MUTATED: static offset' \
    "a chase camera is graded against the offset its keyframes state at that time" \
    tests/test_camera_verify.py || failures=$((failures+1))

# -- Phase 2, package A: the synthesised ridge never stands in for a
# place scene-setting staged (the -89.5 m AGL refusal over "413 m
# staged terrain").
mutate webapp/runs.py \
    '    if float(spec.terrain_elevation.value) > 0.0 and not scene_set(spec):' \
    '    if float(spec.terrain_elevation.value) > 0.0:  # MUTATED: ridge under any datum' \
    "a staged place with no bake is flat at its datum, never the control ridge" \
    tests/test_webapp.py || failures=$((failures+1))

# -- Phase 2, package I part 2 (CI fix): the page renders only with an
# engine AND every airframe's imported model; ue_available() alone sent
# the macOS runner into aircraft.mesh on every preview and campaign.
mutate webapp/generate.py \
    '    missing = [name for name in names if not is_imported(name)]' \
    '    missing = []  # MUTATED: an engine alone decides; the model is never checked' \
    "the guided page renders only when every airframe's model is imported" \
    tests/test_webapp_generate.py || failures=$((failures+1))

# -- Camera Phase 2: the capture stage and the web app it reaches.
mutate core/capture/verify.py \
    '    if worst > tol_m:' \
    '    if False:  # MUTATED: the labelled flight need not be the rendered one' \
    "a manifest labelling a different flight than the frames show fails" \
    tests/test_camera_flight_agreement.py || failures=$((failures+1))

mutate webapp/server.py \
    '        resolved.relative_to(root)        # the image stays inside the run' \
    '        pass  # MUTATED: a symlinked image may lead out of the run' \
    "an image path that climbs out of the run directory is refused" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Phase 10, P10-2: ground-truth labels per frame ----------------------

mutate core/capture/airframe.py \
    '    return ((cx - x) * INCH_M, (y - cy) * INCH_M, (cz - z) * INCH_M)' \
    '    return ((x - cx) * INCH_M, (y - cy) * INCH_M, (cz - z) * INCH_M)  # MUTATED: x aft kept aft' \
    "the structural frame is mapped to the body frame, x flipped" \
    tests/test_camera_labels.py || failures=$((failures+1))

mutate core/capture/airframe.py \
    '    if not isinstance(labels, dict):' \
    '    if False:  # MUTATED: an airframe with no stated geometry is labelled anyway' \
    "an airframe with no stated geometry refuses by name" \
    tests/test_camera_labels.py || failures=$((failures+1))

mutate core/capture/airframe.py \
    '            if not definition.get("source"):' \
    '            if False:  # MUTATED: an unsourced stated point is accepted' \
    "a stated keypoint without a source is refused" \
    tests/test_camera_labels.py || failures=$((failures+1))

mutate core/capture/airframe.py \
    '            if contact is None:' \
    '            if False:  # MUTATED: a contact the FDM lacks silently skipped' \
    "a keypoint naming a contact the FDM lacks refuses" \
    tests/test_camera_labels.py || failures=$((failures+1))

mutate core/capture/labels.py \
    '        truncation = (1.0 - (_area(clipped) / full if clipped else 0.0)' \
    '        truncation = (0.0 * (_area(clipped) / full if clipped else 0.0)  # MUTATED: never truncated' \
    "truncation is the clipped-away fraction of the box" \
    tests/test_camera_labels.py || failures=$((failures+1))

mutate core/capture/labels.py \
    '    good = [y for y in roots if A + B * y <= 1e-12]' \
    '    good = list(roots)  # MUTATED: the spurious squared root is allowed' \
    "the horizon keeps the root that points below level" \
    tests/test_camera_labels.py || failures=$((failures+1))

mutate core/capture/manifest.py \
    '            frames[-1]["labels"] = frame_labels(' \
    '            frames[-1]["labels_unused"] = frame_labels(  # MUTATED: no labels on the frame' \
    "every frame carries its labels" \
    tests/test_camera_labels.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    ok = worst <= LABEL_REPROJECTION_TOL_PX' \
    '    ok = True  # MUTATED: any reprojection disagreement passes' \
    "labels are graded against an independent reprojection" \
    tests/test_camera_labels.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if not (u0 - t <= kp["u"] <= u1 + t and v0 - t <= kp["v"] <= v1 + t):' \
    '            if False:  # MUTATED: a keypoint may lie anywhere' \
    "every keypoint lies inside its own box" \
    tests/test_camera_labels.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                continue
            counted += 1
            if not (Path(run_dir) / "frames" / camera / file).is_file():' \
    '                continue
            counted += 1
            if False:  # MUTATED: a declared label file need not exist' \
    "every declared label file exists" \
    tests/test_camera_labels.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    ok = worst >= MASK_CONTAINMENT_MIN' \
    '    ok = True  # MUTATED: a mask anywhere in the image passes' \
    "the engine mask lies inside the label box" \
    tests/test_camera_labels.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    ok = worst >= DEPTH_IN_RANGE_MIN' \
    '    ok = True  # MUTATED: any depth at the aircraft passes' \
    "depth at the aircraft lies within the box's span" \
    tests/test_camera_labels.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        if box is None:
            return Check("mask_containment", FAIL,' \
    '        if False:
            return Check("mask_containment", FAIL,  # MUTATED: a mask with no box is ignored' \
    "an engine mask where the label says nothing is in frame fails" \
    tests/test_camera_labels.py || failures=$((failures+1))

# -- Phase 10, P10-3: the sensor model ------------------------------------

mutate core/capture/profile.py \
    '    if not str(data.get("source", "")).strip():' \
    '    if False:  # MUTATED: a profile with no source is accepted' \
    "a camera profile without a source refuses by name" \
    tests/test_camera_profile.py || failures=$((failures+1))

mutate core/capture/profile.py \
    '    if dist.get("model") not in DISTORTION_MODELS:' \
    '    if False:  # MUTATED: any distortion model word is accepted' \
    "an unmodelled distortion model refuses" \
    tests/test_camera_profile.py || failures=$((failures+1))

mutate core/capture/profile.py \
    '    xd = x * radial + 2.0 * profile.p1 * x * y + profile.p2 * (r2 + 2.0 * x * x)' \
    '    xd = x * radial  # MUTATED: tangential term dropped' \
    "the forward distortion is the full Brown-Conrady model" \
    tests/test_camera_profile.py || failures=$((failures+1))

mutate core/capture/profile.py \
    '    return profile.readout_s * (v / height - 0.5)' \
    '    return profile.readout_s * (v / height)  # MUTATED: readout not centred' \
    "the rolling shutter readout is centred on the frame" \
    tests/test_camera_profile.py || failures=$((failures+1))

mutate core/capture/profile.py \
    '        electrons += rng.normal(0.0, profile.read_noise_e, size=electrons.shape)' \
    '        pass  # MUTATED: no read noise' \
    "read noise is part of the EMVA 1288 model" \
    tests/test_camera_profile.py || failures=$((failures+1))

mutate core/capture/profile.py \
    '    digest = hashlib.sha256(f"{run_seed}:{camera_id}:{index}".encode()).digest()' \
    '    digest = hashlib.sha256(f"{run_seed}:{camera_id}".encode()).digest()  # MUTATED: every frame the same grain' \
    "every frame has its own noise stream" \
    tests/test_camera_profile.py || failures=$((failures+1))

mutate core/capture/profile.py \
    '        image = image * ((cos_theta ** 4) ** profile.vignetting_strength)[..., None]' \
    '        image = image * 1.0  # MUTATED: no vignetting' \
    "cos^4 vignetting reaches the pixels" \
    tests/test_camera_profile.py || failures=$((failures+1))

mutate core/capture/manifest.py \
    '    return [body[1], body[2], body[0]]      # (right, down, forward)' \
    '    return [body[0], body[1], body[2]]      # MUTATED: body axes, not camera axes' \
    "the angular rate is expressed in camera axes" \
    tests/test_camera_profile.py || failures=$((failures+1))

mutate core/capture/manifest.py \
    '                "labels_sensor": sensor_labels(profile, frames[-1],' \
    '                "labels_sensor": sensor_labels(load_profile("ideal_pinhole"), frames[-1],  # MUTATED' \
    "the sensor labels are mapped through the camera's own profile" \
    tests/test_camera_profile.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    ok = worst <= SENSOR_UNDISTORT_TOL_PX' \
    '    ok = True  # MUTATED: any undistortion error passes' \
    "sensor labels must undistort back onto the pinhole labels" \
    tests/test_camera_profile.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if not (frames_dir / camera / str(item.get("sensor", ""))).is_file():' \
    '            if False:  # MUTATED: a declared sensor frame need not exist' \
    "every declared sensor frame exists" \
    tests/test_camera_profile.py || failures=$((failures+1))

mutate core/capture/validate.py \
    '        load_profile(str(camera.profile.value))' \
    '        pass  # MUTATED: any profile name validates' \
    "an unknown camera profile refuses in validation" \
    tests/test_camera_profile.py || failures=$((failures+1))

mutate webapp/runs.py \
    '    return stem.with_suffix(".r16").is_file() and stem.with_suffix(".json").is_file()' \
    '    return stem.with_suffix(".r16").is_file()  # MUTATED: samples alone count' \
    "a half-written bake is not a bake" \
    tests/test_webapp.py || failures=$((failures+1))

mutate webapp/server.py \
    '        resolved.relative_to(root)        # the clip stays inside the run' \
    '        pass  # MUTATED: a symlinked clip may lead out of the run' \
    "a clip path that climbs out of the run directory is refused" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate core/capture/aircraft_mesh.py \
    '            return None                    # partial source is not a model' \
    '            continue  # MUTATED: draw whatever parts happen to exist' \
    "a partial airframe source is refused, never drawn as the real aircraft" \
    tests/test_camera_airframe.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        if indices != list(range(emitted)):' \
    '        if False:  # MUTATED: gaps in the frame index pass' \
    "a gap in the frame index sequence fails the count check" \
    tests/test_camera_verify_corruption.py || failures=$((failures+1))

# -- Camera Phase 2: the checks that replaced the tautologies. Each of
# these corruptions PASSED the Phase 1 verifier.
mutate core/capture/verify.py \
    '            if emitted != int(requested):' \
    '            if False:  # MUTATED: the requested count is not read' \
    "an emitted count that is not the count the SPEC requested fails" \
    tests/test_camera_verify_corruption.py || failures=$((failures+1))

# Measured (Phase 2, package D): the 12-space '            if gap > tol:'
# below is a SUBSTRING of the 16-space world-anchored clause that comes
# first in verify.py, and mutate() replaces the FIRST occurrence -- so the
# chase entry re-disabled the tower clause and reported ok for the wrong
# reason while the chase clause was never tested. Each entry now names
# its clause by the lines that only it has (NEXT.md gotcha 28).
mutate core/capture/verify.py \
    '                gap = math.dist(camera, expected)
                worst_placement = max(worst_placement, gap)
                graded += 1
                if gap > tol:' \
    '                gap = math.dist(camera, expected)
                worst_placement = max(worst_placement, gap)
                graded += 1
                if False:  # MUTATED: a stated placement may move' \
    "a world-anchored camera moved off its stated position fails" \
    tests/test_camera_verify_corruption.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            gap = math.dist(station, offset)
            worst_placement = max(worst_placement, gap)
            graded += 1
            if gap > tol:' \
    '            gap = math.dist(station, offset)
            worst_placement = max(worst_placement, gap)
            graded += 1
            if False:  # MUTATED: a chase camera may leave station' \
    "a chase camera displaced from its stated station fails" \
    tests/test_camera_verify_corruption.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                if angle > AIM_TOL_DEG:' \
    '                if False:  # MUTATED: an aimed camera may look away' \
    "an aircraft-aimed camera that stops tracking the aircraft fails" \
    tests/test_camera_verify_corruption.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if not (lo - 1e-9 <= focal <= hi + 1e-9):' \
    '            if False:  # MUTATED: any focal length is accepted' \
    "a focal length the spec never stated fails the intrinsics check" \
    tests/test_camera_verify_corruption.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if worst_fx > 1e-6:' \
    '    if False:  # MUTATED: fx need not follow from the lens' \
    "pixel focal lengths that do not follow from focal/sensor*pixels fail" \
    tests/test_camera_verify_corruption.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if gap > 1e-6:' \
    '            if False:  # MUTATED: cameras may disagree about the aircraft' \
    "two cameras disagreeing about one instant fail the consistency check" \
    tests/test_camera_verify_corruption.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if not measured:' \
    '    if False:  # MUTATED: triangulate without an independent reference' \
    "two-view triangulation reports NOT RUN without engine-measured pixels" \
    tests/test_camera_verify_corruption.py || failures=$((failures+1))

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

# -- Mesh origin: measured from the vertices (manifest version 3) ---------
# The pinned-source tests fetch three model repositories; the guards are
# proven on the synthetic mesh alone, so they stay off the network.

mutate assets_pipeline/convert.py \
    '    if deviation > MESH_EXTENT_TOLERANCE:' \
    '    if False:  # MUTATED: a mesh of any length passes as the labelled airframe' \
    "a mesh whose span is not the labelled length refuses aircraft.mesh_extent" \
    tests/test_aircraft_assets.py -k "not pinned" || failures=$((failures+1))

mutate assets_pipeline/convert.py \
    '    origin_x = nose_actor_cm[0] - extents.nose_cm  # the measured rule (x)' \
    '    origin_x = vrp_actor_cm[0]  # MUTATED: eb5c71d, the staged FDM VRP as the origin' \
    "the mesh origin x is measured from the nose vertex, not the VRP" \
    tests/test_aircraft_assets.py -k "not pinned" || failures=$((failures+1))

mutate assets_pipeline/convert.py \
    '        origin_z = gear_contact_z_cm - extents.gear_lowest_cm  # the measured rule (z)' \
    '        origin_z = vrp_actor_cm[2]  # MUTATED: the VRP z whatever the gear vertices say' \
    "the mesh origin z aligns the lowest gear vertex with the main-gear contact" \
    tests/test_aircraft_assets.py -k "not pinned" || failures=$((failures+1))

mutate assets_pipeline/importer.py \
    'MESH_MANIFEST_VERSION = 3' \
    'MESH_MANIFEST_VERSION = 2  # MUTATED: a VRP-origin manifest counts as current' \
    "a version-2 (VRP-origin) mesh manifest is stale and re-converts" \
    tests/test_aircraft_assets.py -k "not pinned" || failures=$((failures+1))

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

echo "-- the camera identifier and the waypoint vocabulary --"
# Guards for safeguards this branch did not previously have: a camera id
# that named a directory unchecked (measured: '../../pwned' wrote preview
# images OUTSIDE the run directory on Linux; ':' or CON is an
# unrecoverable file-creation failure mid-run on Windows). The count
# contract already has its guard above; the proximity trigger the
# scheduler implemented but no specification could reach is covered by
# the vocabulary tests it now passes through.

mutate core/capture/validate.py \
    '        out.extend(identifier_violations(camera, index))' \
    '        pass  # MUTATED: unsafe camera ids reach the filesystem' \
    "an unsafe camera id refuses before it names a directory" \
    tests/test_camera_validate.py || failures=$((failures+1))

mutate core/capture/validate.py \
    '    bad = sorted({c for c in value if c not in _CAMERA_ID_ALLOWED})' \
    '    bad = []  # MUTATED: separators and wildcards allowed' \
    "a camera id may not contain a path separator or a wildcard" \
    tests/test_camera_validate.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    return sorted(Path(run_dir).rglob("host_telemetry.json"))' \
    '    return [Path(run_dir) / "telemetry.json"]  # MUTATED: the pre-run again' \
    "flight_agreement reads the host's flight, not the pre-run it was solved from" \
    tests/test_camera_flight_agreement.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if t < times[0] - interval or t > times[-1] + interval:' \
    '            if False:  # MUTATED: uncovered frames dropped in silence' \
    "a frame outside the host's recorded flight is not quietly dropped" \
    tests/test_camera_flight_agreement.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if len(unique) > 1:' \
    '    if False:  # MUTATED: a host that flies differently each pass passes' \
    "host determinism is what licenses re-flying instead of replaying" \
    tests/test_camera_flight_agreement.py || failures=$((failures+1))

# -- one flight, not two: solving over the host's own flight -----------

mutate core/capture/verify.py \
    '        tol_m = (HOST_FLIGHT_AGREEMENT_TOL_M' \
    '        tol_m = (PRE_RUN_AGREEMENT_TOL_M  # MUTATED: fallback invisible' \
    "a manifest claiming a host solve is held to the host's tolerance" \
    tests/test_camera_host_flight.py || failures=$((failures+1))

mutate core/capture/manifest.py \
    '    if solve_source not in SOLVE_SOURCES:' \
    '    if False:  # MUTATED: the manifest need not say which flight' \
    "a manifest has to declare which flight its aircraft labels describe" \
    tests/test_camera_host_flight.py || failures=$((failures+1))

mutate core/capture/hostflight.py \
    '    missing = [name for name in REQUIRED_CHANNELS if name not in columns]' \
    '    missing = []  # MUTATED: solve over a flight missing channels' \
    "the host flight is refused by name when the solver's channels are absent" \
    tests/test_camera_host_flight.py || failures=$((failures+1))

mutate core/capture/hostflight.py \
    "    h = hashlib.sha256()" \
    "    h = hashlib.sha256(b'salt')  # MUTATED: not the runner's digest" \
    "the host flight digests exactly as run_spec digests its own" \
    tests/test_camera_host_flight.py || failures=$((failures+1))

mutate core/capture/validate.py \
    '    if value in RESERVED_CAMERA_IDS:' \
    '    if False:  # MUTATED: a camera may shadow the host flight dir' \
    "a camera may not take a directory name the run writes itself" \
    tests/test_camera_validate.py || failures=$((failures+1))

mutate scripts/run_ue_scenario.ps1 \
    '$out = Join-Path (Resolve-Path $outDir).Path (Split-Path -Leaf $args[1])' \
    '$out = Join-Path (Resolve-Path (if ($outDir) { $outDir } else { "." })).Path (Split-Path -Leaf $args[1])' \
    "a PowerShell statement may not sit where a value is expected" \
    tests/test_powershell_scripts.py || failures=$((failures+1))

mutate scripts/run_ue_scenario.ps1 \
    '    "-run=FlightSimBridge.FlightSimScenario",' \
    '    -run=FlightSimBridge.FlightSimScenario' \
    "a dotted native argument must be quoted or PowerShell splits it" \
    tests/test_powershell_scripts.py || failures=$((failures+1))

# The CALL SITE in flightsim/capture.py cannot be guarded here: it runs
# only when ue_available(), so on any machine without the engine it is
# unreachable and a guard on it would report WEAK forever. What is
# guarded is the function it calls, which the unit tests do reach.
mutate core/capture/hostflight.py \
    '    for name, values in columns.items():' \
    '    for name, values in [(n, columns[n]) for n in REQUIRED_CHANNELS if n in columns]:' \
    "the host flight digest covers every recorded column, not seven" \
    tests/test_camera_host_flight.py || failures=$((failures+1))

# -- the web app: every view, and the flight its labels describe -------

mutate webapp/capture.py \
    '                    telemetry=out / "host_telemetry.json", **render_kwargs)' \
    '                    **render_kwargs)  # MUTATED: one shared recording' \
    "each camera pass records the host flight that produced ITS frames" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/capture.py \
    'solve_source=solved["solve_source"],' \
    'solve_source=SOLVE_PRE_RUN,  # MUTATED: the label is a constant' \
    "a web manifest names the flight it was actually solved over" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/server.py \
    '    while camera_id in taken:' \
    '    while False:  # MUTATED: two views may share a directory' \
    "an added view gets an id no other camera has" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/capture.py \
    '    frames = [f for f in manifest.get("frames", [])
              if str(f.get("camera_id")) == camera_id]' \
    '    frames = list(manifest.get("frames", []))  # MUTATED: every camera' \
    "a camera's manifest carries that camera's frames and no others" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# No guard on the per-camera manifest route's name check (webapp/server.py
# run_camera_manifest, _CAMERA_NAME): the one that stood here mutated the
# check into a bodiless `if False:` -- a syntax error, so its "ok" was a
# broken import, never a test -- and the honest mutation (the check
# removed, the module importable) is WEAK: '..', '..%2f..' and 'a/b' are
# refused by the router before the route, and a 65-character name falls
# through to camera_view(), which 404s too. It returns when
# tests/test_webapp_capture.py::test_the_per_camera_route_refuses_an_unusable_name
# also asserts `"chase0" not in reply.text` (a lookup's 404 lists the
# run's cameras; the check's 404 does not).

mutate webapp/runs.py \
    '        chosen = (named or [line.strip() for line in lines])[-keep:]' \
    '        chosen = []  # MUTATED: the page gets a path, not a reason' \
    "a failed engine pass tells the page why, not where to look" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '        return bool(payload.get("control_inputs"))' \
    '        return False  # MUTATED: send every card to the parity tool' \
    "a scripted card goes to the tool that can fly it" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '                shutil.rmtree(scratch, ignore_errors=True)' \
    '                pass  # MUTATED: leave the solve pass render.json behind' \
    "the solve pass leaves no render.json for the verifier to find" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/capture.py \
    '    return {name: list(values)[:keep] for name, values in columns.items()}' \
    '    return columns  # MUTATED: schedule past the end of the clip' \
    "the capture schedule is cut to the flight the host will fly" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/runs.py \
    '                   "landmarks": capture_landmarks})' \
    '                   })  # MUTATED: the pre-run landmark set is kept' \
    "the engine projects the landmarks the manifest names" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/server.py \
    '    plan_full_capture(' \
    '    (lambda *a, **k: None)(  # MUTATED: three stills from the page' \
    "a view added from the page captures the whole clip" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate core/scenario/camera.py \
    '    camera.plan("trigger", "continuous", frm=frm)' \
    '    pass  # MUTATED: keep the one-capture-a-second default' \
    "a view nobody counted captures every recorded sample" \
    tests/test_camera_spec.py tests/test_webapp_capture.py \
    || failures=$((failures+1))

mutate core/scenario/camera.py \
    '    if int(camera.capture_count.value or 0) > 0:' \
    '    if False:  # MUTATED: plan continuous over a stated count' \
    "a stated image count is never turned into a schedule refusal" \
    tests/test_camera_spec.py tests/test_llm_compiler.py \
    || failures=$((failures+1))

mutate core/scenario/camera.py \
    '    if camera.period_s.source is not Source.DEFAULT:' \
    '    if False:  # MUTATED: drop a stated capture rate in silence' \
    "a stated capture rate is never planned away" \
    tests/test_camera_spec.py tests/test_llm_compiler.py \
    || failures=$((failures+1))

mutate core/nl/compiler.py \
    '        plan_full_capture(camera, frm="a view named in the prompt with "' \
    '        (lambda *a, **k: None)(camera, frm="MUTATED: three stills "' \
    "a view named in the prompt captures the whole clip" \
    tests/test_camera_spec.py || failures=$((failures+1))

mutate core/nl/llm_compiler.py \
    '        plan_full_capture(camera, frm="a view named in the prompt with "' \
    '        (lambda *a, **k: None)(camera, frm="MUTATED: three stills "' \
    "a view the model named captures the whole clip" \
    tests/test_llm_compiler.py || failures=$((failures+1))

mutate webapp/static/frames.html \
    'loading="lazy" decoding="async" ` +
                   `alt="${esc(label)}"' \
    '` +
                   `alt="${esc(label)}"' \
    "the frame browser lazily loads hundreds of images" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate scripts/report_run.ps1 \
    '    Invoke-Git @("show-ref", "--verify", "--quiet", "refs/heads/$Branch") | Out-Null' \
    '    $parent = & $gitExe -C $repo rev-parse "refs/heads/$Branch" 2>$null  # MUTATED' \
    "a redirected stderr is not a terminating error" \
    tests/test_powershell_scripts.py || failures=$((failures+1))

mutate scripts/report_run.ps1 \
    '          "--cacheinfo", "100644,$blob,reports/$name.txt") | Out-Null' \
    '          "--index-info") | Out-Null  # MUTATED: an entry on stdin' \
    "the index entry never travels through a PowerShell pipe" \
    tests/test_powershell_scripts.py || failures=$((failures+1))

mutate scripts/ue_preflight.ps1 \
    '        $core = Probe $py @("-c",' \
    '        $core = & $py 2>$null @("-c",  # MUTATED: unguarded redirect' \
    "the preflight probes can report a failure instead of dying on it" \
    tests/test_powershell_scripts.py || failures=$((failures+1))

mutate scripts/report_run.ps1 \
    '$env:GIT_TERMINAL_PROMPT = "0"' \
    '$env:GIT_TERMINAL_PROMPT = "1"  # MUTATED: wait for a credential' \
    "the push refuses to sit waiting for a credential" \
    tests/test_powershell_scripts.py || failures=$((failures+1))

mutate scripts/report_run.ps1 \
    '-Tail $TAIL_LINES' \
    '-Raw  # MUTATED: read every engine log end to end' \
    "engine logs are read from the tail, not end to end" \
    tests/test_powershell_scripts.py || failures=$((failures+1))

mutate scripts/report_run.ps1 \
    '    Write-Host ("  ... {0}" -f $text) -ForegroundColor DarkGray' \
    '    # MUTATED: Step prints nothing, so a slow phase is silence' \
    "the report says which phase it is in" \
    tests/test_powershell_scripts.py || failures=$((failures+1))

mutate scripts/report_run.ps1 \
    'function Invoke-Git {' \
    'function Git {  # MUTATED: shadows git.exe and calls itself' \
    "no wrapper function shadows the command it calls" \
    tests/test_powershell_scripts.py || failures=$((failures+1))

mutate scripts/report_run.ps1 \
    '    try { & $gitExe -C $repo @GitArgs }' \
    '    try { & git -C $repo @GitArgs }  # MUTATED: the word, not the path' \
    "git is called through a resolved path, never by name" \
    tests/test_powershell_scripts.py || failures=$((failures+1))

# -- version 4: the whole recorded row rides with every frame -----------

mutate core/capture/manifest.py \
    '                "state": frame_state(columns, sample_index),' \
    '                "state": {},  # MUTATED: six numbers, the rest dropped' \
    "every frame carries the whole recorded row" \
    tests/test_camera_manifest.py tests/test_webapp_capture.py \
    || failures=$((failures+1))

mutate core/capture/manifest.py \
    '    return {name: float(values[index]) for name, values in columns.items()}' \
    '    return {name: float(values[0]) for name, values in columns.items()}  # MUTATED: the first sample for every frame' \
    "a frame's state is the row at ITS sample, not the first" \
    tests/test_camera_manifest.py || failures=$((failures+1))

mutate core/capture/manifest.py \
    '    return {name: channel_unit(name) for name in columns}' \
    '    return {}  # MUTATED: no units, so a consumer guesses' \
    "every state channel has a stated unit" \
    tests/test_camera_manifest.py || failures=$((failures+1))

mutate core/capture/manifest.py \
    '    return "?"' \
    '    return "m"  # MUTATED: an unrecognised channel is guessed as metres' \
    "an unrecognised channel unit is a question, not a guess" \
    tests/test_camera_manifest.py || failures=$((failures+1))

mutate core/capture/manifest.py \
    '        if section not in ("initial", "environment"):' \
    '        if section not in ("run",):  # MUTATED: the wrong sections' \
    "the conditions asked for ride in the manifest" \
    tests/test_camera_manifest.py || failures=$((failures+1))

mutate core/capture/manifest.py \
    'SUPPORTED_MANIFEST_VERSIONS = (3, 4, 5, 6, 7)' \
    'SUPPORTED_MANIFEST_VERSIONS = (4, 5, 6, 7)  # MUTATED: every earlier run refused' \
    "a version 3 manifest still reads" \
    tests/test_camera_manifest.py || failures=$((failures+1))

mutate core/capture/manifest.py \
    '            if stale.resolve() not in named:' \
    '            if False:  # MUTATED: stale sidecars kept beside the frames' \
    "stale sidecars are removed like stale frames" \
    tests/test_camera_manifest.py || failures=$((failures+1))

mutate core/capture/manifest.py \
    '        "camera": cameras.get(str(record.get("camera_id"))),' \
    '        "camera": next(iter(cameras.values()), None),  # MUTATED: the first camera for every frame' \
    "a sidecar names ITS camera" \
    tests/test_camera_manifest.py || failures=$((failures+1))

mutate core/capture/hostflight.py \
    '        if name not in record and len(values) == n:' \
    '        if name not in record:  # MUTATED: a ragged column misaligned' \
    "a column of the wrong length is not the flight's" \
    tests/test_camera_host_flight.py || failures=$((failures+1))

mutate webapp/capture.py \
    '        columns = clip_columns(read_host_record(host_telemetry), duration_s)' \
    '        columns = clip_columns(read_host_columns(host_telemetry), duration_s)  # MUTATED: seven columns' \
    "the host solve hands the manifest the whole record" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/capture.py \
    '    write_frame_sidecars(manifest, out)' \
    '    pass  # MUTATED: no sidecars beside the frames' \
    "the web run writes a label file beside every frame" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/capture.py \
    '            zf.write(path, arcname=f"{camera_id}/{path.name}",' \
    '            if path.suffix == ".json": continue  # MUTATED: pictures only\n            zf.write(path, arcname=f"{camera_id}/{path.name}",' \
    "the zip packs every frame's labels beside it" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/capture.py \
    '        if archive.stat().st_mtime >= newest:' \
    '        if True:  # MUTATED: a stale zip is served forever' \
    "the archive follows a re-render" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/server.py \
    '    if resolved.suffix in (".json", ".f32") and kind != "frames":' \
    '    if False:  # MUTATED: any .json under any image dir is served' \
    "a json outside frames is not a label file" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate core/capture/schedule.py \
    '        indices = list(range(n))' \
    '        indices = [0]  # MUTATED: continuous is one frame' \
    "continuous captures every recorded sample" \
    tests/test_camera_schedule.py tests/test_webapp_capture.py \
    || failures=$((failures+1))

mutate webapp/runs.py \
    '        return max(1.0, min(float(FPS), 1.0 / median(gaps)))' \
    '        return float(FPS)  # MUTATED: play the flight 3x too fast' \
    "a camera clip plays at the rate its frames were taken" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- Phase 10, P10-4: render reproducibility is measured, never asserted --

mutate core/capture/repro.py \
    '                  if p.stem[-4:].isdigit() and len(p.stem) == len("frame_0000"))' \
    '                  )  # MUTATED: masks and depth are compared as frames' \
    "only the plain frames are compared" \
    tests/test_render_repro.py || failures=$((failures+1))

mutate core/capture/repro.py \
    '    if missing:' \
    '    if False:  # MUTATED: an absent frame is not incomplete' \
    "a frame missing from one render is incomplete, not ignored" \
    tests/test_render_repro.py || failures=$((failures+1))

mutate core/capture/repro.py \
    '    elif compared and identical == compared:' \
    '    elif compared:  # MUTATED: a differing frame is bit-identical' \
    "one differing pixel is bounded, not bit-identical" \
    tests/test_render_repro.py || failures=$((failures+1))

mutate core/capture/repro.py \
    '            if ea != ha or eb != hb:' \
    '            if False:  # MUTATED: a replaced frame passes as the engine'"'"'s' \
    "a frame the engine did not write is reported apart" \
    tests/test_render_repro.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        if frame_sha256(path) != expected:' \
    '        if False:  # MUTATED: every frame hashes to the record' \
    "frame_integrity fails on a replaced frame" \
    tests/test_render_repro.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        path = frames_dir / camera / name
        if expected is None:' \
    '        path = frames_dir / camera / name
        if False:  # MUTATED: an unrecorded frame is checked as recorded' \
    "a frame the engine never recorded is named" \
    tests/test_render_repro.py || failures=$((failures+1))

mutate experiments/gate10_render_repro.py \
    '        command += [str(card), str(frames), "-Visual", "-deterministic", *extra]' \
    '        command += [str(card), str(frames), "-Visual", *extra]  # MUTATED: no pins' \
    "Gate 10-R renders with the determinism pins" \
    tests/test_render_repro.py || failures=$((failures+1))

mutate experiments/gate10_render_repro.py \
    '            print(f"report: {report_path}")
            return 2' \
    '            print(f"report: {report_path}")
            return 0  # MUTATED: NOT RUN exits as a pass' \
    "NOT RUN is not a verdict and not an exit 0" \
    tests/test_render_repro.py || failures=$((failures+1))

# -- Phase 10, P10-7: domain randomisation, sampled once and recorded --

mutate core/scenario/spec.py \
    '        if not self.randomization.is_default():
            out["randomization"] = self.randomization.to_dict()' \
    '        if True:  # MUTATED: a default block is written, so every digest moves
            out["randomization"] = self.randomization.to_dict()' \
    "an absent block is the canonical default" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '    if not block.is_enabled():
        return
    if block.seed.source' \
    '    if False:  # MUTATED: an OFF block samples anyway
        return
    if block.seed.source' \
    "an off block draws nothing" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '    if getattr(block, name).source in PLANNABLE:
        block.plan(name, value, frm=frm)' \
    '    if True:  # MUTATED: a stated block field is planned over
        block.plan(name, value, frm=frm)' \
    "a stated day or hour is used, not redrawn" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '        if position.elevation_deg >= floor:
            break' \
    '        if True:  # MUTATED: a night draw is accepted
            break' \
    "a draw below the sun floor is rejected" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '        if q.source not in PLANNABLE:
            note = ' \
    '        if False:  # MUTATED: a stated camera field is jittered
            note = ' \
    "the jitter never moves a stated camera field" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '        base = float(q.detail.get(JITTER_BASE_KEY, q.value))
        if kind == "fraction":' \
    '        base = float(q.value)  # MUTATED: the jitter jitters the jitter
        if kind == "fraction":' \
    "a second planner pass lands on the same jitter" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '    return (90.0 - float(compass_azimuth_deg)) % 360.0' \
    '    return float(compass_azimuth_deg) % 360.0  # MUTATED: compass as yaw' \
    "the engine yaw points at the sun's compass bearing" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '    if sun_elevation_deg <= e0:
        return b0' \
    '    if False:  # MUTATED: exposure extrapolated below the dawn point
        return b0' \
    "exposure is clamped to the calibrated points" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '    if not block.is_sampled():
        raise RandomizationError(' \
    '    if False:  # MUTATED: an unsampled block renders a zero sun
        raise RandomizationError(' \
    "an enabled block nobody sampled refuses to render" \
    tests/test_randomization.py || failures=$((failures+1))

mutate webapp/runs.py \
    '    sampled = randomization_look(spec)
    if sampled is not None:
        return sampled' \
    '    sampled = randomization_look(spec)
    if False:  # MUTATED: the sample never reaches the render
        return sampled' \
    "the render is given the sampled look" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/validate.py \
    '    if not isinstance(block.enabled.value, bool):' \
    '    if False:  # MUTATED: a string "false" switches the block on' \
    "the switch must be a boolean" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/card.py \
    '    if randomization:
        # Phase 10 (package 7)' \
    '    if False:  # MUTATED: the card forgets the sampled look
        # Phase 10 (package 7)' \
    "the card carries the sampled block" \
    tests/test_randomization.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '    try:
        sample_randomization(spec)' \
    '    try:
        pass  # MUTATED: the CLI never samples' \
    "the capture command samples the block" \
    tests/test_randomization.py || failures=$((failures+1))

mutate webapp/server.py \
    '    randomization_refusal = sample_randomization_or_refuse(spec)
    project_for_ue_host(spec)' \
    '    randomization_refusal = None  # MUTATED: /run never samples
    project_for_ue_host(spec)' \
    "/run samples and refuses by name" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/capture/manifest.py \
    '        "randomization": randomization,' \
    '        "randomization": None,  # MUTATED: the manifest forgets the block' \
    "the manifest carries the same block as the card" \
    tests/test_randomization.py || failures=$((failures+1))

# -- Phase 10, P10-6: batch execution and dataset export --

mutate core/dataset/export.py \
    '    if not record.is_file():
        raise ExportError(
            "export.unverified",' \
    '    if False:  # MUTATED: an unverified run exports
        raise ExportError(
            "export.unverified",' \
    "an unverified run refuses the export by name" \
    tests/test_dataset.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '    if failed or not verification.get("ok", False):' \
    '    if False:  # MUTATED: a failed verification exports' \
    "a run with a failed check refuses the export" \
    tests/test_dataset.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '    if missing:
        raise ExportError(
            "export.missing_frames",' \
    '    if False:  # MUTATED: frames with no pixels are silently dropped
        raise ExportError(
            "export.missing_frames",' \
    "a frame with no image refuses unless labels-only" \
    tests/test_dataset.py || failures=$((failures+1))

mutate core/capture/manifest.py \
    '    payload.pop("cameras", None)
    # Phase 10 (package 7)' \
    '    pass  # MUTATED: the cameras enter the simulation identity
    # Phase 10 (package 7)' \
    "the simulation digest ignores the cameras" \
    tests/test_dataset.py || failures=$((failures+1))

mutate core/capture/manifest.py \
    '    payload.pop("randomization", None)' \
    '    pass  # MUTATED: the sampled look enters the simulation identity' \
    "the simulation digest ignores the randomisation" \
    tests/test_dataset.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '    random.Random(int(seed)).shuffle(digests)' \
    '    pass  # MUTATED: the split ignores its seed' \
    "the split follows its seed" \
    tests/test_dataset.py || failures=$((failures+1))

mutate core/dataset/batch.py \
    '        done = {row["run_id"] for row in log.rows() if row.get("ok")}' \
    '        done = set()  # MUTATED: a resumed batch reruns everything' \
    "a resumed batch skips what the ledger records" \
    tests/test_dataset.py || failures=$((failures+1))

mutate core/dataset/batch.py \
    '        index += 1
        log.append(row)' \
    '        index += 1
        if row.get("ok"): log.append(row)  # MUTATED: failures dropped' \
    "a failed run is a ledger line" \
    tests/test_dataset.py || failures=$((failures+1))

mutate core/dataset/batch.py \
    '                    raise BatchError(
                        "batch.factors",
                        f"factor {name!r} is not a spec field ({exc})") from exc' \
    '                    continue  # MUTATED: an unknown factor is skipped
                    raise BatchError(
                        "batch.factors",
                        f"factor {name!r} is not a spec field ({exc})") from exc' \
    "an unknown factor refuses before any run" \
    tests/test_dataset.py || failures=$((failures+1))

mutate core/dataset/batch.py \
    '                sample_randomization(spec)
            except RandomizationError as exc:' \
    '                pass  # MUTATED: the run id names a spec no run has
            except RandomizationError as exc:' \
    "the run id is the digest the manifest records" \
    tests/test_dataset.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '    return math.atan2(-fz, fx)' \
    '    return math.atan2(fz, fx)  # MUTATED: rotation_y sign' \
    "KITTI rotation_y follows the stated convention" \
    tests/test_dataset.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '            flat += [float(kp["u"]), float(kp["v"]), 2]' \
    '            flat += [float(kp["u"]), float(kp["v"]), 1]  # MUTATED: visible = occluded' \
    "COCO keypoint visibility is 2 for an in-frame point" \
    tests/test_dataset.py || failures=$((failures+1))

mutate flightsim/verify.py \
    '    written = write_verification(report, args.run_dir)' \
    '    written = Path(args.run_dir)  # MUTATED: the verdict is never recorded' \
    "flightsim.verify records its verdict" \
    tests/test_dataset.py || failures=$((failures+1))

# -- Phase 2, package E: export formats (YOLO, VOC), the object reader, the card --

mutate core/dataset/export.py \
    '        raise ExportError(
            "export.unverified",
            f"{directory} has no {VERIFICATION_FILE}: run "' \
    '        raise ExportError(
            "export.unnamed",  # MUTATED: the refusal loses its name
            f"{directory} has no {VERIFICATION_FILE}: run "' \
    "the unverified refusal carries its name (export.unverified)" \
    tests/test_dataset_formats.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '    return splits[sample.simulation_digest]' \
    '    return SPLITS[int(sample.record["index"]) % 2]  # MUTATED: a frame picks its own side' \
    "a frame of one flight never straddles train and val, in every format" \
    tests/test_dataset_formats.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '        truncated = int(float(truncation) > 0.0)' \
    '        truncated = 0  # MUTATED: VOC truncated ignores the truncation' \
    "VOC truncated follows the truncation key" \
    tests/test_dataset_formats.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '        truncated = int(float(fraction) < 1.0)' \
    '        truncated = 0  # MUTATED: VOC truncated ignores fraction_in_frame' \
    "VOC truncated follows fraction_in_frame when a record carries it" \
    tests/test_dataset_formats.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '        occluded = int(float(visible) < VOC_OCCLUDED_BELOW)' \
    '        occluded = 0  # MUTATED: VOC occluded ignores the visibility' \
    "VOC occluded follows visible_fraction" \
    tests/test_dataset_formats.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '        difficult = int(extent < threshold)' \
    '        difficult = 0  # MUTATED: VOC difficult ignores the not-claimed threshold' \
    "VOC difficult follows the not-claimed pixel threshold" \
    tests/test_dataset_formats.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '    if fraction >= KITTI_VISIBLE_FULL:
        return 0
    if fraction >= KITTI_VISIBLE_PARTLY:
        return 1
    return 2' \
    '    return KITTI_OCCLUDED_UNKNOWN  # MUTATED: the visibility is never read' \
    "KITTI occluded is derived from visible_fraction" \
    tests/test_dataset_formats.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '            if ungraded:
                ships = [f for f in formats if suffix in SHIPPED_LABEL_FILES.get(f, ())]' \
    '            if False:  # MUTATED: ungraded masks ship
                ships = [f for f in formats if suffix in SHIPPED_LABEL_FILES.get(f, ())]' \
    "a mask the verifier never graded refuses export.unverified_labels" \
    tests/test_dataset_formats.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '    info.mtime = 0
    info.uid = info.gid = 0' \
    '    info.mtime = __import__("time").time()  # MUTATED: the member carries the clock
    info.uid = info.gid = 0' \
    "a with-pixels WebDataset shard is byte-reproducible" \
    tests/test_dataset_formats.py || failures=$((failures+1))


# -- Phase 2, package E review round: the export's refusals and the card --
# Each refusal by name before a file is written (two runs with one
# folder name, a manifest edited after its verdict, a different picture
# already under the key, a class outside the taxonomy, a class image or
# depth no check graded); YOLO data.yaml carries no path key; a licence
# disagreement between runs is one entry each; render.json provenance
# and every airframe reach the card; the batch runner binds every
# verdict to the manifest it graded.
mutate core/dataset/export.py \
    '    if clashes:
        name, paths = sorted(clashes.items())[0]
        raise ExportError(
            "export.run_names",' \
    '    if False:  # MUTATED: two runs with one name export over each other
        name, paths = sorted(clashes.items())[0]
        raise ExportError(
            "export.run_names",' \
    "two different runs with one directory name refuse export.run_names" \
    tests/test_dataset_formats.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '    if bound is not None and str(bound) != digest:
        raise ExportError(
            "export.verification_stale",' \
    '    if False:  # MUTATED: a manifest edited after verification exports under the old verdict
        raise ExportError(
            "export.verification_stale",' \
    "a manifest changed since its verdict refuses export.verification_stale" \
    tests/test_dataset_formats.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '        if target.read_bytes() != sample.image.read_bytes():
            raise ExportError(
                "export.out_directory",' \
    '        if False:  # MUTATED: a different image already there is kept
            raise ExportError(
                "export.out_directory",' \
    "a dataset directory holding a different image refuses export.out_directory" \
    tests/test_dataset_formats.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '    refuse_classes_outside_taxonomy(samples, names)  # ...and a stray class, before any file' \
    '    pass  # MUTATED: a stray class is only found while writing' \
    "a class outside the taxonomy refuses before a file is written" \
    tests/test_dataset_formats.py || failures=$((failures+1))

mutate core/dataset/export.py \
    'LABEL_FILE_CHECKS = {"_mask.png": MASK_CHECKS, "_class.png": MASK_CHECKS,
                     "_depth.f32": DEPTH_CHECKS, **PASS_FILE_CHECKS,' \
    'LABEL_FILE_CHECKS = {"_mask.png": MASK_CHECKS, "_class.png": (),
                     "_depth.f32": (), **PASS_FILE_CHECKS,  # MUTATED: class image and depth ship ungraded' \
    "an ungraded class image or depth refuses export.unverified_labels" \
    tests/test_dataset_formats.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '    data = {"train": "images/train", "val": "images/val", "test": "images/test",' \
    '    data = {"path": ".", "train": "images/train", "val": "images/val", "test": "images/test",  # MUTATED' \
    "YOLO data.yaml names no path key" \
    tests/test_dataset_formats.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '            key = ("object", str(obj.get("id")), str(obj.get("licence")),
                   str(obj.get("mesh_sha256")))' \
    '            key = ("object", str(obj.get("id")))  # MUTATED: the first run'"'"'s licence wins' \
    "runs that disagree on an asset licence get one entry each" \
    tests/test_dataset_formats.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '            categories.append({"id": i + 1, "name": name, "supercategory": name})' \
    '            categories.append({"id": i + 1, "name": name, "supercategory": AIRCRAFT_CLASS, "keypoints": list(KEYPOINT_NAMES), "skeleton": [[1, 2], [3, 4], [1, 5], [6, 7]]})  # MUTATED' \
    "COCO keypoints are declared on the airframe categories only" \
    tests/test_dataset_formats.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '        out[camera.name] = {k: payload.get(k) for k in RENDER_PROVENANCE_KEYS}' \
    '        out[camera.name] = {k: None for k in RENDER_PROVENANCE_KEYS}  # MUTATED' \
    "render.json drawn / render_settings / look_applied reach the card" \
    tests/test_dataset_formats.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '        "aircraft": sorted({name for r in runs for name in r.airframes()}),' \
    '        "aircraft": sorted({s.aircraft for s in samples}),  # MUTATED: the primary only' \
    "the card names every airframe in the dataset" \
    tests/test_dataset_formats.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '        if image == "ideal" and tight is not None:' \
    '        if False:  # MUTATED: the projected box always' \
    "the 2-D box is the mask's wherever the record carries one" \
    tests/test_dataset_boxes.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '        if not_run:
            raise ExportError(
                "export.annotation_not_run",' \
    '        if False:  # MUTATED: NOT RUN gates count as checked
            raise ExportError(
                "export.annotation_not_run",' \
    "engine labels whose annotation gates did not run refuse export" \
    tests/test_dataset_boxes.py || failures=$((failures+1))

mutate core/dataset/export.py \
    '                      and str(c.get("detail", "")).startswith(SUPERSEDED_MARK))}' \
    '                      and False)}  # MUTATED: a superseded check never counts' \
    "a superseded depth_range does not block a manifest-6 run's depth" \
    tests/test_dataset_boxes.py || failures=$((failures+1))

mutate core/capture/labels.py \
    '            "fraction_in_frame": fraction_in_frame(labels["bbox_2d"],
                                                   labels["bbox_2d_unclipped"]),' \
    '            "fraction_in_frame": None,  # MUTATED: no producer' \
    "every aircraft object record carries fraction_in_frame" \
    tests/test_dataset_boxes.py || failures=$((failures+1))

mutate core/dataset/batch.py \
    '    bind_verification(run_dir)      # the verdict names the manifest it graded' \
    '    pass  # MUTATED: the batch verdict is not bound' \
    "the batch runner binds every verdict to its manifest" \
    tests/test_dataset_formats.py || failures=$((failures+1))

# -- Camera Phase 1 gap closure: vocabulary, question, moves, lag, matrices, schema --

mutate core/nl/compiler.py \
    '        if name not in seen:
            seen.add(name)
            out.append((phrase, name))' \
    '        if True:  # MUTATED: a view named twice is two cameras
            seen.add(name)
            out.append((phrase, name))' \
    "one camera per view named, however often" \
    tests/test_camera_prompts.py || failures=$((failures+1))

mutate core/nl/compiler.py \
    '    if _view_mentions(text):
        return questions
    if not any(' \
    '    if False:  # MUTATED: a named view still asks which view
        return questions
    if not any(' \
    "a named view is never asked about" \
    tests/test_camera_prompts.py || failures=$((failures+1))

mutate core/nl/compiler.py \
    '    if not mentions and answered is not None:
        mentions = [answered]' \
    '    if False:  # MUTATED: the answer round is ignored
        mentions = [answered]' \
    "the camera_view answer compiles" \
    tests/test_camera_prompts.py || failures=$((failures+1))

mutate core/nl/compiler.py \
    '            if keyframes is None:
                notes.append(' \
    '            if False:  # MUTATED: an inexpressible move crashes instead of a note
                notes.append(' \
    "an inexpressible move is reported, not guessed" \
    tests/test_camera_prompts.py || failures=$((failures+1))

mutate core/nl/compiler.py \
    '        if abs(last - old_duration_s) > 1e-9:
            continue' \
    '        if False:  # MUTATED: stated keyframe times are rescaled too
            continue' \
    "only prompt-spanning moves follow the clip selector" \
    tests/test_camera_prompts.py || failures=$((failures+1))

mutate webapp/server.py \
    '        rescale_moves(spec, previous, seconds)' \
    '        pass  # MUTATED: a shorter clip keeps the long move' \
    "the clip selector rescales prompt moves" \
    tests/test_camera_prompts.py || failures=$((failures+1))

mutate webapp/server.py \
    '        compiler_used = "regex"
        questions = [] if request.answers else camera_questions(prompt)' \
    '        compiler_used = "regex"
        questions = []  # MUTATED: the regex path never asks' \
    "the regex path asks its one question" \
    tests/test_camera_prompts.py || failures=$((failures+1))

mutate core/capture/poses.py \
    '    return x_now - slope * tau + (y_prev - x_prev + slope * tau) * decay' \
    '    return x_now + (y_prev - x_now) * decay  # MUTATED: zero-order hold again' \
    "the lag integrator is the exact first-order-hold solution" \
    tests/test_camera_poses.py || failures=$((failures+1))

mutate core/capture/poses.py \
    '            gn, ge, gup = _heading_only(air_yaw[i], *offset_at(t[i]))' \
    '            gn, ge, gup = _heading_only(air_yaw[i], *offset)  # MUTATED: offsets never keyframed' \
    "push, pull and orbit reach the solver" \
    tests/test_camera_prompts.py || failures=$((failures+1))

mutate core/capture/validate.py \
    '        if unknown:
            out.append(Violation(
                "camera.moves",' \
    '        if False:  # MUTATED: an unknown keyframe key is silently ignored
            out.append(Violation(
                "camera.moves",' \
    "a keyframe key the solver never reads refuses by name" \
    tests/test_camera_prompts.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if err > PROJECTION_MATRIX_TOL_PX:' \
    '            if False:  # MUTATED: a wrong matrix passes' \
    "projection_matrix fails on a matrix that disagrees" \
    tests/test_capture_schema.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            bad.append(f"{name}: intrinsic_matrix is not [[fx,0,cx],[0,fy,cy],[0,0,1]]")' \
    '            pass  # MUTATED: a wrong K passes' \
    "the intrinsic matrix must be the record's own K" \
    tests/test_capture_schema.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if problems:
        return Check("json_schema", FAIL,' \
    '    if False:  # MUTATED: schema violations pass
        return Check("json_schema", FAIL,' \
    "json_schema fails on a violation" \
    tests/test_capture_schema.py || failures=$((failures+1))

mutate core/capture/schema.py \
    '            if key not in instance:
                out.append(f"{path}: missing required key {key!r}")' \
    '            if False:  # MUTATED: required keys are optional
                out.append(f"{path}: missing required key {key!r}")' \
    "the validator enforces required keys" \
    tests/test_capture_schema.py || failures=$((failures+1))

mutate core/capture/schema.py \
    '        if unknown and where.rsplit("/", 1)[-1] not in ("properties", "$defs"):' \
    '        if False:  # MUTATED: unenforced keywords pass silently' \
    "the validator refuses keywords it does not enforce" \
    tests/test_capture_schema.py || failures=$((failures+1))

mutate core/capture/manifest.py \
    '            frames[-1]["projection_matrix"] = P' \
    '            frames[-1]["projection_matrix"] = [[0.0] * 4 for _ in range(3)]  # MUTATED' \
    "the manifest's P is the record's own projection" \
    tests/test_capture_schema.py || failures=$((failures+1))

# -- the matrices and the run's records on the web page --

mutate webapp/server.py \
    '    if not _SCHEMA_NAME.match(name):
        return JSONResponse({"error": "no such schema"}, status_code=404)' \
    '    if False:  # MUTATED: any name under docs/schemas is served
        return JSONResponse({"error": "no such schema"}, status_code=404)' \
    "only a schema file's own name is served" \
    tests/test_webapp_capture.py || failures=$((failures+1))

mutate webapp/capture.py \
    '    "airframe", "label_conventions", "assets", "randomization",
)' \
    '    "assets", "randomization",  # MUTATED: no airframe, no conventions
)' \
    "the per-camera view carries the airframe and the conventions" \
    tests/test_webapp_capture.py || failures=$((failures+1))

# -- the derived airframe is written atomically and idempotently (batch workers) --

mutate core/control/derive.py \
    '        if path.is_file() and path.read_bytes() == data:
            return False' \
    '        if False:  # MUTATED: an identical file is rewritten every time
            return False' \
    "an identical derived file is never rewritten" \
    tests/test_control.py || failures=$((failures+1))

mutate core/control/derive.py \
    '    tmp.write_bytes(data)
    os.replace(tmp, path)' \
    '    path.write_bytes(data)  # MUTATED: written in place, readers see a partial file' \
    "the derived airframe is written atomically" \
    tests/test_control.py || failures=$((failures+1))

# -- audit fixes: the web camera refusal surface, geographic placement, schema NOT RUN, applied pose --

mutate webapp/server.py \
    '    if camera_refusals:
        verdict["ok"] = False
        verdict["violations"].extend(camera_refusals)' \
    '    if False:  # MUTATED: camera refusals never reach the page
        verdict["ok"] = False
        verdict["violations"].extend(camera_refusals)' \
    "a buried camera refuses on the web surface" \
    tests/test_webapp.py || failures=$((failures+1))

mutate core/capture/poses.py \
    '            north, east = frame.to_local(lat, lon)' \
    '            north, east = 0.0, 0.0  # MUTATED: geographic placement ignored' \
    "a geographic placement resolves through the scene projection" \
    tests/test_camera_poses.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if (version in SUPPORTED_MANIFEST_VERSIONS and version != MANIFEST_VERSION
            and not schema_path(manifest).is_file()):' \
    '    if False:  # MUTATED: an older supported manifest FAILS on a schema nobody published' \
    "json_schema is NOT RUN, not FAIL, for an unpublished older version" \
    tests/test_capture_schema.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        if dist > APPLIED_POSE_TOL_M or angles > APPLIED_POSE_TOL_DEG:' \
    '        if False:  # MUTATED: a pose the engine did not apply passes' \
    "applied_pose fails past the director's tolerance" \
    tests/test_render_repro.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        if (not isinstance(version, (int, float))
                or version < DRAWN_MESH_MIN_MANIFEST_VERSION):' \
    '        if False:  # MUTATED: a mesh attached at the structural datum passes' \
    "drawn_airframe fails on a mesh drawn from a manifest with no origin" \
    tests/test_camera_verify_corruption.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if expected_sha is not None:
                problems.append(' \
    '            if False:  # MUTATED: placeholder boxes pass under a manifest naming the mesh
                problems.append(' \
    "drawn_airframe fails on placeholder boxes where the manifest names a mesh" \
    tests/test_camera_verify_corruption.py || failures=$((failures+1))

mutate core/nl/llm_compiler.py \
    '    if isinstance(nested, list) and not payload["cameras"]:' \
    '    if False:  # MUTATED: a nested camera list refuses the whole response' \
    "a camera list nested under fields is lifted, not refused" \
    tests/test_llm_compiler.py || failures=$((failures+1))

# -- the expert page, Phase 2 review round (webapp area) ----------------
# A sampled wind is as fixed as a stated one and the stated synthesised
# ridge is never re-planned as a place; the depth .f32 the bundle
# declares is served; the page's digest keeps the policy; the schema
# link is built from the manifest version shown. Each target is spelled
# once in its file; the -k selector names the test that fails.
mutate webapp/runs.py \
    '    if (str(spec.wind_speed.source) not in PLANNABLE_SOURCES
            or str(spec.wind_direction.source) not in PLANNABLE_SOURCES):' \
    '    if (str(spec.wind_speed.source) == "user"  # MUTATED: a sampled wind is re-planned
            or str(spec.wind_direction.source) == "user"):' \
    "a sampled wind is as fixed as a stated one" \
    tests/test_webapp.py -k sampled_wind || failures=$((failures+1))

mutate webapp/runs.py \
    'if pick_scene(spec)["key"] in SYNTHESISED_SCENE_KEYS:' \
    'if pick_scene(spec)["key"] == "control":  # MUTATED' \
    "the stated synthesised ridge is not a place" \
    tests/test_webapp.py -k synthesised_ridge || failures=$((failures+1))

mutate webapp/server.py \
    '{1,80}\.(png|json|f32)$' \
    '{1,80}\.(png|json)$' \
    "the depth .f32 the bundle declares is served" \
    tests/test_webapp_capture.py -k metric_depth || failures=$((failures+1))

mutate webapp/server.py \
    '    if "policy" in canonical_section:' \
    '    if False:  # MUTATED: the policy is dropped from the page dict' \
    "the page digest is the run digest with a policy" \
    tests/test_webapp.py -k policy_so_the_page || failures=$((failures+1))

mutate webapp/static/index.html \
    'capture_manifest.v${manifestVersion}.schema.json' \
    'capture_manifest.v5.schema.json' \
    "the expert page links the schema of the version it shows" \
    tests/test_webapp_capture.py -k schema_of_the_manifest_version || failures=$((failures+1))

# -- Phase 2, package A: the spec-8 bump ---------------------------------------
# Every guarded line is spelled uniquely in its file (mutate() replaces the
# FIRST occurrence; NEXT.md gotcha 28).

mutate core/scenario/spec.py \
    '        if not self.scene.is_default():
            out["scene"] = self.scene.to_dict()' \
    '        if True:  # MUTATED: a default scene block is written; old digests move
            out["scene"] = self.scene.to_dict()' \
    "an absent spec-8 block is the canonical default" \
    tests/test_spec8_blocks.py || failures=$((failures+1))

mutate core/scenario/camera.py \
    '        if not self.exposure.is_default(str(self.preset.value)):
            out["exposure"] = self.exposure.to_dict()' \
    '        if True:  # MUTATED: a default exposure is written; every camera digest moves
            out["exposure"] = self.exposure.to_dict()' \
    "a default exposure is absent from the canonical camera" \
    tests/test_spec8_blocks.py || failures=$((failures+1))

mutate core/scenario/blocks.py \
    '        if current.source not in PLANNABLE_SOURCES:
            raise ValueError(
                f"plan() only moves defaulted/derived/model fields; "
                f"{self.BLOCK}.{name} is {current.source.value!r} -- a "' \
    '        if False:  # MUTATED: stated block fields silently move
            raise ValueError(
                f"plan() only moves defaulted/derived/model fields; "
                f"{self.BLOCK}.{name} is {current.source.value!r} -- a "' \
    "a stated scene/taxonomy/traffic field is never silently moved" \
    tests/test_spec8_blocks.py || failures=$((failures+1))

mutate core/scenario/camera.py \
    '        if current.source not in PLANNABLE_SOURCES:
            raise ValueError(
                f"plan() only moves defaulted/derived/model fields; camera "
                f"exposure.{name} is {current.source.value!r} -- a stated "' \
    '        if False:  # MUTATED: a stated exposure silently moves
            raise ValueError(
                f"plan() only moves defaulted/derived/model fields; camera "
                f"exposure.{name} is {current.source.value!r} -- a stated "' \
    "a stated exposure field is never silently moved" \
    tests/test_spec8_blocks.py || failures=$((failures+1))

mutate core/scenario/validate.py \
    '    if source not in TERRAIN_SOURCES:' \
    '    if False:  # MUTATED: any terrain_source word passes' \
    "an unknown terrain_source refuses by name" \
    tests/test_spec8_blocks.py || failures=$((failures+1))

mutate core/scenario/validate.py \
    '    elif len(set(classes)) != len(classes):' \
    '    elif False:  # MUTATED: a repeated class name passes' \
    "a repeated taxonomy class refuses by name" \
    tests/test_spec8_blocks.py || failures=$((failures+1))

mutate core/scenario/validate.py \
    '    if len(spec.traffic) > MAX_TRAFFIC:' \
    '    if False:  # MUTATED: any number of traffic aircraft passes' \
    "more than two traffic aircraft refuse by name" \
    tests/test_spec8_blocks.py || failures=$((failures+1))

mutate core/scenario/validate.py \
    '        if aircraft not in airframes:' \
    '        if False:  # MUTATED: an unconfigured traffic airframe passes' \
    "an unconfigured traffic airframe refuses by name" \
    tests/test_spec8_blocks.py || failures=$((failures+1))

mutate core/scenario/validate.py \
    '            if nested:
                problems.append(
                    f"{here}: a group holds distribution leaves (one of "' \
    '            if False:  # MUTATED: a misspelt distribution reads as a group of fixed values
                problems.append(
                    f"{here}: a group holds distribution leaves (one of "' \
    "a misspelt policy distribution is refused, not read as a group" \
    tests/test_spec8_blocks.py || failures=$((failures+1))

mutate core/scenario/validate.py \
    '        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return str(value)' \
    '        if False:  # MUTATED: every limit is formatted as a number again
            return str(value)' \
    "a string limit renders instead of crashing the refusal" \
    tests/test_spec8_blocks.py || failures=$((failures+1))

mutate core/capture/validate.py \
    '        if isinstance(raw, bool) or value is None or not value > 0.0:' \
    '        if False:  # MUTATED: any exposure value passes' \
    "a non-positive exposure refuses by name" \
    tests/test_spec8_blocks.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '    if terrain_stem is None and (args.synth_terrain
                                 or terrain_source == "synthesised"):' \
    '    if terrain_stem is None and args.synth_terrain:  # MUTATED: the flag alone' \
    "scene.terrain_source synthesised needs no flag" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '        if terrain_stem is None:
            return _refuse([Violation(
                "scene.terrain",
                "scene.terrain_source is baked but no bake is named: "' \
    '        if False:  # MUTATED: baked with no bake flies the flat datum
            return _refuse([Violation(
                "scene.terrain",
                "scene.terrain_source is baked but no bake is named: "' \
    "baked with no bake named refuses by name on the CLI" \
    tests/test_camera_cli.py || failures=$((failures+1))

mutate webapp/runs.py \
    '    stated = _stated_terrain_scene(spec)
    if stated is not None:
        return stated' \
    '    stated = None  # MUTATED: the stated terrain_source is ignored
    if stated is not None:
        return stated' \
    "the web picker honours a stated terrain_source" \
    tests/test_webapp.py || failures=$((failures+1))

mutate webapp/runs.py \
    '    if scene.get("refused") == "terrain.unbaked":' \
    '    if False:  # MUTATED: baked with nothing baked runs on the slab' \
    "baked with nothing baked refuses terrain.unbaked on the web" \
    tests/test_webapp.py || failures=$((failures+1))

# -- Phase 2, package I part 1: the message catalogue --------------------------

mutate core/messages/__init__.py \
    '        _catalogue = loaded
    return _catalogue' \
    '        loaded.pop("camera.terrain_clearance", None)  # MUTATED: an entry vanishes
        _catalogue = loaded
    return _catalogue' \
    "every refusal name the code emits has a catalogue entry" \
    tests/test_messages.py || failures=$((failures+1))

mutate core/messages/__init__.py \
    '    return {"sentence": rule or "refused",
            "hint": technical(obj),' \
    '    return {"sentence": "This request was refused.",  # MUTATED: invented
            "hint": technical(obj),' \
    "an unknown refusal name is shown raw, never given an invented sentence" \
    tests/test_messages.py || failures=$((failures+1))

mutate core/messages/__init__.py \
    '        return _PRESENT + shown(value)' \
    '        return _PRESENT  # MUTATED: every number dropped from the sentence' \
    "a catalogue sentence carries the refusal's own numbers" \
    tests/test_messages.py || failures=$((failures+1))

# -- the catalogue, Phase 2 review round: numbers reach the sentence ------
# An error's detail numbers reach its catalogue sentence; a bracketed
# aside whose every number is absent is dropped whole; the done sentence
# names labels and says whether a picture was drawn; campaign.duplicate_case
# says what workers.py refuses (the two yaml targets are the sentence
# lines themselves, spelled once in the catalogue).
mutate core/messages/__init__.py \
    '        detail = getattr(obj, "detail", None)
        if isinstance(detail, Mapping):' \
    '        detail = None  # MUTATED: the error'"'"'s detail numbers never reach the sentence
        if isinstance(detail, Mapping):' \
    "an error's detail numbers reach its catalogue sentence" \
    tests/test_messages.py || failures=$((failures+1))

mutate core/messages/__init__.py \
    '        if _ABSENT in inner and _PRESENT not in inner:
            return ""' \
    '        if False:  # MUTATED: an aside that lost every number is kept, "(of)"
            return ""' \
    "a bracketed aside whose every number is absent is dropped whole" \
    tests/test_messages.py || failures=$((failures+1))

mutate core/messages/catalog.yaml \
    '  sentence: "Every requested image has its labels generated and checked ({done} {done:picture|pictures} from {cases_verified} {cases_verified:scenario|scenarios}, {total} asked for){drawn:, and its picture drawn|; no picture was drawn on this machine}."' \
    '  sentence: "Every requested image has been generated and checked."' \
    "the done sentence names labels and is drawn-aware" \
    tests/test_messages.py || failures=$((failures+1))

mutate core/messages/catalog.yaml \
    '  sentence: "Two scenarios came out identical because the request leaves nothing to vary between them, so the second was not flown."' \
    '  sentence: "The same case was recorded twice in the ledger, so it was not run again."' \
    "campaign.duplicate_case says what workers.py refuses" \
    tests/test_messages.py || failures=$((failures+1))

# -- the capture command's own words (misc review round) ------------------
# An unreadable spec is refused by name; the flight model's banner stays
# off the default path and the relay drops exactly the banner lines;
# --help states the engine that is pinned rather than a stale number.
mutate flightsim/capture.py \
    '        print(f"REFUSED -- spec.read: {exc}")' \
    '        print(f"REFUSED -- {exc}")  # MUTATED: no name' \
    "an unreadable spec is refused by name (spec.read)" \
    tests/test_capture_cli_words.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '    with quiet_library_banners(enabled=not args.verbose):' \
    '    with quiet_library_banners(enabled=False):  # MUTATED: the banner is back' \
    "the flight model's banner stays off the default path" \
    tests/test_capture_cli_words.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '                             f"poses (Windows with UE {UE_ENGINE_VERSION} "' \
    '                             "poses (Windows with UE 5.5 "  # MUTATED: stale pin' \
    "capture --help states the pinned engine version" \
    tests/test_capture_cli_words.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '        if _is_library_banner(line):
            self.pending_blank = 0
            self.after_banner = True
            return' \
    '        if False:  # MUTATED: banner lines relayed
            self.pending_blank = 0
            self.after_banner = True
            return' \
    "the relay drops exactly the banner lines" \
    tests/test_capture_cli_words.py || failures=$((failures+1))

# The quieted stdout is a spool FILE, never a pipe: a full pipe blocks a
# writer that holds the GIL (the flight model's C++) while the relay
# thread waits for that GIL -- the Windows CI deadlock of run 36217163564
# (4 KB anonymous pipes; the A320 description printed on load is 16 KB).
# And that description stays off the card's own flight model.
mutate flightsim/capture.py \
    '    spool_fd, spool_path = tempfile.mkstemp(prefix="flightsim-stdout-", suffix=".spool")' \
    '    _r, spool_fd = os.pipe(); spool_path = f"/dev/fd/{_r}"  # MUTATED: a pipe again, relayed' \
    "the quieted stdout is a spool file, never a pipe (a full pipe deadlocks a GIL-holding writer)" \
    tests/test_capture_cli_words.py || failures=$((failures+1))

mutate core/scenario/card.py \
    '        fdm.set_debug_level(0)' \
    '        fdm.set_debug_level(1)  # MUTATED: the aircraft description is printed on load' \
    "the run card's flight model prints no aircraft description" \
    tests/test_capture_cli_words.py || failures=$((failures+1))

# --- Phase 2 Look lane part 1: the engine pin and the renderer settings ---
# (tests/test_platform.py). Text files, not Python; mutate() is a string
# replace so it applies to them the same way.
mutate ue/FlightSim.uproject \
    '"EngineAssociation": "5.7"' \
    '"EngineAssociation": "5.5"' \
    "the uproject pins the engine the scripts and refusals name" \
    tests/test_platform.py || failures=$((failures+1))

mutate core/util/platform.py \
    'UE_ENGINE_VERSION = "5.7"' \
    'UE_ENGINE_VERSION = "5.5"  # MUTATED: refusals name the old engine' \
    "the platform refusals and install roots name the pinned engine" \
    tests/test_platform.py || failures=$((failures+1))

mutate scripts/ue_preflight.ps1 \
    '$ueRoot = "C:\Program Files\Epic Games\UE_5.7"' \
    '$ueRoot = "C:\Program Files\Epic Games\UE_5.5"' \
    "a stale 5.5 install path in a script is caught by name" \
    tests/test_platform.py || failures=$((failures+1))

# Two-line targets on purpose (gotcha 28): the ini's comment block quotes
# each key=value once BEFORE the real assignment, and mutate() replaces
# the first occurrence -- a one-line target edits the comment and the
# guard reads WEAK.
mutate ue/Config/DefaultEngine.ini \
    'r.DynamicGlobalIlluminationMethod=1
r.ReflectionMethod=1' \
    'r.DynamicGlobalIlluminationMethod=0
r.ReflectionMethod=1' \
    "the renderer settings are read back from the parsed ini, not asserted" \
    tests/test_platform.py || failures=$((failures+1))

mutate ue/Config/DefaultEngine.ini \
    'ExtendDefaultLuminanceRange=True
r.Substrate=False' \
    'ExtendDefaultLuminanceRange=True
r.Substrate=True' \
    "Substrate stays off until a material is authored for it" \
    tests/test_platform.py || failures=$((failures+1))

# -- Phase 2, packages B + C: object identity and the per-object record ----
# Each target is a multi-line, file-unique string (gotcha 28: mutate()
# replaces the FIRST occurrence).

mutate core/capture/objects.py \
    '    for number, entry in enumerate(entries, start=1):
        if entry["id"] in seen:' \
    '    for number, entry in enumerate(entries, start=2):  # MUTATED: the primary is no longer 1
        if entry["id"] in seen:' \
    "int_ids are assigned in composition order from 1: the primary is always 1" \
    tests/test_capture_objects.py || failures=$((failures+1))

mutate core/capture/objects.py \
    '    if len(entries) > MAX_INT_ID:
        raise ObjectIdentityError(' \
    '    if False:  # MUTATED: a 256th object wraps into another id
        raise ObjectIdentityError(' \
    "a scene needing more than 255 ids refuses annotation.identity" \
    tests/test_capture_objects.py || failures=$((failures+1))

mutate core/capture/labels.py \
    '        out["bbox_2d_tight"] = [float(xs.min()), float(ys.min()),
                                float(xs.max()) + 1.0, float(ys.max()) + 1.0]' \
    '        out["bbox_2d_tight"] = [float(xs.min()), float(ys.min()),
                                float(xs.max()), float(ys.max())]  # MUTATED: one pixel short' \
    "the tight box covers the ID pixels, far edges one past the last pixel" \
    tests/test_capture_objects.py || failures=$((failures+1))

mutate core/capture/labels.py \
    '        if pixels_alone > 0:
            out["visible_fraction"] = pixels / pixels_alone' \
    '        if pixels_alone > 0:
            out["visible_fraction"] = 1.0  # MUTATED: every object fully visible' \
    "visible_fraction is ID-pass pixels over alone-pass pixels" \
    tests/test_capture_objects.py || failures=$((failures+1))

mutate core/capture/labels.py \
    '            others = np.unique(mask[footprint])
            out["occluded_by"] = [int(v) for v in others
                                  if int(v) not in (0, int_id)]' \
    '            out["occluded_by"] = []  # MUTATED: nobody occludes anybody' \
    "occluded_by lists the ids found inside the alone-pass footprint" \
    tests/test_capture_objects.py || failures=$((failures+1))

mutate core/capture/poses.py \
    '        cross_n = centre["north_m"] + range_m * forward[0]
        cross_e = centre["east_m"] + range_m * forward[1]' \
    '        cross_n = centre["north_m"] + 0.5 * range_m * forward[0]  # MUTATED: crosses at half the range
        cross_e = centre["east_m"] + 0.5 * range_m * forward[1]' \
    "a crossing track crosses at the stated range" \
    tests/test_capture_objects.py || failures=$((failures+1))

mutate core/capture/manifest.py \
    '    if len(traffic_tracks) != len(traffic_entries):
        raise ValueError(' \
    '    if False:  # MUTATED: a traffic aircraft with no track is silently unlabelled
        raise ValueError(' \
    "a spec with traffic and no solved tracks refuses the manifest" \
    tests/test_capture_objects.py || failures=$((failures+1))

mutate core/capture/labels.py \
    '    if raw.size != width * height:
        raise ValueError(' \
    '    if False:  # MUTATED: a truncated depth file labels the cut as sky
        raise ValueError(' \
    "a depth .f32 of the wrong size refuses rather than reshaping" \
    tests/test_capture_objects.py || failures=$((failures+1))

# -- Phase 2, package F: the randomisation policy (contracts §5) --------------
# Each guard names the safeguard it removes; each test below fails
# without it (confirmed by hand on landing, see docs/PHASE2_REPORT.md).

mutate core/scenario/randomization.py \
    '            # A refused draw is COUNTED, then re-drawn (never dropped).
            refused.append({"draw_index": int(draw_index), "attempt": attempt,' \
    '            # MUTATED: the refused draw is forgotten
            _forgotten = ({"draw_index": int(draw_index), "attempt": attempt,' \
    "a refused policy draw is counted, not quietly discarded" \
    tests/test_randomization_policy.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '    raise RandomizationError(
        "randomization.infeasible",' \
    '    spec.__dict__.update(candidate.__dict__)  # MUTATED: the last refused draw ships
    return
    raise RandomizationError(
        "randomization.infeasible",' \
    "an exhausted slot refuses randomization.infeasible instead of shipping a refused draw" \
    tests/test_randomization_policy.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    'PLANNABLE = (Source.DEFAULT, Source.DERIVED, Source.MODEL)' \
    'PLANNABLE = (Source.DEFAULT, Source.DERIVED, Source.MODEL, Source.SAMPLED)  # MUTATED' \
    "a sampled field is never re-planned" \
    tests/test_randomization_policy.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '    if policy_q is not None and policy_q.detail.get("unmapped"):' \
    '    if False:  # MUTATED: an unmapped variation is silently defaulted' \
    "an unexpressible variation refuses randomization.vocabulary by name" \
    tests/test_randomization_prompts.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '            names = _new_violations(candidate, baseline, check_feasibility)' \
    '            names = []  # MUTATED: draws skip validate()' \
    "every policy draw goes through validate()" \
    tests/test_randomization_policy.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '        entropy=[int(draw_index), int(campaign_seed)],' \
    '        entropy=[int(campaign_seed)],  # MUTATED: every draw index is the same draw' \
    "draws are seeded per (draw index, campaign seed)" \
    tests/test_randomization_policy.py || failures=$((failures+1))

mutate core/scene/weather_visuals.py \
    '    return KOSCHMIEDER_CONSTANT / (1000.0 * v)' \
    '    return KOSCHMIEDER_CONSTANT / v  # MUTATED: per km written as per metre' \
    "the fog extinction is Koschmieder in the engine's per-metre unit" \
    tests/test_weather_visuals.py || failures=$((failures+1))

mutate core/nl/compiler.py \
    '    if re.search(VARIATION_INTENT, consumed, flags=re.IGNORECASE):' \
    '    if False:  # MUTATED: leftover variation words are ignored' \
    "the compiler records a variation the vocabulary lacks" \
    tests/test_randomization_prompts.py || failures=$((failures+1))

mutate core/nl/llm_compiler.py \
    '        problems = policy_problems({name: value})
        if problems:' \
    '        problems = []  # MUTATED: any leaf shape is accepted
        if problems:' \
    "the LLM tier refuses a policy leaf of an undocumented form" \
    tests/test_llm_compiler.py || failures=$((failures+1))

# -- Phase 2, package F review round: campaign draws, gates, coverage -----
# A campaign case folds its index into the Phase 10 streams (draw 0
# unchanged); a gate is typed and refused by name before any draw; a
# shut gate resolves a location range name and records its stream seed;
# coverage is over the requested bins (windows, integers, dates, one
# drawn value one bin); the cameras group reaches the record; a
# requested leaf nothing recorded is at coverage 0; a compass draw wraps.
mutate core/scenario/randomization.py \
    '    return f"draw {int(draw_index)}:{label}" if int(draw_index) else label' \
    '    return label  # MUTATED: every campaign case draws the single run'"'"'s day, fog and jitter' \
    "a campaign case folds its index into the Phase 10 streams" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '            if problem is not None:
                problems.append(problem)' \
    '            if False:  # MUTATED: a gate the sampler cannot judge is drawn anyway
                problems.append(problem)' \
    "a gate is typed before any draw" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '    if not _NUMBER_TEXT.match(rhs):
        raise RandomizationError(' \
    '    if False:  # MUTATED: a number is compared to a word
        raise RandomizationError(' \
    "the gate judge refuses a number against a word" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '        if op not in _WORD_OPS or _NUMBER_TEXT.match(rhs):' \
    '        if False:  # MUTATED: words are ordered as strings' \
    "the gate judge refuses an ordered or numbered word" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '                    value = _location_choices(path, [value])[0]' \
    '                    value = value  # MUTATED: the range name reaches LOCATIONS[...]' \
    "a shut gate resolves a location range name" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '                _, seed = policy_stream(seed_base, draw_index, attempt, path)' \
    '                seed = 0  # MUTATED: a gated leaf records seed 0' \
    "a shut gate records the leaf's stream seed" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '        if entry.get("kind") == "number" and entry.get("words"):
            return "windows"' \
    '        if False:  # MUTATED: window choices binned as words
            return "windows"' \
    "named hour windows are the requested bins" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '    if entry.get("kind") == "integer":
        return "integers"' \
    '    if False:  # MUTATED: a count is binned 8 ways
        return "integers"' \
    "an integer leaf has one bin per integer" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '    if isinstance(leaf, dict) and "uniform_dates" in leaf:
        return "dates"' \
    '    if False:  # MUTATED: dates are their own bins
        return "dates"' \
    "a date span is binned over the requested span" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '    if hi <= lo:
        edges = [(lo, lo)]' \
    '    if False:  # MUTATED: one value is spread over 8 bins
        edges = [(lo, lo)]' \
    "one drawn value is one bin" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '        cameras = sampled_camera_values(spec)
        if cameras:' \
    '        cameras = {}  # MUTATED: the cameras group never reaches the record
        if cameras:' \
    "the cameras group reaches the record" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '    for name in flat:
        per_leaf.setdefault(name, {})' \
    '    for name in ():  # MUTATED: an unrecorded leaf is silently absent
        per_leaf.setdefault(name, {})' \
    "a requested leaf nothing recorded is at coverage 0" \
    tests/test_randomization.py || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '        value = round(float(value) % float(period), 4)' \
    '        value = value  # MUTATED: a draw past 360 is refused, not wrapped' \
    "a circular leaf wraps instead of refusing" \
    tests/test_randomization.py || failures=$((failures+1))

# -- the NL compiler, Phase 2 review round (compiler area) ----------------
# A traffic clause fills the traffic block and a second airframe the
# compiler cannot place is reported; a bare m is metres; a conjunction
# varies every noun and an item the vocabulary cannot vary is reported;
# an unrecognised aircraft is asked about, never replaced by the default,
# and the answer compiles; the LLM tier refuses a traffic entry with no
# aircraft, more than the contract's two, or an unknown field, and a
# transport failure is named compile.unreachable and told in words.
mutate core/nl/compiler.py \
    '    traffic, text = _traffic(text)' \
    '    traffic, text = [], text  # MUTATED: the second aircraft clause is ignored' \
    "a traffic clause fills the traffic block" \
    tests/test_nl_compiler.py || failures=$((failures+1))

mutate core/nl/compiler.py \
    '    for phrase in _other_airframes(text, model):' \
    '    for phrase in []:  # MUTATED: a second airframe is dropped silently' \
    "a second airframe the compiler cannot place is reported" \
    tests/test_nl_compiler.py || failures=$((failures+1))

mutate core/nl/compiler.py \
    '(?:min|mins|minute|minutes)\b", text)' \
    '(?:m|min|mins|minute|minutes)\b", text)' \
    "a bare m is metres, never minutes" \
    tests/test_nl_compiler.py || failures=$((failures+1))

mutate core/nl/compiler.py \
    '    consumed = _expand_conjunctions(text)' \
    '    consumed = text  # MUTATED: varied weather and lighting varies the weather only' \
    "a conjunction varies every noun" \
    tests/test_nl_compiler.py || failures=$((failures+1))

mutate core/nl/compiler.py \
    '    for phrase, item in _dangling_items(text):' \
    '    for phrase, item in []:  # MUTATED: an item the vocabulary cannot vary is dropped' \
    "an item the vocabulary cannot vary is reported" \
    tests/test_nl_compiler.py || failures=$((failures+1))

mutate core/nl/compiler.py \
    '    if subject is not None and not subject[1]:' \
    '    if False:  # MUTATED: an unknown aircraft name falls through to the default' \
    "an unrecognised aircraft is never replaced by the default" \
    tests/test_nl_compiler.py || failures=$((failures+1))

mutate core/nl/compiler.py \
    '    asked = aircraft_question(text)
    if asked is not None:' \
    '    asked = None  # MUTATED: the aircraft question is never asked
    if asked is not None:' \
    "the aircraft question is asked" \
    tests/test_nl_compiler.py || failures=$((failures+1))

mutate core/nl/compiler.py \
    '    answered = _answered_aircraft(answers)
    if answered is not None:
        return answered' \
    '    if False:  # MUTATED: the aircraft answer is ignored
        return None' \
    "the aircraft answer compiles" \
    tests/test_nl_compiler.py || failures=$((failures+1))

mutate core/nl/compiler.py \
    '    ("tower camera", "tower"),' \
    '    ("tower cameraX", "tower"),  # MUTATED' \
    "tower camera names the tower view" \
    tests/test_camera_prompts.py || failures=$((failures+1))

mutate core/nl/llm_compiler.py \
    '        if "aircraft" not in block:
            raise _fail(' \
    '        if False:  # MUTATED: a traffic entry with no airframe is accepted
            raise _fail(' \
    "the LLM tier refuses a traffic entry with no aircraft" \
    tests/test_llm_compiler.py || failures=$((failures+1))

mutate core/nl/llm_compiler.py \
    '    if len(traffic) > MAX_TRAFFIC:
        raise _fail(' \
    '    if False:  # MUTATED: any number of traffic aircraft is accepted
        raise _fail(' \
    "the LLM tier caps traffic at the contract's two" \
    tests/test_llm_compiler.py || failures=$((failures+1))

mutate core/nl/llm_compiler.py \
    '            if name not in TRAFFIC_FIELD_VALUE_SCHEMAS:
                raise _fail(' \
    '            if False:  # MUTATED: unknown traffic fields are accepted
                raise _fail(' \
    "the LLM tier refuses an unknown traffic field" \
    tests/test_llm_compiler.py || failures=$((failures+1))

mutate core/nl/llm_compiler.py \
    '        raise LLMCompileError(
            UNREACHABLE_SENTENCE, constraint="compile.unreachable",
            details={"error": f"{type(exc).__name__}: {exc}"}) from exc' \
    '        raise _fail(f"API call failed ({type(exc).__name__}: {exc})") from exc  # MUTATED' \
    "a transport failure is named and told in words" \
    tests/test_llm_compiler.py || failures=$((failures+1))

# Phase 2 package A (contracts §9): the ONE render-command builder both
# the CLI and the web app draw their flags from. The -mesh= forwarding is
# the line the placeholder rule hangs on: without it the commandlet draws
# the placeholder boxes under a manifest that names the real mesh.
mutate core/render/flags.py \
    '    if mesh is not None:' \
    '    if False:  # MUTATED: the mesh is never forwarded; the placeholder boxes draw' \
    "the render builder forwards -mesh= to both callers" \
    tests/test_render_flags.py || failures=$((failures+1))

# -- Phase 2, package D: the annotation gates (contracts §4) ------------------
# One guard per clause that can fail a run; each old-string carries enough
# of its own lines to be unique in the file (mutate() replaces the FIRST
# occurrence). Each confirmed to fire by hand on landing: applied with this
# script's replacement, the test file run, the source restored
# byte-identical, __pycache__ purged (docs/PHASE2_REPORT.md, P2-D).

mutate core/capture/verify.py \
    '        out = {"name": self.name, "status": self.status, "detail": self.detail}
        if self.status == FAIL and self.failure:' \
    '        out = {"name": self.name, "status": self.status, "detail": self.detail}
        if False:  # MUTATED: a FAIL never carries its name' \
    "a failed check records its refusal name in verification.json" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        for kind, file in extra:
            counted += 1
            if not (Path(run_dir) / "frames" / camera / file).is_file():' \
    '        for kind, file in extra:
            counted += 1
            if False:  # MUTATED: a declared alone pass or .f32 need not exist' \
    "a declared alone pass or float depth file that is missing fails label_files" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if _declared_objects(manifest):
        return Check("mask_containment", NOT_RUN,' \
    '    if False:  # MUTATED: the version-5 check grades a manifest-6 run
        return Check("mask_containment", NOT_RUN,' \
    "mask_containment is superseded on a manifest that declares objects[]" \
    tests/test_camera_labels.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if _declared_objects(manifest):
        return Check("depth_range", NOT_RUN,' \
    '    if False:  # MUTATED: the version-5 check grades a manifest-6 run
        return Check("depth_range", NOT_RUN,' \
    "depth_range is superseded on a manifest that declares objects[]" \
    tests/test_camera_labels.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        if undeclared:
            return Check("mask_integers_only", FAIL,' \
    '        if False:  # MUTATED: any integer in the ID image is accepted
            return Check("mask_integers_only", FAIL,' \
    "an ID image value no object declares fails mask_integers_only" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                if disagree:
                    return Check("mask_integers_only", FAIL,' \
    '                if False:  # MUTATED: the class image is not read against the ids
                    return Check("mask_integers_only", FAIL,' \
    "a blended ID edge whose class the class image contradicts fails mask_integers_only" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        if isinstance(non_integer, (int, float)) and non_integer > 0:' \
    '        if False:  # MUTATED: the engine'"'"'s non-integer count is ignored' \
    "an engine that read non-integer ids fails mask_integers_only" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if extent > MASK_EXTENT_TOL_FRACTION and extent_px > MASK_TOL_PX:' \
    '            if False:  # MUTATED: a silhouette of any size passes' \
    "a silhouette smaller than its projected hull fails mask_vs_geometry" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                if relative > MASK_CENTROID_TOL_FRACTION and offset > MASK_TOL_PX:' \
    '                if False:  # MUTATED: a silhouette anywhere in the image passes' \
    "a mesh drawn 3 m from its label fails mask_vs_geometry" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if iou < floor:
                return Check("box_vs_mask", FAIL,' \
    '            if False:  # MUTATED: any IoU passes
                return Check("box_vs_mask", FAIL,' \
    "a tight box half its projected hull fails box_vs_mask" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                if gap > tol(z_kp):
                    return Check("depth_vs_geometry", FAIL,' \
    '                if False:  # MUTATED: the nearest keypoint does not bound the depth
                    return Check("depth_vs_geometry", FAIL,' \
    "a depth image scaled by 1.02 fails depth_vs_geometry" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if stray > VISIBILITY_TOL_FRACTION * max(n_alone, 1):' \
    '            if False:  # MUTATED: pixels outside the alone footprint pass' \
    "an id drawn outside its own alone footprint fails visibility_vs_scene" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                if n_bad > VISIBILITY_TOL_FRACTION * max(n_alone, 1):' \
    '                if False:  # MUTATED: a footprint hidden by nothing passes' \
    "an object dropped from the full pass where nothing hides it fails visibility_vs_scene" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                if wrong > VISIBILITY_TOL_FRACTION * n_overlap:' \
    '                if False:  # MUTATED: the farther object may own the overlap' \
    "the occluder hidden in the full pass fails visibility_vs_scene" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        for key, value in seen.items():
            if reference.get(key) != value:' \
    '        for key, value in seen.items():
            if False:  # MUTATED: a frame may map an id to another integer' \
    "two ids swapped in a frame's labels fail identity_stable" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            for key, value in echoed.items():
                if reference.get(key) != value:' \
    '            for key, value in echoed.items():
                if False:  # MUTATED: the engine'"'"'s echo is not read against objects[]' \
    "two ids swapped in the engine's echo fail identity_stable" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        if gap > APPLIED_FOV_TOL_DEG:' \
    '        if False:  # MUTATED: any applied field of view passes' \
    "a render at a field of view one degree off fails applied_intrinsics" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate flightsim/verify.py \
    '    named = [c for c in report.failures() if c.failure]' \
    '    named = []  # MUTATED: refusals are not printed by name' \
    "flightsim.verify prints every refusal by name" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    staged.write_text(json.dumps(report.to_dict(), indent=1), encoding="utf-8")
    os.replace(staged, path)' \
    '    path.write_text(json.dumps(report.to_dict(), indent=1), encoding="utf-8")  # MUTATED: written in place, not atomically' \
    "the verdict is written atomically (a crash mid-write leaves the previous verdict intact)" \
    tests/test_annotation_gates.py || failures=$((failures+1))

# -- Phase 2, package D review round: the verifier's own failures ---------
# A declared bundle file the disk does not hold is annotation.files on
# every check that reads it and a check that breaks is a FAIL in a
# sentence, the verdict written either way; a bad --against is a named
# FAIL; a render.json with no objects[] echo is not the engine's word; a
# null bbox, depth or visible_fraction is graded, not skipped; a rendered
# camera with no applied lens is not skipped; the origin_basis gate; the
# summary's superseded list; the cited mesh extent as the hull; and the
# annotation sheets record what they drew.
mutate core/capture/verify.py \
    '        except BundleFileError as exc:
            return Check(name, FAIL, str(exc), failure=FAIL_FILES)' \
    '        except ():  # MUTATED: a declared file the disk does not hold is a traceback
            return Check(name, FAIL, str(exc), failure=FAIL_FILES)' \
    "a missing declared bundle file is annotation.files on every check that reads it, never a traceback" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        except Exception as exc:        # noqa: BLE001 -- the verdict must be written' \
    '        except ():  # MUTATED: a check that breaks ends the verification with no verdict' \
    "a check that breaks is a FAIL in a sentence and the verdict is still written" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    other = read_manifest(other_run_dir, "against_") if other_run_dir is not None else None' \
    '    other = read_capture_manifest(Path(other_run_dir) / "capture_manifest.json") if other_run_dir is not None else None  # MUTATED: a bad --against is a traceback' \
    "a missing or unreadable --against manifest is a named FAIL check, never a traceback" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '            echoed = mapping(payload.get("objects"))
            if not echoed:' \
    '            echoed = mapping(payload.get("objects"))
            if False:  # MUTATED: a render.json with no objects[] echo counts as the engine'"'"'s word' \
    "identity_stable never counts a render.json without an objects[] echo as the engine's echo" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                if not (isinstance(recorded, (list, tuple)) and len(recorded) == 4):' \
    '                if False:  # MUTATED: a null bbox_2d_tight is skipped, not graded' \
    "box_vs_mask fails a null bbox_2d_tight where the ID image holds pixels" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                if not isinstance(value, (int, float)) or isinstance(value, bool):' \
    '                if False:  # MUTATED: a null depth record is skipped, not graded' \
    "depth_vs_geometry fails a null depth_min_m / depth_median_m under a mask with pixels" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                if (not isinstance(rec_fraction, (int, float))
                        or isinstance(rec_fraction, bool)):' \
    '                if False:  # MUTATED: a null visible_fraction is skipped, not graded' \
    "visibility_vs_scene fails a null visible_fraction under an alone pass with pixels" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '    silent = [c for c in manifest_cameras if c in rendered and c not in applied]' \
    '    silent = []  # MUTATED: a rendered camera with no applied lens is skipped silently' \
    "applied_intrinsics fails a rendered camera that recorded no applied intrinsics while another did" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        basis = drawn.get("origin_basis")
        if not (isinstance(basis, str)
                and basis.startswith(DRAWN_MESH_ORIGIN_BASIS_PREFIX)):' \
    '        basis = drawn.get("origin_basis")
        if False:  # MUTATED: a rule-placed origin passes drawn_airframe' \
    "drawn_airframe fails a mesh whose origin_basis is not measured from vertices" \
    tests/test_camera_verify_corruption.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '        superseded = [c.name for c in self.checks if is_superseded(c)]' \
    '        superseded = []  # MUTATED: superseded checks are listed as waiting for evidence' \
    "the summary lists superseded checks apart from those waiting for evidence" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                if (isinstance(version, (int, float)) and version >= 3
                        and origin and all(k in extent for k in "xyz")):' \
    '                if False:  # MUTATED: the cited mesh extent is never the hull' \
    "the hull is the cited mesh manifest's measured extent when that file is on this machine" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate tests/visual/annotation_sheets.py \
    '            drawn, error = False, f"{exc.__class__.__name__}: {exc}"' \
    '            drawn, error = True, None  # MUTATED: an undrawn sheet is recorded as drawn' \
    "a sheet whose painter threw is recorded as not drawn" \
    tests/test_annotation_gates.py || failures=$((failures+1))

mutate tests/visual/annotation_sheets.py \
    '            draw.wire(pen, corners, draw.YELLOW)' \
    '            pass  # MUTATED: the projected hull is never drawn' \
    "mask_vs_geometry.png shows the projected hull" \
    tests/test_annotation_gates.py || failures=$((failures+1))

# Phase 2 package G (contracts §6.1): the campaign. Four guards, each
# the plan's own rubric line: never done below target; seeds derived
# from the slot INDEX (the exit criterion -- mutate to completion order
# and the 1-vs-2-worker ledgers diverge); the disk budget refused by
# name; progress read from the ledger, never from memory.
mutate core/campaign/campaign.py \
    '            if verified >= self.target:' \
    '            if True:  # MUTATED: done regardless of the yield' \
    "a campaign is never done below its target" \
    tests/test_campaign.py || failures=$((failures+1))

mutate core/campaign/workers.py \
    '        spec, seed = build_case(index, record)' \
    '        spec, seed = build_case(len(os.listdir(os.path.join(out_dir, RUNS_DIR))), record)  # MUTATED: seeded by completion order' \
    "campaign seeds derive from the slot index, not completion order" \
    tests/test_campaign.py || failures=$((failures+1))

mutate core/campaign/campaign.py \
    '        if picture["within_budget"] is False:' \
    '        if False:  # MUTATED: the disk budget is never enforced' \
    "the disk budget is refused storage.budget_exceeded by name" \
    tests/test_campaign.py || failures=$((failures+1))

mutate core/campaign/campaign.py \
    '        summary = summarise(self.ledger.rows())   # the ledger, never a counter' \
    '        summary = summarise([])   # MUTATED: nothing read from the ledger' \
    "campaign progress is computed from the ledger" \
    tests/test_campaign.py || failures=$((failures+1))

# Package G review round: a duplicate slot is refused by index before
# dispatch (the ledger is the same at any worker count), and a refused
# slot's draws name the constraint they hit.
mutate core/campaign/campaign.py \
    '            seen_case_ids[case_id] = min(index, seen_case_ids.get(case_id, index))' \
    '            pass  # MUTATED: nothing claimed by index; the first slot to return keeps the spec' \
    "a duplicate slot is refused by index, never by completion order (the ledger is the same at any worker count)" \
    tests/test_campaign.py || failures=$((failures+1))

mutate core/campaign/ledger.py \
    '                if name:' \
    '                if False:  # MUTATED: the refused slots'"'"' draws are never named' \
    "a refused slot's draws name the constraint they hit in the campaign's totals and the unreachable message" \
    tests/test_campaign.py || failures=$((failures+1))

# -- Phase 2, package I part 2: the guided page (contracts §8) ----------------
# The catalogue-only rule: the page's default fields carry the catalogue's
# sentence and the rule name lives under details (mutate the one place a
# refusal is put into words to emit the raw name); progress is read from
# the ledger file on every call, never from memory (mutate the read away
# and a ledger the test wrote by hand is no longer reported).
mutate webapp/generate.py \
    '        sentence = explained["sentence"]        # the catalogue sentence, never the name' \
    '        sentence = rule  # MUTATED: the raw rule name in the default field' \
    "the guided page renders a refusal as the catalogue sentence, never the raw rule name" \
    tests/test_webapp_generate.py || failures=$((failures+1))

mutate webapp/generate.py \
    '        rows = campaign.ledger.rows()        # the ledger file, never a counter' \
    '        rows = []  # MUTATED: nothing read from the ledger' \
    "the guided page reports progress from the ledger" \
    tests/test_webapp_generate.py || failures=$((failures+1))

# Package I part 2 review round: the capture log is read by the name the
# catalogue keeps (the catalogue, not the regex, decides what is a name);
# an uncatalogued reason never reaches the sentence; the paragraph says a
# mountain word raised the datum; the page prints no exception text.
mutate webapp/generate.py \
    '_LOG_REFUSED = re.compile(r"^REFUSED\s*--\s*([a-z_]+(?:\.[a-z_]+)*)\s*:\s*(.*)$")' \
    '_LOG_REFUSED = re.compile(r"^REFUSED\s*--\s*([a-z_]+(?:\.[a-z_]+)+)\s*:\s*(.*)$")  # MUTATED' \
    "a bare catalogued name in the capture log is read" \
    tests/test_webapp_generate.py -k bare_catalogued_name || failures=$((failures+1))

mutate webapp/generate.py \
    '        if match and (is_catalogued(match.group(1)) or "." in match.group(1)):' \
    '        if match:  # MUTATED: the regex shape decides' \
    "the catalogue, not the regex, decides what is a name" \
    tests/test_webapp_generate.py -k bare_catalogued_name || failures=$((failures+1))

mutate webapp/generate.py \
    '    return {"sentence": explained["sentence"], "hint": explained["hint"],' \
    '    return {"sentence": str(reason), "hint": explained["hint"],  # MUTATED' \
    "an uncatalogued reason never reaches the sentence" \
    tests/test_webapp_generate.py -k uncatalogued_reason || failures=$((failures+1))

mutate webapp/generate.py \
    '    elif datum > 0:' \
    '    elif False:  # MUTATED: the raised datum is not said' \
    "the paragraph says a mountain word raised the datum" \
    tests/test_webapp_generate.py -k mountain_prompt_really || failures=$((failures+1))

mutate webapp/static/generate.html \
    'refusalHtml(p.thread_error_words)' \
    '`<p>${esc(p.thread_error)}</p>`' \
    "the page never prints an exception's text on the default path" \
    tests/test_webapp_generate.py -k interpolates_no_code_identifier || failures=$((failures+1))

# Phase 2 package H (contracts §7): the agent's authority. One guard per
# rule, each the plan's own rubric line: a stated field is never moved
# (mutate the comparison away and the rogue's doctored spec validates);
# run/render/export need the token validate() minted for THIS digest
# (mutate the match away and a forged or foreign token runs a case); a
# spec carrying a refusal is not run (mutate the check away and the
# unflyable campaign runs on a forged token); the call budget ends the
# loop (mutate it away and the fourth call goes through); the token is
# minted only for a spec with no refusal (mutate and the refused spec
# gets one); every denial is written to the trace (mutate the write
# away and the rogue's denials vanish from trace.jsonl).
mutate core/agent/policy.py \
    '        moves = stated_moves(self.reference, candidate, allow_new=allow_new)
        if moves:' \
    '        moves = stated_moves(self.reference, candidate, allow_new=allow_new)
        if False:  # MUTATED: a stated field may move' \
    "authority.stated_field: a user/inferred/sampled field is never moved by a tool input" \
    tests/test_agent.py || failures=$((failures+1))

mutate core/agent/policy.py \
    '        if spec_digest is None or token != expected_token(spec_digest):' \
    '        if False:  # MUTATED: any token matches' \
    "authority.validation_token: run/render/export need the token minted for this digest" \
    tests/test_agent.py || failures=$((failures+1))

mutate core/agent/policy.py \
    '        kept = self.refused.get(str(spec_digest)) if spec_digest else None
        if kept:' \
    '        kept = self.refused.get(str(spec_digest)) if spec_digest else None
        if False:  # MUTATED: a refused spec runs' \
    "authority.refusal_is_not_a_run: a spec carrying a refusal is denied for run" \
    tests/test_agent.py || failures=$((failures+1))

mutate core/agent/policy.py \
    '        if self.calls > int(self.budget.max_calls):' \
    '        if False:  # MUTATED: no call budget' \
    "authority.budget: the tool-call allowance ends the loop" \
    tests/test_agent.py || failures=$((failures+1))

mutate core/agent/tools.py \
    '        if not refusals:
            token = mint_token(digest)' \
    '        if True:  # MUTATED: a refused spec is given a token
            token = mint_token(digest)' \
    "the validation token is minted only for a spec with no refusal" \
    tests/test_agent.py || failures=$((failures+1))

mutate core/agent/tools.py \
    '        output = denial.as_output()
        self.trace.record(tool, kwargs, output, reason,' \
    '        output = denial.as_output()
        if False: self.trace.record(tool, kwargs, output, reason,  # MUTATED: a denial leaves no trace' \
    "every policy denial is a line of trace.jsonl" \
    tests/test_agent.py || failures=$((failures+1))

# -- the advancement additions, batch 1 part 1: geoid, limits, instruments, modes, DIS ----
mutate core/terrain/geoid.py \
    '    if expected_sha256 is not None and digest != expected_sha256:' \
    '    if False and expected_sha256 is not None and digest != expected_sha256:  # MUTATED: any grid passes' \
    "a geoid grid with the wrong sha256 is refused by name" tests/test_geoid.py \
    || failures=$((failures+1))

mutate core/terrain/geoid.py \
    '        dy = fy - iy
        dx = fx - ix' \
    '        dy = float(round(fy - iy))  # MUTATED: nearest neighbour
        dx = float(round(fx - ix))' \
    "the geoid undulation is bilinear, not nearest-neighbour" tests/test_geoid.py \
    || failures=$((failures+1))

mutate core/terrain/geoid.py \
    'with_value=float(n), without_value=0.0,' \
    'with_value=float(n), without_value=float(n),  # MUTATED: the null test measures nothing' \
    "the undulation record's null test compares N against 0" tests/test_geoid.py \
    || failures=$((failures+1))

mutate core/terrain/geoid.py \
    '        "undulation_m": None,' \
    '        "undulation_m": 0.0,  # MUTATED: absence recorded as zero' \
    "a flat or synthesised scene records the undulation as null, never zero" tests/test_geoid.py \
    || failures=$((failures+1))

mutate core/terrain/glo30.py \
    '    baked.provenance["datum"] = datum_for_heightfield(baked)' \
    '    pass  # MUTATED: the sidecar carries no datum block' \
    "the bake sidecar carries the datum block" tests/test_geoid.py \
    || failures=$((failures+1))

mutate core/capture/manifest.py \
    '        "datum": datum,' \
    '        "datum": None,  # MUTATED: the manifest carries no datum block' \
    "the capture manifest carries the datum block" tests/test_geoid.py \
    || failures=$((failures+1))

mutate core/scenario/card.py \
    '        card["datum"] = dict(datum)' \
    '        pass  # MUTATED: the card drops the datum' \
    "the run card carries the datum block" tests/test_geoid.py \
    || failures=$((failures+1))

mutate core/telemetry/limits.py \
    '        return 1 if value > limit else 0' \
    '        return 1 if value >= limit else 0  # MUTATED: a sample AT the limit is flagged' \
    "limits.monitor: the comparison is strict -- at a positive limit is not beyond it" \
    tests/test_limits.py || failures=$((failures+1))

mutate core/telemetry/limits.py \
    '    return 1 if value < limit else 0' \
    '    return 1 if value <= limit else 0  # MUTATED: a sample AT the negative limit is flagged' \
    "limits.monitor: the comparison is strict -- at a negative limit is not beyond it" \
    tests/test_limits.py || failures=$((failures+1))

mutate core/telemetry/limits.py \
    '        count = int(sum(flags))' \
    '        count = 0  # MUTATED: the per-limit summary never counts' \
    "limits.monitor: the per-limit count is the number of flagged samples" \
    tests/test_limits.py || failures=$((failures+1))

mutate core/telemetry/limits.py \
    '    any_count = int(sum(any_flags))' \
    '    any_count = 0  # MUTATED: any_exceedance never counts' \
    "limits.monitor: the any_exceedance count is the number of flagged samples" \
    tests/test_limits.py || failures=$((failures+1))

mutate core/telemetry/limits.py \
    '    constraint = "limits.config"' \
    '    constraint = "limits.misconfigured"  # MUTATED: the refusal loses its name' \
    "limits.config: a malformed limits table refuses by that name" \
    tests/test_limits.py || failures=$((failures+1))

mutate core/telemetry/limits.py \
    '    if unknown:
        raise refuse(f"unknown keys {unknown}; a limits block carries "' \
    '    if False:  # MUTATED: an unknown key is ignored, so a misspelt limit is never monitored
        raise refuse(f"unknown keys {unknown}; a limits block carries "' \
    "limits.config: an unknown key in the limits block is refused, not ignored" \
    tests/test_limits.py || failures=$((failures+1))

mutate core/telemetry/limits.py \
    '    if not isinstance(config, dict) or "limits" not in config:
        return None' \
    '    if not isinstance(config, dict) or "limits" not in config:
        raise LimitsConfigError(aircraft, "no limits block")  # MUTATED: an airframe without a table refuses' \
    "limits: an airframe without a limits block is recorded unmonitored and never refuses" \
    tests/test_limits.py || failures=$((failures+1))

mutate core/scenario/runner.py \
    '    if limits_record is not None:
        attach_record(manifest, limits_record)' \
    '    if False:  # MUTATED: the limits.monitor record is never attached
        attach_record(manifest, limits_record)' \
    "limits.monitor: the AppliedVariable record is attached to the run manifest" \
    tests/test_limits.py || failures=$((failures+1))

mutate core/scenario/runner.py \
    '        "limits": limits_block,' \
    '        "limits": None,  # MUTATED: the manifest carries no limits block' \
    "limits: the run manifest carries the limits block (table and summary)" \
    tests/test_limits.py || failures=$((failures+1))

mutate core/scenario/runner.py \
    '    limits_block, limits_record = monitor_run(recorder, str(spec.aircraft.value))' \
    '    limits_block, limits_record = monitor_run(recorder, str(spec.aircraft.value))
    output_digest = _digest_telemetry(recorder)  # MUTATED: the digest is taken after the flags are added' \
    "limits: output_digest covers the recorded telemetry, taken before the monitor annotates" \
    tests/test_limits.py || failures=$((failures+1))

mutate core/telemetry/recorder.py \
    '        if len(values) != len(self):
            raise ValueError(f"annotation {name!r} has {len(values)} values for "' \
    '        if False:  # MUTATED: an annotation of the wrong length is accepted
            raise ValueError(f"annotation {name!r} has {len(values)} values for "' \
    "recorder.annotate: a derived column must have one value per sample" \
    tests/test_limits.py || failures=$((failures+1))

mutate core/telemetry/instruments.py \
    '    rng = generator(int(seed), "imu", int(replicate))' \
    '    rng = generator(int(seed), "gps", int(replicate))  # MUTATED: the IMU borrows the GPS stream' \
    "instruments: each instrument draws from its own named seed stream" tests/test_instruments.py || failures=$((failures+1))

mutate core/telemetry/instruments.py \
    '        [cp * sy, sr * sp * sy + cr * cy, cr * sp * sy - sr * cy],' \
    '        [cp * sy, sr * sp * sy + cr * cy, cr * sp * sy + sr * cy],  # MUTATED: one sign of the rotation' \
    "instruments: the GPS lever arm is rotated by the attitude" tests/test_instruments.py || failures=$((failures+1))

mutate core/telemetry/instruments.py \
    '        if t[i] >= next_fix - 1e-9:' \
    '        if True:  # MUTATED: a fix every sample, no hold' \
    "instruments: the GPS holds the last fix between fixes" tests/test_instruments.py || failures=$((failures+1))

mutate core/telemetry/instruments.py \
    '    alpha = dt / (tau_s + dt)' \
    '    alpha = 1.0  # MUTATED: no lag' \
    "instruments: the pitot-static lag is the stated first-order filter" tests/test_instruments.py || failures=$((failures+1))

mutate core/telemetry/instruments.py \
    '    if result.data is None:
        return None' \
    '    if False:  # MUTATED: the ideal profile writes a file
        return None' \
    "instruments: the ideal profile writes nothing" tests/test_instruments.py || failures=$((failures+1))

mutate core/telemetry/instruments_check.py \
    'SIGMA_FACTOR = 1.5' \
    'SIGMA_FACTOR = 3.0  # MUTATED: the band swallows a doubled noise' \
    "instruments check: the residual band refuses a doubled noise" tests/test_instruments.py || failures=$((failures+1))

mutate core/telemetry/instruments_check.py \
    '        if list(columns[name]) != list(truth_columns[name]):' \
    '        if False:  # MUTATED: the truth beside the measurement is not compared' \
    "instruments check: the truth beside the measurement is the recorder's" tests/test_instruments.py || failures=$((failures+1))

mutate core/telemetry/instruments_check.py \
    '                if not math.isfinite(drawn) or abs(drawn) > BIAS_SIGMAS * rep + 1e-12:' \
    '                if False:  # MUTATED: any drawn bias is accepted' \
    "instruments check: a drawn bias lies within the stated repeatability" tests/test_instruments.py || failures=$((failures+1))

mutate core/telemetry/instruments_check.py \
    '            or record["null_test"].get("ok") is not True:' \
    '            or False:  # MUTATED: a null test that measured nothing passes' \
    "instruments check: the record's null test measured a difference" tests/test_instruments.py || failures=$((failures+1))

mutate core/experiments/seeds.py \
    '    "imu",' \
    '    # MUTATED: no imu stream' \
    "seeds: the instrument streams are declared" tests/test_instruments.py || failures=$((failures+1))

mutate flightsim/capture.py \
    '    write_measured(measured, out)' \
    '    pass  # MUTATED: the measured file is not written' \
    "capture: --instruments writes telemetry_measured.json" tests/test_instruments.py || failures=$((failures+1))

mutate core/fdm/linearize.py \
    '        J[:, j] = (f_plus - f_minus) / (2.0 * step)' \
    '        J[:, j] = (f_plus - f_minus) / step  # MUTATED: the central difference divided by the step, not twice it' \
    "modes.residual: the finite-difference Jacobian divides by twice the step" \
    tests/test_modes.py || failures=$((failures+1))

mutate core/fdm/linearize.py \
    'RESIDUAL_STEP = 1e-4' \
    'RESIDUAL_STEP = 1e-1  # MUTATED: a perturbation of 0.1 rad / 0.1 ft/s straddles the tables' \
    "modes.residual: the independent perturbation is 1e-4 in each state's own unit" \
    tests/test_modes.py || failures=$((failures+1))

mutate core/fdm/modes.py \
    '    pairs = sorted((e for e in eigenvalues if e.imag > tol), key=lambda e: -abs(e))' \
    '    pairs = sorted((e for e in eigenvalues if e.imag > tol), key=lambda e: abs(e))  # MUTATED: the slower pair is named first' \
    "the short period is the faster longitudinal pair, the Dutch roll the faster lateral pair" \
    tests/test_modes.py || failures=$((failures+1))

mutate core/fdm/modes.py \
    '            "B": {1: (0.30, 2.00), 2: (0.20, 2.00), 3: (0.15, math.inf)},' \
    '            "B": {1: (0.70, 2.00), 2: (0.20, 2.00), 3: (0.15, math.inf)},  # MUTATED: Level 1 floor raised' \
    "MIL-F-8785C Table IV: Category B Level 1 short-period damping is 0.30 to 2.00" \
    tests/test_modes.py || failures=$((failures+1))

mutate core/fdm/linearize.py \
    '    if not residual.ok:' \
    '    if False:  # MUTATED: a residual beyond the bound is not refused' \
    "modes.residual: a Jacobian residual beyond the bound is refused by name" \
    tests/test_modes.py || failures=$((failures+1))

mutate core/fdm/linearize.py \
    '    if not getattr(fdm, "is_trimmed", False):' \
    '    if False:  # MUTATED: an untrimmed state is linearised' \
    "modes.untrimmed: only a trimmed FDM is linearised" \
    tests/test_modes.py || failures=$((failures+1))

mutate core/fdm/modes.py \
    '    entry = AIRFRAME_CLASS.get(str(aircraft))
    if entry is None:' \
    '    entry = AIRFRAME_CLASS.get(str(aircraft))
    if False:  # MUTATED: an airframe without a class is graded' \
    "modes.airframe_class: an airframe with no stated class is refused, not guessed" \
    tests/test_modes.py || failures=$((failures+1))

mutate core/interop/dis.py \
    '"fff" "ddd" "fff"' \
    '"ddd" "fff" "fff"' \
    "DIS byte layout: velocity and location swapped" tests/test_dis.py || failures=$((failures+1))

mutate core/interop/dis.py \
    'h_ellipsoidal_m = altitude_m + undulation_m' \
    'h_ellipsoidal_m = altitude_m + 0.0 * undulation_m' \
    "DIS ellipsoidal height (+N)" tests/test_dis.py || failures=$((failures+1))

mutate core/interop/dis.py \
    'if isinstance(n, (int, float)) and not isinstance(n, bool):' \
    'if False:' \
    "DIS datum block undulation read" tests/test_dis.py || failures=$((failures+1))

mutate core/interop/geodesy.py \
    'psi = math.atan2(r[0][1], r[0][0])' \
    'psi = math.atan2(r[1][0], r[0][0])' \
    "DIS Euler convention: psi off the matrix" tests/test_dis.py || failures=$((failures+1))

mutate core/interop/geodesy.py \
    'return matmul(rot_x(phi_rad), matmul(rot_y(theta_rad), rot_z(psi_rad)))' \
    'return matmul(rot_z(psi_rad), matmul(rot_y(theta_rad), rot_x(phi_rad)))' \
    "DIS Euler convention: rotation order" tests/test_dis.py || failures=$((failures+1))

mutate core/interop/dis.py \
    'TIMESTAMP_UNITS_PER_HOUR = 2 ** 31' \
    'TIMESTAMP_UNITS_PER_HOUR = 2 ** 32' \
    "DIS timestamp units" tests/test_dis.py || failures=$((failures+1))

mutate core/interop/geodesy.py \
    'z = (n * (1.0 - WGS84_E2) + h_m) * math.sin(lat)' \
    'z = (n + h_m) * math.sin(lat)' \
    "WGS 84 ECEF flattening" tests/test_dis.py || failures=$((failures+1))

mutate core/interop/dis.py \
    'if version != PROTOCOL_VERSION or pdu_type != PDU_TYPE_ENTITY_STATE:' \
    'if False:' \
    "DIS PDU version and type refusal" tests/test_dis.py || failures=$((failures+1))

# -- the advancement additions, batch 1 part 2: passes, land cover, the held verifier guards ----
mutate core/capture/labels.py \
    '    return (stored - NORMAL_ENCODE_OFFSET) / NORMAL_ENCODE_SCALE' \
    '    return stored / NORMAL_ENCODE_SCALE  # MUTATED: no 0.5 offset' \
    "the normal reader undoes the 0.5 offset" \
    tests/test_annotation_passes.py || failures=$((failures+1))

mutate ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp \
    'constexpr float RenderPassNormalEncodeOffset = 0.5f;' \
    'constexpr float RenderPassNormalEncodeOffset = 0.0f;' \
    "the commandlet encodes normals with the 0.5 offset the reader undoes" \
    tests/test_gate6_visual.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                du_pred = p_now[0] - p_prev[0]' \
    '                du_pred = p_prev[0] - p_now[0]  # MUTATED: flow sign' \
    "the flow is graded as previous-to-current, not the reverse" \
    tests/test_annotation_passes.py || failures=$((failures+1))

mutate ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp \
    'const float DyPx = -NdcY * 0.5f * Height;' \
    'const float DyPx = NdcY * 0.5f * Height;' \
    "the flow's dy is screen-down (clip y is up)" \
    tests/test_gate6_visual.py || failures=$((failures+1))

mutate core/capture/verify.py \
    'NORMAL_ANGLE_TOL_DEG = 10.0' \
    'NORMAL_ANGLE_TOL_DEG = 1000.0' \
    "a normal image 30 deg off the depth fails normals_vs_depth" \
    tests/test_annotation_passes.py || failures=$((failures+1))

mutate core/capture/verify.py \
    'FLOW_TOL_PX = 2.0' \
    'FLOW_TOL_PX = 1000.0' \
    "a flow scaled by two fails flow_vs_motion" \
    tests/test_annotation_passes.py || failures=$((failures+1))

mutate core/capture/verify.py \
    'ALBEDO_MIN_DIFFERENT_FRACTION = 0.01' \
    'ALBEDO_MIN_DIFFERENT_FRACTION = 0.0' \
    "an albedo that is the beauty picture fails albedo_range" \
    tests/test_annotation_passes.py || failures=$((failures+1))

mutate core/capture/verify.py \
    '                if np.any(flow != 0.0):' \
    '                if False:  # MUTATED: any first frame passes' \
    "a first flow frame that is not zeros fails" \
    tests/test_annotation_passes.py || failures=$((failures+1))

mutate core/capture/verify.py \
    'FAIL_FLOW = "annotation.flow"' \
    'FAIL_FLOW = "annotation.flows"' \
    "a failed flow check carries its catalogue name" \
    tests/test_annotation_passes.py || failures=$((failures+1))

mutate ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp \
    'TEXT("labels.pass_material: -passes=%s needs the post-process material ")' \
    'TEXT("labels.pass_materials: -passes=%s needs the post-process material ")' \
    "a missing pass material refuses by its catalogue name" \
    tests/test_gate6_visual.py || failures=$((failures+1))

mutate core/render/flags.py \
    '    if pass_token is not None and pass_token not in flags:' \
    '    if False:  # MUTATED: -passes= never emitted' \
    "the builder emits -passes= when asked" \
    tests/test_annotation_passes.py || failures=$((failures+1))

mutate core/capture/labels.py \
    '    if pass_words_seen:' \
    '    if False:  # MUTATED: no passes record' \
    "attach records the render.passes applied variable" \
    tests/test_annotation_passes.py || failures=$((failures+1))

mutate experiments/gate6_visual.py \
    '    if control < LOOK_THRESHOLDS["albedo_control_min_changed_px"]:' \
    '    if False:  # MUTATED: no control' \
    "the albedo clause is vacuous when the sun moved no beauty pixel" \
    tests/test_gate6_visual.py || failures=$((failures+1))

mutate ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp \
    'PassVelocity->bAlwaysPersistRenderingState = true;' \
    'PassVelocity->bAlwaysPersistRenderingState = false;' \
    "the velocity capture keeps its view state" \
    tests/test_gate6_visual.py || failures=$((failures+1))

mutate core/terrain/landcover.py \
    '    raw = stack * 255.0 / float(k * k)' \
    '    raw = stack * 255.0 / float(k)  # MUTATED: fraction over k, not k^2' \
    "weights are 255 times the fraction of k^2 fine cells" tests/test_landcover.py \
    || failures=$((failures+1))

mutate core/terrain/landcover.py \
    '    extra = (rank < remainder[None, :, :]).astype(np.float64)' \
    '    extra = np.zeros_like(base)  # MUTATED: remainders never distributed' \
    "largest-remainder rounding sums to exactly 255" tests/test_landcover.py \
    || failures=$((failures+1))

mutate core/terrain/landcover.py \
    '        "sha256": provenance["sha256"],' \
    '        "sha256": None,  # MUTATED: source digest not recorded' \
    "landcover.json records the source sha256" tests/test_landcover.py \
    || failures=$((failures+1))

mutate core/terrain/landcover.py \
    '    constraint = "terrain.landcover"' \
    '    constraint = "terrain.land_cover"  # MUTATED: refusal renamed' \
    "a bad land cover source refuses terrain.landcover by name" tests/test_landcover.py \
    || failures=$((failures+1))

mutate core/terrain/landcover.py \
    '    constraint = "terrain.landcover_grid"' \
    '    constraint = "terrain.land_cover_grid"  # MUTATED: refusal renamed' \
    "a bake without a grid refuses terrain.landcover_grid by name" tests/test_landcover.py \
    || failures=$((failures+1))

mutate core/terrain/landcover.py \
    '    "(c) ESA WorldCover project 2021 / Contains modified Copernicus "' \
    '    "(c) a land cover product / Contains modified Copernicus "  # MUTATED' \
    "the CC BY 4.0 attribution line is the manual's" tests/test_landcover.py \
    || failures=$((failures+1))

mutate core/terrain/landcover.py \
    '    report["ok"] = bool(compared >= samples * 0.9
                        and report["agreement"] >= VERIFY_MIN_AGREEMENT)' \
    '    report["ok"] = True  # MUTATED: every rasterisation verifies' \
    "rasterised classes must agree with the source window" tests/test_landcover.py \
    || failures=$((failures+1))

mutate core/terrain/landcover.py \
    'without_value=prior,' \
    'without_value=float(legend[dominant]),  # MUTATED: null test against itself' \
    "the land cover null test compares against the uniform prior" tests/test_landcover.py \
    || failures=$((failures+1))

mutate core/capture/verify.py \
    'DATUM_TOL_M = 0.01' \
    'DATUM_TOL_M = 1e9  # MUTATED: any undulation agrees' \
    "the verifier holds the manifest undulation to 0.01 m of its own read" tests/test_geoid.py \
    || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if recorded != digest:' \
    '    if False and recorded != digest:  # MUTATED: any grid is the same grid' \
    "the verifier refuses an undulation from a grid other than its own" tests/test_geoid.py \
    || failures=$((failures+1))

# -- the advancement additions, wave 1: record 2 and the registry (R1), the non-standard atmosphere (P1) ----
mutate core/records.py \
    '        return abs(self.difference) <= allowed' \
    '        return True  # MUTATED: every readback agrees' \
    "a readback is graded against its tolerance" tests/test_records.py \
    || failures=$((failures+1))

mutate core/records.py \
    '            allowed = allowed * abs(float(self.written))' \
    '            allowed = allowed * 1e9  # MUTATED: relative means anything' \
    "a relative readback tolerance scales by the written value" tests/test_records.py \
    || failures=$((failures+1))

mutate core/records.py \
    '            return abs(self.difference) <= float(self.threshold)' \
    '            return abs(self.difference) >= float(self.threshold)  # MUTATED: bounded reads as reached' \
    "the bounded null test is ok only at or under its bound" tests/test_records.py \
    || failures=$((failures+1))

mutate core/record_null.py \
    'NULL_FLOOR_ALTITUDE_M = 0.5' \
    'NULL_FLOOR_ALTITUDE_M = 0.0  # MUTATED: any altitude effect counts' \
    "the altitude null floor is 10 x the V9 noise" tests/test_record_null.py \
    || failures=$((failures+1))

mutate core/record_null.py \
    '    if applied == entry.null_value:' \
    '    if False:  # MUTATED: a run may be paired with itself' \
    "a null pair refuses the value that is already the null" tests/test_record_null.py \
    || failures=$((failures+1))

mutate core/capture/manifest.py \
    '("_kgm3", "kg/m^3"), ("_kgm2", "kg m^2"), ("_mps2", "m/s^2"), ("_rads", "rad/s"),' \
    '("_kgm3", "kg/m^3"), ("_kgm2", "kg m^2"), ("_mps2", "m/s"), ("_rads", "rad/s"),  # MUTATED: specific force in m/s' \
    "the m/s^2 suffix reads as m/s^2, not m/s" tests/test_registry.py \
    || failures=$((failures+1))

mutate core/capture/manifest.py \
    '    registered = _registered_channel_units().get(name)' \
    '    registered = None  # MUTATED: the registry is never consulted' \
    "state_units consults the registry before the suffix table" tests/test_registry.py \
    || failures=$((failures+1))

mutate core/registry.py \
    '                if f"{section}.{leaf}" not in claimed:' \
    '                if False:  # MUTATED: every spec field is registered' \
    "a spec field outside the registry refuses record.unregistered" tests/test_registry.py \
    || failures=$((failures+1))

mutate core/registry.py \
    '            raise RecordError("record.unregistered",
                              f"{name!r} is not a registered variable (registered: "
                              f"{'"'"', '"'"'.join(self.names())})") from None' \
    '            return next(iter(self._entries.values()))  # MUTATED: an unknown name gets the first entry' \
    "an unknown variable name refuses record.unregistered" tests/test_registry.py \
    || failures=$((failures+1))

mutate core/registry.py \
    '            if suffix != "?" and suffix != channel.unit:' \
    '            if False:  # MUTATED: a unit may contradict its name' \
    "an effect channel unit that contradicts its name refuses" tests/test_registry.py \
    || failures=$((failures+1))

mutate core/uncertainty.py \
    '    e = abs(float(difference)) / (ratio ** p - 1.0)' \
    '    e = abs(float(difference))  # MUTATED: no Richardson denominator' \
    "u_num divides the twin difference by 2^p - 1" tests/test_uncertainty.py \
    || failures=$((failures+1))

mutate core/uncertainty.py \
    '    return {"error_estimate": e, "gci": fs * e}' \
    '    return {"error_estimate": e, "gci": e}  # MUTATED: no safety factor' \
    "u_num carries the GCI safety factor" tests/test_uncertainty.py \
    || failures=$((failures+1))

mutate core/environment/atmosphere.py \
    '    if temperature_deviation_c is not None and not lo <= temperature_deviation_c <= hi:' \
    '    if False and temperature_deviation_c is not None and not lo <= temperature_deviation_c <= hi:  # MUTATED: any deviation passes' \
    "atmosphere: a temperature deviation outside -60..+45 degC is refused by name" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/environment/atmosphere.py \
    '    if sea_level_pressure_hpa is not None and not lo <= sea_level_pressure_hpa <= hi:' \
    '    if False and sea_level_pressure_hpa is not None and not lo <= sea_level_pressure_hpa <= hi:  # MUTATED: any pressure passes' \
    "atmosphere: a sea-level pressure outside 870..1085 hPa is refused by name" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/environment/atmosphere.py \
    '    if dew_point_c is not None and relative_humidity_pct is not None:' \
    '    if False and dew_point_c is not None and relative_humidity_pct is not None:  # MUTATED: both humidity fields accepted' \
    "atmosphere: a dew point and a relative humidity together are refused by name" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/environment/atmosphere.py \
    '    if celsius_to_rankine(dew_point_c) > t_scene_r:' \
    '    if False and celsius_to_rankine(dew_point_c) > t_scene_r:  # MUTATED: JSBSim'"'"'s silent cap is reached' \
    "atmosphere: a dew point above the scene temperature is refused by name, not capped by JSBSim" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/environment/atmosphere.py \
    '    if e < p_scene and vapour_mass_fraction(e, p_scene) > cap:' \
    '    if False and e < p_scene and vapour_mass_fraction(e, p_scene) > cap:  # MUTATED: the vapour cap is reached silently' \
    "atmosphere: a dew point beyond the model's vapour cap is refused by name" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/environment/atmosphere.py \
    '    if word in DAY_WORDS:
        return None' \
    '    if True:  # MUTATED: any day word passes
        return None' \
    "atmosphere: a MIL-HDBK-310 profile or an unknown day word is refused by name" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/scenario/runner.py \
    '    environment.prepare(fdm)
' \
    '    pass  # MUTATED: the atmosphere is written only after the trim
' \
    "atmosphere: the day is written BEFORE the trim (the trimmed throttle differs)" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/environment/stack.py \
    '                observe(fdm)' \
    '                pass  # MUTATED: nothing is read back per step' \
    "atmosphere: every step's write is read back before the next" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/environment/stack.py \
    '            writes.update(provider.properties(position, time_s))' \
    '            pass  # MUTATED: the atmosphere is not written per step' \
    "atmosphere: the day is written every step" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/environment/atmosphere.py \
    '        "sigma": rho / (P_SL_PSF / (R_DRY * T_SL_R)),' \
    '        "sigma": 1.01 * rho / (P_SL_PSF / (R_DRY * T_SL_R)),  # MUTATED: the predicted ratio is 1 % off' \
    "atmosphere: expected_density_ratio is the delivered density over the ISA sea-level density" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/environment/atmosphere.py \
    '    return (fraction * R_WATER + R_DRY) / (1.0 + fraction)' \
    '    return R_DRY  # MUTATED: the dry gas constant, water ignored' \
    "atmosphere: the closed form carries the moist gas constant" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/environment/atmosphere.py \
    '                unit="kg/m3", with_value=with_, without_value=without,' \
    '                unit="kg/m3", with_value=with_, without_value=with_,  # MUTATED: the null test measures nothing' \
    "atmosphere: each variable's null test is the density before against after its write" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/environment/atmosphere.py \
    'CARD_KEYS = (PROPERTY_DELTA_T, PROPERTY_P_SL, PROPERTY_DEW_POINT,' \
    'CARD_KEYS = (PROPERTY_P_SL, PROPERTY_DELTA_T, PROPERTY_DEW_POINT,  # MUTATED: the key order moved' \
    "atmosphere: the card block's keys are in the fixed order" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/scenario/card.py \
    '        card["atmosphere_properties"] = atmosphere' \
    '        pass  # MUTATED: the card drops the atmosphere' \
    "atmosphere: the run card carries the atmosphere_properties block" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/scenario/spec.py \
    '        if not self.atmosphere.is_default():
            out["atmosphere"] = self.atmosphere.to_dict()' \
    '        if True:  # MUTATED: the default block is serialised and every digest moves
            out["atmosphere"] = self.atmosphere.to_dict()' \
    "atmosphere: the block is absent-canonical (the committed examples keep their digests)" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/scenario/blocks.py \
    '            if out[name].source is not Source.DEFAULT:
                continue' \
    '            if False:  # MUTATED: the day word overwrites a stated number
                continue' \
    "atmosphere: a day word fills only defaulted fields; a stated number wins" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/environment/atmosphere.py \
    '        if t_r < value:
            value, limited = t_r, "temperature"' \
    '        if False and t_r < value:  # MUTATED: the dew point is written above the air temperature
            value, limited = t_r, "temperature"' \
    "atmosphere: the per-step dew point is limited to the modelled air temperature" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/environment/atmosphere.py \
    '    if relative_humidity_pct <= 0.0:
        return None' \
    '    if False and relative_humidity_pct <= 0.0:  # MUTATED: zero humidity hits the Magnus pole
        return None' \
    "atmosphere: zero humidity is dry air and writes nothing" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/telemetry/recorder.py \
    '    "density_altitude_m",
    "pressure_altitude_m",' \
    '    # MUTATED: the density and pressure altitudes are not recorded' \
    "atmosphere: the density and pressure altitudes are recorded channels" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/scenario/validate.py \
    '    report.violations.extend(validate_atmosphere(spec))' \
    '    pass  # MUTATED: the validator never looks at the atmosphere' \
    "atmosphere: validate() refuses the atmosphere block by name" tests/test_atmosphere.py \
    || failures=$((failures+1))

# -- wave 1 integration: the registry meets the block --------------------------------
mutate core/registry.py \
    '        name="atmosphere.day", spec_path="atmosphere.day", unit="word",' \
    '        name="atmosphere.day", spec_path=None, unit="word",  # MUTATED: the word is not a spec field' \
    "the day word is a registered spec field" tests/test_registry.py \
    || failures=$((failures+1))

mutate core/registry.py \
    '                         EffectChannel("temperature_k", "K"), EffectChannel("tas_kt", "kt")),' \
    '                         EffectChannel("sigma", "1"), EffectChannel("tas_kt", "kt")),  # MUTATED: an unrecorded channel' \
    "a registered effect channel is a recorded column" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/record_null.py \
    '        if stated.get("value") is None:
            continue                     # unstated (a block lists every field): nothing applied' \
    '        pass  # MUTATED: an unstated field runs a pair against its null' \
    "an unstated field runs no null pair" tests/test_atmosphere.py \
    || failures=$((failures+1))

mutate core/record_null.py \
    'NULL_FLOOR_HUMIDITY_PCT = 0.1' \
    'NULL_FLOOR_HUMIDITY_PCT = 0.0  # MUTATED: any humidity effect counts' \
    "the humidity null floor is the stated tenth of a percent" tests/test_record_null.py \
    || failures=$((failures+1))

# -- the advancement additions, wave 2: P2 the XML-injection pipeline (failures re-anchored, icing, icing_alpha, gust_rotation) ----
# P2 -- the XML-injection pipeline. Every guard below was applied on the
# working copy, its test file run with -x (pytest rc 1 under each mutation),
# and the file restored byte-identically (sha256sum -c, all OK). Fires: yes, 23/23.

mutate core/control/derive.py \
    '        fcs = _input_pattern(f"fcs/{surface}-cmd-norm").sub(
            f"<input>failure/{surface}/cmd-in</input>", fcs)' \
    '        fcs = fcs  # MUTATED: the FCS keeps reading the host command; the chain is bypassed' \
    "the surface command is re-anchored to the failure chain" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/systems/failures.xml.tmpl \
    '      <output>failure/@SURFACE@/cmd-in</output>' \
    '      <output>fcs/@SURFACE@-cmd-norm</output>' \
    "the failure chain writes a new property, not the host one (no cumulative loop)" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/systems/icing.xml \
    '  <property value="1.0">icing/lift-factor</property>' \
    '  <property value="0.9">icing/lift-factor</property>' \
    "icing lift factor is neutral at 1.0" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/systems/icing.xml \
    '  <property value="1.0">icing/drag-factor</property>' \
    '  <property value="0.9">icing/drag-factor</property>' \
    "icing drag factor is neutral at 1.0" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/systems/icing.xml \
    '  <property value="1.0">icing/side-factor</property>' \
    '  <property value="0.9">icing/side-factor</property>' \
    "icing side factor is neutral at 1.0" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/systems/icing.xml \
    '  <property value="1.0">icing/roll-factor</property>' \
    '  <property value="0.9">icing/roll-factor</property>' \
    "icing roll factor is neutral at 1.0" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/systems/icing.xml \
    '  <property value="1.0">icing/pitch-factor</property>' \
    '  <property value="0.9">icing/pitch-factor</property>' \
    "icing pitch factor is neutral at 1.0" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/systems/icing.xml \
    '  <property value="1.0">icing/yaw-factor</property>' \
    '  <property value="0.9">icing/yaw-factor</property>' \
    "icing yaw factor is neutral at 1.0" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/systems/icing_alpha.xml \
    '  <property value="0.0">icing/alpha-shift-rad</property>' \
    '  <property value="0.01">icing/alpha-shift-rad</property>' \
    "the icing alpha shift is neutral at 0" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/systems/gust_rotation.xml \
    '  <property value="0.0">gust/p-equivalent-rad_sec</property>' \
    '  <property value="0.01">gust/p-equivalent-rad_sec</property>' \
    "the gust equivalent roll rate is neutral at 0" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/derive.py \
    '    wrapped = (f"\n{pad}<product>\n{pad}    <property>{factor}</property>"' \
    '    wrapped = (f"\n{pad}<product>\n{pad}    <value>1.0</value>"  # MUTATED: no factor' \
    "every axis function is wrapped by its icing factor" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/derive.py \
    '                      rf"\g<1>{ALPHA_EFFECTIVE_PROPERTY}\g<2>", m.group(0)),' \
    '                      rf"\g<1>{ALPHA_PROPERTY}\g<2>", m.group(0)),  # MUTATED: table keeps alpha' \
    "the LIFT table reads the effective alpha" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/derive.py \
    '                f"\n{pad}    <property>{GUST_P_PROPERTY}</property>\n{pad}</sum>")' \
    '                f"\n{pad}    <value>0.0</value>\n{pad}</sum>")  # MUTATED: no gust term' \
    "the roll-damping term sums the gust roll rate" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/derive.py \
    '        if actual != want:' \
    '        if False:  # MUTATED: a changed build copy passes the hash check' \
    "a built file that no longer hashes as recorded is refused" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/derive.py \
    '    if (expected_derived_sha256 is not None
            and derived.derived_sha256 != expected_derived_sha256):' \
    '    if False:  # MUTATED: the expected hash is never compared' \
    "a derivation not matching the expected hash is refused at the door" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/fdm/fdm.py \
    '        verify_hashes(spec, expected_derived_sha256)' \
    '        pass  # MUTATED: nothing is hashed before the load' \
    "with_injections hashes the derived airframe before loading it" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/derive.py \
    '        if inputs == 0:' \
    '        if False:  # MUTATED: a surface with no FCS input is not refused' \
    "a surface whose FCS input is absent is refused by name" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/derive.py \
    '        if mentions != inputs:' \
    '        if False:  # MUTATED: a command read outside an <input> is not refused' \
    "a surface command read outside an input is an ambiguous anchor" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/derive.py \
    '    if len(with_alpha) != 1:' \
    '    if False:  # MUTATED: zero or several alpha tables are not refused' \
    "the LIFT axis needs exactly one alpha table for the shift" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/derive.py \
    '    if terms != 1 or mentions != 1:' \
    '    if False:  # MUTATED: a second roll-rate term is not refused' \
    "the ROLL axis needs exactly one roll-rate term for the gust sum" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/derive.py \
    '        if clash:' \
    '        if False:  # MUTATED: a derived airframe is derived again' \
    "injecting on top of an injection is a conflict" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/derive.py \
    'INJECTION_ORDER = ("tecs", "failures", "icing", "icing_alpha", "gust_rotation")' \
    'INJECTION_ORDER = ("failures", "tecs", "icing", "icing_alpha", "gust_rotation")  # MUTATED' \
    "injections apply in the fixed order tecs, failures, icing, icing_alpha, gust_rotation" tests/test_derive_injections.py \
    || failures=$((failures+1))

mutate core/control/derive.py \
    '        anchor_test=_failures_anchor, suffix="fail", system_file="Systems/failures.xml",' \
    '        anchor_test=_failures_anchor, suffix="ice", system_file="Systems/failures.xml",  # MUTATED' \
    "the derivation suffix encodes the injection set" tests/test_derive_injections.py \
    || failures=$((failures+1))
# -- the advancement additions, wave 2: D1 the EGM2008 datum extension (each applied to the real file here, its tests red, restored byte-identically) --
mutate core/terrain/geoid.py \
    '    if expected_sha256 is not None and expected_sha256 != digest:' \
    '    if False and expected_sha256 is not None and expected_sha256 != digest:  # MUTATED: any EGM2008 grid passes' \
    "datum: an EGM2008 grid with the wrong sha256 is refused by name (geoid.grid_digest)" tests/test_geoid.py \
    || failures=$((failures+1))

mutate core/terrain/geoid.py \
    '    if digest != EGM2008_TARBALL_SHA256:' \
    '    if False:  # MUTATED: any tarball is extracted' \
    "datum: a fetched tarball with the wrong sha256 is refused before extraction" tests/test_geoid.py \
    || failures=$((failures+1))

mutate core/terrain/geoid.py \
    '    if south * step < -90.0 or north * step > 90.0:' \
    '    if False:  # MUTATED: a crop may leave the grid' \
    "datum: a crop that would leave the grid refuses datum.outside_grid" tests/test_geoid.py \
    || failures=$((failures+1))

mutate core/terrain/geoid.py \
    '        if not (0.0 <= fy <= self.rows - 1 and 0.0 <= fx <= self.cols - 1):' \
    '        if False:  # MUTATED: a point outside the crop is interpolated anyway' \
    "datum: a point outside the crop refuses datum.outside_grid" tests/test_geoid.py \
    || failures=$((failures+1))

mutate core/terrain/geoid.py \
    '        return self.offset_m + self.scale_m * float(value)' \
    '        return self.undulation(lat_deg, lon_deg)  # MUTATED: the cubic is the bilinear' \
    "datum: the cubic interpolation is GeographicLib's 12-point fit, not the bilinear" tests/test_geoid.py \
    || failures=$((failures+1))

mutate core/terrain/geoid.py \
    '        matrix = _C3N if iy == 0 else (_C3S if iy == self.height - 2 else _C3)' \
    '        matrix = _C3  # MUTATED: the interior matrix at the poles' \
    "datum: the polar rows use the constrained transfer matrices" tests/test_geoid.py \
    || failures=$((failures+1))

mutate core/terrain/geoid.py \
    '    header = struct.pack(">ddddii", crop["lat_south"], crop["lon_west"], step, step, rows, cols)' \
    '    header = struct.pack(">ddddii", crop["lat_south"] + step / 3.0, crop["lon_west"], step, step, rows, cols)  # MUTATED: the crop corner is not a node' \
    "datum: the gtx crop is node-aligned (its corner is a whole node of the posting)" tests/test_geoid.py tests/test_datum_block.py \
    || failures=$((failures+1))

mutate core/terrain/geoid.py \
    '    if actual != declared:' \
    '    if False:  # MUTATED: a declared model is never checked against the bake'"'"'s' \
    "datum: a declared geoid model that is not the bake's refuses datum.model_mismatch" tests/test_datum_block.py \
    || failures=$((failures+1))

mutate core/terrain/geoid.py \
    '    if actual is None:
        raise DatumError(
            "datum.model_mismatch",' \
    '    if False:
        raise DatumError(
            "datum.model_mismatch",' \
    "datum: a declared model on a scene with no geoid refuses datum.model_mismatch" tests/test_datum_block.py \
    || failures=$((failures+1))

mutate core/terrain/geoid.py \
    '    if require_block:
        raise DatumError(' \
    '    if False:  # MUTATED: a bake without its block is evaluated on the fly
        raise DatumError(' \
    "datum: a georeferenced bake without its datum block refuses datum.sidecar_without_datum" tests/test_datum_block.py \
    || failures=$((failures+1))

mutate core/terrain/geoid.py \
    '    if vertical != VERTICAL_ORTHOMETRIC:' \
    '    if False:  # MUTATED: ellipsoidal heights are accepted and flown as orthometric' \
    "datum: ellipsoidal heights refuse datum.physics_frame_unsupported" tests/test_datum_block.py \
    || failures=$((failures+1))

mutate core/terrain/geoid.py \
    '    if frame != PHYSICS_FRAME_ORTHOMETRIC:' \
    '    if False:  # MUTATED: the ellipsoid physics frame is accepted' \
    "datum: the ellipsoid physics frame refuses datum.physics_frame_unsupported" tests/test_datum_block.py \
    || failures=$((failures+1))

mutate core/terrain/geoid.py \
    '    missing = [key for key in DTED_REQUIRED if provenance.get(key) is None]' \
    '    missing = []  # MUTATED: blanks are documented' \
    "datum: DTED metadata that cannot name its source refuses dted.metadata_incomplete" tests/test_datum_block.py \
    || failures=$((failures+1))

mutate core/scenario/runner.py \
    '    output_digest = _digest_telemetry(recorder)
    # Gap P10 (D1): the two datum channels appended AFTER the digest so no
    # digest moves (measured: the recorded columns re-digest identically),
    # with the readback and the record.
    datum_record = datum_run(spec, recorder, scene_datum, output_digest)' \
    '    datum_record = datum_run(spec, recorder, scene_datum, "")  # MUTATED: the datum channels are appended BEFORE the digest
    output_digest = _digest_telemetry(recorder)' \
    "datum: undulation_m and hae_m are appended AFTER the output digest (the digest pin)" tests/test_datum_block.py \
    || failures=$((failures+1))

mutate core/scenario/runner.py \
    '    refuse_datum_spec(spec)
' \
    '    pass  # MUTATED: the runner flies an ellipsoidal datum block
' \
    "datum: the runner refuses a datum block it cannot fly before the flight" tests/test_datum_block.py \
    || failures=$((failures+1))

mutate core/scenario/runner.py \
    '    attach_record(manifest, datum_record)
' \
    '    pass  # MUTATED: the scene.geoid_undulation_m record is never attached to the run
' \
    "datum: the run manifest carries the scene.geoid_undulation_m record with its readback" tests/test_datum_block.py \
    || failures=$((failures+1))

mutate core/scenario/spec.py \
    '        if not self.datum.is_default():
            out["datum"] = self.datum.to_dict()' \
    '        if True:  # MUTATED: the default datum block is serialised and every digest moves
            out["datum"] = self.datum.to_dict()' \
    "datum: the block is absent-canonical (the committed examples keep their digests)" tests/test_datum_block.py \
    || failures=$((failures+1))

mutate core/terrain/glo30.py \
    '    baked.provenance["dted"] = dted_block(baked)' \
    '    pass  # MUTATED: no DTED metadata in the sidecar' \
    "datum: the bake sidecar carries the DTED-style metadata" tests/test_datum_block.py \
    || failures=$((failures+1))

mutate core/terrain/glo30.py \
    '    grid = grid_for_model(geoid_model)
' \
    '    grid = grid_for_model("EGM96")  # MUTATED: the asked-for model is ignored
' \
    "datum: a bake that asks for EGM2008 refuses geoid.grid_missing when the cache lacks it" tests/test_datum_block.py \
    || failures=$((failures+1))

# The two verifier guards target core/capture/verify.py once integration patch 0 lands (the same strings); measured here by mutating the identical patch text in tests/test_geoid.py: both fire.
mutate core/capture/verify.py \
    '    evaluator = Transformer.from_pipeline(f"+inv +proj=vgridshift +grids={path}")' \
    '    evaluator = Transformer.from_pipeline(f"+proj=vgridshift +grids={path}")  # MUTATED: the forward pipeline reads -N' \
    "datum: the independent evaluation uses +inv (the forward vgridshift reads -N)" tests/test_datum_block.py \
    || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if worst > DATUM_INDEPENDENT_TOL_M:' \
    '    if False:  # MUTATED: the interior residual is not graded' \
    "datum: datum_independent holds the 100 interior points to 0.01 m" tests/test_datum_block.py \
    || failures=$((failures+1))

# -- the advancement additions, wave 3: W1 land-cover weightmaps, the layer import manifest and the roughness inference ----
mutate core/terrain/weightmaps.py \
    '    extra = (rank < remainder[None, :, :]).astype(np.float64)' \
    '    extra = np.zeros_like(base)  # MUTATED: remainders never distributed' \
    "Landscape layers sum to exactly 255 at every texel" tests/test_weightmaps.py \
    || failures=$((failures+1))

mutate core/terrain/weightmaps.py \
    '    best = np.argmax(legend, axis=0)' \
    '    best = np.argmin(legend, axis=0)  # MUTATED: the smallest layer wins' \
    "the argmax round trip takes the largest layer" tests/test_weightmaps.py \
    || failures=$((failures+1))

mutate core/terrain/weightmaps.py \
    '    if code not in LEGEND_CODES:' \
    '    if code not in LEGEND_CODES and False:  # MUTATED: a foreign code is never refused' \
    "a code outside the legend refuses landcover.legend" tests/test_weightmaps.py \
    || failures=$((failures+1))

mutate core/terrain/weightmaps.py \
    '    constraint = "landcover.legend"' \
    '    constraint = "landcover.legend_code"  # MUTATED: refusal renamed' \
    "the taxonomy refusal is named landcover.legend" tests/test_weightmaps.py \
    || failures=$((failures+1))

mutate core/environment/surface.py \
    'DOMINANCE_THRESHOLD = 0.5' \
    'DOMINANCE_THRESHOLD = 0.0  # MUTATED: any plurality infers' \
    "the dominant class must hold half the scene" tests/test_surface_inference.py \
    || failures=$((failures+1))

mutate core/environment/surface.py \
    '    return replace(cls, thermals=None,' \
    '    return replace(cls, thermals=cls.thermals,  # MUTATED: the word'"'"'s thermals ride along' \
    "the land cover inference infers roughness only" tests/test_surface_inference.py \
    || failures=$((failures+1))

mutate core/environment/surface.py \
    '    source: str = "inferred"' \
    '    source: str = "derived"  # MUTATED: provenance word' \
    "an inferred surface carries provenance inferred" tests/test_surface_inference.py \
    || failures=$((failures+1))

mutate core/environment/surface.py \
    '    if str(quantity.value) != UNSPECIFIED or str(quantity.source) != "default":' \
    '    if str(quantity.value) != UNSPECIFIED:  # MUTATED: a stated unspecified is overridden' \
    "a user-stated surface beats the inference" tests/test_surface_inference.py \
    || failures=$((failures+1))

mutate core/environment/surface.py \
    '    constraint = "landcover.surface_inference"' \
    '    constraint = "landcover.surface_inferred"  # MUTATED: refusal renamed' \
    "the inference refusal is named landcover.surface_inference" tests/test_surface_inference.py \
    || failures=$((failures+1))

mutate core/environment/surface.py \
    'NULL_WIND_THRESHOLD_KT = 0.5' \
    'NULL_WIND_THRESHOLD_KT = 50.0  # MUTATED: no effect reaches' \
    "the surface record's null test is graded at 0.5 kt" tests/test_surface_inference.py \
    || failures=$((failures+1))

mutate core/terrain/landscape.py \
    '    if bake.get("sha256") != field.digest():' \
    '    if False:  # MUTATED: any bake verifies' \
    "a bake whose sha256 is not the manifest's refuses terrain.landscape_stale" tests/test_weightmaps.py tests/test_terrain.py \
    || failures=$((failures+1))

mutate core/terrain/landscape.py \
    '    manifest["datum"] = bake_datum_block(field)' \
    '    manifest["datum"] = {"undulation_m": None}  # MUTATED: the bake'"'"'s datum not copied' \
    "the import manifest copies the bake's datum block" tests/test_weightmaps.py tests/test_terrain.py \
    || failures=$((failures+1))

mutate core/terrain/landscape.py \
    '        if layout != spec.layout or resolution != spec.resolution:' \
    '        if False:  # MUTATED: any layout accepted' \
    "a layer of another layout refuses terrain.landscape_layout" tests/test_weightmaps.py tests/test_terrain.py \
    || failures=$((failures+1))

mutate core/terrain/landscape.py \
    '        "sum_ok": bool(checked) and int(total.min()) == 255 and int(total.max()) == 255,' \
    '        "sum_ok": bool(checked),  # MUTATED: the sum is not graded' \
    "the layer sum is graded at 255 in the import verification" tests/test_terrain.py \
    || failures=$((failures+1))
mutate core/scenario/runner.py \
    '        except SurfaceInferenceError as exc:' \
    '        except ():  # MUTATED: the inference refusal escapes and stops the flight' \
    "a scene the roughness map cannot read flies the default surface and says why" tests/test_surface_inference.py \
    || failures=$((failures+1))

# -- the advancement additions, wave 3: P6 the gust provider, von Karman turbulence and layered shear ----
# P6 -- every guard below was applied on the real file, its test file(s) run with -x
# (pytest rc 1, or 2 where the mutation refuses at import), and the file restored
# byte-identically (sha256 compared). Fires: yes, 17/17.

mutate core/environment/stack.py \
    '        writes.update(gust_writes)' \
    '        if self.gust:  # MUTATED: the gust channel is written only while a provider exists
            writes.update(gust_writes)' \
    "the gust sum is written every step, zero included, because the channel persists" tests/test_gust_provider.py tests/test_environment.py \
    || failures=$((failures+1))

mutate core/environment/von_karman.py \
    'L_VW_HIGH_FT = L_U_HIGH_FT / 2.0' \
    'L_VW_HIGH_FT = L_U_HIGH_FT  # MUTATED: L_u = L_v = L_w' \
    "the von Karman scale lengths above 2000 ft are L_u = 2 L_v = 2 L_w = 2500 ft" tests/test_von_karman.py \
    || failures=$((failures+1))

mutate core/environment/von_karman.py \
    'LOW_ALTITUDE_FT = 1000.0' \
    'LOW_ALTITUDE_FT = 500.0  # MUTATED: the low band ends at 500 ft' \
    "the sigma ladder branches at 1000 ft as FGWinds L276 does" tests/test_von_karman.py \
    || failures=$((failures+1))

mutate core/environment/von_karman.py \
    '    return sigma ** 2 * (2.0 * length / math.pi) / (1.0 + x * x) ** (5.0 / 6.0)' \
    '    return sigma ** 2 * (2.0 * length / math.pi) / (1.0 + x * x) ** (1.0)  # MUTATED: a -2 slope' \
    "the realised u spectrum falls as Omega^-5/3 (fitted on the table)" tests/test_von_karman.py \
    || failures=$((failures+1))

mutate core/environment/von_karman.py \
    'SEED_STREAM = "von_karman"' \
    'SEED_STREAM = "turbulence"  # MUTATED: another subsystem'"'"'s stream' \
    "the von Karman phases come from the named stream von_karman" tests/test_von_karman.py \
    || failures=$((failures+1))

mutate core/environment/von_karman.py \
    'ROW_FORMAT = "%.17g"' \
    'ROW_FORMAT = "%.15g"  # MUTATED: two digits short of a round trip' \
    "the card rows are %.17g strings that round-trip to the same doubles" tests/test_von_karman.py tests/test_gust_provider.py \
    || failures=$((failures+1))

mutate core/environment/shear.py \
    '    if any(b <= a for a, b in zip(altitudes, altitudes[1:])):' \
    '    if False:  # MUTATED: unsorted layers accepted' \
    "layers must be strictly ascending in altitude (wind_profile.layers)" tests/test_shear.py \
    || failures=$((failures+1))

mutate core/environment/shear.py \
    'MILSPEC_MAX_HEIGHT_FT = 1000.0' \
    'MILSPEC_MAX_HEIGHT_FT = 10000.0  # MUTATED: the log law claimed to 10000 ft' \
    "the MIL-F-8785C log law is valid 3..1000 ft AGL and refused outside" tests/test_shear.py \
    || failures=$((failures+1))

mutate core/environment/shear.py \
    '    if not isinstance(expected, str) or expected != digest:' \
    '    if not isinstance(expected, str):  # MUTATED: an altered fixture accepted' \
    "an NWP fixture whose sha256 is not its sidecar's refuses weather.fixture_digest" tests/test_shear.py \
    || failures=$((failures+1))

mutate core/environment/stack.py \
    '                                else "property" if self._p_equivalent else "absent")' \
    '                                else "property")  # MUTATED: delivery claimed on a stock airframe' \
    "the roll gust delivery is recorded absent where the airframe declares no property" tests/test_gust_provider.py \
    || failures=$((failures+1))

mutate core/scenario/runner.py \
    '        stack.add(DrydenTurbulence("none"))' \
    '        stack.add(DrydenTurbulence(intensity, seed=seed))  # MUTATED: Dryden runs beside the field' \
    "the von Karman model switches JSBSim's own Dryden process off" tests/test_gust_provider.py \
    || failures=$((failures+1))

mutate core/scenario/runner.py \
    '    if profile_wind is not None:' \
    '    if False:  # MUTATED: the uniform wind written before the trim' \
    "a wind profile's wind at the initial altitude is the one written before the trim" tests/test_shear.py \
    || failures=$((failures+1))

mutate core/scenario/validate.py \
    '        elif model == "dryden":' \
    '        elif False:  # MUTATED: a W20 number silently accepted by the Dryden path' \
    "a numeric W20 with the dryden model refuses turbulence.model" tests/test_gust_provider.py \
    || failures=$((failures+1))

mutate core/scenario/card.py \
    '    stack.prepare(fdm)' \
    '    pass  # MUTATED: the card table is not built from the FDM' \
    "the gust_table card block is built as the run builds it" tests/test_gust_provider.py \
    || failures=$((failures+1))

mutate core/scenario/runner.py \
    'extra={**SURFACES, **environment.recorder_extras()}' \
    'extra=dict(SURFACES)' \
    "the wind profile's layer index and gradient are recorded columns" tests/test_shear.py \
    || failures=$((failures+1))

mutate core/capture/manifest.py \
    '    ("_rad_s", "rad/s"), ("_per_s", "1/s"),' \
    '    # MUTATED: no per-second suffixes; _rad_s and _per_s read as seconds' \
    "a per-second channel name is never read as seconds" tests/test_registry.py \
    || failures=$((failures+1))

mutate core/fdm/state.py \
    '                        if has is not None and has(P_EQUIVALENT_PROPERTY) else 0.0)' \
    '                        if False else 0.0)  # MUTATED: the delivered roll gust never recorded' \
    "the equivalent roll rate the derived airframe received is recorded" tests/test_gust_provider.py \
    || failures=$((failures+1))

# -- the advancement additions, wave 4: P4 loading (payload, fuel, the CG read back) and P3 the failure schedule ----
mutate core/scenario/loading.py \
    'CG_TOLERANCE_IN = 0.1' \
    'CG_TOLERANCE_IN = 10.0  # MUTATED: the hand CG may sit ten inches from JSBSim'"'"'s' \
    "loading: the hand CG is read back against JSBSim's cg-x-in within 0.1 in (V13)" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/scenario/loading.py \
    '        if not cg_check["agrees"]:' \
    '        if False:  # MUTATED: a hand CG outside the tolerance is accepted' \
    "loading: a hand CG that misses JSBSim's cg-x-in by more than the tolerance is refused by name" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/scenario/runner.py \
    '    loading = loading_for(spec)
    if loading is not None:
        stack.add(loading)' \
    '    loading = None  # MUTATED: the loading is never attached, so nothing is written before the trim
    if loading is not None:
        stack.add(loading)' \
    "loading: the stations and tanks are written once before the trim, after the atmosphere" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/scenario/runner.py \
    '        environment = EnvironmentStack([p for p in (atmosphere_for(spec), loading_for(spec))' \
    '        environment = EnvironmentStack([p for p in (atmosphere_for(spec),)  # MUTATED: the probe trims the unloaded aircraft' \
    "loading: the validator's feasibility probe trims the loaded aircraft" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/scenario/loading.py \
    '            fdm.relatch_initial_conditions()
            now = self._read(fdm)
            steps.append({"variable": "payload",' \
    '            pass  # MUTATED: no re-latch, so the CG property is the stale one
            now = self._read(fdm)
            steps.append({"variable": "payload",' \
    "loading: the initial conditions are re-latched after each station write so FGMassBalance recomputes the CG" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/scenario/loading.py \
    '            if station.key == key:' \
    '            if True:  # MUTATED: any name resolves to the first station' \
    "loading: a station the airframe does not list is refused by name" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/scenario/loading.py \
    '            if kg > station.max_kg:' \
    '            if False:  # MUTATED: any mass passes the station maximum' \
    "loading: a mass over the station's stated maximum is refused by name" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/scenario/loading.py \
    '        if gross_kg > self.config.max_takeoff_weight_kg:' \
    '        if False and gross_kg > self.config.max_takeoff_weight_kg:  # MUTATED: no maximum weight' \
    "loading: the gross weight summed over empty weight, stations and fuel is held to the maximum takeoff weight" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/scenario/loading.py \
    '                inside = not inside' \
    '                inside = inside  # MUTATED: the crossing count never toggles' \
    "loading: the envelope test is a point-in-polygon crossing count" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/scenario/loading.py \
    '            if not 0.0 < fraction <= 1.0:' \
    '            if False:  # MUTATED: any fuel fraction passes' \
    "loading: a fuel fraction outside 0..1 is refused by name" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/scenario/loading.py \
    '            if kg <= 0.0:' \
    '            if kg < 0.0:  # MUTATED: a zero fuel load is accepted' \
    "loading: a fuel load of zero leaves the engines nothing to start on and is refused by name" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/scenario/loading.py \
    '        refusal = self.config.envelope_refusal()
        if refusal is not None:
            raise refusal
        return self.envelope_check()' \
    '        refusal = None  # MUTATED: the envelope is checked on an unverified datum
        if refusal is not None:
            raise refusal
        return self.envelope_check()' \
    "loading: the envelope check asked for on an airframe whose arm comparison is not green is refused by name" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/scenario/loading.py \
    'CARD_KEYS = ("stations", "tanks", "expected_cg_in", "tolerance_in", "datum")' \
    'CARD_KEYS = ("tanks", "stations", "expected_cg_in", "tolerance_in", "datum")  # MUTATED: another key order' \
    "loading: the card block's keys are in the fixed order the host reads" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/scenario/loading.py \
    '            if abs(arm - station.arm_in) > 1e-6:
                raise refuse(f"arm of station {station.name!r} in", station.arm_in, arm)' \
    '            if False:  # MUTATED: a configured arm that is not the model'"'"'s passes
                raise refuse(f"arm of station {station.name!r} in", station.arm_in, arm)' \
    "loading: a configured station arm that is not the loaded model's is refused by name before any write" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/scenario/card.py \
    '    loading = loading_card_block(spec)
    if loading is not None:' \
    '    loading = None  # MUTATED: the card never carries the loading
    if loading is not None:' \
    "loading: the run card carries the loading_properties block for a stated loading" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/scenario/validate.py \
    '    report.violations.extend(validate_loading(spec))' \
    '    pass  # MUTATED: the loading is never validated' \
    "loading: the validator names the loading refusals" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/fdm/state.py \
    '            cg_x_m=u.ft_to_m(g("inertia/cg-x-in") / 12.0),' \
    '            cg_x_m=0.0,  # MUTATED: the CG is not read from JSBSim' \
    "loading: the CG is recorded every sample from JSBSim's inertia/cg-x-in" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/telemetry/recorder.py \
    '    "cg_x_m",
    "iyy_kgm2",
    # -- the measured channels (R2)' \
    '    # MUTATED: the loading channels are not recorded
    # -- the measured channels (R2)' \
    "loading: cg_x_m and iyy_kgm2 are recorded columns" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/scenario/randomization.py \
    '    elif target.startswith("loading."):' \
    '    elif False:  # MUTATED: a loading leaf falls through to the spec fields' \
    "loading: the fuel_fraction and payload_kg policy leaves write the loading block" tests/test_loading.py \
    || failures=$((failures+1))

mutate core/scenario/loading.py \
    '            fdm.relatch_initial_conditions()
            now = self._read(fdm)
            steps.append({"variable": "fuel_kg" if plan.fuel_kg is not None else "fuel_fraction",' \
    '            pass  # MUTATED: no re-latch after the tank writes, so the CG property is the stale one
            now = self._read(fdm)
            steps.append({"variable": "fuel_kg" if plan.fuel_kg is not None else "fuel_fraction",' \
    "loading: the initial conditions are re-latched after the tank writes so FGMassBalance recomputes the CG" tests/test_loading.py \
    || failures=$((failures+1))
mutate core/telemetry/failures.py \
    '            if t >= event.at_s:' \
    '            if t > event.at_s:  # MUTATED: the step AT the stated time is skipped' \
    "failures: an event lands at the first step at or past its time (>= not >)" tests/test_failures.py \
    || failures=$((failures+1))

mutate core/telemetry/failures.py \
    '        t = sim_time - self.first_call_t' \
    '        t = sim_time - self.first_call_t - 0.05  # MUTATED: six steps late' \
    "failures: the write lands within one step of the stated time (V15)" tests/test_failures.py \
    || failures=$((failures+1))

mutate core/telemetry/failures.py \
    'JAM_HOLD_TOLERANCE_RAD = 1e-6' \
    'JAM_HOLD_TOLERANCE_RAD = 1e-1  # MUTATED: a drifting surface passes as held' \
    "failures: a jammed surface holds within 1e-6 rad over 100 steps" tests/test_failures.py \
    || failures=$((failures+1))

mutate core/telemetry/failures.py \
    '                threshold=NULL_FLOOR_FORCE_N, kind="reached",' \
    '                threshold=1e9, kind="reached",  # MUTATED: no thrust change ever reaches' \
    "failures: the engine-out null test grades thrust after against before at the force floor" tests/test_failures.py \
    || failures=$((failures+1))

mutate core/telemetry/failures.py \
    '        elif not 0.0 <= float(value) <= 1.0:' \
    '        elif False and not 0.0 <= float(value) <= 1.0:  # MUTATED: any authority passes' \
    "failures: an authority outside 0..1 is refused by name" tests/test_failures.py \
    || failures=$((failures+1))

mutate core/telemetry/failures.py \
    '                if not has(switch):' \
    '                if False and not has(switch):  # MUTATED: a stock airframe is written to' \
    "failures: a surface failure on an airframe without the chain is refused by name" tests/test_failures.py \
    || failures=$((failures+1))

mutate core/telemetry/failures.py \
    '        st.agrees = (st.readback == st.written)' \
    '        st.agrees = True  # MUTATED: the readback is asserted, not measured' \
    "failures: the readback agreement is measured against the value written" tests/test_failures.py \
    || failures=$((failures+1))

mutate core/scenario/validate.py \
    '    report.violations.extend(validate_failures(spec))' \
    '    report.violations.extend([])  # MUTATED: the schedule is never validated' \
    "failures: the validator refuses a bad schedule by name" tests/test_failures_block.py \
    || failures=$((failures+1))

mutate core/scenario/runner.py \
    '    fdm.register_step_hook(schedule.apply)' \
    '    pass  # MUTATED: the schedule is bound and never applied' \
    "failures: the runner applies the schedule through the step hook" tests/test_failures_block.py \
    || failures=$((failures+1))

mutate core/scenario/runner.py \
    '    if injections:' \
    '    if False and injections:  # MUTATED: the stock airframe is flown' \
    "failures: a surface failure derives the airframe with the failures injection" tests/test_failures_block.py \
    || failures=$((failures+1))

mutate core/scenario/card.py \
    '        card["failure_schedule"] = failure_schedule' \
    '        pass  # MUTATED: the card carries no schedule' \
    "failures: the card carries the failure_schedule block" tests/test_failures_block.py \
    || failures=$((failures+1))

mutate core/scenario/spec.py \
    '        if not self.failures.is_default():' \
    '        if True:  # MUTATED: the default block is serialised too' \
    "failures: the block is absent-canonical (every committed example keeps its digest)" tests/test_failures_block.py tests/test_registry.py \
    || failures=$((failures+1))

mutate core/registry.py \
    '        name="failures.events", spec_path="failures.events", unit="events",' \
    '        name="failures.events", spec_path=None, unit="events",  # MUTATED: the block is unclaimed' \
    "failures: the registry claims the block's field" tests/test_failures_block.py tests/test_registry.py \
    || failures=$((failures+1))

# -- the advancement additions, wave 5: P5 the icing provider and D2 the DIS entity-state stream ----
mutate core/environment/icing.py \
    '        fraction = min(1.0, max(0.0, (t - onset_s) / ramp_s))' \
    '        fraction = (t - onset_s) / ramp_s  # MUTATED: no clamp, eta runs past eta_max and below 0' \
    "icing: the severity ramp is clamped to 0..eta_max" tests/test_icing.py \
    || failures=$((failures+1))

mutate core/environment/icing.py \
    '        return {axis: 1.0 + eta * self.values[axis] for axis in AXES}' \
    '        return {axis: 1.0 + self.values[axis] for axis in AXES}  # MUTATED: the factor ignores eta' \
    "icing: the factor form is 1 + eta k per axis (Bragg)" tests/test_icing.py \
    || failures=$((failures+1))

mutate core/environment/icing.py \
    '        writes = self.writes_at(t)
        s = self.schedule' \
    '        writes = {} if self.steps_written else self.writes_at(t)  # MUTATED: written on the first step only
        s = self.schedule' \
    "icing: the eight properties are written every step" tests/test_icing.py \
    || failures=$((failures+1))

mutate core/environment/icing.py \
    '            errors[prop] = max(errors.get(prop, 0.0), abs(read - written))' \
    '            errors[prop] = 0.0  # MUTATED: every read-back is reported as agreeing' \
    "icing: the per-step read-back error is measured, not assumed" tests/test_icing.py \
    || failures=$((failures+1))

mutate core/scenario/blocks.py \
    'ICING_SEVERITY_WORDS: Dict[str, float] = {"trace": 0.05, "light": 0.10, "moderate": 0.20,
                                          "severe": 0.30}' \
    'ICING_SEVERITY_WORDS: Dict[str, float] = {"trace": 0.05, "light": 0.10, "moderate": 0.25,
                                          "severe": 0.30}  # MUTATED: another moderate' \
    "icing: the severity words are the stated mapping to eta" tests/test_icing.py \
    || failures=$((failures+1))

mutate core/scenario/blocks.py \
    '        if eta.source is Source.DEFAULT or eta.value is None:' \
    '        if True:  # MUTATED: the word overrides a stated number' \
    "icing: a stated eta_max wins over the severity word" tests/test_icing.py \
    || failures=$((failures+1))

mutate core/environment/icing.py \
    '    elif not ETA_RANGE[0] <= float(eta_max) <= ETA_RANGE[1]:' \
    '    elif False:  # MUTATED: any eta_max is accepted' \
    "icing: eta_max outside 0..1 is refused by name" tests/test_icing.py \
    || failures=$((failures+1))

mutate core/environment/icing.py \
    '    table = load_k_table(aircraft, config_dir)
    if table is None:' \
    '    table = load_k_table(aircraft, config_dir)
    if False:  # MUTATED: an airframe without a k-table is not refused' \
    "icing: an airframe with no k-table is refused by name" tests/test_icing.py \
    || failures=$((failures+1))

mutate core/environment/icing.py \
    'CARD_KEYS = ("eta_max", "onset_s", "ramp_s", "alpha_shift_deg", "k_table", "source")' \
    'CARD_KEYS = ("onset_s", "eta_max", "ramp_s", "alpha_shift_deg", "k_table", "source")  # MUTATED: another key order' \
    "icing: the card block's keys are in the fixed order the host reads" tests/test_icing.py \
    || failures=$((failures+1))

mutate core/environment/icing.py \
    '        return math.radians(self.alpha_shift_deg) * (eta / self.eta_max)' \
    '        return math.radians(self.alpha_shift_deg)  # MUTATED: the full shift whatever eta' \
    "icing: the alpha shift is a linear cue in eta" tests/test_icing.py \
    || failures=$((failures+1))

mutate core/environment/icing.py \
    '        fdm.props.set_many(neutral)
        fdm.relatch_initial_conditions()
        restored = self._measure(fdm)' \
    '        fdm.props.set_many(writes)  # MUTATED: the factors at eta_max are left for the trim
        fdm.relatch_initial_conditions()
        restored = self._measure(fdm)' \
    "icing: the trim is of the un-iced aircraft (neutral values before the trim)" tests/test_icing.py \
    || failures=$((failures+1))

mutate core/scenario/runner.py \
    '    icing_injections = icing_injections_for(spec)' \
    '    icing_injections = ()  # MUTATED: the stock airframe is flown with the block stated' \
    "icing: a stated block derives the airframe with the icing and icing_alpha injections" tests/test_icing.py \
    || failures=$((failures+1))

mutate core/scenario/runner.py \
    '    icing = icing_for(spec)
    if icing is not None:
        stack.add(icing)' \
    '    icing = None  # MUTATED: the icing provider is never attached
    if icing is not None:
        stack.add(icing)' \
    "icing: the provider is in the stack (neutral before the trim, eta every step)" tests/test_icing.py \
    || failures=$((failures+1))

mutate core/scenario/spec.py \
    '        if not self.icing.is_default():' \
    '        if True:  # MUTATED: the default block is serialised too' \
    "icing: the block is absent-canonical (every committed example keeps its digest)" tests/test_icing.py tests/test_registry.py \
    || failures=$((failures+1))

mutate core/scenario/validate.py \
    '    report.violations.extend(validate_icing(spec))' \
    '    pass  # MUTATED: the icing block is never validated' \
    "icing: the validator refuses the block by name" tests/test_icing.py \
    || failures=$((failures+1))

mutate core/scenario/card.py \
    '        card["icing_schedule"] = icing_schedule' \
    '        pass  # MUTATED: the card carries no icing schedule' \
    "icing: the card carries the icing_schedule block" tests/test_icing.py \
    || failures=$((failures+1))

mutate core/registry.py \
    '        name="icing.eta", spec_path="icing.eta_max", unit="1",' \
    '        name="icing.eta", spec_path=None, unit="1",  # MUTATED: the block'"'"'s number is unclaimed' \
    "icing: the registry claims the block's fields" tests/test_icing.py \
    || failures=$((failures+1))
mutate core/interop/dis.py \
    'ESPDU_LENGTH = 144' \
    'ESPDU_LENGTH = 148  # MUTATED: the struct length is not the wire length' \
    "DIS D2: the Entity State PDU struct length is 144 bytes" tests/test_dis.py \
    || failures=$((failures+1))

mutate core/interop/dis.py \
    '    return (units << 1) | (TIMESTAMP_ABSOLUTE_BIT if absolute else 0)' \
    '    return (units << 1)  # MUTATED: the absolute flag never reaches the LSB' \
    "DIS D2: the timestamp LSB carries the absolute flag" tests/test_dis.py \
    || failures=$((failures+1))

mutate core/interop/dis.py \
    '                      * TIMESTAMP_UNITS_PER_HOUR)) % TIMESTAMP_UNITS_PER_HOUR' \
    '                      * TIMESTAMP_UNITS_PER_HOUR))  # MUTATED: no modulo rollover at the hour' \
    "DIS D2: the timestamp rolls over modulo 2^31 at the hour (a round within a unit of the hour overflows to 33 bits)" tests/test_dis.py \
    || failures=$((failures+1))

mutate core/interop/dis.py \
    '    return timestamp_from_seconds(past_hour, absolute=True)' \
    '    return timestamp_from_seconds(past_hour, absolute=False)  # MUTATED: absolute mode writes LSB 0' \
    "DIS D2: the absolute timestamp mode sets the LSB" tests/test_dis.py tests/test_dis_stream.py \
    || failures=$((failures+1))

mutate core/interop/dis.py \
    '    if epoch is None or not str(epoch).strip():
        raise DisError("dis.timestamp_epoch_missing",' \
    '    if epoch is None:
        return 0.0  # MUTATED: a missing epoch is silently the Unix epoch
    if not str(epoch).strip():
        raise DisError("dis.timestamp_epoch_missing",' \
    "DIS D2: absolute timestamps without an epoch refuse dis.timestamp_epoch_missing" tests/test_dis.py tests/test_dis_stream.py \
    || failures=$((failures+1))

mutate core/interop/dis.py \
    '    if len(text) > MARKING_MAX_CHARACTERS or not text.isascii():
        raise DisError("dis.marking_too_long",' \
    '    if False:  # MUTATED: any marking is accepted and truncated on the wire
        raise DisError("dis.marking_too_long",' \
    "DIS D2: a marking over 11 ASCII characters refuses dis.marking_too_long" tests/test_dis.py \
    || failures=$((failures+1))

mutate core/interop/dis_stream.py \
    '        if len(text) > MARKING_MAX_CHARACTERS or not text.isascii():
            out.append(DisError("dis.marking_too_long",' \
    '        if False:  # MUTATED: the block accepts any marking
            out.append(DisError("dis.marking_too_long",' \
    "DIS D2: the dis block's marking is checked by the validator's list" tests/test_dis_stream.py \
    || failures=$((failures+1))

mutate core/interop/dis.py \
    '        heights = columns["hae_m"]' \
    '        heights = columns["altitude_m"] if "altitude_m" in columns else columns["hae_m"]  # MUTATED: the orthometric height is exported' \
    "DIS D2: the geoid undulation is added at the export boundary (hae_m, not altitude_m)" tests/test_dis.py tests/test_dis_stream.py \
    || failures=$((failures+1))

mutate core/interop/dis.py \
    '    lo, hi = max(0, i - 1), min(n - 1, i + 1)' \
    '    lo, hi = i, min(n - 1, i + 1)  # MUTATED: a forward difference' \
    "DIS D2: the DRM acceleration is the central difference of the recorded ECEF velocity" tests/test_dis.py \
    || failures=$((failures+1))

mutate core/interop/dis.py \
    '        bad = [c for c, v in values.items() if not _finite(v)]' \
    '        bad = []  # MUTATED: a frame without a finite place is exported' \
    "DIS D2: a recorded frame without a finite geodetic place refuses dis.frame_without_geodetic" tests/test_dis.py \
    || failures=$((failures+1))

mutate core/interop/dis.py \
    '    if septuplet is None:
        raise DisError("dis.entity_type_unknown",' \
    '    if septuplet is None:
        return EntityType(1, 2, 0, 0, 0, 0, 0), row  # MUTATED: an empty row is guessed
    if False:
        raise DisError("dis.entity_type_unknown",' \
    "DIS D2: an empty standard-table row refuses dis.entity_type_unknown, never a guessed septuplet" tests/test_dis.py tests/test_dis_stream.py \
    || failures=$((failures+1))

mutate core/interop/dis.py \
    '    return {"type": EntityType(), "septuplet": None, "source": "unspecified",' \
    '    return {"type": EntityType(1, 2, 0, 0, 0, 0, 0), "septuplet": None, "source": "unspecified",  # MUTATED: Platform-Air guessed' \
    "DIS D2: the unspecified policy writes 0 = Other in every field" tests/test_dis.py tests/test_dis_stream.py \
    || failures=$((failures+1))

mutate core/interop/dis_stream.py \
    '    if udp is not None:
        sender = UdpSender(*udp)' \
    '    if True:  # MUTATED: a socket is opened and datagrams sent by default
        sender = UdpSender(*(udp or ("127.0.0.1", 3000)))' \
    "DIS D2: the UDP sender is off by default (no socket without a target)" tests/test_dis_stream.py \
    || failures=$((failures+1))

mutate core/interop/dis_stream.py \
    '    if udp is not None and in_campaign_worker(out_dir):' \
    '    if False and udp is not None and in_campaign_worker(out_dir):  # MUTATED: a campaign case may send' \
    "DIS D2: a campaign case refuses dis.udp_in_campaign before any socket exists" tests/test_dis_stream.py \
    || failures=$((failures+1))

mutate core/interop/dis_stream.py \
    '        if (position_error > options.position_threshold_m' \
    '        if (position_error > 1e9 * options.position_threshold_m  # MUTATED: the position threshold never fires' \
    "DIS D2: the thresholded emitter reconstructs the full-rate stream within its position threshold" tests/test_dis_stream.py \
    || failures=$((failures+1))

mutate core/capture/verify.py \
    'DIS_LOCATION_TOL_M = 0.05' \
    'DIS_LOCATION_TOL_M = 500.0  # MUTATED: a PDU moved a metre or a stale undulation passes' \
    "DIS D2: the verifier holds every PDU location to 0.05 m of pyproj" tests/test_dis_stream.py \
    || failures=$((failures+1))

mutate core/capture/verify.py \
    'DIS_EULER_TOL_RAD = 1e-4' \
    'DIS_EULER_TOL_RAD = 10.0  # MUTATED: a flipped Euler sign passes' \
    "DIS D2: the verifier holds every PDU orientation to 1e-4 rad of its own composition" tests/test_dis_stream.py \
    || failures=$((failures+1))

mutate core/capture/verify.py \
    '    phi = math.atan2(m[1][2], m[2][2])
    return psi, theta, phi' \
    '    phi = -math.atan2(m[1][2], m[2][2])  # MUTATED: the checker'"'"'s own roll sign flipped
    return psi, theta, phi' \
    "DIS D2: the verifier's own Euler composition agrees with the wire" tests/test_dis_stream.py \
    || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if seconds <= previous:' \
    '            if False and seconds <= previous:  # MUTATED: a clock that runs backwards passes' \
    "DIS D2: the verifier requires strictly increasing timestamps" tests/test_dis_stream.py \
    || failures=$((failures+1))

mutate core/capture/verify.py \
    '    if record is None and not have_files:
        return Check("dis_roundtrip", NOT_RUN,' \
    '    if False:  # MUTATED: a run without a stream fails instead of NOT RUN
        return Check("dis_roundtrip", NOT_RUN,' \
    "DIS D2: the verifier reports NOT RUN without a stream, never a pass or a fail on absence" tests/test_dis_stream.py \
    || failures=$((failures+1))

mutate core/scenario/validate.py \
    '    report.violations.extend(validate_dis(spec))' \
    '    pass  # MUTATED: the dis block is not validated' \
    "DIS D2: the validator refuses the dis block's fields by name" tests/test_dis_block.py \
    || failures=$((failures+1))

mutate core/scenario/spec.py \
    '        if not self.dis.is_default():' \
    '        if True:  # MUTATED: the default dis block is serialised too' \
    "DIS D2: the dis block is absent-canonical (every committed example keeps its digest)" tests/test_dis_block.py tests/test_registry.py \
    || failures=$((failures+1))

mutate core/registry.py \
    '        name="dis.site", spec_path="dis.site", unit="1",' \
    '        name="dis.site", spec_path=None, unit="1",  # MUTATED: the field is unclaimed' \
    "DIS D2: the registry claims every field of the dis block" tests/test_dis_block.py tests/test_registry.py \
    || failures=$((failures+1))

mutate flightsim/capture.py \
    '    if args.cigi:' \
    '    if False and args.cigi:  # MUTATED: --cigi runs a capture as if it spoke CIGI' \
    "DIS D2: --cigi refuses interop.cigi_not_implemented before anything runs" tests/test_dis_block.py \
    || failures=$((failures+1))

mutate flightsim/capture.py \
    '            preflight(str(spec.aircraft.value), dis_options)' \
    '            pass  # MUTATED: no pre-flight gate; the refusal comes after the flight' \
    "DIS D2: the DIS refusals are printed before any flight" tests/test_dis_block.py \
    || failures=$((failures+1))

mutate flightsim/capture.py \
    '        keyed = attach_frame_keys(manifest, dis_index)' \
    '        keyed = 0  # MUTATED: no frame carries its PDU keys' \
    "DIS D2: every frame record carries dis.pdu_index and dis.byte_offset" tests/test_dis_block.py \
    || failures=$((failures+1))

mutate core/telemetry/recorder.py \
    '    "yaw_rate_dps",' \
    '    # "yaw_rate_dps",  # MUTATED: the yaw rate is not recorded' \
    "DIS D2: the recorder records the body yaw rate the RVW block needs" tests/test_dis_block.py \
    || failures=$((failures+1))

# -- the advancement additions, wave 6: P7 the wake-vortex pair and S1 radiometry (the sun in lux, optics, blur, the profile blocks) ----
# P7: the wake-vortex pair (core/environment/wake.py); the tests are selected with -k so the file is named.
mutate core/environment/wake.py \
    'CORE_RADIUS_FACTOR = 0.035' \
    'CORE_RADIUS_FACTOR = 0.05  # MUTATED: another core-radius convention' \
    "wake: the core radius is r_c = 0.035 b (Proctor's convention)" tests/test_wake.py -k "test_the_closed_forms_b0_rc_gamma0_and_w0" \
    || failures=$((failures+1))
mutate core/environment/wake.py \
    '    return float(gamma_m2_s) * r / (2.0 * math.pi * (r * r + float(r_c_m) ** 2))' \
    '    return float(gamma_m2_s) * r / (2.0 * math.pi * (r * r + 2.0 * float(r_c_m) ** 2))  # MUTATED: the core factor doubled' \
    "wake: the Burnham-Hallock core factor gives V(r_c) = Gamma / (4 pi r_c)" tests/test_wake.py -k "test_v16_burnham_hallock_at_the_core_radius_is_gamma_over_4_pi_rc" \
    || failures=$((failures+1))
mutate core/environment/wake.py \
    'B0_FACTOR = math.pi / 4.0' \
    'B0_FACTOR = math.pi / 3.0  # MUTATED: another vortex spacing' \
    "wake: the vortex spacing is b_0 = pi b / 4" tests/test_wake.py -k "test_the_closed_forms_b0_rc_gamma0_and_w0" \
    || failures=$((failures+1))
mutate core/environment/wake.py \
    'GL_POINTS = 32' \
    'GL_POINTS = 2  # MUTATED: a two-point rule' \
    "wake: the strip-theory integral is 32-point Gauss-Legendre" tests/test_wake.py -k "test_the_32_point_quadrature_matches_a_fine_rule_on_the_pair_field or test_the_card_block_carries_the_pair_in_the_fixed_key_order_with_the_selftest_vectors" \
    || failures=$((failures+1))
mutate core/environment/wake.py \
    '    for y0, sign in ((+0.5 * spacing_m, +1.0), (-0.5 * spacing_m, -1.0)):' \
    '    for y0, sign in ((+0.5 * spacing_m, +1.0), (-0.5 * spacing_m, +1.0)):  # MUTATED: both vortices turn the same way' \
    "wake: the pair is counter-rotating, so the far field decays as a dipole" tests/test_wake.py -k "test_v16_the_far_field_tends_to_zero_as_a_dipole" \
    || failures=$((failures+1))
mutate core/environment/wake.py \
    '    return 3.0 / b * total' \
    '    return -3.0 / b * total  # MUTATED: the sign of the equivalent roll rate' \
    "wake: a linear upwash p y gives p_eq = p (the strip-theory sign)" tests/test_wake.py -k "test_v16_p_eq_of_a_uniform_upwash_is_0_and_of_a_linear_one_is_p" \
    || failures=$((failures+1))
mutate core/environment/wake.py \
    '    elif model == "sarpkaya":' \
    '    elif model == "sarpkaya" and eps_star is not None:  # MUTATED: a missing eps* is not refused' \
    "wake: the sarpkaya decay without eps* is refused wake.decay" tests/test_wake.py -k "test_problems_refuse_by_name_and_a_block_without_a_generator_yields_nothing" \
    || failures=$((failures+1))
mutate core/environment/wake.py \
    '        elif not (_number(eps_star) and EPS_STAR_RANGE[0] < float(eps_star) <= EPS_STAR_RANGE[1]):' \
    '        elif not _number(eps_star):  # MUTATED: any number is admitted as eps*' \
    "wake: eps* outside 0 < eps* <= 1 is refused wake.decay" tests/test_wake.py -k "test_validation_refuses_the_wake_problems_by_name" \
    || failures=$((failures+1))
mutate core/environment/wake.py \
    '    if not stated:' \
    '    if False:  # MUTATED: an encounter without an age is accepted' \
    "wake: an encounter states separation_s or age_s (wake.geometry)" tests/test_wake.py -k "test_validation_refuses_the_wake_problems_by_name" \
    || failures=$((failures+1))
mutate core/environment/wake.py \
    '        probes = ((0.0, 0.0), (0.5 * b0 + rc, 0.0), (0.5 * b0, 0.5 * b0),' \
    '        probes = ((0.0, 0.0), (0.5 * b0 + 2.0 * rc, 0.0), (0.5 * b0, 0.5 * b0),  # MUTATED: the second probe moved' \
    "wake: the card's five selftest vectors are the pinned probes" tests/test_wake.py -k "test_the_card_block_carries_the_pair_in_the_fixed_key_order_with_the_selftest_vectors" \
    || failures=$((failures+1))
mutate core/environment/wake.py \
    'CARD_KEYS = ("generator", "gamma_0", "b_0", "r_c", "decay", "geometry", "selftest")' \
    'CARD_KEYS = ("gamma_0", "generator", "b_0", "r_c", "decay", "geometry", "selftest")  # MUTATED: another key order' \
    "wake: the card block's keys are in the fixed order the host reads" tests/test_wake.py -k "test_the_card_block_carries_the_pair_in_the_fixed_key_order_with_the_selftest_vectors" \
    || failures=$((failures+1))
mutate core/environment/wake.py \
    '    return INJECTIONS' \
    '    return ()  # MUTATED: a stated wake flies the stock airframe' \
    "wake: a stated generator flies the airframe derived with the gust_rotation injection" tests/test_wake.py -k "test_the_demo_run_flies_the_derived_airframe_delivers_the_field_and_reads_it_back" \
    || failures=$((failures+1))
mutate core/capture/radiometry.py \
    'CALIBRATION_CONSTANT = 1.2' \
    'CALIBRATION_CONSTANT = 1.0  # MUTATED: not ISO 12232'"'"'s 78 over ISO 2720'"'"'s 65' \
    "S1 radiometry: the calibration constant is 1.2 = 78 / (0.65 x 100)" tests/test_radiometry.py \
    || failures=$((failures+1))

mutate core/capture/radiometry.py \
    'LENS_ATTENUATION_DEFAULT = 0.78' \
    'LENS_ATTENUATION_DEFAULT = 1.0  # MUTATED: no lens attenuation' \
    "S1 radiometry: the lens attenuation A = 0.78 divides the luminance per unit" tests/test_radiometry.py \
    || failures=$((failures+1))

mutate core/capture/radiometry.py \
    '    return CALIBRATION_CONSTANT * a * math.pow(2.0, ev - ec)' \
    '    return CALIBRATION_CONSTANT * a * math.pow(2.0, ev + ec)  # MUTATED: the EC sign' \
    "S1 radiometry: +1 EC halves the luminance per unit" tests/test_radiometry.py \
    || failures=$((failures+1))

mutate core/capture/radiometry.py \
    '    return float(np.trapezoid(s * v * w, grid) / denominator)' \
    '    return float(np.trapezoid(s * w, grid) / denominator)  # MUTATED: V(lambda) dropped from K_band' \
    "S1 radiometry: K_band integrates the illuminant under V(lambda)" tests/test_radiometry.py \
    || failures=$((failures+1))

mutate core/capture/radiometry.py \
    '    if not path.is_file():
        raise RadiometryError("sensing.radiometry",' \
    '    if False:  # MUTATED: an absent table is not refused
        raise RadiometryError("sensing.radiometry",' \
    "S1 radiometry: an absent table refuses sensing.radiometry" tests/test_radiometry.py \
    || failures=$((failures+1))

mutate core/capture/radiometry.py \
    '    if digest != recorded:' \
    '    if False and digest != recorded:  # MUTATED: an altered table is accepted' \
    "S1 radiometry: a table whose digest is not its sidecar's refuses sensing.radiometry" tests/test_radiometry.py \
    || failures=$((failures+1))

mutate core/capture/radiometry.py \
    '    if data.get("proxy") is not True:' \
    '    if False:  # MUTATED: a band file need not declare itself a proxy' \
    "S1 radiometry: a band file not declared a proxy refuses sensing.band" tests/test_radiometry.py \
    || failures=$((failures+1))

mutate core/capture/radiometry.py \
    '    if units == PHYSICAL_LIGHT_UNITS:
        return numbers' \
    '    if True:  # MUTATED: any light unit passes as lux
        return numbers' \
    "S1 radiometry: a sun not in lux refuses sensing.exposure_units" tests/test_radiometry.py \
    || failures=$((failures+1))

mutate core/capture/radiometry.py \
    '    if not asked:
        return None' \
    '    if False:  # MUTATED: every camera gets a sensing block
        return None' \
    "S1 manifest: the sensing block is absent-canonical (written only when asked)" tests/test_sensing_block.py \
    || failures=$((failures+1))

mutate core/scenario/solar.py \
    'DIRECT_LUMINOUS_EFFICACY_LM_PER_W = 107.92' \
    'DIRECT_LUMINOUS_EFFICACY_LM_PER_W = 100.0  # MUTATED: not the G173 direct spectrum'"'"'s' \
    "S1 solar: the declared efficacy is the one recomputed from the cached tables" tests/test_radiometry.py \
    || failures=$((failures+1))

mutate core/scenario/solar.py \
    '    if lux > SUN_LUX_MAX:
        raise SunLuxError(' \
    '    if False:  # MUTATED: no ceiling on the sun
        raise SunLuxError(' \
    "S1 solar: a sun above the extraterrestrial illuminance refuses sensing.sun_lux" tests/test_radiometry.py \
    || failures=$((failures+1))

mutate core/scenario/solar.py \
    '    if elevation <= 0.0:' \
    '    if elevation <= -90.0:  # MUTATED: a sun below the horizon still shines' \
    "S1 solar: below the horizon the direct sun is 0 lx with its reason" tests/test_radiometry.py \
    || failures=$((failures+1))

mutate core/capture/optics.py \
    '    return 1.0 / (_positive(wavelength_m, "the wavelength") * _positive(f_number, "the f-number"))' \
    '    return 2.0 / (_positive(wavelength_m, "the wavelength") * _positive(f_number, "the f-number"))  # MUTATED' \
    "S1 optics: the diffraction cutoff is 1 / (lambda N)" tests/test_optics.py \
    || failures=$((failures+1))

mutate core/capture/optics.py \
    '    psf = psf / total                                        # energy 1' \
    '    psf = psf / (2.0 * total)                                # MUTATED: energy one half' \
    "S1 optics: the kernel is normalised to energy 1" tests/test_optics.py \
    || failures=$((failures+1))

mutate core/capture/blur.py \
    '    n = max(MIN_TAPS, int(math.ceil(2.0 * blur_px)))' \
    '    n = max(MIN_TAPS, int(math.ceil(blur_px)))  # MUTATED: taps a pixel apart' \
    "S1 blur: N = max(3, ceil(2 L)) taps" tests/test_blur.py \
    || failures=$((failures+1))

mutate core/capture/blur.py \
    '    return tuple(float(length_px) * (k / (n - 1) - 0.5) for k in range(n))' \
    '    return tuple(float(length_px) * (k / (n - 1)) for k in range(n))  # MUTATED: one-sided window' \
    "S1 blur: the tap window is symmetric about the capture instant" tests/test_blur.py \
    || failures=$((failures+1))

mutate core/capture/blur.py \
    '    if length_max == 0.0:
        return frame, block                                     # the null: nothing moved' \
    '    if False:  # MUTATED: exposure 0 still resamples the frame
        return frame, block' \
    "S1 blur: exposure 0 returns the frame itself (the null)" tests/test_blur.py \
    || failures=$((failures+1))

mutate core/capture/profile.py \
    '    for stage in POST_PASS_ORDER:' \
    '    for stage in reversed(POST_PASS_ORDER):  # MUTATED: the stages run backwards' \
    "S1 profile: the post-pass runs in POST_PASS_ORDER" tests/test_camera_profile.py \
    || failures=$((failures+1))

mutate core/capture/profile.py \
    'POST_PASS_ORDER = ("radiance", "psf", "blur", "vignetting", "geometry",
                   "exposure", "noise", "adc")' \
    'POST_PASS_ORDER = ("radiance", "blur", "psf", "vignetting", "geometry",
                   "exposure", "noise", "adc")  # MUTATED: blur before the PSF' \
    "S1 profile: the post-pass order is radiance, psf, blur, vignetting, geometry, exposure, noise, adc" tests/test_camera_profile.py \
    || failures=$((failures+1))

mutate core/capture/profile.py \
    '    if profile.optics is None:
        return image
    from .optics import convolve, optics_block' \
    '    if profile.optics is None:
        import dataclasses; profile = dataclasses.replace(profile, optics={"model": "diffraction_gaussian", "sigma_um": 100.0})  # MUTATED
    from .optics import convolve, optics_block' \
    "S1 profile: an absent optics block leaves the frame bit-identical" tests/test_optics.py \
    || failures=$((failures+1))

mutate core/scenario/camera.py \
    '            if q.to_dict() != defaults[name].to_dict():
                out[name] = q.to_dict()' \
    '            if True:  # MUTATED: the sensing fields always serialise
                out[name] = q.to_dict()' \
    "S1 camera: the two sensing fields are absent-canonical (every example keeps its digest)" tests/test_registry.py \
    || failures=$((failures+1))

mutate core/render/flags.py \
    '    for token in sensing_flags(calibration, sun_lux, accumulate):' \
    '    for token in sensing_flags(True, sun_lux, accumulate):  # MUTATED: -calibration by default' \
    "S1 flags: the sensing flags are emitted only when asked (the default list is byte-identical)" tests/test_render_flags.py tests/test_annotation_passes.py \
    || failures=$((failures+1))

mutate core/capture/verify.py \
    '        if error > PSF_MTF50_TOL:' \
    '        if False and error > PSF_MTF50_TOL:  # MUTATED: any MTF50 passes' \
    "S1 verify: psf_slanted_edge fails annotation.psf beyond the MTF50 tolerance" tests/test_radiometry.py \
    || failures=$((failures+1))

mutate core/capture/verify.py \
    '            if error > tolerance:' \
    '            if False and error > tolerance:  # MUTATED: any streak passes' \
    "S1 verify: blur_vs_flow fails annotation.blur beyond the streak tolerance" tests/test_radiometry.py \
    || failures=$((failures+1))

mutate core/capture/verify.py \
    '        if abs(ratio - 1.0) > GREY_CARD_TOL:' \
    '        if False:  # MUTATED: any grey-card ratio passes' \
    "S1 verify: radiometry_grey_card fails annotation.radiometry beyond 2 %" tests/test_radiometry.py \
    || failures=$((failures+1))

mutate core/registry.py \
    '        name="scene.sun_lux", spec_path="scene.sun_lux", unit="lx",' \
    '        name="scene.sun_lux", spec_path="scene.sun_lux", unit="lux",  # MUTATED' \
    "S1 registry: scene.sun_lux is registered in lux (lx)" tests/test_sensing_block.py \
    || failures=$((failures+1))

mutate core/scenario/blocks.py \
    '    OPTIONAL_FIELDS = ("sun_lux", "buildings", "night")' \
    '    OPTIONAL_FIELDS = ("buildings", "night")  # MUTATED: sun_lux always serialises' \
    "S1 blocks: sun_lux is absent-canonical inside the scene block (the mountain example keeps its digest)" tests/test_sensing_block.py \
    || failures=$((failures+1))

mutate core/scenario/validate.py \
    '    if sun_problem:' \
    '    if False:  # MUTATED: a stated sun is never refused' \
    "S1 validate: a stated sun outside its range refuses sensing.sun_lux" tests/test_sensing_block.py \
    || failures=$((failures+1))

mutate core/capture/validate.py \
    '        except RadiometryError as exc:
            out.append(Violation(exc.constraint, f"{who}: {exc.message}"))' \
    '        except RadiometryError as exc:
            pass  # MUTATED: an unknown band file is not refused' \
    "S1 capture validate: an unknown band file refuses sensing.band" tests/test_sensing_block.py \
    || failures=$((failures+1))

mutate flightsim/capture.py \
    '        calibration=bool(args.calibration), sun_lux=sun_lux_flag,' \
    '        calibration=False, sun_lux=sun_lux_flag,  # MUTATED: --calibration ignored' \
    "S1 capture: --calibration reaches the render command" tests/test_sensing_block.py \
    || failures=$((failures+1))

mutate flightsim/capture.py \
    '                if problem:
                    raise SunLuxError(problem)' \
    '                if False:  # MUTATED: a bad sun reaches the render
                    raise SunLuxError(problem)' \
    "S1 capture: a --sun-lux outside its range is refused before any render" tests/test_sensing_block.py \
    || failures=$((failures+1))

mutate core/capture/poses.py \
    '        if getattr(camera, "sensing_stated", None) is not None and camera.sensing_stated():' \
    '        if False:  # MUTATED: the card never carries the sensing keys' \
    "S1 poses: the card's camera entry carries the stated sensing keys" tests/test_sensing_block.py \
    || failures=$((failures+1))


if [ "$guard_n" -ne "$total" ]; then
    echo "INTERNAL: $guard_n mutate calls ran but $total are written; the count is off" >&2
    exit 1
fi

if [ "$run_suite" -eq 1 ]; then
    echo
    purge_cache
    if $PYTEST -q >/dev/null 2>&1; then echo "Restored: suite is green"; else
        echo "Restored: SUITE IS NOT GREEN -- a restore failed"; exit 1; fi
fi

echo
case "$mode" in
    list) exit 0 ;;
    check)
        if [ "$failures" -eq 0 ]; then
            echo "All $ran target(s) occur exactly once in their file."
        else
            echo "$failures of $ran target(s) are missing or ambiguous: their guards cannot fire."
        fi
        exit "$failures" ;;
esac
if [ "$failures" -eq 0 ]; then
    echo "All $ran guard(s) run are load-bearing. (${SECONDS}s)"
else
    echo "$failures of $ran guard(s) run are not covered by a failing test. (${SECONDS}s)"
fi
if [ "$ran" -ne "$total" ] || [ "$run_suite" -ne 1 ]; then
    echo "This was a subset ($ran of $total guards; full suite $([ "$run_suite" -eq 1 ] && echo run || echo skipped)); the contract is the plain run."
fi
exit "$failures"
