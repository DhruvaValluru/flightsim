# Phase 3 integrator brief (sonnet)

You integrate one built unit from its worktree branch `p3-<box>` into
`phase-2-final` in the MAIN checkout `/Users/dhruva/flightsim`. Budget: 30
tool calls. Log every command through
`python3 scripts/phase3_event.py run --agent integrator --box <box> --stage build -- <cmd>`
(run from MAIN) and notes through `... log ... --note "..."`.

## Review (in the worktree ../p3-<box>, read-only)

1. `git diff phase-2-final...p3-<box> --stat` then the diff itself, in pieces.
2. Read every touched file's changed region and every caller/import of what
   changed (`grep -rn "<name>" core webapp flightsim scripts tests`).
3. Fit: same names as the surroundings, the module's own refuse helper, the
   message catalogue keyed by rule name, the manifest conventions, no
   duplicate of an existing helper (grep for a near-duplicate before accepting
   a new one).
4. Run the box's tests plus the touched modules' tests, from the worktree:
   `/Users/dhruva/flightsim/.venv/bin/pytest -q <box tests> <tests of touched modules>`
   (the mechanical half is `bash scripts/phase3_integrate.sh <box> <tests...>`: merge
   --no-ff, those tests, guard targets for the touched files, diff guard, worktree
   removal, state; you add only the fit review and the note. Never the full suite;
   `mutation_check.sh` only with `--check-targets`/`--no-suite` and `--match`.)
   (use `--cwd ../p3-<box>` on the runner). No full-suite run.
5. Diff guard, automatic FAIL on any of: a weakened assertion in an existing
   test; a new `skip`/`xfail` other than the Windows-fixture skip the note
   names; a caught exception where the plan said to raise or refuse; a new flag
   or environment variable on the user path; a CLAUDE.md breach:
   `grep -rn "GOOGLE_TILES\|WEATHER_BACKEND\|subscribe" <touched files>` must
   show nothing that turns tiles or weather off or subscribes to a PR.
6. Compare the diff to the note: every `mac` step present, nothing extra, no
   TODO/stub.

## Fix or bounce

Small fixes (a name, an import, a message key, a missing test assertion): make
them in the worktree, commit there, record each under `## integrator_edits`
at the bottom of the note. Larger problems: do not fix; log
`FAIL integrate <box>: <file:line> <what>` and return with the list for the
builder.

## Merge (only when the review passes)

    cd /Users/dhruva/flightsim && git merge --no-ff p3-<box> -m "Merge p3-<box>: <one line>"
    /Users/dhruva/flightsim/.venv/bin/pytest -q <box tests>      # after the merge, in MAIN

On a merge conflict: resolve it only if it is trivial (two boxes appending to
the same catalogue or test file); otherwise abort (`git merge --abort`) and
return `FAIL merge conflict <files>`. Then
`python3 scripts/phase3_state.py set <box> stage=built integrated_commit=<sha>`,
`python3 scripts/phase3_state.py release <box>`, log `PASS integrated <box>`.
Leave the worktree in place.

## Return (at most 40 lines)

Verdict, the tests run with exit codes, edits you made, what you bounced.
