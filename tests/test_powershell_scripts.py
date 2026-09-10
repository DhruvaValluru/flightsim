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


def _inside_quotes(line: str, index: int) -> bool:
    """True when `line[index]` sits inside a quoted string.

    Counts unescaped quotes before it; odd means open.
    """
    single = line.count("'", 0, index) - line.count("\\'", 0, index)
    double = line.count('"', 0, index) - line.count('\\"', 0, index)
    return (single % 2 == 1) or (double % 2 == 1)


#: `-name=value` where the value contains a dot -- the shape that broke.
DOTTED_SWITCH = re.compile(r"-[A-Za-z][\w-]*=[^\s\"']*\.[^\s\"']*")


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_dotted_native_arguments_are_quoted(script):
    """The second half of the same failure, and the more dangerous half.

    `run_ue_scenario.ps1` passed its commandlet name bare::

        & $editor ... -run=FlightSimBridge.FlightSimScenario ...

    PowerShell split that token at the dot, so UE received `-run=
    FlightSimBridge` and `.FlightSimScenario` as two arguments and
    reported "FlightSimBridgeCommandlet looked like a commandlet, but we
    could not find the class" -- naming a class nobody wrote, which
    reads like a broken build rather than a quoting bug. It cost a full
    headless flight per attempt to find out otherwise.

    `render_ue_scenario.ps1` has always passed a quoted array and has
    always worked. An unquoted native-command argument is at the mercy
    of PowerShell's tokenizer; a quoted one is not.
    """
    offenders = []
    for number, line in code_lines(script):
        for match in DOTTED_SWITCH.finditer(line):
            if not _inside_quotes(line, match.start()):
                offenders.append((number, match.group(0)))
    assert not offenders, (
        f"{script.name}: an unquoted native argument carries a dot and "
        f"PowerShell may split it; quote it:\n" +
        "\n".join(f"  line {n}: {text}" for n, text in offenders))


def test_the_dotted_argument_lint_catches_the_bug_it_was_written_for():
    """Its own reference case, for the same reason as above."""
    shipped = "    -run=FlightSimBridge.FlightSimScenario `"
    match = DOTTED_SWITCH.search(shipped)
    assert match and not _inside_quotes(shipped, match.start())

    fixed = '    "-run=FlightSimBridge.FlightSimScenario",'
    match = DOTTED_SWITCH.search(fixed)
    assert match and _inside_quotes(fixed, match.start()), (
        "a quoted argument must pass")

    # A switch with no dot cannot be split this way, so it is not the
    # lint's business.
    plain = "    -unattended -nopause -nosplash"
    assert not DOTTED_SWITCH.search(plain)


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


def test_the_run_report_collects_what_diagnosis_has_actually_needed():
    """Every failure on this branch was diagnosed from one of these.

    The PowerShell parse error, the split commandlet name, the
    scripted-card refusal, the schedule that outran the clip, the
    landmark sets that disagreed -- each was found in a verification
    detail or a named engine-log line. A report that stopped collecting
    one of them would quietly cost a round trip, so this pins the set.
    """
    script = (Path(__file__).resolve().parents[1]
              / "scripts" / "report_run.ps1").read_text(encoding="utf-8")

    for needed in ("capture_manifest.json", "verify.json", "solve_source",
                   "LogFlightSim", "Error:", "refus"):
        assert needed in script, f"the report no longer collects {needed}"

    # NOT RUN is not a pass, so its reason is as wanted as a failure's.
    assert 'status -ne "PASS"' in script, (
        "the report must explain every check that did not pass, not only "
        "the ones that failed")

    # And it must not commit anything but the report.
    assert "GIT_INDEX_FILE" in script, (
        "pushing must not touch the working tree; a temporary index is "
        "how an in-progress edit avoids being committed or stashed")
