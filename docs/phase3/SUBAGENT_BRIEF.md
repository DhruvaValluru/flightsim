# Phase 3 sub-agent brief (planning, no code)

You plan one unit of Phase 3 (one or two boxes). You write NO code. Budget: 25
tool calls in total, counted by you. Work from `docs/phase3/digest_<L>.md`
(the plan section for your box, the files it names, their signatures) and
`docs/phase3/decisions.md` (the six owner decisions: engine pin 5.5, A-4
loadout, J-11A, storm on, tiles key once, no control surfaces). Open a source
file only to confirm a name or a line number; never read whole files when a
grep answers. CLAUDE.md rules: Google tiles stay on, storm weather stays on,
nothing subscribes to a PR, nothing schedules a check-in.

## Logging (every unit, mandatory)

- Start: `python3 scripts/phase3_event.py log --agent sub --box <box> --stage plan --note "start <unit>"`
- Each file you open: `... log --agent sub --box <box> --stage plan --note "open <path>"`
- Hand-off: `... log --agent sub --box <box> --stage plan --note "PASS note written" `
  (or `--note "FAIL <why>"` if you could not finish).
- Then: `python3 scripts/phase3_state.py set <box> stage=planned budget_used=<n> needs_windows=<true|false>`
  (one call per box in the unit).
Never write JSON by hand. Never retype a file into your reply.

## The note: `docs/phase3/notes/<box>.md` (one per box, even in a grouped unit)

Sections, in this order, these exact headings:

- `## goal` — the box's **Do** and **Verify** lines verbatim from the plan.
- `## found_in_repo` — what already exists, is half-done, or contradicts the
  plan, each with `file:line`. Say plainly when a line number in the plan is
  stale.
- `## steps` — the smallest steps, numbered, each with its own check (a command
  or an observation) and a `machine: mac|windows` tag. A step that needs the
  Unreal engine, a Windows build, a PowerShell run on Windows, or a real render
  is `windows`. Python, tests, docs, web pages are `mac`.
- `## approaches` — at least two, with the trade-off, the one chosen and why.
- `## coding_plan` — modules, functions, signatures, imports, test file and
  test names. Every name is marked `[exists file:line]` or `[new]`. An unmarked
  name is a defect. No code bodies.
- `## depends_on` — other boxes whose output this box needs (by box id).
- `## needs_windows` — the checks only Windows can run, each as a one-line
  check description, or `none`.
- `## decision_needed` — anything the owner must still decide, or `none`.
- `## windows_steps` — leave as `(filled by Align/build)`.

## Return to the parent (at most 40 lines)

What you did, the note path(s), the files you opened, the checks you ran with
their exit codes, blockers. Nothing else.
