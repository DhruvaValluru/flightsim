"""Requirement traceability (ADVANCEMENTS_BLUEPRINT section 2, work item
R3): every claim the additions make, as a requirement with an id, traced
forward to the tests that exercise it and the mutation guards that make
those tests bite, and backward from every test that cites one.

THE REQUIREMENTS are ``docs/REQUIREMENTS.yaml``: one entry per landed
addition item, id ``R-<AREA>-<nn>`` (AREA one of PHY physics, REC the
record, SEN sensing, WLD world, INT interoperability and datums -- the
blueprint's five areas), each with the item, a one-line statement, the
document section it comes from (checked to exist as a heading), the
tests that exist for it, and -- when no guard reaches those tests -- the
stated reason (``lean build: none`` for the items built without guards).
A top-level ``reviewed_by`` names who reviewed the matrix; ``none`` is
the honest value (no independent V&V agent exists for these additions).

THE CITATION CONVENTION: a test cites a requirement by writing its id
in the test function's DOCSTRING (``R-PHY-03`` anywhere in it), or by
a marker ``@pytest.mark.requirement("R-PHY-03", ...)`` (the marker needs
registering in pytest.ini before use; the docstring needs nothing).
Citations are harvested with ``ast`` -- no test module is imported.

THE GUARDS are ``scripts/mutation_check.sh``, read by the suite's own
parser (``parse_guards`` in tests/test_mutation_targets.py, loaded by
path, not copied). A guard reaches a requirement when one of the tests
it names lies in a test file (or is a test node) the requirement lists.

REFUSED, by name:

* ``traceability.orphan`` -- a test cites an id REQUIREMENTS.yaml does
  not define (every citation must land on a requirement);
* ``traceability.uncovered`` -- a requirement with no test, a listed test
  file or test node that does not exist, no guard and no stated reason,
  or a source section that is not a heading of its document.

``docs/TRACEABILITY.md`` is GENERATED (``python scripts/traceability.py``)
and committed; tests/test_traceability.py asserts the regenerated table
equals the committed one, so a requirement, a citation or a guard that
changes without the table changing is a red test.

NOT claimed: a requirement listed with a test says the test exists and
exercises the item, not that the test is sufficient; the matrix has not
been reviewed by anyone independent (``reviewed_by: none``); DO-178C
section 5.5 / 6.3 and ISO/IEC/IEEE 29148 bidirectional traceability are
the form followed [unverified here], not a certification.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

REPO = Path(__file__).resolve().parents[2]
REQUIREMENTS_FILE = REPO / "docs" / "REQUIREMENTS.yaml"
TABLE_FILE = REPO / "docs" / "TRACEABILITY.md"
TESTS_DIR = REPO / "tests"
GUARD_SCRIPT = REPO / "scripts" / "mutation_check.sh"
GUARD_PARSER = TESTS_DIR / "test_mutation_targets.py"

REQUIREMENTS_VERSION = 1

#: The blueprint's five areas.
AREAS = {"PHY": "physics layers", "REC": "the record every variable returns",
         "SEN": "sensing", "WLD": "the world", "INT": "interoperability and datums"}

ID_FORM = re.compile(r"^R-(?P<area>[A-Z]{3})-\d{2}$")
CITATION = re.compile(r"\bR-[A-Z]{3}-\d{2}\b")

#: The honest value of ``reviewed_by`` while no independent reviewer exists.
REVIEWED_BY_NONE = "none"


class TraceabilityError(ValueError):
    """A named refusal (``constraint``) of the traceability matrix."""

    def __init__(self, constraint: str, message: str):
        super().__init__(message)
        self.constraint = constraint
        self.message = message


@dataclass(frozen=True)
class Requirement:
    id: str
    item: str
    title: str
    statement: str
    document: str
    section: str
    tests: Tuple[str, ...]
    guard_reason: Optional[str]
    reviewed_by: str

    @property
    def area(self) -> str:
        return self.id.split("-")[1]


# -- reading ------------------------------------------------------------------

_KEYS = {"id", "item", "title", "statement", "source", "tests", "guard_reason", "reviewed_by"}


def load_requirements(path=REQUIREMENTS_FILE) -> Tuple[Dict[str, Any], List[Requirement]]:
    """The file's top-level fields and its requirements, shape-checked
    (a malformed file is a ValueError naming the entry)."""
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("requirements_version") != REQUIREMENTS_VERSION:
        raise ValueError(f"{path} is not a version-{REQUIREMENTS_VERSION} requirements file")
    reviewed_by = data.get("reviewed_by")
    if not isinstance(reviewed_by, str) or not reviewed_by.strip():
        raise ValueError(f"{path} states no reviewed_by ('none' is the honest value)")
    out: List[Requirement] = []
    seen: Set[str] = set()
    for n, entry in enumerate(data.get("requirements") or []):
        if not isinstance(entry, dict):
            raise ValueError(f"requirement {n} is not a mapping")
        unknown = set(entry) - _KEYS
        if unknown:
            raise ValueError(f"requirement {entry.get('id', n)} carries unknown keys {sorted(unknown)}")
        rid = str(entry.get("id", ""))
        match = ID_FORM.match(rid)
        if not match or match.group("area") not in AREAS:
            raise ValueError(f"requirement {n}: {rid!r} is not R-<AREA>-<nn> with AREA in {sorted(AREAS)}")
        if rid in seen:
            raise ValueError(f"requirement {rid} is defined twice")
        seen.add(rid)
        source = entry.get("source") or {}
        if not isinstance(source, dict) or not source.get("document") or not source.get("section"):
            raise ValueError(f"requirement {rid} cites no source document and section")
        for key in ("item", "title", "statement"):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                raise ValueError(f"requirement {rid} states no {key}")
        tests = entry.get("tests") or []
        if not isinstance(tests, list) or not all(isinstance(t, str) for t in tests):
            raise ValueError(f"requirement {rid}: tests is not a list of test paths")
        reason = entry.get("guard_reason")
        out.append(Requirement(
            id=rid, item=entry["item"].strip(), title=entry["title"].strip(),
            statement=" ".join(entry["statement"].split()),
            document=str(source["document"]), section=str(source["section"]),
            tests=tuple(tests), guard_reason=None if reason is None else str(reason),
            reviewed_by=str(entry.get("reviewed_by", reviewed_by))))
    if not out:
        raise ValueError(f"{path} defines no requirement")
    return data, out


# -- harvesting ---------------------------------------------------------------

def _marker_ids(node: ast.AST) -> List[str]:
    """Ids named by ``@pytest.mark.requirement("R-...", ...)`` decorators."""
    ids: List[str] = []
    for decorator in getattr(node, "decorator_list", []):
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        if isinstance(func, ast.Attribute) and func.attr == "requirement":
            for arg in decorator.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    ids.extend(CITATION.findall(arg.value))
    return ids


def _test_functions(tree: ast.Module) -> List[Tuple[str, ast.AST]]:
    """(node id, function) for every module-level ``test*`` function and
    every ``test*`` method of a module-level ``Test*`` class."""
    found: List[Tuple[str, ast.AST]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            found.append((node.name, node))
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and item.name.startswith("test"):
                    found.append((f"{node.name}::{item.name}", item))
    return found


def _test_files(tests_dir: Path) -> List[Path]:
    return sorted(p for p in Path(tests_dir).rglob("test_*.py") if "__pycache__" not in p.parts)


def harvest(tests_dir=TESTS_DIR, repo=REPO) -> Tuple[Dict[str, Set[str]], Dict[str, List[str]]]:
    """({test file: {test node names}}, {test node: [cited ids]}) over every
    ``test_*.py`` under ``tests_dir``, by ``ast`` alone. Paths are
    repository-relative with forward slashes."""
    repo = Path(repo)
    nodes: Dict[str, Set[str]] = {}
    citations: Dict[str, List[str]] = {}
    for path in _test_files(Path(tests_dir)):
        rel = path.relative_to(repo).as_posix() if path.is_relative_to(repo) else path.as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names = set()
        for name, function in _test_functions(tree):
            names.add(name)
            ids = CITATION.findall(ast.get_docstring(function) or "") + _marker_ids(function)
            if ids:
                citations[f"{rel}::{name}"] = sorted(set(ids))
        nodes[rel] = names
    return nodes, citations


def load_guards(script=GUARD_SCRIPT, parser=GUARD_PARSER) -> List[Any]:
    """Every guard of the mutation script, read by the suite's own parser
    (loaded from its file, so the parser checked by
    tests/test_mutation_targets.py is the one used here)."""
    spec = importlib.util.spec_from_file_location("_traceability_guard_parser", str(parser))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.parse_guards(Path(script).read_text(encoding="utf-8"))


def _guard_targets(guard) -> Set[str]:
    return {t for t in guard.tests if t.startswith("tests/")}


def guards_for(requirement: Requirement, guards: Sequence[Any]) -> List[int]:
    """The numbers of the guards whose named tests lie in a test file (or
    are a test node) the requirement lists."""
    files = {t.split("::")[0] for t in requirement.tests if "::" not in t}
    nodes = {t for t in requirement.tests if "::" in t}
    out = []
    for guard in guards:
        targets = _guard_targets(guard)
        if any(t in nodes or t.split("::")[0] in files for t in targets):
            out.append(int(guard.number))
    return out


# -- the matrix ---------------------------------------------------------------

def _headings(document: Path) -> List[str]:
    return [line.lstrip("#").strip() for line in document.read_text(encoding="utf-8").splitlines()
            if line.startswith("#")]


def build_matrix(requirements: Sequence[Requirement], nodes: Mapping[str, Set[str]],
                 citations: Mapping[str, Sequence[str]], guards: Sequence[Any],
                 repo=REPO) -> List[Dict[str, Any]]:
    """One row per requirement; refuses ``traceability.orphan`` and
    ``traceability.uncovered`` (see the module doc)."""
    known = {r.id for r in requirements}
    orphans = sorted(f"{node} cites {rid}" for node, ids in citations.items()
                     for rid in ids if rid not in known)
    if orphans:
        raise TraceabilityError(
            "traceability.orphan",
            f"{len(orphans)} test citation(s) name no requirement in the requirements file: "
            + "; ".join(orphans))
    problems: List[str] = []
    rows: List[Dict[str, Any]] = []
    headings: Dict[str, List[str]] = {}
    for req in requirements:
        document = Path(repo) / req.document
        if req.document not in headings:
            headings[req.document] = _headings(document) if document.is_file() else []
        if not any(req.section in h for h in headings[req.document]):
            problems.append(f"{req.id}: {req.document} has no heading containing {req.section!r}")
        for test in req.tests:
            file, _, name = test.partition("::")
            if file not in nodes:
                problems.append(f"{req.id}: the test file {file} does not exist")
            elif name and name not in nodes[file]:
                problems.append(f"{req.id}: {file} has no test {name}")
            elif not name and not nodes[file]:
                problems.append(f"{req.id}: {file} holds no test")
        citing = sorted(node for node, ids in citations.items() if req.id in ids)
        if not req.tests and not citing:
            problems.append(f"{req.id}: no test lists or cites it")
        numbers = guards_for(req, guards)
        if not numbers and not req.guard_reason:
            problems.append(f"{req.id}: no mutation guard reaches its tests and no reason is stated")
        rows.append({"id": req.id, "area": req.area, "item": req.item, "title": req.title,
                     "statement": req.statement, "source": f"{req.document} -- {req.section}",
                     "tests": list(req.tests), "cited_by": citing, "guards": numbers,
                     "guard_reason": req.guard_reason, "reviewed_by": req.reviewed_by})
    if problems:
        raise TraceabilityError(
            "traceability.uncovered",
            f"{len(problems)} requirement(s) are not traced to an existing test and a guard "
            f"or a stated reason: " + "; ".join(problems))
    return rows


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_table(meta: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> str:
    """docs/TRACEABILITY.md: forward (requirement to tests and guards) and
    backward (test to requirements). Deterministic: no date, no totals
    from outside the requirements' own tests."""
    lines = [
        "# Traceability",
        "",
        "GENERATED by `python scripts/traceability.py` from `docs/REQUIREMENTS.yaml`, the",
        "requirement ids cited in test docstrings (or `@pytest.mark.requirement`), and the",
        "guards of `scripts/mutation_check.sh`; do not edit by hand. `tests/test_traceability.py`",
        "asserts this file equals a fresh generation.",
        "",
        f"Reviewed by: **{meta.get('reviewed_by')}** -- no independent V&V agent has reviewed",
        "this matrix; it records what exists, not that it is sufficient.",
        "",
        "Citation convention: a test names a requirement id (`R-<AREA>-<nn>`) in its docstring.",
        "A guard reaches a requirement when a test it names lies in a test file the requirement",
        "lists. Areas: " + ", ".join(f"{k} {v}" for k, v in AREAS.items()) + ".",
        "",
        "## Requirements to tests and guards",
        "",
        "| Id | Item | Requirement | Source | Tests | Cited by | Guards | Reviewed by |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        guards = str(len(row["guards"]))
        if row.get("guard_reason"):
            guards += f"; {row['guard_reason']}"
        lines.append("| " + " | ".join(_cell(c) for c in (
            row["id"], row["item"], f"**{row['title']}.** {row['statement']}", row["source"],
            "<br>".join(f"`{t}`" for t in row["tests"]) or "none",
            "<br>".join(f"`{t}`" for t in row["cited_by"]) or "none",
            guards, row["reviewed_by"])) + " |")
    backward: Dict[str, List[str]] = {}
    for row in rows:
        for test in row["tests"]:
            backward.setdefault(test, []).append(row["id"])
        for node in row["cited_by"]:
            backward.setdefault(node, []).append(row["id"])
    lines += ["", "## Tests to requirements", "", "| Test | Requirements |", "|---|---|"]
    for test in sorted(backward):
        lines.append(f"| `{_cell(test)}` | {', '.join(sorted(set(backward[test])))} |")
    lines += ["", "## Not claimed", ""]
    lines += [f"- {item}" for item in (meta.get("not_claimed") or [])]
    return "\n".join(lines) + "\n"


def generate(requirements_file=REQUIREMENTS_FILE, tests_dir=TESTS_DIR,
             script=GUARD_SCRIPT, repo=REPO) -> str:
    """The table, generated from the three sources (refusing by name)."""
    meta, requirements = load_requirements(requirements_file)
    nodes, citations = harvest(tests_dir, repo)
    rows = build_matrix(requirements, nodes, citations, load_guards(script), repo)
    return render_table(meta, rows)
