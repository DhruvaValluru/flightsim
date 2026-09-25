"""The message catalogue and the code's refusal names are in step.

Two directions, both measured against the source tree rather than
asserted (contracts §8, §11; brainstorm §8.2):

* coverage -- every rule name the code emits, in every shape it emits
  it (``Violation("...")`` first arguments including the multi-line
  calls, ``constraint=`` keywords and class attributes, ``"constraint":``
  and ``"refused":`` dict literals, ``<X>Error("<name>", ...)`` positional
  constraints, ``getattr(..., "constraint", "<name>")`` defaults,
  ``"<name>: ..."`` message prefixes and every ``REFUSED -- <name>:``
  line the CLIs print) has a catalogue entry;
* liveness -- every catalogue entry is emitted by the code today, or is
  a verifier check name, or names an un-named exception whose raise
  site still says the sentence this file pins, or is listed in
  ALLOWED_FUTURE with the package that will emit it.

The scanner is written here, not imported from the package, so the
thing that produces the catalogue is not the thing that checks it.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Set, Tuple

import pytest

from core.messages import (
    CATALOG_PATH, catalogue, explain, fill, is_catalogued, name_of, render,
)

REPO = Path(__file__).resolve().parents[1]

#: Where refusal names are emitted. assets_pipeline/ is included because
#: its two error classes name aircraft.mesh* on the same surface.
SCANNED = ("core", "webapp", "flightsim", "assets_pipeline")

NAME = r"[a-z_]+(?:\.[a-z_{}]+)*"

#: Every shape a refusal name takes in the code (label, regex, group).
PATTERNS: Tuple[Tuple[str, "re.Pattern"], ...] = (
    ("Violation(", re.compile(
        r'Violation\(\s*(?:constraint\s*=\s*)?f?"(' + NAME + r')"', re.S)),
    ("<X>Error(", re.compile(
        r'\b[A-Z]\w*Error\(\s*(?:constraint\s*=\s*)?f?"([a-z_]+\.'
        r'[a-z_{}.]+)"', re.S)),
    ("constraint=", re.compile(r'\bconstraint\s*=\s*f?"(' + NAME + r')"')),
    ('"constraint":', re.compile(r'"constraint"\s*:\s*f?"(' + NAME + r')"')),
    ('"refused":', re.compile(r'"refused"\s*:\s*"([a-z_]+(?:\.[a-z_]+)*)"')),
    ("REFUSED --", re.compile(
        r'REFUSED\s*(?:--\s*)?([a-z_]+(?:\.[a-z_]+)*):')),
    ('getattr(..., "constraint", default)', re.compile(
        r'getattr\([^()]*,\s*"constraint",\s*"([a-z_]+\.[a-z_]+)"\)')),
    ('"<name>: " message prefix', re.compile(
        r'f?"([a-z_]+\.[a-z_]+): ')),
)

#: Names the contracts assign to exceptions that carry no constraint
#: string (contracts §11 "catalogued under the new names"). Each is live
#: while its raise site still says the fragment.
NAMED_EXCEPTIONS: Dict[str, Tuple[str, str]] = {
    "spec.version": ("core/scenario/spec.py",
                     "is not supported by this build"),
    "manifest.version": ("core/capture/manifest.py",
                         "capture manifest version"),
    "compile.rejected": ("core/nl/llm_compiler.py",
                         "the language model's response was rejected"),
    "compile.unavailable": ("core/nl/llm_compiler.py",
                            "the LLM compiler is unavailable"),
}

#: Catalogue entries no code emits yet, each with the package that will
#: (contracts §11, §4, §6.1, §7, §8). A package that lands a name REMOVES
#: it from here in the same commit; a name that stays here after its
#: package landed is a finding.
ALLOWED_FUTURE: Dict[str, str] = {
    # package D: the annotation gates (contracts §4)
    "aircraft.placeholder_drawn": "D: drawn_airframe's FAIL name in Check.failure",
    "annotation.mask_blend": "D: mask_integers_only",
    "annotation.mask_offset": "D: mask_vs_geometry",
    "annotation.box_mismatch": "D: box_vs_mask",
    "annotation.depth_range": "D: depth_vs_geometry",
    "annotation.visibility": "D: visibility_vs_scene",
    "annotation.identity": "D: identity_stable",
    "annotation.intrinsics": "D: applied_intrinsics",
    "annotation.files": "D: label_files' FAIL name",
    "check.mask_integers_only": "D: new check",
    "check.mask_vs_geometry": "D: new check",
    "check.box_vs_mask": "D: new check",
    "check.depth_vs_geometry": "D: new check",
    "check.visibility_vs_scene": "D: new check",
    "check.identity_stable": "D: new check",
    "check.applied_intrinsics": "D: new check",
    # package F: the randomisation policy
    "randomization.vocabulary": "F: prompt vocabulary miss",
    "randomization.location": "F: no bake for the named place",
    "randomization.infeasible": "F: too many refused draws",
    # package G: campaigns
    "storage.budget_exceeded": "G: disk budget",
    "campaign.target_unreachable": "G: images_target unreachable",
    "progress.campaign.planned": "G: campaign.json state",
    "progress.campaign.running": "G: campaign.json state",
    "progress.campaign.paused": "G: campaign.json state",
    "progress.campaign.failed": "G: campaign.json state",
    "progress.campaign.done": "G: campaign.json state",
    "progress.campaign.cancelled": "G: campaign.json state",
    "progress.case.sampled": "G: ledger status",
    "progress.case.refused": "G: ledger status",
    "progress.case.running": "G: ledger status",
    "progress.case.rendered": "G: ledger status",
    "progress.case.verified": "G: ledger status",
    "progress.case.failed": "G: ledger status",
    # package H: authority
    "authority.stated_field": "H: core/agent/policy.py",
    "authority.validation_token": "H: core/agent/policy.py",
    "authority.refusal_is_not_a_run": "H: core/agent/policy.py",
    "authority.budget": "H: core/agent/policy.py",
    # package I part 2: the page
    "progress.page.ask": "I: generate.html state",
    "progress.page.clarify": "I: generate.html state",
    "progress.page.preview": "I: generate.html state",
    "progress.page.generate": "I: generate.html state",
    "progress.page.review": "I: generate.html state",
    "progress.page.download": "I: generate.html state",
    "verdict.pass": "I: a check's status in words",
    "verdict.fail": "I: a check's status in words",
    "verdict.not_run": "I: a check's status in words",
}


# -- the scanner -----------------------------------------------------------

def _sources():
    for top in SCANNED:
        for path in sorted((REPO / top).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path, path.read_text(encoding="utf-8")


def _field_order() -> Tuple[str, ...]:
    """RandomizationSpec.FIELD_ORDER read from its source, not imported."""
    text = (REPO / "core/scenario/randomization.py").read_text(encoding="utf-8")
    match = re.search(r"FIELD_ORDER\s*=\s*\((.*?)\)", text, re.S)
    assert match, "RandomizationSpec.FIELD_ORDER not found by the scanner"
    return tuple(re.findall(r'"([a-z_]+)"', match.group(1)))


def _expand(name: str, text: str, where: str) -> Set[str]:
    """A dynamic name (``randomization.{name}``) becomes every field the
    emitting file names by quoted literal -- the only dynamic prefix the
    code has; any other is a scanner gap and fails here by name."""
    if "{" not in name:
        return {name}
    prefix = name.split("{", 1)[0]
    assert prefix == "randomization.", (
        f"{where}: dynamic refusal name {name!r} has no expansion rule in "
        f"tests/test_messages.py; add one so the catalogue can cover it")
    return {prefix + field for field in _field_order()
            if f'"{field}"' in text}


def scan_codebase() -> Dict[str, Set[str]]:
    """Every rule name the code emits -> the shapes and files it was
    found in ("<shape> @ <relative path>")."""
    found: Dict[str, Set[str]] = {}
    for path, text in _sources():
        rel = str(path.relative_to(REPO))
        for label, pattern in PATTERNS:
            for match in pattern.finditer(text):
                for name in _expand(match.group(1), text, rel):
                    found.setdefault(name, set()).add(f"{label} @ {rel}")
    return found


def _check_names() -> Set[str]:
    text = (REPO / "core/capture/verify.py").read_text(encoding="utf-8")
    return set(re.findall(r'Check\(\s*"([a-z_]+)"', text))


# -- the scanner itself is measured -----------------------------------------

def test_scanner_sees_every_shape_the_code_uses():
    """A scanner that quietly finds nothing would pass coverage on an
    empty catalogue. Each emitting shape is pinned to one real site."""
    found = scan_codebase()
    expected = {
        "camera.terrain_clearance": "Violation( @ core/capture/validate.py",
        "aircraft.exists": "Violation( @ core/scenario/validate.py",
        "camera.labels": "constraint= @ core/capture/airframe.py",
        "terrain.clearance": '"constraint": @ webapp/runs.py',
        "validation": '"refused": @ webapp/server.py',
        "terrain.impact": "REFUSED -- @ flightsim/capture.py",
        "trim": "REFUSED -- @ flightsim/capture.py",
        "batch.matrix": "<X>Error( @ core/dataset/batch.py",
        "export.runs": "<X>Error( @ core/dataset/export.py",
        "randomization.livery": "<X>Error( @ core/scenario/randomization.py",
        "aircraft.mesh_import": "<X>Error( @ assets_pipeline/importer.py",
        "camera.track": 'getattr(..., "constraint", default) @ webapp/capture.py',
        "camera.multi_render": '"<name>: " message prefix @ webapp/runs.py',
        "ue.platform": "REFUSED -- @ core/util/platform.py",
        "randomization.fog_density_min": "Violation( @ core/scenario/validate.py",
    }
    missing = {name: site for name, site in expected.items()
               if site not in found.get(name, set())}
    assert not missing, f"the scanner lost these sites: {missing}"
    assert len(found) >= 80, f"only {len(found)} names found; the scan shrank"


# -- coverage ---------------------------------------------------------------

def test_every_refusal_name_in_the_code_has_a_catalogue_entry():
    found = scan_codebase()
    uncovered = {name: sorted(sites) for name, sites in found.items()
                 if not is_catalogued(name)}
    assert not uncovered, (
        f"refusal names without a catalogue entry in {CATALOG_PATH.name}: "
        f"{uncovered}")


def test_every_check_name_has_a_catalogue_entry():
    missing = sorted(f"check.{n}" for n in _check_names()
                     if not is_catalogued(f"check.{n}"))
    assert not missing, f"verifier checks without a sentence: {missing}"


# -- liveness ---------------------------------------------------------------

def test_every_catalogue_entry_is_live():
    found = scan_codebase()
    checks = {f"check.{n}" for n in _check_names()}
    dead = []
    for name in catalogue():
        if name in found or name in checks or name in NAMED_EXCEPTIONS:
            continue
        if name in ALLOWED_FUTURE:
            continue
        dead.append(name)
    assert not dead, (
        f"catalogue entries no code emits and no package claims: {dead}; "
        f"remove them or list them in ALLOWED_FUTURE with their package")


def test_allowed_future_names_are_still_future():
    """A name that landed stays in ALLOWED_FUTURE only until its package
    removes it; this is the reminder."""
    found = scan_codebase()
    checks = {f"check.{n}" for n in _check_names()}
    landed = sorted(n for n in ALLOWED_FUTURE if n in found or n in checks)
    assert not landed, (
        f"these names are now emitted by the code; drop them from "
        f"ALLOWED_FUTURE: {landed}")
    unknown = sorted(n for n in ALLOWED_FUTURE if not is_catalogued(n))
    assert not unknown, f"ALLOWED_FUTURE names without an entry: {unknown}"


def test_named_exception_sentences_still_exist():
    for name, (rel, fragment) in NAMED_EXCEPTIONS.items():
        text = (REPO / rel).read_text(encoding="utf-8")
        assert fragment in text, (
            f"{name}: {rel} no longer says {fragment!r}; the catalogue "
            f"name has lost its raise site")
        assert is_catalogued(name)


# -- the sentences are for people -----------------------------------------

IDENTIFIER = re.compile(r"\b[a-z]+_[a-z_]+\b|\b[a-z_]+\.[a-z_]+\b")


def test_sentences_carry_no_field_names_or_identifiers():
    offenders = {}
    for name, entry in catalogue().items():
        for key in ("sentence", "hint"):
            text = entry.get(key) or ""
            stripped = re.sub(r"\{[^{}]*\}", "", text)
            hits = IDENTIFIER.findall(stripped)
            if hits:
                offenders[f"{name}.{key}"] = hits
    assert not offenders, f"identifiers in plain sentences: {offenders}"


def test_every_sentence_ends_as_a_sentence():
    bad = [n for n, e in catalogue().items()
           if not e["sentence"].rstrip().endswith((".", "!", "?"))]
    assert not bad, f"sentences without a full stop: {bad}"


# -- rendering --------------------------------------------------------------

def test_a_violation_renders_its_numbers():
    from core.scenario.validate import Violation

    v = Violation("camera.terrain_clearance",
                  "camera 'chase': the solved pose track descends into the "
                  "scene's terrain", actual=-89.5, limit=2.0, unit="m AGL")
    out = explain(v)
    assert out["rule"] == "camera.terrain_clearance"
    assert "91.5 m below" in out["sentence"], out
    assert "at least 2 m above the terrain" in out["sentence"], out
    assert "AGL" not in out["sentence"]
    assert out["hint"]

    v = Violation("altitude.terrain_clearance",
                  "commanded altitude is below the terrain it flies over",
                  actual=1200.0, limit=3073.0, unit="m MSL")
    assert explain(v)["sentence"] == (
        "A starting height of 1200 m is too close to the ground there; it "
        "needs to be at least 3073 m above sea level.")


def test_a_refusal_dict_renders_like_the_violation():
    d = {"constraint": "airspeed.stall_margin",
         "message": "commanded airspeed is below 1.05 x the measured stall",
         "actual": 95.0, "limit": 118.2, "unit": "kt CAS"}
    out = explain(d)
    assert out == {
        "sentence": "A speed of 95 knots is too slow for this aircraft to "
                    "keep flying; it needs at least 118.2 knots.",
        "hint": "Ask for a faster speed.",
        "rule": "airspeed.stall_margin"}


def test_string_limits_render_verbatim():
    """The randomisation range clauses pass '1950-2050' style strings."""
    d = {"constraint": "randomization.year", "message": "...",
         "actual": 1800.0, "limit": "1950-2050", "unit": "year"}
    assert explain(d)["sentence"] == (
        "The year 1800 is outside the years the sun-position model is "
        "accurate for (1950-2050).")


def test_plural_reads_correctly_for_one_and_for_three():
    one = render("camera.hazard_intersection", actual=1.0)
    three = render("camera.hazard_intersection", actual=3.0)
    assert "at 1 point along" in one, one
    assert "at 3 points along" in three, three
    assert render("validation", violations=[{}]).startswith(
        "The scenario failed 1 check;")
    assert render("validation", violations=[{}, {}, {}]).startswith(
        "The scenario failed 3 checks;")
    assert render("randomization.infeasible", refused=3, draws=5) == (
        "3 of 5 draws came out impossible to fly, so the variation asked "
        "for cannot be met.")
    assert render("randomization.infeasible", refused=1, draws=1) == (
        "1 of 1 draw came out impossible to fly, so the variation asked "
        "for cannot be met.")


def test_a_missing_placeholder_renders_without_it_and_never_raises():
    assert render("camera.terrain_clearance") == (
        "The camera's path drops m below the minimum height above the "
        "ground; it must stay at least m above the terrain.")
    assert render("randomization.year") == (
        "The year is outside the years the sun-position model is accurate "
        "for.")
    assert fill("{n} {n:thing|things} ({unit})", {}) == ""
    # None is "absent", not the word None.
    assert "None" not in render("camera.intrinsics", actual=None, limit=None,
                                unit=None)


def test_every_entry_renders_with_no_parameters():
    for name in catalogue():
        text = render(name)
        assert text and "{" not in text and "}" not in text, (name, text)


def test_unknown_name_returns_the_raw_name_with_the_technical_message():
    d = {"constraint": "nowhere.such_rule",
         "message": "the producer's own words"}
    assert explain(d) == {"sentence": "nowhere.such_rule",
                          "hint": "the producer's own words",
                          "rule": "nowhere.such_rule"}
    assert render("nowhere.such_rule", actual=1) == "nowhere.such_rule"
    # A dict with no name at all is still shown, never swallowed.
    assert explain({"refused": "a whole paragraph of engine text"}) == {
        "sentence": "refused", "hint": "a whole paragraph of engine text",
        "rule": ""}


def test_explain_reads_the_error_classes_and_the_value_errors(tmp_path):
    from core.capture.manifest import read_capture_manifest
    from core.scenario.randomization import RandomizationError
    from core.scenario.spec import ScenarioSpec

    exc = RandomizationError("randomization.unsampled", "not drawn")
    assert explain(exc)["rule"] == "randomization.unsampled"
    assert explain(exc)["sentence"].startswith("Variation is switched on")

    with pytest.raises(ValueError) as info:
        ScenarioSpec.from_dict({"spec_version": 1})
    out = explain(info.value)
    assert out["rule"] == "spec.version"
    assert "different version" in out["sentence"]

    stale = tmp_path / "capture_manifest.json"
    stale.write_text('{"manifest_version": 99}', encoding="utf-8")
    with pytest.raises(ValueError) as info:
        read_capture_manifest(stale)
    assert name_of(info.value) == "manifest.version"
    assert "cannot read" in explain(info.value)["sentence"]

    class TrimError(Exception):
        pass

    assert name_of(TrimError("no trim")) == "trim"
    assert explain(TrimError("no trim"))["rule"] == "trim"

    class Nameless(Exception):
        pass

    out = explain(Nameless("something the code never named"))
    assert out == {"sentence": "refused",
                   "hint": "something the code never named", "rule": ""}


def test_the_web_run_refusal_shapes_resolve_to_their_names():
    """The three dict shapes webapp/server.py returns on 409."""
    assert name_of({"refused": "validation", "ok": False,
                    "violations": []}) == "validation"
    assert name_of({"refused": "weather",
                    "constraint": "weather.unavailable",
                    "message": "offline"}) == "weather.unavailable"
    assert name_of({"refused": "REFUSED ue.platform: ...",
                    "constraint": "ue.platform"}) == "ue.platform"
    assert name_of({"refused": "terrain.unbaked", "constraint":
                    "terrain.unbaked", "message": "..."}) == "terrain.unbaked"


def test_the_module_lists_and_renders_from_the_command_line():
    listing = subprocess.run(
        [sys.executable, "-m", "core.messages"], cwd=REPO,
        capture_output=True, text=True, check=True)
    assert "camera.terrain_clearance" in listing.stdout
    one = subprocess.run(
        [sys.executable, "-m", "core.messages", "camera.terrain_clearance",
         "actual=-89.5", "limit=2"], cwd=REPO, capture_output=True, text=True)
    assert one.returncode == 0
    assert "91.5 m below" in one.stdout
    assert "[camera.terrain_clearance]" in one.stdout
    unknown = subprocess.run(
        [sys.executable, "-m", "core.messages", "no.such_name"], cwd=REPO,
        capture_output=True, text=True)
    assert unknown.returncode == 1
    assert unknown.stdout.splitlines()[0] == "no.such_name"
