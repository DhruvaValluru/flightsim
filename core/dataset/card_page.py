"""The dataset card as a summary page a person reads.

``dataset.json`` holds everything; ``DATASET_CARD.md`` says it in lines.
This module adds the aggregates a reader looks for first and renders the
whole card as one self-contained page, ``DATASET_CARD.html``, beside them
in every export:

* **image counts** -- per split, per camera, per run;
* **class balance** -- instances and images per class, per split, with bars;
* **conditions** -- what was stated and what the randomisation drew;
* **seeds** -- the split seed, each run's seed, each randomisation seed;
* **check results** -- every verification check across the runs (passed /
  failed / not run, with the first failing sentence), and the per-frame
  box / depth results where the runs carry them;
* **what the dataset does not promise** -- the card's not-claimed list and
  every per-frame limit (core/capture/limits.py) with the number of
  frames it applies to;
* the choices the person made, licences, and where everything came from.

Nothing here decides anything: the numbers are the card's and the runs'
own files, counted.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

CARD_HTML = "DATASET_CARD.html"


def summary_blocks(runs: Sequence, samples: Sequence) -> Dict[str, Any]:
    """The aggregates the page shows first, added to the card as
    ``summary``: image counts per camera and per run, seeds, check results
    across runs (and per frame), and the per-frame limits counted."""
    from core.capture.limits import limits_section

    per_camera: Dict[str, int] = {}
    per_run: Dict[str, int] = {}
    for sample in samples:
        camera = f"{sample.run.name}/{sample.record.get('camera_id')}"
        per_camera[camera] = per_camera.get(camera, 0) + 1
        per_run[sample.run.name] = per_run.get(sample.run.name, 0) + 1

    seeds: Dict[str, Any] = {"runs": {}, "randomization": {}}
    for run in runs:
        seeds["runs"][run.name] = run.manifest.get("seed")
        block = run.manifest.get("randomization")
        if isinstance(block, dict) and block.get("seed") is not None:
            seeds["randomization"][run.name] = block.get("seed")

    checks: Dict[str, Dict[str, Any]] = {}
    for run in runs:
        for check in run.verification.get("checks") or []:
            name = str(check.get("name"))
            entry = checks.setdefault(name, {"PASS": 0, "FAIL": 0, "NOT RUN": 0,
                                             "first_failure": None, "first_not_run": None})
            status = str(check.get("status"))
            entry[status] = entry.get(status, 0) + 1
            if status == "FAIL" and entry["first_failure"] is None:
                entry["first_failure"] = f"{run.name}: {check.get('detail')}"
            if status == "NOT RUN" and entry["first_not_run"] is None:
                entry["first_not_run"] = str(check.get("detail"))

    frame_checks: Dict[str, Dict[str, int]] = {}
    failing_frames: List[str] = []
    for run in runs:
        path = Path(run.directory) / "frame_checks.json"
        if not path.is_file():
            continue
        try:
            graded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for name, counts in (graded.get("counts") or {}).items():
            into = frame_checks.setdefault(name, {})
            for status, n in counts.items():
                into[status] = into.get(status, 0) + int(n)
        failing_frames += [f"{run.name}/{f}" for f in graded.get("failed_frames") or []]

    limits: Dict[str, Dict[str, Any]] = {}
    for sample in samples:
        try:
            section = limits_section(sample.run.manifest, sample.record)
        except Exception:                       # a reader, never a gate
            continue
        for item in section.get("limits") or []:
            entry = limits.setdefault(item["key"], {"limit": item["limit"], "why": item["why"],
                                                    "frames": 0, "always": False})
            if item.get("applies") == "always":
                entry["always"] = True
                entry["frames"] += 1
            elif item.get("applies") is True:
                entry["frames"] += 1

    return {"images_per_camera": per_camera, "images_per_run": per_run,
            "seeds": seeds, "checks": checks, "frame_checks": frame_checks,
            "failing_frames": failing_frames, "limits": limits,
            "frames_counted": len(samples)}


# -- the page ---------------------------------------------------------------

STYLE = """
:root { --bg:#0f1318; --fg:#e7ebef; --dim:#8b98a5; --card:#151b22; --line:#263240;
        --ok:#7fd18b; --bad:#e0896f; --warn:#d9bf63; --bar:#4b8fd1; }
@media (prefers-color-scheme: light) { :root:not([data-theme="dark"]) {
  --bg:#f6f7f9; --fg:#18202a; --dim:#5b6774; --card:#ffffff; --line:#d9dee5;
  --ok:#1f7a35; --bad:#b0422a; --warn:#8a6d00; --bar:#2f6fb5; } }
body { background:var(--bg); color:var(--fg); font:15px/1.45 system-ui, sans-serif;
       margin:0; padding:16px; }
main { max-width: 1000px; margin: 0 auto; }
h1 { font-size: 1.6rem; margin: .2rem 0 .3rem; }
h2 { font-size: 1.15rem; margin: 1.6rem 0 .5rem; border-bottom: 1px solid var(--line);
     padding-bottom: .25rem; }
.dim { color: var(--dim); }
.tiles { display:grid; grid-template-columns: repeat(auto-fit, minmax(150px,1fr)); gap:10px; }
.tile { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
.tile b { display:block; font-size:1.4rem; }
table { border-collapse: collapse; width: 100%; margin: .3rem 0; font-size: .92em; }
th, td { border-bottom: 1px solid var(--line); padding: .3rem .5rem; text-align: left;
         vertical-align: top; }
.wrap { overflow-x: auto; }
.ok { color: var(--ok); } .bad { color: var(--bad); } .warn { color: var(--warn); }
.bar { background: var(--bar); height: 10px; border-radius: 3px; min-width: 2px; }
ul { margin: .3rem 0 .3rem 1.2rem; padding: 0; }
li { margin: .2rem 0; }
code { font-size: .9em; }
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _table(head: Sequence[str], rows: Sequence[Sequence[Any]], raw: bool = False) -> str:
    cells = "".join(
        "<tr>" + "".join(f"<td>{c if raw else _e(c)}</td>" for c in row) + "</tr>"
        for row in rows)
    return ("<div class='wrap'><table><thead><tr>" + "".join(f"<th>{_e(h)}</th>" for h in head)
            + f"</tr></thead><tbody>{cells}</tbody></table></div>")


def render_card_html(card: Dict[str, Any]) -> str:
    summary = card.get("summary") or {}
    choices = card.get("choices") or {}
    parts: List[str] = []
    labels_only = card.get("labels_only")
    parts.append(
        f"<h1>Dataset card</h1><p class='dim'>Format {_e(card.get('format'))} · images: "
        f"{_e(card.get('image'))}{' (labels only, no pictures)' if labels_only else ''} · "
        f"software {_e(card.get('software_revision'))}</p>")
    failed = sum(1 for r in card.get("runs") or [] if r["verification"]["status"] != "passed")
    parts.append("<div class='tiles'>" + "".join(
        f"<div class='tile'><b>{_e(v)}</b><span class='dim'>{_e(k)}</span></div>"
        for k, v in (("images", card.get("images")), ("labelled objects", card.get("instances")),
                     ("classes", len(card.get("classes") or [])),
                     ("runs", len(card.get("runs") or [])),
                     ("runs failing verification", failed),
                     ("frames failing a per-frame check", len(summary.get("failing_frames") or []))))
        + "</div>")

    if choices:
        parts.append("<h2>What was chosen</h2>" + _table(
            ("choice", "value"),
            [(k, v if not isinstance(v, (list, dict)) else json.dumps(v))
             for k, v in choices.items() if v is not None]))

    parts.append("<h2>Image counts</h2>")
    parts.append(_table(("split", "images"), list((card.get("frames_per_split") or {}).items())))
    if summary.get("images_per_camera"):
        parts.append(_table(("run / camera", "images"),
                            sorted(summary["images_per_camera"].items())))

    parts.append("<h2>Class balance</h2>")
    balance = card.get("class_balance") or {}
    most = max([c.get("instances", 0) for c in balance.values()] or [1]) or 1
    rows = []
    for name, c in balance.items():
        per_split = ", ".join(f"{s} {p['instances']}" for s, p in (c.get("per_split") or {}).items())
        bar = f"<div class='bar' style='width:{100.0 * c.get('instances', 0) / most:.1f}%'></div>"
        rows.append((_e(name), _e(c.get("instances")), _e(c.get("images")), _e(per_split), bar))
    parts.append(_table(("class", "instances", "images", "per split", ""), rows, raw=True))
    parts.append(f"<p class='dim'>Class order: {_e(card.get('class_order'))}; classes "
                 f"{_e(', '.join(card.get('classes') or []))}.</p>")

    parts.append("<h2>Conditions</h2>")
    conditions = card.get("conditions") or {}
    stated = conditions.get("stated") or {}
    parts.append(_table(("condition", "values", "source"), [
        (name, ", ".join(f"{v} ×{n}" for v, n in (b.get("values") or {}).items()),
         ", ".join(f"{s} ×{n}" for s, n in (b.get("sources") or {}).items()))
        for name, b in stated.items()]))
    sampled = conditions.get("sampled") or {}
    if sampled:
        parts.append("<p>Drawn by the randomisation block:</p>" + _table(
            ("condition", "draws"),
            [(name, (f"n {b['n']}, min {b['min']}, max {b['max']}, mean {b['mean']:.4g}"
                     if "n" in b else ", ".join(f"{v} ×{n}" for v, n in b.items())))
             for name, b in sampled.items()]))

    parts.append("<h2>Seeds</h2>")
    seeds = summary.get("seeds") or {}
    split = card.get("split") or {}
    rows = [("split (train / val / test)", split.get("seed"),
             f"fractions {split.get('fractions')}, by {split.get('by')}")]
    rows += [(f"run {name}", seed, "the run's seed (turbulence and every stochastic stream)")
             for name, seed in (seeds.get("runs") or {}).items()]
    rows += [(f"randomisation {name}", seed, "the randomisation block's draws")
             for name, seed in (seeds.get("randomization") or {}).items()]
    parts.append(_table(("what", "seed", "what it seeds"), rows))

    parts.append("<h2>Check results</h2>")
    checks = summary.get("checks") or {}
    rows = []
    for name, c in sorted(checks.items(), key=lambda kv: (-kv[1].get("FAIL", 0), kv[0])):
        status = ("<span class='bad'>FAIL</span>" if c.get("FAIL") else
                  "<span class='ok'>PASS</span>" if c.get("PASS") else
                  "<span class='warn'>NOT RUN</span>")
        note = c.get("first_failure") or (c.get("first_not_run") if not c.get("PASS") else "")
        rows.append((_e(name), status, _e(c.get("PASS", 0)), _e(c.get("FAIL", 0)),
                     _e(c.get("NOT RUN", 0)), _e(note)))
    parts.append(_table(("check", "result", "passed", "failed", "not run", "why"), rows, raw=True)
                 if rows else "<p class='dim'>No verification checks recorded.</p>")
    if summary.get("frame_checks"):
        parts.append("<p>Per frame:</p>" + _table(
            ("check", "pass", "fail", "not run"),
            [(name, c.get("PASS", 0), c.get("FAIL", 0), c.get("NOT RUN", 0))
             for name, c in summary["frame_checks"].items()]))
        if summary.get("failing_frames"):
            parts.append("<p class='bad'>Failing frames: "
                         + _e(", ".join(summary["failing_frames"][:50])) + "</p>")

    parts.append("<h2>What this dataset does not promise</h2>")
    limits = summary.get("limits") or {}
    total = summary.get("frames_counted") or 0
    if limits:
        rows = []
        for key, item in sorted(limits.items(), key=lambda kv: -kv[1]["frames"]):
            where = ("every frame" if item["always"] else
                     f"{item['frames']} of {total} frame(s)" if item["frames"] else "no frame here")
            rows.append((item["limit"], where, item["why"]))
        parts.append(_table(("limit", "applies to", "why"), rows))
    not_claimed = card.get("not_claimed") or []
    if not_claimed:
        parts.append("<p>Also stated by the export:</p><ul>" + "".join(
            f"<li>{_e(n if not isinstance(n, dict) else json.dumps(n))}</li>"
            for n in not_claimed) + "</ul>")

    licences = card.get("licences") or []
    if licences:
        parts.append("<h2>Licences</h2>" + _table(
            ("asset", "licence", "runs", "verdict"),
            [(f"{e.get('kind')} {e.get('asset')}", e.get("licence") or "unknown",
              len(e.get("runs") or []), e.get("verdict") or "") for e in licences]))

    parts.append("<h2>Runs</h2>" + _table(
        ("run", "aircraft", "frames", "cameras", "seed", "verification", "solve"),
        [(r["name"], r["aircraft"], r["frames"], ", ".join(r["cameras"]), r["seed"],
          f"{r['verification']['passed']} passed / {r['verification']['failed']} failed / "
          f"{r['verification']['not_run']} not run", r.get("solve_source"))
         for r in card.get("runs") or []]))
    parts.append("<p class='dim'>Everything on this page is in <code>dataset.json</code> "
                 "beside it; <code>DATASET_CARD.md</code> says it in lines.</p>")
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>Dataset card</title>"
            f"<style>{STYLE}</style></head><body><main>{''.join(parts)}</main></body></html>\n")
