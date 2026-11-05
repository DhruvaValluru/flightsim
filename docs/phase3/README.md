# Phase 3 · running the two-machine pipeline

Branch: `phase-2-final`. Machines: a Mac (plans, Python builds, progress
windows) and a Windows laptop with Unreal 5.5 (proves everything, builds the
C++). Model: Claude Fable 5.1, with cheaper models for mechanical roles as
the prompts say. The design is in two maps kept outside the repo; the
prompts here are the executable version of them.

## Files

| Path | What |
|---|---|
| `docs/phase3/PROMPT_MAC.md` | paste into the Mac session |
| `docs/phase3/PROMPT_WINDOWS.md` | paste into the Windows session, first |
| `scripts/phase3_event.py` | every agent logs and runs commands through this |
| `scripts/phase3_monitor.py` | the progress windows (`progress`, `mac`, `windows`) |
| `scripts/phase3_terminals.sh` | opens the three windows on the Mac |
| `docs/phase3/state/<box>.json` | per-box state, one writer at a time |
| `docs/phase3/notes/<box>.md` | the sub-agent's plan for the box, edited by Align |
| `docs/phase3/decisions.md` | the six calls, written by the Windows decision agent |
| `docs/phase3/sync_log_<L>.md`, `gate_log_<L>.md` | written by Windows per letter |
| `docs/phase3/events_mac.log`, `events_windows.log` | one JSON line per agent event |
| `tasks/phase3_checklist.md` | the tick boxes; only the Windows cross-check ticks |

## One-time setup, both machines

1. Claude Code signed in to the same claude.ai account (not an API key).
   Mac needs 2.1.225+, native Windows 2.1.234+ and Git for Windows.
2. Clone and switch:
   `git clone https://github.com/dhruvavalluru/flightsim && cd flightsim && git checkout phase-2-final`
3. The venv the scripts expect, at the repo root:
   Mac `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt`
   Windows `py -m venv .venv; .venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt`
4. Remote Control is turned on *inside* the working session, not in a
   separate window: after `claude` starts, type `/remote-control`, then
   `/rename p3-mac` (or `p3-windows`), then `/list-agents` to confirm the
   other machine's session appears. A separate `claude remote-control`
   window is a different session and does not connect the working one.

## Windows only

- Unreal Engine 5.5 with the MSVC toolset and Windows SDK. Note the install
  path; set `UE_ROOT` to it.
- Cesium for Unreal, ffmpeg and Python installed (B2 pins their versions).
- Playwright and its Chromium in the venv, for the newcomer agent.
- A cache folder outside the clone, e.g. `D:\flightsim-cache`; set
  `FLIGHTSIM_CACHE` to it.
- `FLIGHTSIM_MACHINE=windows` in the shell that runs the session.
- The Google tiles key typed once into the app's Settings.
- Plugged in, sleep off, lid open. A sleeping laptop looks offline to the Mac.

## Start the run

1. **Windows first.** Open Claude Code in the checkout, type
   `/remote-control` and `/rename p3-windows`, then paste
   `docs/phase3/PROMPT_WINDOWS.md` (everything under the line). It writes
   `decisions.md`, finds the Mac session, and sends `P3 go A`.
2. **Mac second.** Open Claude Code in the checkout, type `/remote-control`
   and `/rename p3-mac`, then paste `docs/phase3/PROMPT_MAC.md`. It opens the three progress windows and waits
   for `P3 go A`.
3. Watch the windows. Window 1: a bar per letter, what each machine is doing
   with elapsed time, the last message in flight, failures against caps.
   Window 2: every Mac command with its exit code as it happens. Window 3:
   the same for Windows, plus messages.
4. When it finishes, a draft PR to `phase-2-final` exists and both sessions
   have stopped. Read `docs/PHASE3_REPORT.md` first page: decisions and cuts.

## If a session dies

Start it again with the same prompt. All state is in the repo; the session
reads `docs/phase3/state/` and continues from the first box not marked
`verdict: PASS` or `cut`. Nothing depends on memory.

## Finishing run (restart after 5 Nov 2026)

Three things were added after the first run, and they change what "done"
means:

| Path | What |
|---|---|
| `tests/test_phase3_gates.py` | the definition of done: `pytest -m gate_<L>` passes when every box of the letter is ticked (or cut by decision) with a PASS state and run id, and every gate line is ticked with a PASS or owner-pending row in the gate log. Excluded from the default suite; run by name. |
| `tests/test_phase3_decisions.py` | the code matches the decision log: engine pin, tiles on, storm on. In the default suite. |
| `scripts/windows_env_check.ps1` | asserts every Windows precondition by name and writes `docs/phase3/machine.json`; the runner refuses to prove anything without a fresh `ok: true`. |
| `scripts/phase3_repro.py <box>` | reproduce, diff against last green, localize; written to `packets/<box>-repro.md` and read by triage before any re-brainstorm. The runner records `green_commit` on every PASS. |

Rules for the finishing run:

1. A letter is finished only when `pytest -m gate_<L>` passes on the
   laptop and the same commit is green on CI. No other statement counts.
2. Windows first: the engine-side and WINDOWS checks of a letter are
   scheduled before the Mac's work on the next letter, so the long renders
   are never the last thing in the queue.
3. Verification is never skipped for budget: a budget stop halts at the
   next checkpoint with a written reason; it does not thin the checks.
4. Every failure gets a repro packet before anyone proposes a new approach.

What is left (from the status board, 5 Nov): A10 gate re-run; B4 Gate 6
clauses (code); C7 optional; E2 E3 E5 E6 Windows checks; F1 ue_host run;
F2 and F4 (owner); F5; gate lines ticked for every letter; CI green.

Start order: Windows runs `scripts\windows_env_check.ps1` first, then both
sessions get the "Finishing run" section at the end of their prompt.
