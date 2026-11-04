# Phase 3 · Mac session startup prompt

Paste everything below the line into a fresh Claude Code session on the Mac,
in the `flightsim` checkout on branch `phase-2-final`, with
`claude remote-control` running in another terminal. The word **ultracode** in
the first line is what lets the session run multi-agent workflows.

---

ultracode. You are the **Mac session** of the FlightSim Phase 3 two-machine
pipeline. Read `docs/phase3/README.md`, `tasks/phase3_checklist.md` (the
tick-box sheet) and `tasks/phase3_todo.md` (the full plan, one section per
box) before anything else. Do not open the PDF; the two markdown files are the
same content. Follow CLAUDE.md at all times: Google tiles stay on, storm
weather stays on, never subscribe to a PR, never schedule a check-in.

## Your machine, your peer

- You host: breakdown agent, sub-agents, Align, build agents for Mac-tagged
  steps (Python, web, docs, tests), auditor, debug triage, context agent,
  summary agent, overlap agent, final report agent.
- The Windows session hosts: decision agent, runner, synopsis, cross-check,
  letter tester, newcomer agent, build agents for Windows-tagged steps (C++,
  PowerShell, materials, import), cross-letter tester.
- First action: run `ListAgents`, find the Windows session (its name contains
  `flightsim`), write it to `docs/phase3/state/peers.json` as
  `{"windows": "<name>"}`, and read `"mac"` back from the same file once the
  Windows session has written it. Send every message with `SendMessage` to
  that name. Messages are one line, prefixed `P3`, and every message is also
  logged with `scripts/phase3_event.py log --stage msg --note "msg <text>"`.
- Second action: open the three progress windows:
  `bash scripts/phase3_terminals.sh`. They are read-only.

## State, logs, git

- All state is in the repo under `docs/phase3/`: `decisions.md` (written by
  Windows), `state/<box>.json` (one writer at a time), `notes/<box>.md`,
  `digest_<L>.md`, `sync_log_<L>.md` and `gate_log_<L>.md` (written by
  Windows), `summaries/`, `overlap.md`, `events_mac.log` (yours).
- Every command any agent runs goes through
  `python3 scripts/phase3_event.py run --agent <a> --box <b> --stage <s> -- <cmd>`.
  Notes go through `... log --agent <a> --box <b> --stage <s> --note "<text>"`.
  A failure note starts with `FAIL`, a pass note with `PASS`. Never write JSON
  by hand.
- Git: you are the only side that pushes code. Push once per letter batch,
  never per box. Always `git pull --no-rebase origin phase-2-final` first (a
  merge: `--rebase=merges` replays every box merge and re-raises its
  resolved conflicts, measured three times on 2026-11-04; the event logs
  union-merge via .gitattributes, state files take Windows' version).
  Windows only ever commits under `docs/phase3/` and `tasks/`, so a merge
  never conflicts. Builders work in their own worktree
  (`git worktree add ../p3-<box> phase-2-final`), and the integrator merges
  the box into `phase-2-final` in Align's build order.

## Messages you send and receive

| From | Text | Meaning |
|---|---|---|
| Windows → you | `P3 go <L> decisions=ok` | the letter's decisions are in `decisions.md`; start the letter |
| you → Windows | `P3 pushed <commit> letter=<L> boxes=<A2,A4,...>` | a letter batch (or one retried box) is on the branch |
| Windows → you | `P3 verdict <box> PASS run=<id>` / `P3 verdict <box> FAIL packet=docs/phase3/packets/<box>-<n>.md` | per-box verdict |
| Windows → you | `P3 shared-value-changed <box> <what>` | a retry touched the pin, an ID band, a manifest version or a message id |
| you → Windows | `P3 synced <L>` | Align's second run passed; run the letter test |
| Windows → you | `P3 letter <L> PASS` / `P3 letter <L> FAIL boxes=<...> gate=<pass|fail>` | letter test result |
| you → Windows | `P3 phase-end sets=docs/phase3/overlap.md` | run the cross-letter sets |
| Windows → you | `P3 xlt PASS` / `P3 xlt FAIL sets=<...>` | cross-letter result |

After every `pushed` you wait for verdicts by watching `state/<box>.json`
(the Windows side writes `verdict` there). If nothing arrives within 90
minutes for a Python-only batch or 4 hours for a batch that needs an engine
build, re-send `pushed` once; if still nothing, log `FAIL no-verdict` and ask
the Windows decision agent by message to decide.

## Token rules (these are hard rules, not advice)

**Budget mode (owner's rule, 2026-11-04 evening: 83 % of the weekly credit spent).**
Finishing the remaining letters' BUILDS comes first; everything else is cut
until the owner lifts this:
- no integrator agents: the Mac session runs `scripts/phase3_integrate.sh`
  itself and reads the diff only where the script fails;
- no auditor agents: the session runs the letter's test files and
  `mutation_check.sh --check-targets` itself;
- breakdown and Align are ONE fable agent per letter, writing the notes itself
  (no sub-agents); builders stay one Workflow per letter on fable, briefs kept
  to the note's coding plan;
- no new retry builders for letters A-D: a Windows FAIL is logged with its
  packet and left for after F unless the fix is a one-line test or path edit
  the session can make itself;
- Stage 7 keeps the full-suite run (a script) and the final report (fable);
  the summary and overlap agents are skipped and their sections of the report
  are written from the notes by the final-report agent.

1. **Model per role.** `fable` for breakdown, Align, debug triage, context,
   overlap, the final report and (owner's rule, 2026-11-04) every builder.
   `sonnet` for sub-agents, integrators and the auditor. `haiku` for the summary agent. Pass `model`
   on every `Agent` call. **Builders only run as ultracode** (owner's rule,
   2026-11-04): each letter's Stage 3 builders are one `Workflow` run whose
   `agent()` calls use `model: "fable"`, fanned out in Align's build order with
   `parallel()` inside each order group; a retry builder is a one-agent
   workflow. No other role runs through `Workflow`.
2. **Scripts do the mechanical work.** Logging, test running, grep-based
   checks, diffs and merge are shell commands through `phase3_event.py run`.
   An agent never retypes a file to the parent and never composes JSON.
3. **Digest, not repo.** The breakdown agent writes `digest_<L>.md` once per
   letter: for each box, the plan section verbatim, the files it names, and
   the signatures in those files from `grep -n "^def \|^class \|^    def "`
   (not file bodies). Cap 120 lines per box. Sub-agents read the digest and
   open a file only to confirm a name.
4. **Budgets.** Sub-agent 25 tool calls, builder 60, integrator 30, Align 40,
   debug 30. Recorded in `state/<box>.json` as `budget_used`. A unit over
   budget is stopped by the breakdown agent; its partial note goes to the
   Windows decision agent by message (`P3 over-budget <box>`).
5. **Group XS boxes** with the box they serve, one unit each: A1+A2,
   A12+A13, B2+B3, D1+D2, F2+F4+F5. About 30 units per phase, not 41.
6. **No full-suite runs until every letter is finished** (owner's rule,
   2026-11-04). Integrators and the per-letter auditor run the box's own
   tests plus the touched modules' tests only. `scripts/mutation_check.sh`
   runs only in the auditor, serialized, with its subset option for the
   guards the letter touched. The one full `pytest -q` and the one plain
   `scripts/mutation_check.sh` run happen in Stage 7, after `P3 letter F
   PASS`, before any summary.
7. **Retries skip Align** and re-check only the failed box.
8. **Reports are short.** Every agent returns at most 40 lines to its parent:
   what it did, files touched, the check it ran and its exit code, blockers.
9. **Stateless roles, fresh agents.** Every letter gets its own new
   breakdown, Align, auditor and debug agents, and every box (and every
   retry) gets its own new sub-agent, builder and integrator (owner's rule,
   2026-11-04). No agent is reused across boxes or letters; each reads
   everything from the files. Nothing depends on memory.
10. **Letters pipeline, they do not queue** (owner's rule, 2026-11-04). The
   moment letter L's `pushed` message is sent, start letter L+1 at Stage 1
   while Windows proves L. L's retries (Stage 4) and its Align second run
   (Stage 5) interleave with L+1's build; they use separate worktrees and a
   retry push carries only its own box.

## The per-letter loop (A, B, C, D, E, F: each letter's build starts as soon as the previous one is pushed)

**Stage 0.** Do not wait for `P3 go <L>`; it is informational. Start Stage 1
of letter L+1 right after letter L's `pushed` message. Confirm
`docs/phase3/decisions.md` has the lines the letter needs (A: engine pin; C:
A-4 loadout; D: airframe; E: storm default and tiles key). If one is missing,
ask by message and build the boxes that do not depend on it meanwhile.

**Stage 1 · breakdown agent (fable).** Writes `digest_<L>.md`. Groups XS
boxes. Spawns one sub-agent per unit, in parallel, each with: the unit's plan
sections, the digest rows for its files, the decisions file, and the brief
below. Waits for all notes. Then spawns Align. Named exception: during A,
also spawn the units for C1, C5 and C6.

**Sub-agent brief (sonnet).** Write `notes/<box>.md` with: `goal` (the box's
Do and Verify lines verbatim); `found_in_repo` (what exists, half-done or
contradicts the plan, with file:line); `steps` (smallest steps, each with its
own check); `approaches` (at least two, trade-off, chosen one and why);
`coding_plan` (modules, functions, signatures, imports, test file and test
names, each name marked `[exists file:line]` or `[new]`; an unmarked name is a
defect); `machine` tag per step (`mac` or `windows`); `depends_on`;
`needs_windows` (which checks); `decision_needed`. No code. Log start, each
file open and hand-off.

**Stage 2 · Align, first run (fable).** Reads all notes for the letter. Fixes
in place, never sends back: overlap (one owner, rewrite the other note),
gaps (add the step to the right note), agreement (pin, ID band, manifest
version, message ids, settings keys match across notes), feasibility
(re-open the repo only for the chosen approach; replace an approach that
cannot be built on the code as it is), scope (a step with no line in the
box's Do text is cut), names (a plan with an unmarked name goes back to its
sub-agent once, before anything else), machine split (each step tagged mac
or windows; engine-side steps of A5, A6, A9, A11, C4 are windows). Writes a
build order: boxes sharing a file go one after another. Records each edit
with a reason at the bottom of the note. Final pass, then marks the letter
final in `state/<L>.json`.

**Stage 3 · build agents, one per unit, in Align's order.** For every step
tagged `windows`, do not build it here: write the step list to
`notes/<box>.md` under `windows_steps` and include the box in the next
`pushed` message; the Windows session builds those steps itself.

- *Builder (fable, as an ultracode `Workflow` agent; owner's rule 2026-11-04).* Own worktree. Claims its files in `state/<box>.json`
  (`claims`); waits if another box holds one. Codes the whole coding plan,
  nothing stubbed, no TODO. Runs the box's own check from the note until it
  passes locally. Marks every `needs_windows` check `pending`. Logs every
  command. Returns files touched and the check output.
- *Integrator (sonnet).* Reads every touched file and every caller/import of
  what changed. Checks the code fits its surroundings: same names, the
  module's own refuse helper, the message catalogue keyed by rule name, the
  manifest conventions, no duplicate of an existing helper. Runs pytest for
  the box's tests plus the touched modules' tests. Diff guard, automatic
  fail: a weakened assertion in an existing test, a new skip or xfail, a
  caught exception the plan said to raise, a new flag or environment variable
  on the user path, any CLAUDE.md breach (`grep -rn "GOOGLE_TILES\|WEATHER_BACKEND\|subscribe" <touched files>`
  must show nothing that turns tiles or weather off or subscribes to a PR).
  Compares the diff to the note: every planned step present, nothing extra.
  Small fixes itself, recorded; larger ones back to the builder with file and
  line. Merges the box into `phase-2-final` in Align's order and re-runs the
  box tests after the merge. Signs off in `state/<box>.json` (`stage: built`).

**Auditor (sonnet), once per letter** after every integrator signed off:
the letter's box tests plus every touched module's tests once (no full
suite until Stage 7), then `scripts/mutation_check.sh` with its subset
option for the guards this letter touched, serialized. A guard whose test
stays green with the guard removed fails the letter. Hard gate.

**Push.** `git pull --no-rebase`, push, send `P3 pushed <commit> letter=<L>
boxes=<all units, including windows-only ones>`.

**Stage 4 · per-box failure.** On `P3 verdict <box> FAIL packet=<path>` or
`P3 shared-value-changed`, spawn the debug triage (fable) for the letter. It
reads the packet and the note and picks the cheapest route: `machine`
(reply `P3 machine-fix <box> <what>` to Windows, no code change); `box`
(integrator first, builder if needed, sub-agent re-brainstorm only if the
integrator says the approach is wrong); `interaction` (one instruction per
box, builders, auditor); `gate`; `decision` (message the Windows decision
agent). Align is not run on retries. Push the retried box alone:
`P3 pushed <commit> letter=<L> boxes=<box>`. The debug agent keeps counts in
`state/<box>.json` (`failures`) and `state/<L>.json`; at 3 on a box or 5 on a
letter it sends `P3 cap <box>` with the packet paths to the Windows decision
agent and waits for `P3 decision <box> retry-forbid=<approaches>` or
`P3 decision <box> cut`.

**Stage 5 · when every box in the letter is ticked** (`state/<box>.json`
`verdict: PASS` for all, or `cut`): Align second run (fable) reads
`sync_log_<L>.md`, not the notes, and checks the code that passed on Windows
still agrees across the letter and matches the branch. `synced` → send
`P3 synced <L>`. Not synced → debug agent reads the drift list and the sync
log, writes one instruction per affected box, builders, auditor, Align again,
loop until synced.

**Stage 6 · `P3 letter <L> FAIL`** → debug triage with every failing box and
the gate result, same five routes, then: push, Windows re-checks only the
affected boxes, Align second run, `P3 synced <L>` again. Never back to stage
1 for a box that already passed alone.

**`P3 letter <L> PASS`** → nothing to start: the next letter is already
building (rule 10). Record the letter as passed in `state/<L>.json`.

## Stage 7, once, after `P3 letter F PASS`

- *Full suite, once.* `pytest -q` over the whole tree and the plain
  `scripts/mutation_check.sh` run, through `phase3_event.py run`. Any
  failure goes to a debug triage (fable) and a builder workflow, then the
  suite runs again; nothing below starts until both are green.

- *Summary agent (haiku), one reader per letter.* For each box, from
  `git diff` of its sync-log commits and the files on the branch now:
  `summaries/<box>.md` with files changed, functions added or changed,
  shared values set or read, tests, passing run id. Plus `summaries/INDEX.md`.
- *Overlap agent (fable).* Builds the table of shared values, files and call
  paths across letters by grep over the summaries' `shared_values` and
  `files` fields; flags suspect sets (same value or file written by two
  letters; one letter's output is another's input: A4 stamp → E6, C5 → C6 →
  F1, E2 → D4; summary disagrees with sync log). For each set, the exact
  checks: the boxes' verify lines plus the demo E2E. Writes `overlap.md`.
  Boxes in no set are not re-tested. Send `P3 phase-end sets=docs/phase3/overlap.md`.
- *`P3 xlt FAIL sets=<...>`* → context agent (fable) writes one brief per
  set (what was checked, letters involved, which value or call path broke,
  likely owner box and why) to `docs/phase3/packets/xlt-<set>.md`, hands it
  to the debug triage of each letter involved; the normal loop runs; then the
  summary agent refreshes only the changed boxes and you send `phase-end`
  again with only the failed sets.
- *`P3 xlt PASS`* → final report agent (fable) writes
  `docs/PHASE3_REPORT.md`: decisions and cuts first, then one row per
  acceptance criterion with its evidence, then what was measured on one
  machine only. Commit, push, open a **draft** PR to `phase-2-final` with the
  GitHub tools, immediately unsubscribe from it, log `PASS phase-end`, and
  stop. No polling, no check-ins.
