# Phase 3 builder brief (fable, run as an ultracode Workflow agent; owner's rule 2026-11-04)

You build one unit (one or two boxes) from its aligned note(s)
`docs/phase3/notes/<box>.md`, in your OWN worktree. Budget: 60 tool calls,
counted by you. The main checkout is `/Users/dhruva/flightsim` (call it MAIN);
never edit files there. CLAUDE.md rules: Google tiles stay on, storm weather
stays on, nothing subscribes to a PR, nothing schedules a check-in, no new
flag or environment variable on the user path.

## Setup (first commands)

    cd /Users/dhruva/flightsim && git worktree add -b p3-<box> ../p3-<box> phase-2-final
    python3 MAIN/scripts/phase3_state.py claim <box> <every file you will touch>

If `claim` prints `BUSY <other box> holds [...]`, wait: re-run it every 60 s
with `sleep 60` in a loop of at most 20 tries; if still busy, log
`FAIL claim busy` and return. Then
`python3 MAIN/scripts/phase3_state.py set <box> stage=building worktree=../p3-<box>`.

## Logging (mandatory, every command)

Every command runs through the MAIN runner with `--cwd` at your worktree:

    python3 MAIN/scripts/phase3_event.py run --agent builder --box <box> --stage build --cwd ../p3-<box> -- <cmd>

Tests use the MAIN venv: `/Users/dhruva/flightsim/.venv/bin/pytest -q <tests>`
(run from the worktree via `--cwd`; the worktree's own code is imported).
Notes: `python3 MAIN/scripts/phase3_event.py log --agent builder --box <box> --stage build --note "..."`.
A failure note starts with `FAIL`, a pass note with `PASS`. Never write JSON by hand.

## Build

- Read the note's `## steps`, `## coding_plan`, `## align_edits`. Build every
  step tagged `mac`. Do NOT build steps tagged `windows`; they are already
  listed under `## windows_steps` for the Windows session.
- Code the whole coding plan: nothing stubbed, no TODO, no placeholder, no
  `pass` body, no `xfail`, no new `skip` except the one the note names for a
  Windows-only fixture. Keep the module's own refuse helper and the message
  catalogue keyed by rule name, as the note says.
- Follow the signatures and names in the coding plan. Mark nothing "later".
- Run the box's own check from the note (`## goal` Verify lines tagged mac and
  the step checks) until it passes locally. Every `needs_windows` check is
  recorded as pending: `python3 MAIN/scripts/phase3_state.py set <box> pending_windows='["<check>", ...]'`.
- Commit in your worktree: `git add -A && git commit -m "<box>: <one line>"`
  (through the runner). Do not push. Do not merge. Do not touch MAIN.
- Finish: `python3 MAIN/scripts/phase3_state.py set <box> stage=built_local builder_commit=<sha> budget_used=<n>`
  and log `PASS built <box>` (or `FAIL <why>`).

## Return to the parent (at most 40 lines)

Files touched (paths), the check command(s) you ran with exit codes, tests
added (names), pending Windows checks, blockers. Nothing else; never paste code.
