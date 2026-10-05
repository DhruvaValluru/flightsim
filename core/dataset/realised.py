"""The variety a dataset actually got, beside the variety that was asked for.

A prompt says "varied weather"; the randomisation draws; some draws are
refused, some cases fail verification, some frames are left out of the
export -- and what ships can be far narrower than the request (three
cases that all drew cloud cover near 0.5, rain asked for and never
drawn). Reporting the REQUEST describes a dataset nobody built. This
module reports what the exported frames hold:

* :func:`realised_for_export` -- ``core.scenario.randomization.
  realised_distribution`` over exactly the exported frames (each run
  weighted by the frames of it that shipped, cameras counted per camera),
  with per leaf the requested distribution, the histogram over the
  REQUEST's bins, the coverage (share of requested bins holding at least
  one frame) and the requested bins that stayed empty;
* :func:`realised_words` -- one plain sentence per leaf ("Precipitation:
  asked none / rain / snow; got none in 48 frames; rain and snow never
  happened"), and a headline that says when the realised variety is
  narrow.

Nothing is inferred: the numbers are the manifests' recorded draws.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

#: Below this coverage the headline calls the realised variety narrow.
NARROW_COVERAGE = 0.5

#: Plain names for the policy leaves.
LEAF_WORDS = {
    "cloud_cover": "Cloud cover", "visibility_km": "Visibility (km)",
    "precipitation": "Precipitation", "hour_local": "Time of day (local hour)",
    "weather_date": "Date", "location": "Place", "traffic_count": "Other aircraft",
    "wind_speed_kt": "Wind speed (kt)", "wind_direction_deg": "Wind direction (deg)",
    "turbulence": "Turbulence", "surface": "Ground surface", "aircraft": "Aircraft",
    "fuel_fraction": "Fuel load", "payload_kg": "Payload (kg)",
    "cameras.preset": "Camera view", "cameras.focal_length_mm": "Lens (mm)",
    "cameras.offset_jitter_m": "Camera position jitter (m)",
}


def realised_for_export(runs: Sequence, samples: Sequence) -> Dict[str, Any]:
    """The realised distribution over the frames that exported."""
    from core.scenario.randomization import realised_distribution

    shipped: Dict[str, List[Dict]] = {}
    for sample in samples:
        shipped.setdefault(sample.run.name, []).append(sample.record)
    records = []
    for run in runs:
        frames = shipped.get(run.name)
        if not frames:
            continue
        records.append({**run.manifest, "frames": frames})
    return annotate(realised_distribution(records))


def annotate(realised: Dict[str, Any]) -> Dict[str, Any]:
    """Add each field's empty and filled requested bins (in place)."""
    for field in (realised.get("fields") or {}).values():
        hist = field.get("histogram") or {}
        field["empty_bins"] = [str(label) for label, n in hist.items() if not n]
        field["filled_bins"] = sum(1 for n in hist.values() if n)
    return realised


def realised_for_runs(run_dirs: Sequence, policy: Any = None) -> Dict[str, Any]:
    """The realised distribution over whole run directories (every frame
    of each), against ``policy`` -- a campaign's verified cases so far."""
    from core.scenario.randomization import realised_distribution

    return annotate(realised_distribution([str(d) for d in run_dirs],
                                          policy=policy if isinstance(policy, dict) else None))


def _label(label: str) -> str:
    """A bin label 'a..b' with its numbers rounded to 3 significant figures."""
    text = str(label)
    if ".." in text:
        lo, _, hi = text.partition("..")
        try:
            return f"{float(lo):.3g}–{float(hi):.3g}"
        except ValueError:
            return text
    return text


def _requested_words(leaf: Any) -> str:
    if not isinstance(leaf, dict):
        return "a fixed value" if leaf is not None else "nothing (varied by default)"
    if "choice" in leaf:
        return " / ".join(str(c) for c in leaf["choice"])
    for form in ("uniform", "loguniform"):
        if form in leaf:
            lo, hi = leaf[form]
            return f"{form} {lo}–{hi}"
    if "uniform_dates" in leaf:
        return f"any date {leaf['uniform_dates'][0]} to {leaf['uniform_dates'][1]}"
    if "clip" in leaf:
        return f"spread over {leaf['clip'][0]}–{leaf['clip'][1]}"
    if "beta" in leaf:
        return "spread over 0–1"
    if "poisson" in leaf:
        return f"about {leaf['poisson']} on average (up to {leaf.get('max', '?')})"
    return ", ".join(f"{k} {v}" for k, v in leaf.items())


def realised_words(realised: Dict[str, Any], frames_noun: str = "exported") -> Dict[str, Any]:
    """``{"headline", "fields": [{name, label, sentence, coverage, narrow}]}``."""
    fields = realised.get("fields") or {}
    if not fields:
        return {"headline": ("Nothing was varied: every frame in this dataset was made "
                             "under the same conditions (listed under Conditions)."),
                "fields": [], "narrow": []}
    out = []
    narrow = []
    for name, field in sorted(fields.items()):
        label = LEAF_WORDS.get(name, name.replace("_", " ").capitalize())
        hist = field.get("histogram") or {}
        frames = int(field.get("frames") or 0)
        coverage = field.get("coverage")
        got = [(_label(k), int(v)) for k, v in hist.items() if v]
        if len(got) <= 6:
            got_words = ", ".join(f"{k} in {v} frame(s)" for k, v in got) or "nothing"
        else:
            got_words = f"{len(got)} different bins over {frames} frame(s)"
        if field.get("requested") is None:
            sentence = (f"{label} (not asked for; the randomisation block varies it by "
                        f"default): got {got_words}")
        else:
            sentence = (f"{label}: asked for {_requested_words(field.get('requested'))}; "
                        f"got {got_words}")
        empty = [_label(b) for b in field.get("empty_bins") or []]
        if field.get("requested") is not None and empty:
            shown = ", ".join(empty[:6]) + (" …" if len(empty) > 6 else "")
            sentence += f"; never happened: {shown}"
        if coverage is not None and field.get("requested") is not None:
            sentence += (f" — {field.get('filled_bins', 0)} of {field.get('bins')} "
                         f"requested bins filled ({100.0 * float(coverage):.0f} %)")
        is_narrow = (coverage is not None and field.get("requested") is not None
                     and float(coverage) < NARROW_COVERAGE)
        if is_narrow:
            narrow.append(label)
        out.append({"name": name, "label": label, "sentence": sentence + ".",
                    "requested": field.get("requested") is not None,
                    "coverage": coverage, "narrow": is_narrow,
                    "histogram": hist, "frames": frames})
    overall = realised.get("coverage")
    headline = (f"Realised over {realised.get('frames', 0)} {frames_noun} frame(s) from "
                f"{realised.get('runs', 0)} run(s)")
    if overall is not None:
        headline += f": {100.0 * float(overall):.0f} % of the requested variety was filled"
    headline += "."
    if narrow:
        headline += (f" Narrower than asked: {', '.join(narrow)} — more cases (or a "
                     f"different seed) are needed to fill them.")
    if realised.get("refusals"):
        headline += (" Draws refused and re-drawn: " + ", ".join(
            f"{k} ×{v}" for k, v in realised["refusals"].items()) + ".")
    return {"headline": headline, "fields": out, "narrow": narrow}
