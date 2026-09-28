"""The null pair: the same run with the variable at its null value, and
the measured effect per channel (ADVANCEMENTS_BLUEPRINT section 2, R1).

:func:`run_null_pair` takes a spec and a registered variable name, builds
the IDENTICAL spec with that one field at the registry's null value (or
absent, when the null value is None), runs both through the runner, and
measures, per registered effect channel, the peak absolute and RMS
difference between the two recordings, in the channel's registered
unit, against the null-effect FLOOR for that unit. The verdict is
``reached`` when any graded channel moved by at least its floor,
``silent`` when none did, ``ungraded`` when no channel has a floor. Both
output digests ride with the result, so a consumer can see that the
two flights were different flights (or that they were not).

The floors are 10 x the branch's own numerical noise, measured in row V9
of docs/vva/VV_REPORT.md: peak altitude difference 0.098 m between the
1/60 and 1/120 s steps and 0.048 m between 1/120 and 1/240 s (observed
order p = 1.03). Ten times that is 0.5 m for altitude; the angle and
speed floors are the blueprint's stated companions (0.05 deg, 0.1 kt).
An effect below its floor is indistinguishable from the integrator.

The runner is injectable (``runner(spec) -> RunResult``); the default
is :func:`core.scenario.runner.run_spec`. Refusals by name:
``record.unregistered`` (no entry), ``record.null_value`` (no spec
field to null, the field not stated, or the stated value IS the null
value: the pair would compare a run with itself), ``record.effect_channel``
(no registered effect channel, or a registered one the run did not
record).

NOT claimed: a null pair is connectivity and one-sided sensitivity, not
correctness -- it says the variable reached the equations of motion and
by how much on this run, not that the amount is right. The floors grade
against the integrator's noise at the branch's stock rates; a run at
another rate has other noise. A channel with no floor is reported, not
graded. Today no spec-8 field is a registered spec field (the atmosphere
block lands with P1), so :func:`null_pairs_for_spec` over a committed
example returns nothing -- measured in tests/test_record_null.py, where
the mechanics are exercised on a test registry over ``environment.wind_speed``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .records import NullTest
from .registry import REGISTRY, NO_NULL, RecordError, Registry, VariableRecord

#: 1 kt in m/s (exact: 1852 m per hour).
KT_TO_MPS = 1852.0 / 3600.0

#: The null-effect floors: 10 x the V9 numerical noise (docs/vva/VV_REPORT.md
#: row V9: 0.098 m at 1/60 vs 1/120 s, 0.048 m at 1/120 vs 1/240 s, p = 1.03).
NULL_FLOOR_ALTITUDE_M = 0.5
NULL_FLOOR_ANGLE_DEG = 0.05
NULL_FLOOR_SPEED_KT = 0.1
#: The atmosphere's own channels (P1): a tenth of a unit, a STATED choice --
#: far above the read-back noise measured for them (delta-T and P-sl exact,
#: RH 1.0e-10 relative, the dew point 1.5e-6 R per step) and far below the
#: smallest vocabulary step (15 K, 20 %).
NULL_FLOOR_TEMPERATURE_K = 0.1
NULL_FLOOR_HUMIDITY_PCT = 0.1
NULL_FLOOR_PRESSURE_HPA = 0.1
NULL_FLOOR_VAPOUR_PA = 1.0
#: The injections' channels (P2): a stated 1 N (the lift factor 0.8 moved 1666 N;
#: the trimmed c172p's own one-step drift is 1e-3 N) and 0.1 deg/s.
NULL_FLOOR_FORCE_N = 1.0
NULL_FLOOR_RATE_DPS = 0.1
NULL_FLOOR_REFERENCE = (
    "10 x the numerical noise measured on this branch (docs/vva/VV_REPORT.md row V9: "
    "peak altitude difference 0.098 m between 1/60 and 1/120 s, 0.048 m between 1/120 "
    "and 1/240 s, observed order p = 1.03): altitude 0.5 m, angles 0.05 deg, speeds 0.1 kt; "
    "the atmosphere's own channels a stated tenth of a unit (0.1 K, 0.1 %, 0.1 hPa, 1 Pa), "
    "above their measured read-back noise and below the smallest vocabulary step; the "
    "injections' force and rate channels a stated 1 N and 0.1 deg/s (P2)")

#: Floor per channel unit; a unit not listed has no floor (reported, not graded).
FLOORS_BY_UNIT: Dict[str, float] = {
    "m": NULL_FLOOR_ALTITUDE_M,
    "deg": NULL_FLOOR_ANGLE_DEG,
    "kt": NULL_FLOOR_SPEED_KT,
    "m/s": NULL_FLOOR_SPEED_KT * KT_TO_MPS,
    "K": NULL_FLOOR_TEMPERATURE_K,
    "%": NULL_FLOOR_HUMIDITY_PCT,
    "hPa": NULL_FLOOR_PRESSURE_HPA,
    "Pa": NULL_FLOOR_VAPOUR_PA,
    "N": NULL_FLOOR_FORCE_N,
    "deg/s": NULL_FLOOR_RATE_DPS,
}


def floor_for_unit(unit: str) -> Optional[float]:
    """The null-effect floor for a channel unit, or None when none is stated."""
    return FLOORS_BY_UNIT.get(unit)


@dataclass(frozen=True)
class ChannelEffect:
    """The measured difference on one channel between the pair."""

    channel: str
    unit: str
    peak_abs: float
    rms: float
    floor: Optional[float]
    samples: int
    peak_index: int
    with_at_peak: float
    without_at_peak: float

    @property
    def reached(self) -> Optional[bool]:
        """None when the unit has no floor (reported, not graded)."""
        if self.floor is None:
            return None
        return self.peak_abs >= self.floor

    def to_dict(self) -> Dict[str, Any]:
        return {"channel": self.channel, "unit": self.unit, "peak_abs": self.peak_abs,
                "rms": self.rms, "floor": self.floor, "reached": self.reached,
                "samples": self.samples, "peak_index": self.peak_index,
                "with_at_peak": self.with_at_peak, "without_at_peak": self.without_at_peak}


@dataclass(frozen=True)
class NullPair:
    """One null pair, measured."""

    variable: str
    spec_path: str
    applied_value: Any
    null_value: Any
    with_spec_digest: str
    with_output_digest: str
    without_spec_digest: str
    without_output_digest: str
    effects: Tuple[ChannelEffect, ...]
    elapsed_s: float
    basis: str = NULL_FLOOR_REFERENCE
    notes: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def verdict(self) -> str:
        graded = [e for e in self.effects if e.reached is not None]
        if not graded:
            return "ungraded"
        return "reached" if any(e.reached for e in graded) else "silent"

    @property
    def digests_differ(self) -> bool:
        return self.with_output_digest != self.without_output_digest

    @property
    def strongest(self) -> ChannelEffect:
        """The channel that moved most relative to its floor (graded
        channels first; among ungraded, the largest peak)."""
        graded = [e for e in self.effects if e.floor]
        if graded:
            return max(graded, key=lambda e: e.peak_abs / e.floor)
        return max(self.effects, key=lambda e: e.peak_abs)

    def null_test(self) -> NullTest:
        """The record's null test: ``reached`` on the strongest channel,
        with/without at the sample of peak difference, threshold = floor."""
        best = self.strongest
        return NullTest(
            quantity=f"{best.channel} at the sample of peak |with - without| (null pair)",
            unit=best.unit, with_value=best.with_at_peak, without_value=best.without_at_peak,
            threshold=best.floor if best.floor is not None else 0.0,
            kind="reached",
            note=(f"without = the identical spec with {self.spec_path} at its null value "
                  f"{self.null_value!r}; verdict {self.verdict} over {len(self.effects)} "
                  f"channel(s); output digests {'differ' if self.digests_differ else 'are equal'}"
                  + ("" if best.floor is not None else
                     f"; no floor is stated for unit {best.unit!r}, so the threshold 0 grades nothing")))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variable": self.variable, "kind": "reached", "spec_path": self.spec_path,
            "applied_value": self.applied_value, "null_value": self.null_value,
            "digests": {"with": {"spec": self.with_spec_digest, "output": self.with_output_digest},
                        "without": {"spec": self.without_spec_digest,
                                    "output": self.without_output_digest},
                        "differ": self.digests_differ},
            "effect": {e.channel: e.to_dict() for e in self.effects},
            "verdict": self.verdict,
            "floors": {"altitude_m": NULL_FLOOR_ALTITUDE_M, "angle_deg": NULL_FLOOR_ANGLE_DEG,
                       "speed_kt": NULL_FLOOR_SPEED_KT, "by_unit": dict(FLOORS_BY_UNIT),
                       "reference": NULL_FLOOR_REFERENCE},
            "basis": self.basis, "elapsed_s": self.elapsed_s, "notes": list(self.notes),
            "null_test": self.null_test().to_dict(),
        }


def null_spec_dict(data: Mapping[str, Any], entry: VariableRecord) -> Dict[str, Any]:
    """The spec dict with the entry's field at its null value -- for a
    null of None, the field UNSTATED (``value: null``), the one form every
    provenanced block reads back; a block lists every field, so a removed
    key would not be a spec. Refuses ``record.null_value`` when the entry
    has no spec field, the spec does not state it, or the stated value
    already is the null."""
    if entry.spec_path is None:
        raise RecordError("record.null_value",
                          f"{entry.name} has no spec field to set to a null value; its null "
                          f"test is measured by its producer ({entry.null_basis})")
    if entry.null_value is NO_NULL:
        raise RecordError("record.null_value", f"{entry.name} registers no null value")
    section, leaf = entry.spec_path.split(".")
    block = data.get(section)
    if not isinstance(block, Mapping) or leaf not in block:
        raise RecordError("record.null_value",
                          f"the spec states no {entry.spec_path}, so there is nothing to null")
    applied = block[leaf].get("value") if isinstance(block[leaf], Mapping) else block[leaf]
    if applied == entry.null_value:
        raise RecordError("record.null_value",
                          f"the spec's {entry.spec_path} is {applied!r}, which IS the null value; "
                          f"the pair would compare a run with itself")
    out = {k: (dict(v) if isinstance(v, Mapping) else v) for k, v in data.items()}
    stated = dict(block[leaf]) if isinstance(block[leaf], Mapping) else {}
    out[section][leaf] = {
        "value": entry.null_value,
        **({"unit": stated["unit"]} if "unit" in stated else {}),
        "source": "derived",
        "from": (f"null pair: the registry's null value for {entry.name} ({entry.null_basis})"
                 if entry.null_value is not None else
                 f"null pair: {entry.name} unstated ({entry.null_basis})"),
    }
    return out


def _effects(entry: VariableRecord, with_cols: Mapping[str, Sequence[float]],
             without_cols: Mapping[str, Sequence[float]]) -> Tuple[Tuple[ChannelEffect, ...], List[str]]:
    import numpy as np

    if not entry.effect_channels:
        raise RecordError("record.effect_channel",
                          f"{entry.name} registers no effect channel, so a null pair has "
                          f"nothing to measure")
    effects: List[ChannelEffect] = []
    notes: List[str] = []
    for channel in entry.effect_channels:
        if channel.name not in with_cols or channel.name not in without_cols:
            raise RecordError("record.effect_channel",
                              f"{entry.name} registers effect channel {channel.name!r}, which "
                              f"the run did not record (recorded: {sorted(with_cols)})")
        a = np.asarray(with_cols[channel.name], dtype=float)
        b = np.asarray(without_cols[channel.name], dtype=float)
        n = min(len(a), len(b))
        if len(a) != len(b):
            notes.append(f"{channel.name}: {len(a)} with vs {len(b)} without samples; "
                         f"the first {n} compared")
        if n == 0:
            raise RecordError("record.effect_channel",
                              f"{channel.name!r} was recorded with no samples")
        d = a[:n] - b[:n]
        if channel.unit == "deg":
            d = (d + 180.0) % 360.0 - 180.0       # a heading wraps; its difference does not
        k = int(np.argmax(np.abs(d)))
        effects.append(ChannelEffect(
            channel=channel.name, unit=channel.unit, peak_abs=float(abs(d[k])),
            rms=float(np.sqrt(np.mean(d * d))), floor=floor_for_unit(channel.unit),
            samples=n, peak_index=k, with_at_peak=float(a[k]), without_at_peak=float(b[k])))
    return tuple(effects), notes


def _default_runner() -> Callable[[Any], Any]:
    from .scenario.runner import run_spec

    return lambda spec: run_spec(spec, assert_closure=False)


def run_null_pair(spec, variable_name: str, runner: Optional[Callable[[Any], Any]] = None,
                  registry: Registry = REGISTRY) -> NullPair:
    """The identical case with ``variable_name`` at its null value, both
    runs measured (see the module docstring)."""
    from .scenario.spec import ScenarioSpec

    entry = registry.get(variable_name)
    data = spec.to_dict()
    null_data = null_spec_dict(data, entry)
    section, leaf = entry.spec_path.split(".")
    applied = data[section][leaf]["value"]
    null_spec = ScenarioSpec.from_dict(null_data)
    run = runner if runner is not None else _default_runner()
    t0 = time.perf_counter()
    with_result = run(spec)
    without_result = run(null_spec)
    elapsed = time.perf_counter() - t0
    effects, notes = _effects(entry, with_result.telemetry.columns,
                              without_result.telemetry.columns)
    return NullPair(
        variable=entry.name, spec_path=entry.spec_path, applied_value=applied,
        null_value=entry.null_value,
        with_spec_digest=with_result.spec_digest, with_output_digest=with_result.output_digest,
        without_spec_digest=without_result.spec_digest,
        without_output_digest=without_result.output_digest,
        effects=effects, elapsed_s=elapsed, notes=tuple(notes))


def null_pairs_for_spec(spec, runner: Optional[Callable[[Any], Any]] = None,
                        registry: Registry = REGISTRY) -> Dict[str, NullPair]:
    """One null pair per registered spec field the spec states at a value
    other than its null. An unstated field (``value: null``, the form a
    block keeps for what was not said) runs none: nothing was applied.
    Empty when the spec states no registered section (every spec-8 field)."""
    data = spec.to_dict()
    out: Dict[str, NullPair] = {}
    for name, stated in registry.stated_variables(data).items():
        entry = registry.get(name)
        if stated.get("value") is None:
            continue                     # unstated (a block lists every field): nothing applied
        if stated.get("value") == entry.null_value:
            continue                     # at the null already: no pair to run
        out[name] = run_null_pair(spec, name, runner=runner, registry=registry)
    return out


def null_pairs_block(pairs: Mapping[str, NullPair]) -> Dict[str, Any]:
    """The manifest / run.json block: every pair by variable name."""
    return {name: pair.to_dict() for name, pair in pairs.items()}


def attach_null_pair(manifest: Dict[str, Any], pair: NullPair) -> bool:
    """Write the pair's null test into the variable's record in the
    manifest's ``applied_variables`` block, with the pair's digests,
    effects and verdict beside it. Returns False (and writes nothing)
    when no record of that name is in the block -- the record is the
    producer's to attach; the pair then lives in ``null_tests`` only."""
    block = manifest.get("applied_variables") or {}
    for record in block.get("applied_variables", ()):
        if record.get("name") == pair.variable:
            null = pair.null_test().to_dict()
            null.update({"null_value": pair.null_value,
                         "digests": pair.to_dict()["digests"],
                         "effect": {e.channel: e.to_dict() for e in pair.effects},
                         "verdict": pair.verdict, "basis": pair.basis})
            record["null_test"] = null
            return True
    return False
