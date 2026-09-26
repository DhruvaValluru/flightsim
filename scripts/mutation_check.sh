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
    'SUPPORTED_MANIFEST_VERSIONS = (3, 4, 5, 6)' \
    'SUPPORTED_MANIFEST_VERSIONS = (4, 5, 6)  # MUTATED: every earlier run refused' \
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
                     "_depth.f32": DEPTH_CHECKS}' \
    'LABEL_FILE_CHECKS = {"_mask.png": MASK_CHECKS, "_class.png": (),
                     "_depth.f32": ()}  # MUTATED: class image and depth ship ungraded' \
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
            pending_blank = 0
            after_banner = True
            return' \
    '        if False:  # MUTATED: banner lines relayed
            pending_blank = 0
            after_banner = True
            return' \
    "the relay drops exactly the banner lines" \
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
    '    if len(traffic_tracks) != len(spec.traffic):
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
