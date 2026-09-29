"""``report.json`` (contracts §6.1, §5.5): yield, coverage and the
realised distributions, refusals by name, timing -- every number from
the ledger and the run manifests, and a rendering in words for
``flightsim.campaign --report``.

The realised distribution is ``core.scenario.randomization.
realised_distribution`` over the VERIFIED cases' manifests (frames
that would export), beside the requested policy; ``coverage`` is its
fraction of requested bins holding at least ``k`` frames.

Not claimed: a picture. ``python -m core.scene.realised_plot
<campaign>/runs/* --out realised.png`` draws the same numbers (package
F's tool); this module writes the JSON and the words.

RECORD 2 (ADVANCEMENTS_BLUEPRINT section 2, work item R3). The report
states ``record_version: 2`` and carries three blocks computed from the
verified cases' own records (each case's ``capture_manifest.json`` and
``run.json``; nothing is recomputed from the physics):

* ``variables.<name>`` -- per applied variable over the cases that carry
  its record: ``n``, ``min``, ``max``, ``mean``, ``sd`` (population, ddof
  0) and a ``hist`` (numpy edges and counts over ``bins`` bins for a
  number; a count per value otherwise), the provenance ``sources`` counted,
  the ``null_verdicts`` counted (reached / silent / bounded / exceeded /
  ungraded / absent), and the null effect |with - without| as
  ``effect_median`` and ``effect_p95`` (numpy linear percentile);
* ``uncertainty`` -- u_num per SRQ over the cases that flew the dt/2 twin,
  u_input per variable, u_val per SRQ (each n / min / max / mean / median)
  and the cases that did not (NOT RUN, by name);
* ``instruments`` -- the profiles, seeds, rates, rate bases and the Allan
  self-report's white-term verdicts over the cases, read from the case's
  ``instruments`` block (the FDM-rate observer, R2) or, when it has none,
  from its ``instruments.profile`` record (the recorded-rate path), and
  ``instruments.npz`` beside the case re-hashed against the block's sha256.

``record_version`` here is ``core.records.RECORD_VERSION`` (2 since the
INT-final bump): the record shape the blocks summarise and the shape
every record the report reads is written in.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from core.records import RECORD_VERSION, SOURCES
from core.scenario.randomization import realised_distribution

from .ledger import STATUSES, summarise

#: The record shape report.json (and the dataset card) summarises: the
#: blueprint's "report.json / dataset.json gain record_version: 2" --
#: core.records.RECORD_VERSION itself since the INT-final bump.
REPORT_RECORD_VERSION = RECORD_VERSION

#: The provenance rank of a source word (fields.py precedence: user 0 ..
#: default 5) and the rank of a variable a case does not carry.
SOURCE_RANK: Dict[str, int] = {source: rank for rank, source in enumerate(SOURCES)}
ABSENT_RANK = len(SOURCES)

#: The words a record's null test is summarised by. ``reached`` / ``silent``:
#: a reached-kind test that did / did not move its quantity past the
#: threshold; ``bounded`` / ``exceeded``: a bounded-kind (invariance) test
#: that stayed within / went past it; ``ungraded``: a null pair with no
#: graded channel; ``absent``: no null test on the record.
NULL_VERDICTS = ("reached", "silent", "bounded", "exceeded", "ungraded", "absent")

CAPTURE_MANIFEST = "capture_manifest.json"
RUN_JSON = "run.json"
INSTRUMENTS_NPZ = "instruments.npz"
INSTRUMENTS_RECORD = "instruments.profile"


def _seconds_between(start: Any, end: Any) -> Any:
    try:
        a = datetime.fromisoformat(str(start))
        b = datetime.fromisoformat(str(end))
    except (TypeError, ValueError):
        return None
    return round((b - a).total_seconds(), 3)


def _exceedances(rows) -> Optional[Dict[str, Any]]:
    """The limits monitor's summary over the verified cases' ``run.json``
    (core/telemetry/limits.py: ``limits.summary.any_exceedance`` and the
    per-limit counts). None when no verified run carries the block --
    a campaign captured before the monitor existed says nothing rather
    than 'no exceedances'."""
    monitored = unmonitored = with_exceedance = samples = 0
    by_limit: Dict[str, int] = {}
    for row in rows:
        if not row.get("run_dir"):
            continue
        try:
            limits = json.loads((Path(row["run_dir"]) / "run.json")
                                .read_text(encoding="utf-8")).get("limits")
        except (OSError, ValueError, AttributeError):
            continue
        if not isinstance(limits, dict):
            continue
        if not limits.get("monitored"):
            unmonitored += 1
            continue
        monitored += 1
        summary = limits.get("summary") or {}
        count = int((summary.get("any_exceedance") or {}).get("count") or 0)
        samples += count
        if count:
            with_exceedance += 1
        for key, entry in (summary.get("per_limit") or {}).items():
            if entry.get("monitored") and entry.get("count"):
                by_limit[key] = by_limit.get(key, 0) + int(entry["count"])
    if not monitored and not unmonitored:
        return None
    return {"cases_monitored": monitored, "cases_unmonitored": unmonitored,
            "cases_with_exceedance": with_exceedance, "samples_flagged": samples,
            "by_limit": dict(sorted(by_limit.items()))}


# -- record 2: the blocks over the cases' own records ------------------------

def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def run_documents(run_dir) -> Dict[str, Dict[str, Any]]:
    """A case's two records: ``manifest`` (capture_manifest.json) and
    ``run`` (run.json), each ``{}`` when the file is absent or unreadable."""
    run_dir = Path(run_dir)
    return {"manifest": _read_json(run_dir / CAPTURE_MANIFEST) or {},
            "run": _read_json(run_dir / RUN_JSON) or {}}


def _records_of(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    block = document.get("applied_variables")
    records = block.get("applied_variables") if isinstance(block, dict) else None
    return [r for r in (records or []) if isinstance(r, dict) and r.get("name")]


def run_records(run_dir, documents: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """The case's applied-variable records: the capture manifest's block
    (the published one, a superset) and any name only run.json carries,
    one record per name, in the manifest's order."""
    documents = documents if documents is not None else run_documents(run_dir)
    records = _records_of(documents["manifest"])
    present = {r["name"] for r in records}
    records += [r for r in _records_of(documents["run"]) if r["name"] not in present]
    return records


def _is_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def null_verdict(record: Mapping[str, Any]) -> str:
    """One of :data:`NULL_VERDICTS` for a record's null test: a null pair's
    own verdict when it carries one, else the kind's arithmetic (``ok``)."""
    null = record.get("null_test")
    if not isinstance(null, dict):
        return "absent"
    verdict = null.get("verdict")
    if verdict in ("reached", "silent", "ungraded"):
        return str(verdict)
    ok = bool(null.get("ok"))
    if null.get("kind", "reached") == "bounded":
        return "bounded" if ok else "exceeded"
    return "reached" if ok else "silent"


def null_effect(record: Mapping[str, Any]) -> Optional[Tuple[float, str]]:
    """|with - without| of the record's null test and its unit, or None."""
    null = record.get("null_test")
    if not isinstance(null, dict):
        return None
    difference = null.get("difference")
    if not _is_number(difference):
        if _is_number(null.get("with")) and _is_number(null.get("without")):
            difference = float(null["with"]) - float(null["without"])
        else:
            return None
    return abs(float(difference)), str(null.get("unit", ""))


def _stats(values: Sequence[float]) -> Dict[str, Any]:
    """n, min, max, mean, median and the population sd of finite numbers."""
    import numpy as np

    if not values:
        return {"n": 0, "min": None, "max": None, "mean": None, "median": None, "sd": None}
    a = np.asarray(values, dtype=float)
    return {"n": int(a.size), "min": float(a.min()), "max": float(a.max()),
            "mean": float(a.mean()), "median": float(np.median(a)), "sd": float(a.std())}


def _histogram(values: Sequence[float], bins: int) -> Dict[str, Any]:
    import numpy as np

    a = np.asarray(values, dtype=float)
    if float(a.min()) == float(a.max()):
        return {"edges": [float(a.min()), float(a.max())], "counts": [int(a.size)],
                "basis": "one value: a single degenerate bin"}
    counts, edges = np.histogram(a, bins=int(bins))
    return {"edges": [float(e) for e in edges], "counts": [int(c) for c in counts],
            "basis": f"numpy.histogram, {int(bins)} equal-width bins over [min, max]"}


def _value_key(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def variables_block(run_dirs: Iterable, bins: int = 8) -> Dict[str, Dict[str, Any]]:
    """``variables.<name>`` over the cases' records (see the module doc)."""
    import numpy as np

    dirs = [Path(d) for d in run_dirs]
    gathered: Dict[str, Dict[str, Any]] = {}
    for run_dir in dirs:
        for record in run_records(run_dir):
            entry = gathered.setdefault(record["name"], {
                "values": [], "units": {}, "sources": {}, "verdicts": {}, "effects": [],
                "effect_units": {}, "runs": []})
            entry["runs"].append(run_dir.name)
            entry["values"].append(record.get("value"))
            unit = str(record.get("unit", ""))
            entry["units"][unit] = entry["units"].get(unit, 0) + 1
            source = str(record.get("source"))
            entry["sources"][source] = entry["sources"].get(source, 0) + 1
            verdict = null_verdict(record)
            entry["verdicts"][verdict] = entry["verdicts"].get(verdict, 0) + 1
            effect = null_effect(record)
            if effect is not None:
                entry["effects"].append(effect[0])
                entry["effect_units"][effect[1]] = entry["effect_units"].get(effect[1], 0) + 1
    out: Dict[str, Dict[str, Any]] = {}
    for name in sorted(gathered):
        entry = gathered[name]
        values = entry["values"]
        numbers = [float(v) for v in values if _is_number(v)]
        nulls = sum(1 for v in values if v is None)
        # A number, or null with its basis (a flat scene's undulation):
        # numeric when every value is one of the two and one is a number.
        numeric = bool(numbers) and len(numbers) + nulls == len(values)
        block: Dict[str, Any] = {
            "n": len(values), "n_null": nulls, "runs_without": len(dirs) - len(values),
            "unit": sorted(entry["units"], key=lambda u: (-entry["units"][u], u))[0],
            "units": dict(sorted(entry["units"].items())),
            "kind": "numeric" if numeric else "categorical",
        }
        if numeric:
            stats = _stats(numbers)
            block.update({k: stats[k] for k in ("min", "max", "mean", "sd")})
            block["hist"] = _histogram(numbers, bins)
        else:
            counts: Dict[str, int] = {}
            for value in values:
                key = _value_key(value)
                counts[key] = counts.get(key, 0) + 1
            block.update({"min": None, "max": None, "mean": None, "sd": None,
                          "hist": {"values": dict(sorted(counts.items())),
                                   "basis": "a count per distinct value (not a number)"}})
        block["sources"] = {s: entry["sources"][s] for s in sorted(
            entry["sources"], key=lambda s: (SOURCE_RANK.get(s, ABSENT_RANK), s))}
        block["null_verdicts"] = {v: entry["verdicts"][v] for v in NULL_VERDICTS
                                  if v in entry["verdicts"]}
        effects = entry["effects"]
        block["effect_n"] = len(effects)
        block["effect_median"] = float(np.median(effects)) if effects else None
        block["effect_p95"] = float(np.percentile(effects, 95.0)) if effects else None
        block["effect_unit"] = (sorted(entry["effect_units"],
                                       key=lambda u: (-entry["effect_units"][u], u))[0]
                                if effects else None)
        block["effect_basis"] = ("|with - without| of each case's null test; median and "
                                 "the 95th percentile (numpy linear) over the cases")
        out[name] = block
    return out


def _uncertainty_of(documents: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    for key in ("manifest", "run"):
        block = documents[key].get("uncertainty")
        if isinstance(block, dict):
            return block
    return None


def uncertainty_summary(run_dirs: Iterable) -> Dict[str, Any]:
    """The ``uncertainty`` block over the cases (see the module doc)."""
    dirs = [Path(d) for d in run_dirs]
    blocks: List[Tuple[str, Dict[str, Any]]] = []
    without: List[str] = []
    for run_dir in dirs:
        block = _uncertainty_of(run_documents(run_dir))
        if block is None:
            without.append(run_dir.name)
        else:
            blocks.append((run_dir.name, block))
    out: Dict[str, Any] = {
        "runs_with": len(blocks), "runs_without": sorted(without),
        "form": sorted({str(b.get("form")) for _, b in blocks}) or None,
        "u_num": {}, "u_input": {}, "u_val": {},
    }
    if not blocks:
        out["status"] = ("NOT RUN: no case flew the dt/2 twin (the capture's uncertainty "
                         "option), so no u_num, u_input or u_val is summarised")
        return out
    out["status"] = f"summarised over {len(blocks)} of {len(dirs)} case(s)"
    for key in ("u_num", "u_val"):
        per: Dict[str, Dict[str, Any]] = {}
        for _, block in blocks:
            part = block.get(key) or {}
            srqs = part.get("srq") if key == "u_num" else part
            for srq, entry in (srqs or {}).items():
                if not isinstance(entry, dict):
                    continue
                slot = per.setdefault(srq, {"values": [], "unit": entry.get("unit"), "not_run": 0})
                if _is_number(entry.get("value")):
                    slot["values"].append(float(entry["value"]))
                else:
                    slot["not_run"] += 1
        out[key] = {srq: {**_stats(slot["values"]), "unit": slot["unit"],
                          "not_run": slot["not_run"]} for srq, slot in sorted(per.items())}
    inputs: Dict[str, Dict[str, Any]] = {}
    for _, block in blocks:
        for name, entry in (block.get("u_input") or {}).items():
            if not isinstance(entry, dict):
                continue
            slot = inputs.setdefault(name, {"values": [], "unit": entry.get("unit"), "rules": {}})
            if _is_number(entry.get("value")):
                slot["values"].append(float(entry["value"]))
            rule = str(entry.get("rule"))
            slot["rules"][rule] = slot["rules"].get(rule, 0) + 1
    out["u_input"] = {name: {**_stats(slot["values"]), "unit": slot["unit"],
                             "rules": dict(sorted(slot["rules"].items()))}
                      for name, slot in sorted(inputs.items())}
    out["not_claimed"] = [
        "u_D: no referent is added per case, so this is the cases' own uncertainty, "
        "not a validation",
        "the spread over cases is of each case's own estimate; it is not an ensemble "
        "uncertainty of the campaign",
    ]
    return out


def _instruments_of(documents: Mapping[str, Any], records: Sequence[Mapping[str, Any]]
                    ) -> Tuple[Optional[Dict[str, Any]], str]:
    """The case's instruments block and where it came from: the FDM-rate
    observer's block (run.json, then the capture manifest), else the
    recorded-rate ``instruments.profile`` record's parameters, else none."""
    for key, basis in (("run", "run.json instruments block"),
                       ("manifest", "capture manifest instruments block")):
        block = documents[key].get("instruments")
        if isinstance(block, dict):
            return block, basis
    for record in records:
        if record.get("name") == INSTRUMENTS_RECORD:
            params = dict(record.get("parameters") or {})
            profile = params.get("profile") or {}
            return ({"rate_hz": params.get("rate_hz"), "rate_basis": params.get("rate_basis"),
                     "profiles": {"set": profile} if profile else {},
                     "seeds": {"experiment_seed": params.get("experiment_seed"),
                               "streams": params.get("seed_streams")},
                     "allan_self_report": params.get("allan_self_report") or {},
                     "file": params.get("file"), "sha256": None},
                    "instruments.profile record (recorded-rate path)")
    return None, "none"


def _profile_name(profile: Any) -> str:
    if isinstance(profile, dict):
        return str(profile.get("name") or profile.get("profile") or "unnamed")
    return str(profile)


def _npz_summary(run_dir: Path, block: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """instruments.npz beside the case, re-hashed and opened (no pickles)."""
    path = run_dir / INSTRUMENTS_NPZ
    if not path.is_file():
        return None
    import numpy as np

    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    with np.load(path, allow_pickle=False) as data:
        names = sorted(data.files)
        samples = int(len(data[names[0]])) if names else 0
    stated = block.get("sha256")
    return {"file": INSTRUMENTS_NPZ, "sha256": digest, "columns": len(names),
            "samples": samples,
            "sha256_matches_block": None if not stated else stated == digest}


def instruments_summary(run_dirs: Iterable) -> Dict[str, Any]:
    """The ``instruments`` block over the cases (see the module doc)."""
    dirs = [Path(d) for d in run_dirs]
    profiles: Dict[str, Dict[str, int]] = {}
    rates: Dict[str, int] = {}
    bases: Dict[str, int] = {}
    sources: Dict[str, int] = {}
    seeds: Dict[str, Any] = {}
    files: Dict[str, Any] = {}
    allan: Dict[str, Dict[str, Any]] = {}
    without: List[str] = []
    for run_dir in dirs:
        documents = run_documents(run_dir)
        block, basis = _instruments_of(documents, run_records(run_dir, documents))
        sources[basis] = sources.get(basis, 0) + 1
        if block is None:
            without.append(run_dir.name)
            continue
        for instrument, profile in sorted((block.get("profiles") or {}).items()):
            name = _profile_name(profile)
            slot = profiles.setdefault(str(instrument), {})
            slot[name] = slot.get(name, 0) + 1
        rate = block.get("rate_hz")
        rate_key = "none" if rate is None else f"{float(rate):g}"
        rates[rate_key] = rates.get(rate_key, 0) + 1
        rate_basis = str(block.get("rate_basis"))
        bases[rate_basis] = bases.get(rate_basis, 0) + 1
        seed_block = block.get("seeds") or {}
        seeds[run_dir.name] = {"experiment_seed": seed_block.get("experiment_seed"),
                               "streams": seed_block.get("streams")}
        npz = _npz_summary(run_dir, block)
        if npz is not None:
            files[run_dir.name] = npz
        for channel, report in sorted((block.get("allan_self_report") or {}).items()):
            if not isinstance(report, dict):
                continue
            if channel == "estimator_check":
                report = report.get("report") or {}
            white = str(report.get("white_term", "absent"))
            word = ("PASS" if white.startswith("PASS") else "FAIL" if white.startswith("FAIL")
                    else "NOT RUN" if white.startswith("NOT RUN") else white)
            slot = allan.setdefault(channel, {"white_term": {}, "worst_agreement": None,
                                              "runs": 0, "unit": report.get("unit")})
            slot["runs"] += 1
            slot["white_term"][word] = slot["white_term"].get(word, 0) + 1
            agreements = [p.get("agreement") for p in (report.get("short_tau") or [])
                          if isinstance(p, dict) and _is_number(p.get("agreement"))]
            if agreements:
                worst = max(float(a) for a in agreements)
                if slot["worst_agreement"] is None or worst > slot["worst_agreement"]:
                    slot["worst_agreement"] = worst
    return {
        "runs": len(dirs), "runs_without": sorted(without), "sources": dict(sorted(sources.items())),
        "profiles": profiles, "seeds": seeds, "rate_hz": dict(sorted(rates.items())),
        "rate_basis": dict(sorted(bases.items())), "allan_self_report": allan,
        "files": files,
        "not_claimed": [
            "the profiles are stated class models; no device is calibrated",
            "the Allan self-report grades that the model produced the noise it declares, "
            "not a sensor; B and K are not graded on short runs",
        ],
    }


def build_report(campaign, k: int = 1, bins: int = 8) -> Dict[str, Any]:
    campaign._reload()
    rows = campaign.ledger.rows()
    summary = summarise(rows)
    record = campaign.record
    latest = campaign.ledger.latest()
    verified_rows = [r for r in latest.values() if r.get("status") == "verified"]
    walls = [float(r["wall_seconds"]) for r in latest.values()
             if isinstance(r.get("wall_seconds"), (int, float)) and r.get("case_id")]
    realised = realised_distribution(
        [r["run_dir"] for r in verified_rows if r.get("run_dir")],
        policy=record.get("policy") or None, k=k, bins=bins)
    # Refused attempts INSIDE successful draws, by name, from the ledger
    # rows (the manifests say the same; realised_distribution counts
    # them too, over the verified cases only).
    attempt_refusals: Dict[str, int] = {}
    for row in latest.values():
        if row.get("status") in ("refused",):
            continue
        for name in row.get("refusals") or []:
            attempt_refusals[str(name)] = attempt_refusals.get(str(name), 0) + 1
    slot_refusals: Dict[str, int] = {}
    for row in latest.values():
        if row.get("status") == "refused":
            for name in row.get("refusals") or []:
                slot_refusals[str(name)] = slot_refusals.get(str(name), 0) + 1
    target = int(record["images_target"])
    verified_dirs = [r["run_dir"] for r in verified_rows if r.get("run_dir")]
    return {
        "record_version": REPORT_RECORD_VERSION,
        "campaign": record["id"],
        "state": record["state"],
        "reason": record.get("reason"),
        "prompt": record.get("prompt"),
        "tier": record.get("tier"),
        "spec_digest": record.get("spec_digest"),
        "seed": record.get("seed"),
        "workers": record.get("workers"),
        "images_target": target,
        "yield": {
            "frames_verified": summary["frames_verified"],
            "frames_captured": summary["frames_captured"],
            "fraction_of_target": round(min(1.0, summary["frames_verified"] / target), 4),
            "cases": summary["cases"],
            "indices": summary["indices"],
            "verified_cases": len(verified_rows),
            "mean_frames_per_verified_case": (
                round(summary["frames_verified"] / len(verified_rows), 2)
                if verified_rows else None),
            "drawn_cases": sum(1 for r in verified_rows if r.get("drawn")),
        },
        "coverage": realised.get("coverage"),
        "realised": realised,
        "exceedances": _exceedances(verified_rows),
        # Record 2 (R3): over the verified cases' own records.
        "variables": variables_block(verified_dirs, bins=bins),
        "uncertainty": uncertainty_summary(verified_dirs),
        "instruments": instruments_summary(verified_dirs),
        "refusals": {
            "slots": dict(sorted(slot_refusals.items())),
            "attempts_within_draws": dict(sorted(attempt_refusals.items())),
            # The constraints the refused slots' own draws hit: what
            # ``randomization.infeasible`` stands for in this campaign.
            "attempts_within_refused_slots": summary["refused_attempt_names"],
            "total_by_name": summary["refusals"],
        },
        "timing": {
            "created_utc": record.get("created_utc"),
            "started_utc": record.get("started_utc"),
            "finished_utc": record.get("finished_utc"),
            "elapsed_seconds": _seconds_between(record.get("started_utc"),
                                                record.get("finished_utc")),
            "case_wall_seconds_total": round(sum(walls), 3),
            "case_wall_seconds_mean": round(sum(walls) / len(walls), 3) if walls else None,
        },
        "disk": {
            "bytes_per_case": summary["bytes_per_case"],
            "measured_over": summary["bytes_measured_over"],
            "budget_bytes": record.get("disk_budget_bytes"),
        },
        "git": record.get("git"),
        "not_claimed": [
            "pixels unless drawn_cases > 0 (no engine on this platform)",
            "the throughput knee at 2 and 4 workers (unmeasured without an engine)",
            "a variable's spread over the cases is the campaign's realised draw, not an "
            "uncertainty of any one case",
            "no PROV-O or Croissant serialisation: the identifiers (campaign id, spec "
            "digest, variable name) are stable so a later exporter needs no new field",
        ],
    }


def render_report(report: Dict[str, Any]) -> str:
    """The report in words."""
    y = report["yield"]
    lines: List[str] = []
    lines.append(f"campaign {report['campaign']}: {report['state']}"
                 + (f" -- {report['reason']}" if report.get("reason") else ""))
    lines.append(f"  prompt: {report.get('prompt')!r} (compiled by {report.get('tier')}, "
                 f"spec {str(report.get('spec_digest'))[:16]}, seed {report.get('seed')})")
    lines.append(f"  yield: {y['frames_verified']} verified frame(s) of "
                 f"{report['images_target']} asked ({y['fraction_of_target']:.0%}); "
                 f"{y['frames_captured']} captured; {y['verified_cases']} verified "
                 f"case(s), {y['drawn_cases']} with pixels")
    counts = ", ".join(f"{y['cases'][s]} {s}" for s in STATUSES if y["cases"].get(s))
    lines.append(f"  cases: {y['indices']} slot(s) drawn -- {counts or 'none'}")
    if report.get("coverage") is not None:
        lines.append(f"  coverage: {report['coverage']:.0%} of the requested bins hold "
                     f">= {report['realised'].get('k', 1)} frame(s)")
        for name, field in sorted(report["realised"].get("fields", {}).items()):
            if field.get("requested") is None:
                continue
            lines.append(f"    {name}: {field['coverage']:.0%} of {field['bins']} bins, "
                         f"{field['frames']} frame(s)")
    else:
        lines.append("  coverage: no requested distribution (no policy), so none")
    refusals = report["refusals"]
    if refusals["slots"] or refusals["attempts_within_draws"]:
        slots = ", ".join(f"{k} x{v}" for k, v in refusals["slots"].items()) or "none"
        attempts = ", ".join(f"{k} x{v}" for k, v in
                             refusals["attempts_within_draws"].items()) or "none"
        lines.append(f"  refusals: slots {slots}; attempts inside draws {attempts}")
        within = refusals.get("attempts_within_refused_slots") or {}
        if within:
            lines.append("  refused slots' draws were refused "
                         + ", ".join(f"{k} x{v}" for k, v in within.items())
                         + " -- narrow the policy against these")
    else:
        lines.append("  refusals: none")
    exceedances = report.get("exceedances")
    if exceedances:
        by = ", ".join(f"{k} x{v}" for k, v in exceedances["by_limit"].items()) or "none"
        lines.append(f"  exceedances: {exceedances['cases_with_exceedance']} of "
                     f"{exceedances['cases_monitored']} monitored case(s) beyond a "
                     f"stated limit, {exceedances['samples_flagged']} sample(s) "
                     f"flagged ({by})"
                     + (f"; {exceedances['cases_unmonitored']} case(s) unmonitored"
                        if exceedances["cases_unmonitored"] else ""))
    variables = report.get("variables") or {}
    if variables:
        lines.append(f"  variables: {len(variables)} applied variable(s) over the verified cases")
        for name, v in variables.items():
            spread = (f"{v['min']:.6g}..{v['max']:.6g} {v['unit']}" if v["kind"] == "numeric"
                      else ", ".join(f"{k} x{n}" for k, n in v["hist"]["values"].items()))
            nulls = ", ".join(f"{k} x{n}" for k, n in v["null_verdicts"].items())
            lines.append(f"    {name}: n {v['n']}, {spread}; null {nulls}"
                         + (f"; effect median {v['effect_median']:.3g} {v['effect_unit']}"
                            if v.get("effect_median") is not None else ""))
    uncertainty = report.get("uncertainty")
    if uncertainty:
        alt = (uncertainty.get("u_num") or {}).get("altitude_m") or {}
        lines.append(f"  uncertainty: {uncertainty.get('status')}"
                     + (f"; u_num altitude median {alt['median']:.3g} m"
                        if alt.get("median") is not None else ""))
    instruments = report.get("instruments")
    if instruments:
        lines.append("  instruments: rate basis " + (", ".join(
            f"{k} x{n}" for k, n in instruments.get("rate_basis", {}).items()) or "none")
            + "; profiles " + (", ".join(
                f"{inst} {'/'.join(sorted(p))}" for inst, p in instruments.get("profiles", {}).items())
                or "none"))
    t = report["timing"]
    lines.append(f"  timing: started {t.get('started_utc')}, finished {t.get('finished_utc')}"
                 + (f", {t['elapsed_seconds']:.0f} s elapsed" if t.get("elapsed_seconds") is not None else "")
                 + (f", {t['case_wall_seconds_mean']:.1f} s per case" if t.get("case_wall_seconds_mean") else ""))
    d = report["disk"]
    if d.get("bytes_per_case"):
        lines.append(f"  disk: {d['bytes_per_case']} bytes per case measured over "
                     f"{d['measured_over']} case(s)"
                     + (f"; budget {d['budget_bytes']} bytes" if d.get("budget_bytes") else ""))
    lines.append("  not claimed: " + "; ".join(report.get("not_claimed", [])))
    return "\n".join(lines)
