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

mutate core/scenario/envelope.py \
    '        lift_lbs = fdm.props.get("forces/fwz-aero-lbs")' \
    '        lift_lbs = -fdm.props.get("forces/fwz-aero-lbs")' \
    "lift-curve sign" tests/test_validation_and_run.py || failures=$((failures+1))

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
