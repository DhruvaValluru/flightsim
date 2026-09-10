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
                   "LogFlightSim", "Error:", "refus",
                   # Version 4: the first frame's recorded row, with
                   # units, and the conditions the run was asked for.
                   "state_units", "conditions"):
        assert needed in script, f"the report no longer collects {needed}"

    # NOT RUN is not a pass, so its reason is as wanted as a failure's.
    assert 'status -ne "PASS"' in script, (
        "the report must explain every check that did not pass, not only "
        "the ones that failed")

    # And it must not commit anything but the report.
    assert "GIT_INDEX_FILE" in script, (
        "pushing must not touch the working tree; a temporary index is "
        "how an in-progress edit avoids being committed or stashed")


# -- the redirect that means "die if it says anything" -------------------
#
# Under $ErrorActionPreference = "Stop", Windows PowerShell 5.1 turns a
# REDIRECTED stderr line from a native command into a terminating
# NativeCommandError. So `... 2>$null`, which every reader takes to mean
# "I do not care what it prints on stderr", actually means "throw if it
# prints anything at all" -- the precise opposite, on the exact calls
# that were written BECAUSE they were expected to fail.
#
# It has now cost three scripts. setup.ps1 and deploy_windows.ps1 found
# it (the Microsoft Store's python.exe stub printing "Python was not
# found" killed a deploy) and each grew a wrapper. report_run.ps1 was
# then written without one and died on its first -Push, at
# `rev-parse refs/heads/run-reports` -- the line whose whole job was to
# ask whether that branch existed yet. ue_preflight.ps1 carried two more
# of them, each guarding a probe whose own Fail line was unreachable.
#
# A merge (`2>&1 | Tee-Object`) is NOT this bug and must keep passing:
# it makes stderr ordinary output, which is why every engine pass in
# this repo has always logged that way.

#: `2>` to anything that is not `&1`. `2>&1` merges; `2>$null` and
#: `2>file` redirect, and only redirection throws.
STDERR_REDIRECT = re.compile(r"2>\s*(?!&1)(\$null|\$[A-Za-z_]\w*|[\"'./\\A-Za-z])")


def guarded_regions(path: Path):
    """Line spans of functions that drop $ErrorActionPreference.

    Brace-counted from each `function` header. Crude, and enough: the
    safe idiom in this repo is a small wrapper function that saves the
    preference, sets Continue, redirects, and restores in a finally.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    spans = []
    for index, line in enumerate(lines):
        if not re.match(r"\s*function\s+[\w-]+", line):
            continue
        depth = 0
        started = False
        for end in range(index, len(lines)):
            depth += lines[end].count("{") - lines[end].count("}")
            if "{" in lines[end]:
                started = True
            if started and depth <= 0:
                break
        body = "\n".join(lines[index:end + 1])
        if re.search(r'\$ErrorActionPreference\s*=\s*"Continue"', body):
            spans.append((index + 1, end + 1))
    return spans


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_stderr_is_not_redirected_under_a_stop_preference(script):
    text = script.read_text(encoding="utf-8")
    if not re.search(r'\$ErrorActionPreference\s*=\s*"Stop"', text):
        return
    spans = guarded_regions(script)
    offenders = []
    for number, line in code_lines(script):
        if not STDERR_REDIRECT.search(line):
            continue
        if any(lo <= number <= hi for lo, hi in spans):
            continue
        offenders.append((number, line.strip()))
    assert not offenders, (
        f"{script.name}: a native command's stderr is redirected while "
        f"$ErrorActionPreference is 'Stop', which makes any stderr line "
        f"a terminating error; call it through a wrapper that drops the "
        f"preference to 'Continue', or merge with 2>&1 instead:\n" +
        "\n".join(f"  line {n}: {text}" for n, text in offenders))


def test_the_stderr_lint_catches_the_bugs_it_was_written_for():
    """Its own reference cases: the two shapes that actually shipped."""
    assert STDERR_REDIRECT.search(
        '    $parent = & git -C $repo rev-parse "refs/heads/$Branch" 2>$null')
    assert STDERR_REDIRECT.search(
        '        $core = & $py -c "import jsbsim" 2>$null')

    # A MERGE is how every engine pass in this repo logs, and is fine.
    assert not STDERR_REDIRECT.search(
        "& $editor @arguments 2>&1 | Tee-Object -FilePath $log | Out-Null")
    assert not STDERR_REDIRECT.search("Git @('push') | Out-Host")


def test_the_report_does_not_pipe_a_line_into_git():
    """The other half of the same failed run, and the quieter half.

    `"100644 blob $blob`t reports/x.txt" | git update-index --index-info`
    reaches git with PowerShell's CRLF on the end, so the path carries a
    trailing carriage return -- a control character, which Windows git
    rejects. It does not fail loudly: it prints "Ignoring path ..." and
    writes an EMPTY tree, so the push succeeds and delivers a commit
    with no report in it. --cacheinfo passes the entry as an argument,
    where PowerShell's line endings cannot reach it.
    """
    script = (Path(__file__).resolve().parents[1]
              / "scripts" / "report_run.ps1")
    # Code only: this file's own comments name the bug on purpose.
    code = "\n".join(line for _, line in code_lines(script))
    assert "--index-info" not in code, (
        "an index entry piped on stdin picks up PowerShell's CRLF")
    assert "--cacheinfo" in code
    # And the commit message likewise goes in as an argument, not on
    # stdin, for exactly the same reason.
    assert "commit-tree" in code
    assert "| & git" not in code


def test_the_report_cannot_sit_waiting_for_a_credential():
    """A push that WAITS is worse than a push that fails.

    `run-reports` has never existed on the remote, and the first push of
    a new branch is exactly when git reaches for a credential helper. If
    it has nothing cached it waits -- on a terminal prompt, or on a
    Credential Manager window that may open behind everything else. The
    script looks hung, and the report (already written to disk before
    the push) looks lost with it. Reported as "taking way too long",
    which is the only symptom it can produce.
    """
    script = (Path(__file__).resolve().parents[1]
              / "scripts" / "report_run.ps1")
    code = "\n".join(line for _, line in code_lines(script))
    assert 'GIT_TERMINAL_PROMPT = "0"' in code
    assert 'GCM_INTERACTIVE = "never"' in code
    # And it must say where the report already is when the push fails,
    # rather than only that it failed.
    assert "$reportPath" in code.split("could not push")[-1], (
        "a failed push must name the report already on disk")


def test_the_report_reads_engine_logs_from_the_tail():
    """`Select-String -Path` reads the WHOLE file.

    These logs grow with the frame count -- the commandlet logs per
    frame -- so continuous capture makes them an order of magnitude
    longer than the three-still runs this script was written against,
    once per pass. The code only ever kept the last ten matches, so the
    tail gives the same answer in constant time; the whole-file scan
    stays as the fallback for a refusal that fired early.
    """
    script = (Path(__file__).resolve().parents[1]
              / "scripts" / "report_run.ps1")
    code = "\n".join(line for _, line in code_lines(script))
    assert "-Tail $TAIL_LINES" in code
    assert "Select-String -Path" in code, (
        "the whole-file scan must remain as the fallback")


def test_the_report_says_what_it_is_doing():
    """A script that prints nothing for a minute cannot be told from a
    hung one, and that is exactly how this was reported."""
    script = (Path(__file__).resolve().parents[1]
              / "scripts" / "report_run.ps1")
    code = "\n".join(line for _, line in code_lines(script))
    body = re.search(r"function Step\([^)]*\)\s*\{(.*?)\n\}", code, re.S)
    assert body and "Write-Host" in body.group(1), (
        "Step must actually print; a Step that writes nothing is the "
        "same silence with a name on it")
    for phase in ("finding the newest run", "reading {0}", "pushing to"):
        assert phase in code, f"no progress line for: {phase}"


# -- the wrapper that wrapped itself ------------------------------------
#
# PowerShell resolves a command as alias, then FUNCTION, then cmdlet,
# then external program -- case-insensitively. So a wrapper written the
# obvious way:
#
#     function Git {
#         ...
#         try { & git -C $repo @GitArgs }   # <- calls Git, not git.exe
#     }
#
# never reaches git at all. It recurses until the engine gives up:
#
#     The script failed due to call depth overflow.
#
# and it is SLOW before it is fatal, so the run before the one that
# reported it was reported instead as "taking way too long" -- thousands
# of stack frames doing nothing, indistinguishable from a push waiting
# on a credential. Two rounds spent on the wrong diagnosis.

#: A bare `& name` call: an external program or another function, but
#: not `& $variable`, which is a resolved path and cannot collide.
BARE_AMPERSAND_CALL = re.compile(r"&\s+([A-Za-z][\w.-]*)")


def function_blocks(path: Path):
    """(name, body) for every `function NAME {` in the file."""
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks = []
    for index, line in enumerate(lines):
        match = re.match(r"\s*function\s+([\w-]+)", line)
        if not match:
            continue
        depth = 0
        started = False
        for end in range(index, len(lines)):
            depth += lines[end].count("{") - lines[end].count("}")
            if "{" in lines[end]:
                started = True
            if started and depth <= 0:
                break
        blocks.append((match.group(1), "\n".join(lines[index:end + 1])))
    return blocks


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_no_function_shadows_the_command_it_calls(script):
    offenders = []
    for name, body in function_blocks(script):
        for called in BARE_AMPERSAND_CALL.findall(body):
            stem = called.rsplit(".", 1)[0]
            if stem.lower() == name.lower():
                offenders.append((name, called))
    assert not offenders, (
        f"{script.name}: a function invokes a command with its own name, "
        f"which PowerShell resolves back to the function -- infinite "
        f"recursion, not a call to the program. Rename the function "
        f"(Invoke-Git) and call a resolved path (& $gitExe):\n" +
        "\n".join(f"  function {n} calls & {c}" for n, c in offenders))


def test_the_shadowing_lint_catches_the_bug_it_was_written_for(tmp_path):
    """The exact wrapper that shipped, and the fix for it."""
    shipped = tmp_path / "shipped.ps1"
    shipped.write_text(
        'function Git {\n'
        '    param([string[]]$GitArgs)\n'
        '    try { & git -C $repo @GitArgs }\n'
        '}\n', encoding="utf-8")
    assert [n for n, body in function_blocks(shipped)] == ["Git"]
    assert any(c.rsplit(".", 1)[0].lower() == n.lower()
               for n, body in function_blocks(shipped)
               for c in BARE_AMPERSAND_CALL.findall(body))

    fixed = tmp_path / "fixed.ps1"
    fixed.write_text(
        'function Invoke-Git {\n'
        '    param([string[]]$GitArgs)\n'
        '    try { & $gitExe -C $repo @GitArgs }\n'
        '}\n', encoding="utf-8")
    assert not any(c.rsplit(".", 1)[0].lower() == n.lower()
                   for n, body in function_blocks(fixed)
                   for c in BARE_AMPERSAND_CALL.findall(body))

    # `.exe` on the call site is the same collision: PowerShell matches
    # a function named Git against `& git.exe`? It does not -- but the
    # stem comparison is what makes the lint catch `function Git` +
    # `& Git.exe`, which some shells' habits produce.
    both = tmp_path / "both.ps1"
    both.write_text('function Git {\n    & Git.exe status\n}\n',
                    encoding="utf-8")
    assert any(c.rsplit(".", 1)[0].lower() == n.lower()
               for n, body in function_blocks(both)
               for c in BARE_AMPERSAND_CALL.findall(body))


def test_the_report_calls_git_through_a_resolved_path():
    """Belt to the lint's braces: the wrapper must not name git at all."""
    script = (Path(__file__).resolve().parents[1]
              / "scripts" / "report_run.ps1")
    code = "\n".join(line for _, line in code_lines(script))
    assert "function Invoke-Git" in code
    assert "& $gitExe" in code
    assert not re.search(r"&\s+git\b", code), (
        "every git call must go through the resolved $gitExe path")
