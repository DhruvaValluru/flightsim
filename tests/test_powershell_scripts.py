"""The Windows scripts have to parse on Windows PowerShell.

`scripts/run_ue_scenario.ps1` carried this line from the day it was
written::

    $out = Join-Path (Resolve-Path (if ($outDir) { $outDir } else { "." })).Path ...

`if` is a STATEMENT in PowerShell, not an expression, so it cannot sit in
an argument position: that is a parse error, not a conditional. It reads
as valid to anyone used to a language with a ternary, and it stood there
unrun -- Gate 5 drove the `.sh` twin, and nothing on Windows invoked the
`.ps1` at all until the capture path began flying the host to solve
over. The first invocation died on it, at the instructor, after a full
headless flight had already been flown.

There is no PowerShell on the machines this suite runs on, so this
cannot be a real parse. What it can be is a check for the specific
constructs that are parse errors in Windows PowerShell 5.1 -- the shell
`powershell.exe` starts, which is what every documented command in this
repo uses. A narrow lint that catches a known, committed, shipped bug is
worth more than a general one that needs an interpreter nobody has.
"""

import re
from pathlib import Path

import pytest

SCRIPTS = sorted((Path(__file__).resolve().parents[1] / "scripts").glob("*.ps1"))

#: Keywords that begin a STATEMENT. PowerShell does not allow any of them
#: where a value is expected; `$(...)` is how you get a value out of one.
STATEMENT_KEYWORDS = ("if", "for", "foreach", "while", "do", "switch",
                      "try", "trap")

#: An opening `(` or a `,` followed by a statement keyword and its own
#: `(`. Anchored on the paren so `if ($x) { }` at the start of a line --
#: the ordinary, correct use -- does not match.
#:
#: The lookbehind is the whole difference between a bug and the fix for
#: it: `$(if ($x) { 1 } else { 2 })` is a SUBEXPRESSION and is perfectly
#: valid, which is exactly how you are supposed to get a value out of a
#: statement. Only a bare `(` is wrong.
STATEMENT_AS_EXPRESSION = re.compile(
    r"(?<!\$)[(,]\s*(" + "|".join(STATEMENT_KEYWORDS) + r")\s*\(",
    re.IGNORECASE)

#: PowerShell 7 only. Windows PowerShell 5.1 ships with Windows and is
#: what `powershell -File ...` starts, which is the documented invocation
#: throughout this repo, so these are parse errors where it matters.
PS7_ONLY = (
    (re.compile(r"\?\?"), "null-coalescing (??) needs PowerShell 7"),
    (re.compile(r"&&|\|\|"), "pipeline chain (&& / ||) needs PowerShell 7"),
)


def code_lines(path: Path):
    """(number, text) with comments and single-quoted strings removed.

    Crude on purpose: enough to keep a comment ABOUT this bug -- which
    this repo now has, in the very file that had it -- from being read
    as the bug.
    """
    out = []
    in_here_string = False
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw.strip()
        if stripped.startswith("@'") or stripped.startswith('@"'):
            in_here_string = True
            continue
        if in_here_string:
            if stripped in ("'@", '"@'):
                in_here_string = False
            continue
        if stripped.startswith("#"):
            continue
        line = raw.split("#", 1)[0] if "#" in raw else raw
        out.append((number, line))
    return out


def test_there_are_scripts_to_check():
    """A lint that silently checks nothing passes forever."""
    assert len(SCRIPTS) >= 10, f"only found {len(SCRIPTS)} .ps1 scripts"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_no_statement_is_used_as_an_expression(script):
    """The committed bug, and its whole family.

    `(Resolve-Path (if ($outDir) { $outDir } else { "." }))` is a parse
    error in every PowerShell. The fix is either a plain `if` statement
    on its own lines or a `$(...)` subexpression.
    """
    offenders = [(n, line.strip()) for n, line in code_lines(script)
                 if STATEMENT_AS_EXPRESSION.search(line)]
    assert not offenders, (
        f"{script.name}: a statement keyword is used where PowerShell "
        f"expects a value; wrap it in $( ) or lift it out:\n" +
        "\n".join(f"  line {n}: {text}" for n, text in offenders))


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_no_powershell_7_only_syntax(script):
    """Every documented command here runs `powershell -File`, which is
    Windows PowerShell 5.1 -- not `pwsh`."""
    for pattern, why in PS7_ONLY:
        offenders = [(n, line.strip()) for n, line in code_lines(script)
                     if pattern.search(line)]
        assert not offenders, (
            f"{script.name}: {why}:\n" +
            "\n".join(f"  line {n}: {text}" for n, text in offenders))


def test_the_lint_catches_the_bug_it_was_written_for():
    """The lint's own reference: the exact line that shipped broken.

    Without this, a regex that matched nothing would pass every test
    above and prove only that it matches nothing.
    """
    shipped = ('$out = Join-Path (Resolve-Path (if ($outDir) { $outDir } '
               'else { "." })).Path (Split-Path -Leaf $args[1])')
    assert STATEMENT_AS_EXPRESSION.search(shipped)

    fixed = '$out = Join-Path (Resolve-Path $outDir).Path (Split-Path -Leaf $args[1])'
    assert not STATEMENT_AS_EXPRESSION.search(fixed)

    ordinary = 'if (-not (Test-Path $outDir)) { $outDir = "." }'
    assert not STATEMENT_AS_EXPRESSION.search(ordinary), (
        "an ordinary if statement must not trip the lint")

    # The legal way to get a value out of a statement. A lint that
    # rejected this would push people toward the broken form.
    subexpression = '$out = Join-Path $(if ($d) { $d } else { "." }) "x"'
    assert not STATEMENT_AS_EXPRESSION.search(subexpression), (
        "a $( ) subexpression is valid PowerShell and must pass")


def test_the_host_solve_pass_keeps_the_engine_s_output():
    """The other half of what this failure showed.

    The PowerShell parse error reached the instructor only because
    nothing was redirecting the pass's output. A named refusal from the
    commandlet itself would have scrolled past inside UE's log instead.
    render_ue_scenario.ps1 has teed its output to a log since 7cef57d
    for exactly that reason; the scenario pass now does too.
    """
    text = (Path(__file__).resolve().parents[1]
            / "scripts" / "run_ue_scenario.ps1").read_text(encoding="utf-8")
    assert "Tee-Object" in text
    assert "the commandlet's last words" in text
