"""Operational and structural limit monitoring (gap P5, advancement I2).

Every airframe flies inside an envelope its certification states: a
load-factor band by category (14 CFR 23.337 for normal, utility and
aerobatic aeroplanes; 14 CFR 25.337 for transports), a never-exceed or
maximum operating speed (V_NE / V_MO) and, for a jet, a maximum operating
Mach (M_MO). The recorder has always logged ``n_z``, ``cas_kt`` and
``mach``; nothing compared them with a limit. This module does, AFTER the
run, as an observer: it reads the recorded columns, writes 0/1 flag
columns beside them, and summarises the exceedances. It writes no JSBSim
property and changes no trajectory.

The limits table lives in ``assets/aircraft_config/<name>.json`` under
``limits``. Every number carries a ``source`` string; a limit the table
cannot source is ``null`` with a ``reason``, and that limit is reported
unmonitored rather than compared against a guess. An airframe with no
``limits`` block is reported ``{monitored: false, reason}`` and never
refuses. A block that is present and malformed refuses by name
(``limits.config``): a number without a source, a source without a
number, a positive negative-g limit, an unknown key.

Comparison is strict: a sample is flagged when its value is BEYOND the
limit (``>`` a positive limit, ``<`` a negative one). A sample exactly at
the limit is at the limit, not past it, and is not flagged.

Not claimed: any position-error correction (the speed limits are placard
KIAS figures compared against JSBSim's calibrated airspeed, ``vc-kts``);
any gust or manoeuvre load beyond what the FDM's accelerometer reports;
a stall-alpha limit for a model that states none (none of the five
configured models does, measured 2026-09-28); structural damage,
fatigue or any consequence of an exceedance -- the run continues and is
flagged, not stopped; the correctness of the placard values themselves,
each of which the table cites as verified or ``unverified here``.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..records import AppliedVariable, Model, NullTest

REPO = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO / "assets" / "aircraft_config"

#: The limits a table states, in the order the summary lists them.
LIMIT_KEYS = ("n_z_pos_g", "n_z_neg_g", "speed_limit_kt", "m_mo", "alpha_stall_deg")
#: Every key a ``limits`` block may carry.
BLOCK_KEYS = ("category", *LIMIT_KEYS, "note")
#: Certification categories the table may name (14 CFR 23.3 / 25.1; the
#: military word is for a type with no civil category, applied as a
#: stated proxy).
CATEGORIES = ("normal", "utility", "aerobatic", "commuter", "transport", "military")
SPEED_KINDS = ("V_NE", "V_MO")

#: (limit key, flag column, telemetry channel, sense, unit). ``above``:
#: flagged when value > limit; ``below``: flagged when value < limit.
CHECKS: Tuple[Tuple[str, str, str, str, str], ...] = (
    ("n_z_pos_g", "exceed_nz_pos", "n_z", "above", "g"),
    ("n_z_neg_g", "exceed_nz_neg", "n_z", "below", "g"),
    ("speed_limit_kt", "exceed_vne_or_vmo", "cas_kt", "above", "kt CAS"),
    ("m_mo", "exceed_mmo", "mach", "above", "Mach"),
    ("alpha_stall_deg", "exceed_alpha_stall", "alpha_deg", "above", "deg"),
)
ANY_COLUMN = "any_exceedance"
COMPARISON = ("strict: a sample is flagged when its value is beyond the limit "
              "(> a positive limit, < a negative one); a sample exactly at the "
              "limit is not flagged")

#: The null-test probe: how far beyond (or inside) the limit this run's
#: own samples are pushed to show the monitor discriminates.
PROBE_OFFSET = {"speed_limit_kt": 20.0, "n_z_pos_g": 0.5}

RECORD_NAME = "limits.monitor"
MODEL = "exceedance monitor against the certification envelope"


class LimitsConfigError(Exception):
    """A ``limits`` block is present and malformed; refused by name."""

    constraint = "limits.config"

    def __init__(self, aircraft: str, message: str) -> None:
        self.aircraft = aircraft
        self.message = message
        super().__init__(f"limits.config: {aircraft}: {message}")


# -- the table ----------------------------------------------------------------

@dataclass(frozen=True)
class Limit:
    key: str
    value: Optional[float]
    unit: str
    source: Optional[str] = None       # required when value is a number
    reason: Optional[str] = None       # required when value is null
    kind: Optional[str] = None         # V_NE or V_MO for the speed limit

    @property
    def monitored(self) -> bool:
        return self.value is not None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"value": self.value, "unit": self.unit}
        if self.kind is not None:
            out["kind"] = self.kind
        if self.source is not None:
            out["source"] = self.source
        if self.reason is not None:
            out["reason"] = self.reason
        return out


@dataclass(frozen=True)
class LimitsTable:
    aircraft: str
    category: Optional[str]
    regulation: Optional[str]
    category_source: Optional[str]
    limits: Dict[str, Limit]
    note: Optional[str] = None
    config_path: str = ""
    config_sha256: str = ""

    def limit(self, key: str) -> Limit:
        return self.limits[key]

    def monitored_keys(self) -> Tuple[str, ...]:
        return tuple(k for k in LIMIT_KEYS if self.limits[k].monitored)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "aircraft": self.aircraft,
            "category": {"value": self.category, "regulation": self.regulation,
                         "source": self.category_source},
            "limits": {k: self.limits[k].to_dict() for k in LIMIT_KEYS},
            "note": self.note,
            "config_path": self.config_path,
            "config_sha256": self.config_sha256,
        }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def parse_limits(aircraft: str, block: Any, config_path: str = "",
                 config_sha256: str = "") -> LimitsTable:
    """A ``limits`` block into a table, or ``LimitsConfigError`` by name.

    Every limit key must be present; a number needs a non-empty
    ``source`` and a null needs a non-empty ``reason``; the positive
    load-factor limit is positive, the negative one negative, the speed
    limit positive with a ``kind`` of V_NE or V_MO, M_MO in (0, 1),
    a stall alpha in (0, 90) deg; an unknown key is refused rather than
    ignored (a misspelt limit would otherwise be a limit nobody
    monitored).
    """
    def refuse(message: str) -> LimitsConfigError:
        return LimitsConfigError(aircraft, message)

    if not isinstance(block, dict):
        raise refuse(f"'limits' must be a mapping, not {type(block).__name__}")
    unknown = sorted(set(block) - set(BLOCK_KEYS))
    if unknown:
        raise refuse(f"unknown keys {unknown}; a limits block carries "
                     f"{list(BLOCK_KEYS)}")
    missing = [k for k in LIMIT_KEYS if k not in block]
    if missing:
        raise refuse(f"missing {missing}; a limit the table cannot source is "
                     f"written null with a reason, never omitted")

    category = block.get("category")
    cat_value = regulation = cat_source = None
    if category is not None:
        if not isinstance(category, dict):
            raise refuse("category must be a mapping {value, regulation, source}")
        cat_value = category.get("value")
        if cat_value not in CATEGORIES:
            raise refuse(f"category {cat_value!r} is not one of {list(CATEGORIES)}")
        regulation = category.get("regulation")
        cat_source = category.get("source")
        if not _text(regulation) or not _text(cat_source):
            raise refuse("category needs a regulation and a source")

    limits: Dict[str, Limit] = {}
    for key, _column, _channel, sense, unit in CHECKS:
        entry = block[key]
        if not isinstance(entry, dict) or "value" not in entry:
            raise refuse(f"{key} must be a mapping with a 'value'")
        value = entry["value"]
        source = entry.get("source")
        reason = entry.get("reason")
        kind = entry.get("kind")
        allowed = {"value", "source", "reason"} | ({"kind"} if key == "speed_limit_kt" else set())
        extra = sorted(set(entry) - allowed)
        if extra:
            raise refuse(f"{key} carries unknown keys {extra}")
        if value is None:
            if not _text(reason):
                raise refuse(f"{key} is null without a reason")
            limits[key] = Limit(key, None, unit, source=None, reason=reason,
                                kind=kind if key == "speed_limit_kt" else None)
            continue
        if not _is_number(value) or not math.isfinite(value):
            raise refuse(f"{key} must be a finite number or null, not {value!r}")
        if not _text(source):
            raise refuse(f"{key} = {value} has no source; every number is cited")
        value = float(value)
        if key == "n_z_pos_g" and not value > 0.0:
            raise refuse(f"n_z_pos_g must be positive, not {value}")
        if key == "n_z_neg_g" and not value < 0.0:
            raise refuse(f"n_z_neg_g must be negative, not {value}")
        if key == "speed_limit_kt":
            if not value > 0.0:
                raise refuse(f"speed_limit_kt must be positive, not {value}")
            if kind not in SPEED_KINDS:
                raise refuse(f"speed_limit_kt needs kind V_NE or V_MO, not {kind!r}")
        if key == "m_mo" and not 0.0 < value < 1.0:
            raise refuse(f"m_mo must lie in (0, 1) for the subsonic types "
                         f"configured here, not {value}")
        if key == "alpha_stall_deg" and not 0.0 < value < 90.0:
            raise refuse(f"alpha_stall_deg must lie in (0, 90), not {value}")
        limits[key] = Limit(key, value, unit, source=source, reason=None,
                            kind=kind if key == "speed_limit_kt" else None)
    note = block.get("note")
    if note is not None and not _text(note):
        raise refuse("note must be text when present")
    return LimitsTable(aircraft, cat_value, regulation, cat_source, limits,
                       note=note, config_path=config_path,
                       config_sha256=config_sha256)


def load_limits(aircraft: str, config_dir: Optional[Path] = None) -> Optional[LimitsTable]:
    """The airframe's table, or None when it has no config or no block.

    None is not a refusal: an airframe without stated limits is flown
    and recorded ``monitored: false``. A block that is present and
    malformed raises ``LimitsConfigError`` (``limits.config``).
    """
    directory = Path(config_dir) if config_dir is not None else CONFIG_DIR
    path = directory / f"{aircraft}.json"
    if not path.is_file():
        return None
    raw = path.read_bytes()
    try:
        config = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise LimitsConfigError(aircraft, f"{path.name} is not readable JSON: {exc}") from exc
    if not isinstance(config, dict) or "limits" not in config:
        return None
    try:
        rel = path.resolve().relative_to(REPO).as_posix()   # the same string on Windows
    except ValueError:
        rel = str(path)
    return parse_limits(aircraft, config["limits"], config_path=rel,
                        config_sha256=hashlib.sha256(raw).hexdigest())


def unmonitored_reason(aircraft: str, config_dir: Optional[Path] = None) -> str:
    directory = Path(config_dir) if config_dir is not None else CONFIG_DIR
    path = directory / f"{aircraft}.json"
    if not path.is_file():
        return f"no aircraft config at {path.name}: no limits stated for {aircraft}"
    return f"{path.name} has no 'limits' block: no limits stated for {aircraft}"


# -- the monitor ----------------------------------------------------------------

@dataclass
class MonitorResult:
    """The flag columns (0/1 ints, one per sample) and the summary."""

    flags: Dict[str, List[int]] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)

    @property
    def columns(self) -> Tuple[str, ...]:
        return tuple(self.flags)


def _flag(value: float, limit: float, sense: str) -> int:
    if sense == "above":
        return 1 if value > limit else 0
    return 1 if value < limit else 0


def _margin(value: float, limit: float, sense: str) -> float:
    """Distance INSIDE the limit (positive = inside, negative = beyond)."""
    return (limit - value) if sense == "above" else (value - limit)


def monitor(columns: Mapping[str, Sequence[float]], limits: LimitsTable) -> MonitorResult:
    """Flag every sample beyond a stated limit; summarise per limit.

    ``columns`` is the recorder's mapping (``t`` plus the channels each
    limit reads). A limit whose channel is not in the columns is
    reported unmonitored with that reason rather than skipped silently.
    The columns are read, never written: :func:`annotate` is the step
    that adds the flags to a recorder.
    """
    if "t" not in columns:
        raise ValueError("limits.monitor needs the 't' column to date an exceedance")
    t = [float(v) for v in columns["t"]]
    n = len(t)
    for name, values in columns.items():
        if len(values) != n:
            raise ValueError(f"column {name!r} has {len(values)} samples where 't' "
                             f"has {n}; the monitor reads one telemetry table")
    result = MonitorResult()
    per_limit: Dict[str, Any] = {}
    unmonitored: Dict[str, str] = {}
    any_flags = [0] * n
    for key, column, channel, sense, unit in CHECKS:
        limit = limits.limit(key)
        if not limit.monitored:
            unmonitored[key] = limit.reason or "no value stated"
            per_limit[key] = {"limit": None, "unit": unit, "kind": limit.kind,
                              "channel": channel, "column": None,
                              "monitored": False, "reason": unmonitored[key]}
            continue
        if channel not in columns:
            unmonitored[key] = f"channel {channel!r} not recorded"
            per_limit[key] = {"limit": limit.value, "unit": unit, "kind": limit.kind,
                              "channel": channel, "column": None,
                              "monitored": False, "reason": unmonitored[key],
                              "source": limit.source}
            continue
        values = [float(v) for v in columns[channel]]
        flags = [_flag(v, limit.value, sense) for v in values]
        margins = [_margin(v, limit.value, sense) for v in values]
        count = int(sum(flags))
        first = next((t[i] for i, f in enumerate(flags) if f), None)
        if margins:
            worst_i = min(range(n), key=lambda i: margins[i])
            worst = {"worst_margin": margins[worst_i], "worst_value": values[worst_i],
                     "worst_t_s": t[worst_i]}
        else:
            worst = {"worst_margin": None, "worst_value": None, "worst_t_s": None}
        result.flags[column] = flags
        any_flags = [a | f for a, f in zip(any_flags, flags)]
        per_limit[key] = {"limit": limit.value, "unit": unit, "kind": limit.kind,
                          "channel": channel, "column": column, "monitored": True,
                          "count": count, "first_exceedance_s": first, **worst,
                          "source": limit.source}
    result.flags[ANY_COLUMN] = any_flags
    any_count = int(sum(any_flags))
    result.summary = {
        "samples": n,
        "comparison": COMPARISON,
        "monitored": [k for k in LIMIT_KEYS if per_limit[k]["monitored"]],
        "unmonitored": unmonitored,
        "per_limit": per_limit,
        "any_exceedance": {
            "column": ANY_COLUMN,
            "count": any_count,
            "fraction": (any_count / n) if n else None,
            "first_exceedance_s": next((t[i] for i, f in enumerate(any_flags) if f), None),
        },
        "columns_added": list(result.flags),
    }
    return result


def annotate(recorder, result: MonitorResult) -> List[str]:
    """Write the flag columns into a recorder after its run.

    ``Recorder.annotate`` refuses a name clash or a length mismatch, so
    a flag column can neither shadow a recorded channel nor be shorter
    than the run. Returns the names added.
    """
    added = []
    for name, values in result.flags.items():
        recorder.annotate(name, values)
        added.append(name)
    return added


# -- the record ------------------------------------------------------------------

def null_test(columns: Mapping[str, Sequence[float]], limits: LimitsTable) -> Optional[NullTest]:
    """With-versus-without, measured on this run's own samples.

    The monitor's variable is the envelope; its trace is the flags. The
    test compares the flags on the side of the limit the run was flown
    on with the flags on the other side, reached by offsetting this
    run's own samples of the probe channel (the speed limit + 20 kt, the
    ``V_NE + 20`` case of the contract; the positive load-factor limit +
    0.5 g for a type with no stated speed limit). ``with`` is the
    over-limit side, ``without`` the inside; the note says which side
    was flown. A run inside the envelope therefore reads ``with = every
    probed sample beyond, without = 0``; a run beyond it reads ``with =
    as flown, without = 0`` once pushed back inside. Either way a
    monitor that discriminates measures a difference of at least one
    sample. None when no probe limit is monitored or its channel is
    absent -- there is nothing to test.
    """
    for key in ("speed_limit_kt", "n_z_pos_g"):
        limit = limits.limit(key)
        column, channel, sense, unit = next(
            (c, ch, s, u) for k, c, ch, s, u in CHECKS if k == key)
        if not limit.monitored or channel not in columns or not len(columns[channel]):
            continue
        offset = PROBE_OFFSET[key]
        values = [float(v) for v in columns[channel]]
        flown = int(sum(_flag(v, limit.value, sense) for v in values))
        peak = max(values)
        flown_beyond = peak > limit.value
        # Push the peak to offset beyond the limit, or offset inside it.
        target = (limit.value - offset) if flown_beyond else (limit.value + offset)
        shift = target - peak
        probed = int(sum(_flag(v + shift, limit.value, sense) for v in values))
        with_value, without_value = (flown, probed) if flown_beyond else (probed, flown)
        side = "beyond" if flown_beyond else "inside"
        return NullTest(
            quantity=f"samples flagged {column}",
            unit="samples",
            with_value=float(with_value),
            without_value=float(without_value),
            threshold=1.0,
            note=(f"flown {side} the {limit.kind or key} limit of {limit.value:g} "
                  f"{unit} (peak {peak:.3f}); the other side is this run's own "
                  f"{channel} samples offset by {shift:+.3f} {unit} so the peak "
                  f"sits {offset:g} {unit} {'inside' if flown_beyond else 'beyond'} "
                  f"the limit; 'with' is the beyond side, 'without' the inside"))
    return None


def applied_variable(limits: LimitsTable, result: MonitorResult,
                     null: Optional[NullTest]) -> AppliedVariable:
    """The ``limits.monitor`` record (core/records.py) for one run."""
    stated = {k: limits.limit(k).value for k in LIMIT_KEYS}
    references = ["14 CFR 23.337 (limit manoeuvring load factors, normal/utility/"
                  "aerobatic categories)",
                  "14 CFR 25.337 (limit manoeuvring load factors, transport category)"]
    for k in LIMIT_KEYS:
        src = limits.limit(k).source
        if src and src not in references:
            references.append(f"{k}: {src}")
    if limits.category_source and limits.category_source not in references:
        references.append(f"category: {limits.category_source}")
    return AppliedVariable(
        name=RECORD_NAME,
        value=stated,
        unit="g | kt CAS | Mach | deg (per key)",
        source="derived",
        model_name=MODEL,
        parameters={
            "aircraft": limits.aircraft,
            "category": limits.category,
            "regulation": limits.regulation,
            "comparison": COMPARISON,
            "monitored": list(result.summary.get("monitored", [])),
            "unmonitored": dict(result.summary.get("unmonitored", {})),
            "probe_offset": dict(PROBE_OFFSET),
            "config_path": limits.config_path,
            "config_sha256": limits.config_sha256,
        },
        references=tuple(references),
        properties_written=(),
        telemetry_columns=result.columns,
        frame_keys=result.columns,
        null_test=null,
        # Record 2: the structured model, the provenance text and the
        # citation. An observer writes no JSBSim property: no readback.
        model=Model(
            name=MODEL, standard=limits.regulation or "14 CFR 23.337 / 25.337",
            version="strict comparison, 0/1 flags per monitored limit",
            parameters={"comparison": COMPARISON, "probe_offset": dict(PROBE_OFFSET),
                        "category": limits.category},
            references=tuple(references)),
        frm=f"the {limits.aircraft} limit table ({limits.config_path})",
        std="14 CFR 23.337 / 25.337 (load factors); placards per the table's sources",
        not_claimed=(
            "position-error correction: placard KIAS limits are compared against "
            "JSBSim calibrated airspeed (velocities/vc-kts)",
            "any consequence of an exceedance: the run is flagged, not stopped, "
            "and no damage, fatigue or aeroelastic effect is modelled",
            "a stall-alpha limit where the model states none",
            "the placard values marked 'unverified here' in the table",
            "the flag columns are derived after the run and are not part of "
            "output_digest, which covers the recorded telemetry only",
        ),
    )


def monitor_run(recorder, aircraft: str, config_dir: Optional[Path] = None,
                ) -> Tuple[Dict[str, Any], Optional[AppliedVariable]]:
    """The runner's one call: load, monitor, annotate, record.

    Returns the manifest's ``limits`` block and the ``limits.monitor``
    record (None when the airframe states no limits -- there is no
    variable to record, and the block says ``monitored: false`` with
    the reason).
    """
    table = load_limits(aircraft, config_dir)
    if table is None:
        return ({"monitored": False, "aircraft": aircraft,
                 "reason": unmonitored_reason(aircraft, config_dir)}, None)
    result = monitor(recorder.columns, table)
    null = null_test(recorder.columns, table)
    annotate(recorder, result)
    record = applied_variable(table, result, null)
    block = {
        "monitored": True,
        "aircraft": aircraft,
        "config_path": table.config_path,
        "config_sha256": table.config_sha256,
        "table": table.to_dict(),
        "summary": dict(result.summary,
                        columns_in_output_digest=False,
                        interval_s=getattr(recorder, "interval_s", None)),
    }
    return block, record
