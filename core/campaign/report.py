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
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from core.scenario.randomization import realised_distribution

from .ledger import STATUSES, summarise


def _seconds_between(start: Any, end: Any) -> Any:
    try:
        a = datetime.fromisoformat(str(start))
        b = datetime.fromisoformat(str(end))
    except (TypeError, ValueError):
        return None
    return round((b - a).total_seconds(), 3)


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
    return {
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
