"""The message catalogue and the code's refusal names are in step.

Two directions, both measured against the source tree rather than
asserted (contracts §8, §11; brainstorm §8.2):

* coverage -- every rule name the code emits, in every shape it emits
  it (``Violation("...")`` first arguments including the multi-line
  calls, ``constraint=`` keywords and class attributes, ``"constraint":``
  and ``"refused":`` dict literals, ``<X>Error("<name>", ...)`` positional
  constraints, ``getattr(..., "constraint", "<name>")`` defaults,
  ``"<name>: ..."`` message prefixes, every ``REFUSED -- <name>:``
  line the CLIs print, and the ``"progress.*"`` / ``"verdict.*"`` state
  literals the guided page hands to ``state_words`` -- including the
  ``f"progress.case.{status}"`` forms, expanded over the ledger statuses
  and campaign states read from their source) has a catalogue entry;
* liveness -- every catalogue entry is emitted by the code today, or is
  a verifier check name, or names an un-named exception whose raise
  site still says the sentence this file pins, or is static text the
  guided page carries verbatim (STATIC_PAGE_TEXT, measured against the
  HTML), or is listed in ALLOWED_FUTURE with the package that will emit
  it.

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
    # A verifier check's FAIL name (Check.failure, contracts §4): the
    # refusal a failed check carries by name into verification.json.
    ("failure=", re.compile(r'\bfailure\s*=\s*f?"(' + NAME + r')"')),
    ('FAIL_<X> = "<name>"', re.compile(r'\bFAIL_[A-Z_]+\s*=\s*"(' + NAME + r')"')),
    # A campaign ledger row's refusal list (contracts §6.3): the names a
    # worker records for a slot it did not run, rendered by the guided
    # page from this catalogue.
    ('"refusals": ["<name>"', re.compile(
        r'"refusals"\s*:\s*\[\s*"([a-z_]+\.[a-z_]+)"')),
    # A progress state or verdict the guided page renders through
    # state_words (contracts §8): a bare literal ("progress.page.clarify",
    # "verdict.pass") or an f-string over a status/state variable
    # (f"progress.case.{status}"), which _expand widens to every value.
    ('"progress.*" / "verdict.*" literal', re.compile(
        r'f?"((?:progress|verdict)\.[a-z_]+(?:\.(?:[a-z_]+|\{[^}"]*\}))?)"')),
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
#: package landed is a finding. Every Phase 2 package has landed:
#: package D (the annotation gates: the annotation.* names,
#: aircraft.placeholder_drawn and the check.* names), F (the randomisation
#: policy: randomization.vocabulary, .location, .infeasible), G (campaigns:
#: storage.budget_exceeded, campaign.target_unreachable, and the
#: progress.campaign.* / progress.case.* states the page renders from the
#: record and the ledger), H (the agent: the four authority.* names) and
#: I (the page: progress.page.* and verdict.*), so the list is empty.
ALLOWED_FUTURE: Dict[str, str] = {}

#: Catalogue sentences the guided page carries as static text rather
#: than reading them through state_words: the two screens that are
#: served before any request is made. Each is live while the HTML says
#: the sentence verbatim (the test measures it), so the catalogue and
#: the page cannot drift apart.
STATIC_PAGE_TEXT: Dict[str, str] = {
    "progress.page.ask": "webapp/static/generate.html",
    "progress.page.download": "webapp/static/generate.html",
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


def _ledger_statuses() -> Tuple[str, ...]:
    """The ledger's STATUS_* literals read from their source (contracts
    §6.1), not imported."""
    text = (REPO / "core/campaign/ledger.py").read_text(encoding="utf-8")
    statuses = tuple(re.findall(r'^STATUS_[A-Z]+\s*=\s*"([a-z]+)"', text, re.M))
    assert len(statuses) >= 6, f"ledger statuses not found by the scanner: {statuses}"
    return statuses


def _campaign_states() -> Tuple[str, ...]:
    """The campaign record's state literals (the PLANNED, RUNNING, ...
    tuple in core/campaign/campaign.py), read from source."""
    text = (REPO / "core/campaign/campaign.py").read_text(encoding="utf-8")
    match = re.search(r"^PLANNED[^=\n]*=\s*\((.*?)\)", text, re.S | re.M)
    assert match, "campaign states not found by the scanner"
    states = tuple(re.findall(r'"([a-z]+)"', match.group(1)))
    assert len(states) >= 6, f"campaign states not found by the scanner: {states}"
    return states


def _expand(name: str, text: str, where: str) -> Set[str]:
    """A dynamic name becomes every value its variable can take:
    ``randomization.{name}`` every field the emitting file names by
    quoted literal, ``progress.case.{status}`` every ledger status and
    ``progress.campaign.{state}`` every campaign state, each read from
    the defining source. Any other dynamic prefix is a scanner gap and
    fails here by name."""
    if "{" not in name:
        return {name}
    prefix = name.split("{", 1)[0]
    if prefix == "randomization.":
        return {prefix + field for field in _field_order()
                if f'"{field}"' in text}
    if prefix == "progress.case.":
        return {prefix + status for status in _ledger_statuses()}
    if prefix == "progress.campaign.":
        return {prefix + state for state in _campaign_states()}
    raise AssertionError(
        f"{where}: dynamic refusal name {name!r} has no expansion rule in "
        f"tests/test_messages.py; add one so the catalogue can cover it")


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
        "aircraft.placeholder_drawn": "failure= @ core/capture/verify.py",
        "annotation.mask_offset": 'FAIL_<X> = "<name>" @ core/capture/verify.py',
        # the guided page's states: a bare literal, an f-string over the
        # ledger statuses, an f-string over the campaign states, a verdict
        "progress.page.clarify": '"progress.*" / "verdict.*" literal @ webapp/generate.py',
        "progress.case.verified": '"progress.*" / "verdict.*" literal @ webapp/generate.py',
        "progress.campaign.done": '"progress.*" / "verdict.*" literal @ webapp/generate.py',
        "verdict.pass": '"progress.*" / "verdict.*" literal @ webapp/generate.py',
        "campaign.duplicate_case": '"refusals": ["<name>" @ core/campaign/workers.py',
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
        if name in ALLOWED_FUTURE or name in STATIC_PAGE_TEXT:
            continue
        dead.append(name)
    assert not dead, (
        f"catalogue entries no code emits and no package claims: {dead}; "
        f"remove them or list them in ALLOWED_FUTURE with their package")


def test_static_page_text_says_the_catalogue_sentence():
    """The ask and download screens are served before any request, so
    their headlines are HTML text; each is the catalogue's sentence
    word for word, or the entry is dead and this says so."""
    for name, rel in STATIC_PAGE_TEXT.items():
        html = (REPO / rel).read_text(encoding="utf-8")
        assert is_catalogued(name), name
        sentence = catalogue()[name]["sentence"]
        assert sentence in html, (
            f"{name}: {rel} does not say {sentence!r}; the catalogue entry "
            f"and the page have drifted apart")
        assert name not in scan_codebase(), (
            f"{name} is emitted by code now; move it out of STATIC_PAGE_TEXT")


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
    assert render("randomization.infeasible", refused=5, draws=5) == (
        "Every attempt to draw this scenario came out impossible to fly "
        "(5 tries), so the variation asked for cannot be met.")
    assert render("randomization.infeasible", refused=1, draws=1) == (
        "Every attempt to draw this scenario came out impossible to fly "
        "(1 try), so the variation asked for cannot be met.")


def test_a_yes_no_value_picks_the_plural_form():
    """The done state's tail is chosen by whether any picture was drawn
    (the page passes drawn=any(row.drawn)); with no answer the sentence
    claims neither, and 'labels' is what it says was generated."""
    base = "Every requested image has its labels generated and checked"
    assert render("progress.campaign.done") == base + "."
    assert render("progress.campaign.done", drawn=False) == (
        base + "; no picture was drawn on this machine.")
    assert render("progress.campaign.done", drawn=True) == (
        base + ", and its picture drawn.")
    assert render("progress.case.rendered") == "Flown and recorded; checking the labels."
    assert render("progress.case.rendered", drawn=True) == (
        "Flown and recorded; checking the labels, and the pictures.")
    for name in ("progress.campaign.done", "progress.case.running",
                 "progress.case.rendered"):
        assert "generated and checked." != render(name)[-22:] or "labels" in render(name)
        assert "rendering" not in render(name) and "Pictures rendered" not in render(name)


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


def test_an_aside_that_lost_every_number_is_dropped_whole():
    """'(of)' says nothing: a bracketed aside whose placeholders are all
    absent goes, one that kept a value stays, and literal text outside
    brackets is never touched."""
    assert fill("Too much ({a} of {b} bytes).", {}) == "Too much."
    assert fill("Too much ({a} of {b} bytes).", {"a": 3000}) == "Too much (3000 of bytes)."
    assert fill("Too much ({a} of {b} bytes).", {"a": 3000, "b": 1}) == (
        "Too much (3000 of 1 bytes).")
    assert fill("({n} {n:try|tries}) failed", {}) == "failed"
    assert fill("({n} {n:try|tries}) failed", {"n": 2}) == "(2 tries) failed"
    assert fill("kept (as is) and {x}", {}) == "kept (as is) and"
    # A value that is the empty string is present, not absent: the empty
    # brackets it leaves are closed by the ordinary tidy.
    assert fill("x ({u})", {"u": ""}) == "x"
    # The sentinel marks never reach the reader.
    for name in catalogue():
        for value in ({}, {"actual": 1, "limit": 2, "draws": 3, "drawn": False}):
            out = fill(catalogue()[name]["sentence"], value)
            assert "\x00" not in out and "\x01" not in out, (name, out)


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


def test_the_numbers_an_error_keeps_in_its_detail_reach_the_sentence(tmp_path):
    """storage.budget_exceeded and randomization.infeasible carry their
    numbers only in ``detail``; the sentence shows them, and reads
    correctly (no '(of)') when the page renders the record's reason
    string, which has none."""
    from core.campaign import Campaign, CampaignError
    from core.scenario.randomization import RandomizationError

    # The real producer: _check_disk on a campaign with a 1-byte budget
    # and one measured case (contracts §6.4).
    campaign = Campaign.create("photos of the a320 for 2 seconds, chase view",
                               images=100, out=tmp_path / "c", tier="regex",
                               disk_budget_bytes=1)
    summary = {"frames_verified": 0, "bytes_per_case": 1000, "bytes_measured_over": 1}
    with pytest.raises(CampaignError) as info:
        campaign._check_disk(summary, per_case=40)
    out = explain(info.value)
    assert out["rule"] == "storage.budget_exceeded"
    assert out["sentence"] == (
        "The campaign would need more disk space than allowed (about 3000 "
        "bytes still to write, against a limit of 1).")
    assert "(of" not in out["sentence"] and "of)" not in out["sentence"]
    # The record's reason string, as the page renders a failed campaign.
    reason = f"{info.value.constraint}: {info.value.message}"
    head, _, tail = reason.partition(":")
    plain = explain({"constraint": head, "message": tail.strip()})["sentence"]
    assert plain == "The campaign would need more disk space than allowed."

    exc = RandomizationError(
        "randomization.infeasible", "20 of 20 draws of randomization.policy were refused",
        detail={"refused": 20, "draws": 20, "draw_index": 0, "refusals": []})
    out = explain(exc)
    assert out["sentence"] == (
        "Every attempt to draw this scenario came out impossible to fly "
        "(20 tries), so the variation asked for cannot be met.")
    # The ledger's refusal list carries the name and a count of slots only.
    assert explain({"constraint": "randomization.infeasible", "message": "2 slot(s)"},
                   count=2)["sentence"] == (
        "Every attempt to draw this scenario came out impossible to fly, so "
        "the variation asked for cannot be met.")
    # An own field wins over a detail key of the same name.
    exc = RandomizationError("randomization.infeasible", "x", detail={"draws": 20})
    assert "(1 try)" in explain(exc, draws=1)["sentence"]


def test_the_campaign_sentences_say_what_the_code_refuses():
    """campaign.duplicate_case is a slot whose draw collided with another
    slot's spec because nothing varies (core/campaign/workers.py); it is
    not a ledger row written twice, and resuming cannot help.
    campaign.target_unreachable fires for refused draws AND for flights
    that added no checked frame (campaign.py _unreachable_reasons), so
    its sentence blames neither."""
    workers = (REPO / "core/campaign/workers.py").read_text(encoding="utf-8")
    campaign = (REPO / "core/campaign/campaign.py").read_text(encoding="utf-8")
    # The reason is written across two adjacent string literals.
    assert re.search(r'leaves nothing to\s*"\s*f?"?vary between them', workers), (
        "workers.py no longer refuses the duplicate slot for want of variation")
    dup = catalogue()["campaign.duplicate_case"]
    assert "nothing to vary" in dup["sentence"]
    assert "recorded twice" not in dup["sentence"] and "ledger" not in dup["sentence"]
    assert "Resume" not in dup["hint"] and "vary" in dup["hint"]
    assert "failed capture(s)" in campaign and "captured but not verified" in campaign
    unreachable = catalogue()["campaign.target_unreachable"]
    assert "variation" not in unreachable["sentence"]
    assert "refused" in unreachable["hint"] and "checked pictures" in unreachable["hint"]


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
