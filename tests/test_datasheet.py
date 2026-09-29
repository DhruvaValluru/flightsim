"""R3: the datasheet -- Gebru et al.'s seven sections filled from a
two-case campaign's own records, and the ISO/IEC 5259-2 measures, each
recomputed here from the cases' files by its stated formula.
"""

import copy
import json
import math
from pathlib import Path

import pytest

from core.capture.manifest import MANIFEST_VERSION
from core.dataset.datasheet import (
    GEBRU_REFERENCE, MEASURES, SECTIONS, DatasheetError, build_datasheet,
)
from core.dataset.export import load_run, record_blocks
from core.records import SOURCES

from tests.test_campaign_report import PROMPT, case_dirs, two_case_campaign


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    campaign = two_case_campaign(tmp_path_factory.mktemp("datasheet") / "c")
    result = campaign.export("coco")
    dirs = case_dirs(campaign)
    return {"campaign": campaign, "card": result["card"], "dirs": dirs,
            "runs": [load_run(d) for d in dirs]}


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_seven_sections_are_filled_from_the_campaigns_records(exported):
    """R-REC-04: motivation, composition, collection, preprocessing, uses,
    distribution and maintenance, in Gebru's order, each answer traced to
    a record (the campaign's prompt, the card's counts, the verdicts, the
    licences)."""
    sheet = exported["card"]["datasheet"]
    assert "refused" not in sheet
    assert tuple(sheet["sections"]) == SECTIONS == (
        "motivation", "composition", "collection", "preprocessing", "uses",
        "distribution", "maintenance")
    assert sheet["form"] == GEBRU_REFERENCE and "Datasheets for Datasets" in sheet["form"]
    s = sheet["sections"]
    assert s["motivation"]["requests"] == [PROMPT]
    assert s["motivation"]["spec_digests"] == sorted(
        {_json(d / "capture_manifest.json")["spec_digest"] for d in exported["dirs"]})
    assert s["composition"]["frames"] == exported["card"]["frames"] > 0
    assert s["composition"]["classes"] == exported["card"]["classes"]
    verdicts = [_json(d / "verification.json") for d in exported["dirs"]]
    assert s["preprocessing"]["verification"] == {
        k: sum(v[k] for v in verdicts) for k in ("passed", "failed", "not_run")}
    assert s["collection"]["solve_sources"] == sorted(
        {_json(d / "capture_manifest.json")["solve_source"] for d in exported["dirs"]})
    assert s["collection"]["sampling"]["campaign_seeds"] == {exported["campaign"].record["id"]: 7}
    assert s["uses"]["not_claimed"] and s["uses"]["not_suitable"]
    # Distribution names the GPL airframe restriction, from the licence records.
    restriction = s["distribution"]["gpl_airframe_restriction"]
    assert "GNU General Public License" in restriction
    assert "assets/aircraft_config/A320.json (GPL-2.0)" in restriction
    assert s["maintenance"]["versions"]["record_version"] == 2
    assert exported["card"]["software_revision"] in s["maintenance"]["maintainer"]
    assert sheet["reviewed_by"] == "none"


def test_the_5259_measures_are_finite_and_recomputed_by_their_formulas(exported):
    """R-REC-04: completeness, accuracy, consistency, provenance coverage
    and currency, each finite in [0, 1] and equal to its formula applied
    here to the cases' files."""
    measures = exported["card"]["datasheet"]["measures"]
    assert tuple(measures) == MEASURES
    for name, m in measures.items():
        assert m["formula"] and m["characteristic"], name
        assert m["value"] is not None and math.isfinite(m["value"]) and 0.0 <= m["value"] <= 1.0
    expected = missing = 0
    passed = failed = 0
    items = sourced = 0
    compared = agree = 0
    for d in exported["dirs"]:
        manifest = _json(d / "capture_manifest.json")
        channels = list(manifest["state_units"])
        for frame in manifest["frames"]:
            expected += len(channels) + 1
            missing += sum(1 for c in channels
                           if not isinstance(frame["state"].get(c), (int, float))
                           or not math.isfinite(frame["state"][c]))
            missing += not isinstance(frame["labels"].get("in_frame"), bool)
        for check in _json(d / "verification.json")["checks"]:
            passed += check["status"] == "PASS"
            failed += check["status"] == "FAIL"
        records = manifest["applied_variables"]["applied_variables"]
        conditions = list(manifest["conditions"].values())
        items += len(records) + len(conditions)
        sourced += sum(r["source"] in SOURCES for r in records + conditions)
        run = _json(d / "run.json")
        flown = {r["name"]: r for r in run["applied_variables"]["applied_variables"]}
        compared += 1
        agree += run["spec_digest"] == manifest["spec_digest"]
        for r in records:
            if r["name"] in flown:
                compared += 1
                agree += all(r[k] == flown[r["name"]][k] for k in ("value", "unit", "source"))
    assert measures["completeness"]["value"] == pytest.approx(1.0 - missing / expected)
    assert measures["completeness"]["denominator"] == expected
    assert measures["accuracy"]["value"] == pytest.approx(passed / (passed + failed))
    assert measures["provenance_coverage"]["value"] == pytest.approx(sourced / items)
    assert measures["consistency"]["value"] == pytest.approx(agree / compared)
    assert measures["consistency"]["denominator"] == compared
    assert measures["currency"]["value"] == 1.0 and MANIFEST_VERSION == max(
        _json(d / "capture_manifest.json")["manifest_version"] for d in exported["dirs"])
    readback = measures["accuracy"]["readback_agreement"]
    assert readback["denominator"] >= 1 and readback["value"] == 1.0


def test_an_unfillable_section_refuses_datasheet_incomplete(exported):
    """R-REC-04: an asset whose licence was not read, or no software
    revision, refuses datasheet.incomplete naming the section; the card
    records the refusal by name instead of aborting the export."""
    runs = exported["runs"]
    card = copy.deepcopy(exported["card"])
    card.pop("datasheet")
    card["licences"][0]["licence"] = None
    card["licences"][0]["note"] = "the config is not on this machine"
    with pytest.raises(DatasheetError) as err:
        build_datasheet(runs, card)
    assert err.value.constraint == "datasheet.incomplete"
    assert "distribution: the licence of" in err.value.message
    unrevised = copy.deepcopy(exported["card"])
    unrevised["software_revision"] = None
    with pytest.raises(DatasheetError) as err:
        build_datasheet(runs, unrevised)
    assert "motivation and maintenance" in err.value.message
    recorded = record_blocks(card, runs)
    assert recorded["datasheet"]["refused"] == "datasheet.incomplete"
    assert "licence" in recorded["datasheet"]["message"]


def test_the_card_states_record_2_and_words_the_datasheet(exported):
    """R-REC-04: dataset.json carries record_version 2 and the datasheet;
    DATASET_CARD.md words the measures and the GPL restriction."""
    campaign = exported["campaign"]
    target = campaign.dir / "datasets" / "coco"
    on_disk = _json(target / "dataset.json")
    assert on_disk["record_version"] == 2
    assert on_disk["datasheet"]["measures"] == exported["card"]["datasheet"]["measures"]
    words = (target / "DATASET_CARD.md").read_text(encoding="utf-8")
    for heading in ("## Applied variables", "## Uncertainty", "## Instruments", "## Datasheet"):
        assert heading in words
    assert "completeness:" in words and "GNU General Public License" in words
