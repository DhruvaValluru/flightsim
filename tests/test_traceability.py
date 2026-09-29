"""R3: requirement traceability -- docs/REQUIREMENTS.yaml, the ids the
tests cite in their docstrings, the mutation guards, and the generated
docs/TRACEABILITY.md, which must equal a fresh generation.

Nothing here runs another test file: citations are read with ``ast`` and
the guards with the suite's own parser.
"""

import re
import textwrap
from pathlib import Path

import pytest

from core.validation.traceability import (
    AREAS, CITATION, ID_FORM, REQUIREMENTS_FILE, TABLE_FILE, Requirement,
    TraceabilityError, build_matrix, generate, harvest, load_guards, load_requirements,
)

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def loaded():
    meta, requirements = load_requirements(REQUIREMENTS_FILE)
    nodes, citations = harvest()
    guards = load_guards()
    return meta, requirements, nodes, citations, guards


def test_the_committed_table_equals_a_fresh_generation():
    """R-REC-04: docs/TRACEABILITY.md is generated, never hand-edited: the
    committed file equals what scripts/traceability.py writes now."""
    assert TABLE_FILE.read_text(encoding="utf-8") == generate(), (
        "docs/TRACEABILITY.md is stale: run python scripts/traceability.py")


def test_every_requirement_has_a_test_and_a_guard_or_a_stated_reason(loaded):
    """R-REC-04: forward coverage -- each requirement lists or is cited by
    an existing test, and a guard reaches it or its reason is stated."""
    meta, requirements, nodes, citations, guards = loaded
    rows = build_matrix(requirements, nodes, citations, guards)
    assert len(rows) == len(requirements) >= 25
    for row in rows:
        assert row["tests"] or row["cited_by"], row["id"]
        assert row["guards"] or row["guard_reason"], row["id"]
        for test in row["tests"]:
            assert (REPO / test.split("::")[0]).is_file(), (row["id"], test)
    # One requirement per landed item and per item of this wave.
    items = {r.item.split()[0] for r in requirements}
    assert items >= {"I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "P1", "P2", "D1", "W1",
                     "P6", "P4", "P3", "P5", "D2", "P7", "S1", "R2", "W2", "S2", "S3", "W3", "R3"}
    for r in requirements:
        assert ID_FORM.match(r.id) and r.area in AREAS, r.id


def test_the_citations_are_harvested_by_ast_and_land_on_requirements(loaded):
    """R-REC-04: backward coverage -- this file's own tests cite R-REC-04 in
    their docstrings, and every citation in the suite names a defined id."""
    meta, requirements, nodes, citations, guards = loaded
    known = {r.id for r in requirements}
    mine = {node: ids for node, ids in citations.items()
            if node.startswith("tests/test_traceability.py::")}
    assert mine and all(ids == ["R-REC-04"] for ids in mine.values())
    assert all(rid in known for ids in citations.values() for rid in ids)


def test_a_citation_of_an_unknown_id_refuses_orphan(loaded, tmp_path):
    """R-REC-04: a test citing an id the requirements do not define
    refuses traceability.orphan, naming the test and the id; docstrings
    and markers are read, a non-test function's docstring is not."""
    meta, requirements, nodes, citations, guards = loaded
    tests = tmp_path / "tests"
    tests.mkdir()
    source = textwrap.dedent('''
        import pytest

        def helper():
            """Cites R-PHY-98, but is not a test."""

        def test_known():
            """Cites R-PHY-03."""

        @pytest.mark.requirement("R-SEN-02")
        def test_marked():
            pass

        class TestGroup:
            def test_method(self):
                """Cites R-XXX-99 and R-INT-01."""
    ''')
    (tests / "test_fake.py").write_text(source, encoding="utf-8")
    fake_nodes, fake_citations = harvest(tests, repo=tmp_path)
    assert fake_nodes == {"tests/test_fake.py": {"test_known", "test_marked",
                                                 "TestGroup::test_method"}}
    assert fake_citations == {"tests/test_fake.py::test_known": ["R-PHY-03"],
                              "tests/test_fake.py::test_marked": ["R-SEN-02"],
                              "tests/test_fake.py::TestGroup::test_method": ["R-INT-01", "R-XXX-99"]}
    with pytest.raises(TraceabilityError) as err:
        build_matrix(requirements, {**nodes, **fake_nodes}, {**citations, **fake_citations}, guards)
    assert err.value.constraint == "traceability.orphan"
    assert "tests/test_fake.py::TestGroup::test_method cites R-XXX-99" in err.value.message
    assert "R-INT-01" not in err.value.message


def test_an_untraced_requirement_refuses_uncovered(loaded):
    """R-REC-04: a requirement whose listed test file does not exist, or no
    guard reaches and no reason is stated, or whose source section is not
    a heading of its document, refuses traceability.uncovered."""
    meta, requirements, nodes, citations, guards = loaded
    base = dict(item="X1", title="t", statement="s", document="docs/ADVANCEMENTS_BLUEPRINT.md",
                section="2. The record every variable returns", reviewed_by="none")
    cases = [
        (Requirement(id="R-REC-90", tests=("tests/test_no_such_file.py",),
                     guard_reason="lean build: none", **base), "does not exist"),
        (Requirement(id="R-REC-91", tests=("tests/test_traceability.py",),
                     guard_reason=None, **base), "no mutation guard reaches"),
        (Requirement(id="R-REC-92", tests=("tests/test_traceability.py::test_nothing_here",),
                     guard_reason="lean build: none", **base), "has no test test_nothing_here"),
        (Requirement(id="R-REC-93", tests=(), guard_reason="lean build: none", **base),
         "no test lists or cites it"),
        (Requirement(id="R-REC-94", tests=("tests/test_traceability.py",),
                     guard_reason="lean build: none",
                     **{**base, "section": "9. A section nobody wrote"}), "has no heading"),
    ]
    for requirement, words in cases:
        with pytest.raises(TraceabilityError) as err:
            build_matrix([requirement], nodes, {}, guards)
        assert err.value.constraint == "traceability.uncovered", requirement.id
        assert words in err.value.message, (requirement.id, err.value.message)
    # A guard DOES reach a requirement listing a guarded test file.
    guarded = Requirement(id="R-REC-95", tests=("tests/test_records.py",), guard_reason=None, **base)
    assert build_matrix([guarded], nodes, {}, guards)[0]["guards"]


def test_reviewed_by_is_the_honest_none(loaded):
    """R-REC-04: nobody independent has reviewed the matrix, and the file,
    every row and the generated table say so."""
    meta, requirements, nodes, citations, guards = loaded
    assert meta["reviewed_by"] == "none"
    assert {r.reviewed_by for r in requirements} == {"none"}
    text = TABLE_FILE.read_text(encoding="utf-8")
    assert "Reviewed by: **none**" in text
    rows = [line for line in text.splitlines() if re.match(r"^\| R-[A-Z]{3}-\d{2} \|", line)]
    assert len(rows) == len(requirements) and all(line.endswith("| none |") for line in rows)


def test_the_guards_are_read_by_the_suites_own_parser():
    """R-REC-04: every `mutate` line of the script is one parsed guard (the
    parser tests/test_mutation_targets.py checks)."""
    script = (REPO / "scripts" / "mutation_check.sh").read_text(encoding="utf-8")
    guards = load_guards()
    assert len(guards) == sum(1 for line in script.splitlines() if line.startswith("mutate "))
    assert CITATION.fullmatch("R-PHY-03") and not CITATION.fullmatch("R-phy-03")


def test_the_regeneration_script_checks_and_writes(tmp_path, monkeypatch):
    """R-REC-04: scripts/traceability.py --check exits 0 on the committed
    table and 1 on a stale one; a refusal exits 2 by name."""
    import importlib.util

    import core.validation.traceability as trace

    spec = importlib.util.spec_from_file_location("traceability_script",
                                                  REPO / "scripts" / "traceability.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.main(["--check"]) == 0
    stale = tmp_path / "TRACEABILITY.md"
    stale.write_text("stale\n", encoding="utf-8")
    monkeypatch.setattr(trace, "TABLE_FILE", stale)
    assert script.main(["--check"]) == 1
    assert script.main([]) == 0 and stale.read_text(encoding="utf-8") == generate()

    def refuse():
        raise TraceabilityError("traceability.orphan", "a test cites R-XXX-99")
    monkeypatch.setattr(trace, "generate", refuse)
    assert script.main(["--check"]) == 2
