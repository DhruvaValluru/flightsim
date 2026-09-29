"""The datasheet (ADVANCEMENTS_BLUEPRINT section 2, work item R3): the
seven sections of Gebru et al., filled from the exported runs' own
records, and the ISO/IEC 5259-2 data-quality measures computed from
them, each with its formula stated.

Reference: T. Gebru, J. Morgenstern, B. Vecchione, J. Wortman Vaughan,
H. Wallach, H. Daume III and K. Crawford, "Datasheets for Datasets",
Communications of the ACM 64(12), 86-92, 2021 -- the seven sections
motivation, composition, collection process, preprocessing / cleaning /
labelling, uses, distribution and maintenance. ISO/IEC 5259-2:2024,
"Artificial intelligence -- Data quality for analytics and machine
learning (ML) -- Part 2: Data quality measures" [unverified here: the
standard is unreachable from this container; the characteristic names
are cited by topic and every formula below is this module's own
operational definition, stated beside its value].

Every answer comes from a record the runs carry (the capture manifest,
run.json, verification.json, the dataset card built from them, and the
campaign or batch record beside the runs when there is one); an answer
no record supports is written as "not recorded", never guessed. A
section whose REQUIRED facts are absent is refused by name:

REFUSED -- ``datasheet.incomplete``: the section and the missing fact
are named (no software revision for motivation or maintenance, no frame
or class for composition, a run without a spec digest or a solve source
for collection, a run without verifier checks for preprocessing, nothing
not-claimed for uses, an airframe or asset whose licence was not read
for distribution). The dataset export records the refusal in the card
by name rather than aborting (a statement about a dataset never aborts
the dataset); :func:`build_datasheet` raises it for a direct caller.

The measures (``measures``), each {value, numerator, denominator,
formula, characteristic, basis}:

* completeness  C = 1 - N_missing / N_expected, over every frame of
  every run: the expected items are each channel the run's
  ``state_units`` names plus the frame's in-frame flag; an item is
  missing when absent or not a finite number (a boolean flag).
* accuracy      A = N_pass / (N_pass + N_fail) over every verifier check
  of every run that was graded (NOT RUN excluded) -- the verifier is
  independent of the producer (core/capture/verify.py imports nothing
  from core); ``readback_agreement`` beside it: the applied-variable
  readbacks that agree over those graded.
* consistency   K = N_agree / N_compared between each run's two records
  (run.json and capture_manifest.json): the spec digest once per run,
  then value, unit and source of every applied variable both carry.
* provenance coverage  P = N_sourced / N_items over every stated
  condition and every applied-variable record: sourced when its source
  is one of the six provenance words.
* currency      Cu = N_current / N_runs: a run is current when its
  manifest version is this build's and its applied-variable block's
  record version is this build's.

NOT claimed: the datasheet documents what the records say; it is not a
review, an audit or legal advice (the distribution section states the
airframe licences as recorded and the GPL restriction they carry, not a
ruling on whether a rendered image is a derivative work). No PROV-O or
Croissant serialisation is written.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from core.records import RECORD_VERSION, SOURCES

DATASHEET_VERSION = 1

#: Gebru et al. 2021, in their order.
SECTIONS = ("motivation", "composition", "collection", "preprocessing",
            "uses", "distribution", "maintenance")

GEBRU_REFERENCE = ('Gebru, Morgenstern, Vecchione, Wortman Vaughan, Wallach, Daume III, '
                   'Crawford, "Datasheets for Datasets", Communications of the ACM 64(12), '
                   '86-92, 2021')
ISO_5259_REFERENCE = ("ISO/IEC 5259-2:2024, Data quality for analytics and machine learning, "
                      "Part 2: Data quality measures [unverified here]")

#: The measures, in their order.
MEASURES = ("completeness", "accuracy", "consistency", "provenance_coverage", "currency")

NOT_RECORDED = "not recorded in the runs' records"


class DatasheetError(ValueError):
    """A named refusal (``constraint``) of a datasheet that cannot be filled."""

    def __init__(self, constraint: str, message: str):
        super().__init__(message)
        self.constraint = constraint
        self.message = message


# -- the records beside the runs -------------------------------------------

def _read(path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _context(runs: Sequence[Any]) -> Dict[str, Any]:
    """The campaign records (``<campaign>/campaign.json`` two levels above
    a case) and batch records (``<batch>/batch.json`` beside the runs)."""
    campaigns: Dict[str, Dict[str, Any]] = {}
    batches: Dict[str, Dict[str, Any]] = {}
    for run in runs:
        directory = Path(run.directory)
        campaign = _read(directory.parent.parent / "campaign.json")
        if campaign is not None:
            campaigns[str(campaign.get("id") or directory.parent.parent.name)] = campaign
        batch = _read(directory.parent / "batch.json")
        if batch is not None:
            batches[directory.parent.name] = batch
    return {"campaigns": campaigns, "batches": batches}


def _run_json(run) -> Dict[str, Any]:
    return _read(Path(run.directory) / "run.json") or {}


def _records(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    block = document.get("applied_variables")
    records = block.get("applied_variables") if isinstance(block, dict) else None
    return [r for r in (records or []) if isinstance(r, dict) and r.get("name")]


def _finite(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _measure(numerator: int, denominator: int, formula: str, characteristic: str,
             basis: str, complement: bool = False) -> Dict[str, Any]:
    if denominator <= 0:
        value = None
        basis = "NOT RUN: nothing to measure (" + basis + ")"
    else:
        value = (1.0 - numerator / denominator) if complement else numerator / denominator
    return {"value": value, "numerator": int(numerator), "denominator": int(denominator),
            "formula": formula, "characteristic": characteristic, "basis": basis}


# -- the measures ---------------------------------------------------------

def quality_measures(runs: Sequence[Any]) -> Dict[str, Dict[str, Any]]:
    """The five ISO/IEC 5259-2 measures over the runs (see the module doc)."""
    from core.capture.manifest import MANIFEST_VERSION

    expected = missing = 0
    passed = failed = 0
    readbacks = agreeing = 0
    compared = agree = 0
    items = sourced = 0
    current = 0
    for run in runs:
        manifest = run.manifest
        channels = list((manifest.get("state_units") or {}).keys())
        for frame in manifest.get("frames") or []:
            state = frame.get("state") or {}
            expected += len(channels) + 1
            missing += sum(1 for c in channels if not _finite(state.get(c)))
            if not isinstance((frame.get("labels") or {}).get("in_frame"), bool):
                missing += 1
        for check in (run.verification.get("checks") or []):
            status = str(check.get("status"))
            passed += status == "PASS"
            failed += status == "FAIL"
        published = _records(manifest)
        for record in published:
            readback = record.get("readback")
            if isinstance(readback, dict):
                readbacks += 1
                agreeing += readback.get("agrees") is True
        flown = _run_json(run)
        if flown:
            compared += 1
            agree += flown.get("spec_digest") == manifest.get("spec_digest")
            by_name = {r["name"]: r for r in _records(flown)}
            for record in published:
                other = by_name.get(record["name"])
                if other is None:
                    continue
                compared += 1
                agree += all(json.dumps(record.get(k), sort_keys=True)
                             == json.dumps(other.get(k), sort_keys=True)
                             for k in ("value", "unit", "source"))
        for quantity in (manifest.get("conditions") or {}).values():
            if isinstance(quantity, dict):
                items += 1
                sourced += quantity.get("source") in SOURCES
        for record in published:
            items += 1
            sourced += record.get("source") in SOURCES
        block = manifest.get("applied_variables")
        record_version = block.get("record_version") if isinstance(block, dict) else None
        current += (manifest.get("manifest_version") == MANIFEST_VERSION
                    and record_version in (None, RECORD_VERSION))
    accuracy = _measure(
        passed, passed + failed,
        "A = N_pass / (N_pass + N_fail) over every graded verifier check of every run",
        "accuracy (the labels against the independent verifier)",
        f"{passed} PASS, {failed} FAIL; NOT RUN checks are not graded")
    accuracy["readback_agreement"] = _measure(
        agreeing, readbacks,
        "R = N_agree / N_readback over the applied-variable records carrying a readback",
        "accuracy (the applied values read back from the property store)",
        f"{agreeing} of {readbacks} readback(s) agree to their stated tolerance")
    return {
        "completeness": _measure(
            missing, expected,
            "C = 1 - N_missing / N_expected; expected = per frame, each channel the run's "
            "state_units names plus the in-frame flag; missing = absent or not finite",
            "completeness (value completeness)",
            f"{missing} missing of {expected} expected item(s)", complement=True),
        "accuracy": accuracy,
        "consistency": _measure(
            agree, compared,
            "K = N_agree / N_compared between run.json and capture_manifest.json: the spec "
            "digest per run, then value, unit and source of every variable both carry",
            "consistency (between a run's two records)",
            f"{agree} of {compared} comparison(s) agree"),
        "provenance_coverage": _measure(
            sourced, items,
            "P = N_sourced / N_items over every stated condition and applied-variable "
            "record; sourced = its source is one of the six provenance words",
            "traceability / provenance (the value's lineage)",
            f"{sourced} of {items} item(s) carry a provenance source"),
        "currency": _measure(
            current, len(runs),
            f"Cu = N_current / N_runs; current = manifest version {MANIFEST_VERSION} and "
            f"record version {RECORD_VERSION} (this build's)",
            "currency (the data against the build that reads it)",
            f"{current} of {len(runs)} run(s) at this build's versions"),
    }


# -- the sections ---------------------------------------------------------

def _gpl_statement(licences: Sequence[Mapping[str, Any]]) -> str:
    gpl = sorted({f"{e['asset']} ({e.get('licence')})" for e in licences
                  if "GPL" in str(e.get("licence") or "")})
    if not gpl:
        return ("no airframe or asset in these runs is recorded under the GNU GPL; the "
                "licences above are the whole of what the records state")
    return ("the airframe flight models and configurations " + ", ".join(gpl)
            + " are licensed under the GNU General Public License: the dataset does not "
              "relicense them, redistributing the airframe files (with or beside the "
              "dataset) carries the GPL's terms, including source availability and the "
              "same licence for derivative works; whether a rendered image or a label "
              "of a GPL model is a derivative work is not decided here (not legal advice)")


def _sections(runs: Sequence[Any], card: Mapping[str, Any], context: Mapping[str, Any]
              ) -> Dict[str, Dict[str, Any]]:
    campaigns, batches = context["campaigns"], context["batches"]
    revision = card.get("software_revision")
    prompts = sorted({str(c.get("prompt")) for c in campaigns.values() if c.get("prompt")})
    digests = sorted({str(r.manifest.get("spec_digest")) for r in runs if r.manifest.get("spec_digest")})
    variables = card.get("variables") or {}
    uncertainty = card.get("uncertainty") or {}
    verification = {"passed": sum(int(r.verification.get("passed") or 0) for r in runs),
                    "failed": sum(int(r.verification.get("failed") or 0) for r in runs),
                    "not_run": sum(int(r.verification.get("not_run") or 0) for r in runs)}
    not_claimed = list(card.get("not_claimed") or [])
    for record in (rec for r in runs for rec in _records(r.manifest)):
        for item in record.get("not_claimed") or []:
            text = f"{record['name']}: {item}"
            if text not in not_claimed:
                not_claimed.append(text)
    timing = {name: {k: c.get(k) for k in ("created_utc", "started_utc", "finished_utc")}
              for name, c in sorted(campaigns.items())}
    return {
        "motivation": {
            "purpose": ("synthetic aircraft imagery with provenanced flight-state labels, "
                        "generated to "
                        + ("the request(s) " + "; ".join(repr(p) for p in prompts) if prompts
                           else f"{len(digests)} scenario spec(s) by digest")),
            "requests": prompts or None,
            "spec_digests": digests,
            "campaigns": sorted(campaigns) or None,
            "batches": sorted(batches) or None,
            "creators": f"the flightsim pipeline at software revision {revision}",
            "funding": NOT_RECORDED,
            "sources": ["campaign.json", "batch.json", "capture_manifest.json spec_digest",
                        "dataset card software_revision"],
        },
        "composition": {
            "instances": "frames of simulated flights: an image (when drawn) with its labels "
                         "and the frame's whole recorded flight state",
            "frames": card.get("frames"), "labelled_instances": card.get("instances"),
            "classes": list(card.get("classes") or []),
            "class_balance": {k: v.get("instances") for k, v in
                              (card.get("class_balance") or {}).items()},
            "runs": len(runs), "aircraft": list(card.get("aircraft") or []),
            "frames_per_split": card.get("frames_per_split"),
            "labels": "2-D box, truncation, keypoints, 3-D box and horizon per object "
                      "(the manifest's label conventions); per-frame state channels with units",
            "applied_variables": sorted(variables),
            "missing": {"frames_without_pixels": card.get("frames") if card.get("labels_only") else 0,
                        "runs_without_uncertainty": list(uncertainty.get("runs_without") or [])},
            "confidential_or_personal": "none recorded: every value is simulated; the "
                                        "terrain, land cover and footprints are public "
                                        "datasets named in the distribution section",
            "sources": ["dataset card", "capture_manifest.json frames"],
        },
        "collection": {
            "mechanism": "simulated: a JSBSim 1.2.4 flight flown headlessly from each spec, "
                         "camera poses solved over the recorded flight, labels from the "
                         "headless geometry; pixels only where an engine drew them",
            "solve_sources": sorted({str(r.manifest.get("solve_source")) for r in runs}),
            "drawn_runs": sorted(r.name for r in runs if r.render),
            "sampling": {"randomised_runs": list(card.get("randomised_runs") or []),
                         "campaign_seeds": {n: c.get("seed") for n, c in sorted(campaigns.items())},
                         "sampled_conditions": sorted((card.get("conditions") or {}).get("sampled") or {})},
            "timeframe": timing or NOT_RECORDED,
            "applied_variable_sources": {name: v.get("sources") for name, v in variables.items()},
            "sources": ["capture_manifest.json", "campaign.json", "dataset card variables"],
        },
        "preprocessing": {
            "labelling": "computed from the solved geometry by the pipeline; the independent "
                         "verifier re-derives each check without importing the producer",
            "verification": verification,
            "raw_data_kept": "each run's telemetry.json, run.json and capture_manifest.json "
                             "stay beside it; the export copies, it does not edit",
            "conversions": {"formats": list(card.get("formats") or []),
                            "split": (card.get("split") or {}).get("policy")},
            "sources": ["verification.json", "dataset card"],
        },
        "uses": {
            "intended": "training and evaluating aircraft detection, keypoint and pose models "
                        "on synthetic imagery with exact provenanced labels",
            "not_suitable": [
                "evidence of real-world sensor performance or calibration",
                "a validation of the flight model (the uncertainty blocks carry no u_D)",
                "any use that needs a label the not-claimed list withholds",
            ],
            "not_claimed": not_claimed,
            "sources": ["dataset card not_claimed", "applied-variable records not_claimed"],
        },
        "distribution": {
            "licences": [{k: e.get(k) for k in ("asset", "kind", "licence", "note")}
                         for e in (card.get("licences") or [])],
            "gpl_airframe_restriction": _gpl_statement(card.get("licences") or []),
            "formats": list(card.get("formats") or []),
            "sources": ["dataset card licences (the airframe configs' license blocks and the "
                        "manifests' objects[])"],
        },
        "maintenance": {
            "maintainer": f"the repository that produced it, at software revision {revision}",
            "regenerate": "fly the same specs at the same seeds (every run is content-addressed "
                          "by its spec digest) and export again",
            "versions": {"manifest_versions": list(card.get("manifest_versions") or []),
                         "record_version": card.get("record_version")},
            "errata": "none recorded",
            "sources": ["dataset card", "capture_manifest.json"],
        },
    }


def _problems(runs: Sequence[Any], card: Mapping[str, Any]) -> List[str]:
    problems: List[str] = []
    if not card.get("software_revision"):
        problems.append("motivation and maintenance: no software revision is recorded")
    if not runs or not card.get("frames"):
        problems.append("composition: no frame is exported")
    if not card.get("classes"):
        problems.append("composition: no class is named")
    for run in runs:
        if not run.manifest.get("spec_digest") or not run.manifest.get("solve_source"):
            problems.append(f"collection: run {run.name} records no spec digest or solve source")
        if not run.verification.get("checks"):
            problems.append(f"preprocessing: run {run.name} carries no verifier checks")
    if not card.get("not_claimed"):
        problems.append("uses: nothing is stated as not claimed")
    licences = card.get("licences") or []
    if not licences:
        problems.append("distribution: no asset licence is recorded")
    for entry in licences:
        if entry.get("licence") in (None, ""):
            problems.append(f"distribution: the licence of {entry.get('asset')} was not read"
                            + (f" ({entry['note']})" if entry.get("note") else ""))
    return problems


def build_datasheet(runs: Sequence[Any], card: Mapping[str, Any]) -> Dict[str, Any]:
    """The datasheet for the exported ``runs`` (core/dataset/export.py
    ``Run``) and their dataset ``card``. Refuses ``datasheet.incomplete``
    naming every section whose required facts are absent."""
    problems = _problems(runs, card)
    if problems:
        raise DatasheetError(
            "datasheet.incomplete",
            f"{len(problems)} required fact(s) of the datasheet cannot be filled from the "
            f"runs' records: " + "; ".join(problems))
    sections = _sections(runs, card, _context(runs))
    missing = [s for s in SECTIONS if not sections.get(s)]
    if missing:
        raise DatasheetError("datasheet.incomplete",
                             f"the section(s) {missing} came out empty")
    return {
        "datasheet_version": DATASHEET_VERSION,
        "form": GEBRU_REFERENCE,
        "sections": {name: sections[name] for name in SECTIONS},
        "measures": quality_measures(runs),
        "measures_reference": ISO_5259_REFERENCE,
        "reviewed_by": "none",
        "not_claimed": [
            "a review or audit: the datasheet restates the records (reviewed_by none)",
            "legal advice on the airframe licences",
            "the ISO/IEC 5259-2 formulas are this module's operational definitions, the "
            "standard being unreachable here",
            "no PROV-O or Croissant serialisation",
        ],
    }
