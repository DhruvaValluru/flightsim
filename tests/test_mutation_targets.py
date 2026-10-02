"""Every mutation guard in scripts/mutation_check.sh must still be aimed.

A guard is one ``mutate <file> '<old>' '<new>' "<label>" <tests...>`` call;
the script replaces the FIRST occurrence of the old string in the file and
expects the named tests to go red. A refactor that rewrites the guarded
line orphans the guard (the script reports SKIP forty minutes into a run),
and a line that comes to occur twice mutates the wrong site and reports
"ok" for the wrong reason (NEXT.md gotcha 28: this happened to the chase
tolerance clause). The script's own ``--check-targets`` finds both in
seconds; this lint runs the same check inside the suite, with its own
parser, so a commit cannot orphan a guard without a test going red.

Nothing here applies a mutation or runs a test file: it reads the script
and counts strings.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import List, NamedTuple

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "mutation_check.sh"

#: The script's form, as it writes every guard: a `mutate` call at column
#: zero, its arguments on continued lines, closed by the failure tally.
_STATEMENT = re.compile(
    r"^mutate (?P<args>.*?) \|\| failures=\$\(\(failures\+1\)\)$",
    re.S | re.M)


class Guard(NamedTuple):
    number: int
    file: str
    old: str
    new: str
    label: str
    tests: List[str]


def parse_guards(script_text: str) -> List[Guard]:
    """Every guard of the script, in the order the script numbers them.

    The arguments are bash words: single-quoted strings (an apostrophe is
    spelled '"'"' inside them, and a backslash is literal), a double-quoted
    label, and the pytest arguments. ``shlex`` in POSIX mode reads exactly
    that, once the ``\\``-newline continuations are joined.
    """
    body = script_text.split("\nfailures=0\n", 1)[1]
    guards = []
    for number, match in enumerate(_STATEMENT.finditer(body), start=1):
        words = shlex.split(match.group("args").replace("\\\n", " "))
        assert len(words) >= 5, f"guard {number} has too few arguments: {words!r}"
        file, old, new, label, *tests = words
        guards.append(Guard(number, file, old, new, label, tests))
    return guards


@pytest.fixture(scope="module")
def guards() -> List[Guard]:
    text = SCRIPT.read_text(encoding="utf-8")
    parsed = parse_guards(text)
    # The script counts its guards as the lines that begin with `mutate `;
    # the parser must see every one of them, or a guard it cannot read
    # would escape the checks below.
    total = sum(1 for line in text.splitlines() if line.startswith("mutate "))
    assert len(parsed) == total, (
        f"the parser read {len(parsed)} guards but the script holds {total}")
    assert parsed, "no guards parsed"
    return parsed


def test_every_mutation_target_occurs_exactly_once_in_its_file(guards):
    """Zero occurrences: the guard is orphaned and can never fire. Two or
    more: the mutation lands on the first site, which may not be the
    guarded one, and the guard can report ok for the wrong reason."""
    problems = []
    contents = {}
    for guard in guards:
        path = REPO / guard.file
        if guard.file not in contents:
            try:
                contents[guard.file] = path.read_text(encoding="utf-8")
            except OSError as exc:
                problems.append(f"[{guard.number}] {guard.label}: {exc}")
                contents[guard.file] = None
                continue
        source = contents[guard.file]
        if source is None:
            problems.append(f"[{guard.number}] {guard.label}: {guard.file} unreadable")
            continue
        count = source.count(guard.old)
        if count == 0:
            problems.append(f"[{guard.number}] {guard.label}: target not found in "
                            f"{guard.file}: {guard.old!r}")
        elif count > 1:
            problems.append(f"[{guard.number}] {guard.label}: target occurs {count} "
                            f"times in {guard.file}: {guard.old!r}")
        if guard.old == guard.new:
            problems.append(f"[{guard.number}] {guard.label}: the mutation changes nothing")
    assert not problems, "\n".join(problems)


def test_every_guard_names_test_files_that_exist(guards):
    """The arguments after the label are handed to pytest. A guard whose
    test file is gone collects nothing, and pytest's 'no tests ran' exit
    code would read as the guard firing."""
    problems = []
    for guard in guards:
        files = [t for t in guard.tests if t.endswith(".py")]
        if not files:
            problems.append(f"[{guard.number}] {guard.label}: names no test file "
                            f"({guard.tests!r})")
        for name in files:
            if not (REPO / name).is_file():
                problems.append(f"[{guard.number}] {guard.label}: {name} does not exist")
    assert not problems, "\n".join(problems)


def test_the_parser_reads_the_scripts_own_quoting():
    """The parser is trusted with every guard, so its reading of the
    script's quoting is pinned: an apostrophe spelled '"'"', a literal
    backslash inside single quotes, a multi-line target, and a -k
    selector after the test file."""
    sample = (
        "set -u\nfailures=0\n"
        "mutate core/x.py \\\n"
        "    '    if a:\n        raise E(\"x\")' \\\n"
        "    '    if False:  # MUTATED: it'\"'\"'s gone \\b' \\\n"
        "    \"a label with a ' in it\" \\\n"
        "    tests/test_x.py -k some_test || failures=$((failures+1))\n"
    )
    (guard,) = parse_guards(sample)
    assert guard.file == "core/x.py"
    assert guard.old == '    if a:\n        raise E("x")'
    assert guard.new == "    if False:  # MUTATED: it's gone \\b"
    assert guard.label == "a label with a ' in it"
    assert guard.tests == ["tests/test_x.py", "-k", "some_test"]
