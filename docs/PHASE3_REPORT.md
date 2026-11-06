# Phase 3 report

## Acceptance sheet (F5), 5 Nov 2026

**Phase 3 is built and proved on one laptop. It is not accepted.** Letters A to D and F pass
the laptop gate test; F passes with F2 accepted on one machine (decision 26) and two goals
owner-pending. Letter E stays red on purpose: E6 needs the owner's double-click, and no agent
can stand in for it. Evidence is from the Windows
laptop unless a row says otherwise. Run logs under `runs/` stay on that laptop.

| # | Criterion | State | Evidence | Still needed |
|---|---|---|---|---|
| 1 | A newcomer completes a capture without the notes | Owner-pending | An agent, not a person, with only `docs/GUIDE.md`: run d24c496c5872, 35 PASS, 0 FAIL, zip downloaded, tiles drawn with no key. Attempt 1 found a real bug, fixed in cf41ce35. `docs/phase3/gate_log_E.md`, `docs/PHASE3_LOG.md` | A real person: none available on 6 Nov, so this stays open |
| 2 | J-11 available; same pipeline in Desert and Forest | Proved | J11 Desert 57fe18aa0719, J11 Forest 82d994bf7935, A4 Desert 2f5fcb4991ab, A4 Forest 3c8ae258e11e (`gate_log_D.md`); F1 99.66 s on ff491087 | Nothing |
| 3 | Payload boxes wherever payload is visible | Proved | `component_boxes` and `component_coverage` PASS on the D6 cells above; F1's zip clause; J-11 dataset has 12 payload boxes over 6 images | Nothing |
| 4 | Hands-off run on a pinned toolchain | Proved on one machine | Fresh clone, run 027ccd408fe7, 35 PASS, 0 FAIL, 247 s; `toolchain.json`, `requirements.lock`, B1-B3 PASS; Gate 6 `GATE 6: PASS` at e6a60f75 against a substitute only (decision 25) | Owner judges the side-by-side |
| 5 | Short video and a short guide | Proved | `docs/demo/demo.mp4`, 89 s, run e60762d4364b, 35 PASS, 0 FAIL; `docs/GUIDE.md`, 899 words. Scripted on a built install, not a double-click (`docs/demo/README.md`) | Nothing required |
| 6 | No command line on the user path | Owner-pending | `Launch FlightSim.cmd` opened by automation in a new folder: READY in about 565 s, all seven steps (`docs/phase3/packets/E6-materials.md`). Nobody watched the screen | The owner's double-click: browser opened on 6 Nov; READY and no prompt not yet reported |

| Letter | Gate test on the laptop | Align's second run (Mac, on 1b29b7d2) |
|---|---|---|
| A | PASS; other computers owner-pending | Synced, no drift |
| B | PASS; B4 on the substitute baseline, other computers owner-pending | Synced; records corrected below |
| C | PASS | Synced; records corrected below |
| D | PASS | Synced; `sync_log_D.md` does not exist, so it used the gate log and event log |
| E | FAIL on E6, the double-click | Not run; it runs after a letter passes |
| F | PASS, 6 Nov; F2 on one machine (decision 26), goals 1 and 6 owner-pending | Not run |

F2 and F5 were ticked by Windows on 6 Nov at the owner's word. F5 has no run of its own, so
its `run_id` names this report.

**Full test suite.** Mac, Python 3.11, `pytest -n 4`, on this commit's tree: 3,752 tests, 0 failed, 0 errors, 15 skipped (the skips include the `ue_host` tests; F1 ran separately on Windows). The suite did not complete on the Windows laptop: it was killed for low memory, so this is a one-machine result. Two unmarked tests were starting the real editor, which caused the Mac's flaky refusal and very likely added to the laptop's memory load. Both are fixed, and a process sampler saw no editor start in the final run.

**Cut or dropped, and why**

| Item | Why |
|---|---|
| A1 rows 2-3 | Decision 9 |
| D3, a second airframe | Decision 3: one airframe, the J-11A |
| CI on three operating systems | Owner, decision 23. Last green: `0c68db3e`, run 42128478598. Nothing after it was checked on any other OS |
| F2 rows 2 and 3 | Waived by the owner, decision 26: accepted on one machine. Working on three computers stays unproved |
| Old footage comparison | Footage not found. Decision 25: the left panel is this project's own 6 October still. It shows change since then and says nothing about likeness to the old build. The new plain reads much brighter, and nobody has judged it |
| p51d as a primary aircraft | Decision 22: its FDM cannot trim, so it is traffic only. Traffic render PASS, run 64cb84d761a2, re-verified 35 PASS, 0 FAIL |

**Known gaps**

- A traffic aircraft that draws 0 pixels is not flagged by verify.
- A traffic clause naming an unknown aircraft compiles to no traffic. It leaves a note, not a refusal.
- Each launch opens one more browser tab; a script cannot see which tabs are open. The old server window now closes (728dc15d; window count 1 on launches 4 and 5).
- `docs/VALIDITY.md`: the 5.7.4 exposure biases are still not re-measured by a probe file.
- Some state files cite Windows-only or merged-away commit hashes. The code is the same; only the citation is old.

The sections below are the history of how this was reached. Where they differ from this
sheet, this sheet is current.

## First report, 2026-11-04

Written 2026-11-04 by the Mac session, in budget mode. Engine: UE 5.7.4 (decision 10).
Every box with Mac code is built and on `phase-2-final`. **Phase 3 is not accepted yet:**
the open items below are real. Verdicts are the Windows runner's messages, as logged in
`docs/phase3/events_mac.log`. Windows rewrote the state files' `verdict` fields from its
evidence in 500a9698, after a wrong command had left them blank through run A-2.

## The six goals

| # | Goal | State | Evidence | Still needed |
|---|---|---|---|---|
| 1 | A new person does a full capture without help | Built, not proved | E1-E6, `docs/GUIDE.md` (845 words) | E verdicts, Gate E newcomer run |
| 2 | A J-11 is available; Desert and Forest work | Built, not proved | `assets/aircraft_config/J11.json`, D4 presets, D5 places, D6 matrix | D proof on Windows; 3 J11 table tests fail (below) |
| 3 | Payload boxes wherever payload is visible | Proved on one A-4 still | C4 PASS run C-1: mask ids 64/65/66, `component_boxes`, `component_coverage` PASS | D6 matrix for the other cells |
| 4 | One hands-off run on locked tool versions | Partly proved | `toolchain.json`, `requirements.lock`, B1 B2 B3 PASS | F1 `ue_host` run, F2 rows, A10 re-proof, B4 |
| 5 | A short video and a short guide | Guide done | `docs/GUIDE.md` | F4 video (owner and Windows) |
| 6 | Nothing a user does needs the command line | Built, not proved | E5 checkboxes, E6 `Launch FlightSim.cmd` | E6 launch on a fresh folder |

## Box verdicts

| Verdict | Boxes |
|---|---|
| PASS | A2 A3 A4 A5 A6 A7 A8 A9 A11 A12, B1 B2 B3, C1 C2 C3 C4 C5 C6 |
| FAIL | A10 (packet A10-3: its own causes are gone; needs one re-proof after C4, plus llm "unknown field 'notes'"), B4 (packet B4-3: Gate 6 clauses; round 3 deferred) |
| No verdict yet | A13 (NEXT.md fixed after packet A13-1, awaiting re-check), D2 D4 D5 D6, E1-E6, F1 |
| Cut or deferred | A1 rows 2-3 (decision 9), D3 (decision 3), C7 step 6 (deferred: budget) |
| Owner or Windows only | F2, F4 |

Letter gates and Align's second run were not run for any letter. D's audit was stopped
and folded into the single run below.

## The single full test run (Mac, Python 3.11, `pytest -n 6`, before this report)

24 FAILED or ERROR. The pass count was lost to JSBSim's stdout. Parallel running with
`-n 6` is itself unproved on this suite, so some failures may be order effects.

| Tests | Count | Reading |
|---|---|---|
| `test_webapp_generate.py` | 10 | Same cases failed on the unmodified base in the A10 retry (this Mac has no working engine import) |
| `test_modes`, `test_limits`, `test_loading` (every configured airframe) | 3 | Likely a real D2 gap, confirmed for modes: J11 is missing from a table. Not fixed |
| `test_messages` | 1 | Real: `toolchain.pin_unreadable` and `google_tiles.terrain_not_georeferenced` have no catalogue entry. Not fixed |
| `test_ue_physics_source` gauss_legendre, `test_wake`, `test_weather` | 3 | Recorded baseline failures from letter A; the weather one execs a bare `python` |
| `test_ue_physics_source` patches 5 and 6, `test_ue_world_source` (2), `test_ue_materials`, `test_geoid`, `test_dis`, `test_dataset_boxes` | 7 | Not triaged |

The plain `scripts/mutation_check.sh` run did not happen. Mutation guard 242 is a known
weak guard. CI on the branch had no green run to cite when this was written.

## Owner decisions open

- Decision 18: a non-georeferenced test raster declines Google tiles by name instead of refusing.
- Letter E defaults taken without confirmation: settings table in `core/config_surface.py`,
  secrets in plain text in `settings.json`, launcher in the repo root, materials stamp, `cmd /k`.
- F1 reads "pick aircraft" as the page's default A-4; no aircraft picker exists.

## Update after the single run (`e7b128cf`)

Fixed and rerun by file, serially: the J-11A's loading block (it could not parse, so a
loaded J-11A run would refuse: CG envelope reason, a loadable policy station, arms read
live from JSBSim), its class, limits and DIS rows, five missing catalogue entries, and
stale assertions in `test_ue_world_source`, `test_ue_materials`, `test_ue_physics_source`,
`test_geoid`. The J-11A's limit figures are published numbers from memory, marked
"unverified here". The J-11A's policy station is the inboard pylon, a stated choice.

CI runs again since the billing fix. The last finished run (`30945bf5`) failed on all three
operating systems; its ubuntu job's nine failures are all in the set fixed above. No run of
`e7b128cf` had finished when this was written, so no green CI row exists yet.

Still failing on the Mac: `test_webapp_generate` (10, Mac engine import),
`test_dataset_boxes` COCO file not found (first run with pycocotools installed; untriaged),
gauss_legendre, `test_wake`, `test_weather` (baseline).

## Full suite, serial (Mac, Python 3.11, commit `d5f95a4c`, 15.4 min)

3,685 tests: 3,656 passed, 9 failed, 5 errors, 15 skipped. This replaces the `-n 6` run
above. The 14: `test_webapp_generate` (10 of them: 5 failures and 5 setup errors; 9 are the
Mac's engine import, plus the page test that assumes no engine), `test_dataset_boxes` (COCO
file not found, untriaged), gauss_legendre and `test_wake` (last-digit float, baseline),
`test_weather` (bare `python` not on this Mac's path, baseline). Skips: no node (7), no
EGM2008 grid (4), no real bakes here (3+). Later commits (the albedo change, NEXT.md) were
not in this run.

**Blocker, owner's decision (packet A10-4):** `aircraft.licence_dataset` refuses pixel export
for all seven aircraft (A-4 all rights reserved, the rest GPL-2.0), so `/card` and
`/download` answer 409 on a finished campaign. A10's campaign itself verified 12 of 12.

## Later on 2026-11-04

Letter gates as Windows reported them: **C PASS, D PASS on the laptop.** A10 PASS (c172p
campaign 6b69c8dc1d28, tier llm, 12 of 12 verified, card and 19.6 MB download) after the
owner cleared the models (decision 20), so letter A's gate needs a re-run, as does B's.
A13, A7 PASS. B4's albedo clause PASS. D2 D4 D5 D6 PASS, E1 E4 PASS. Windows CI failures
fixed: digest-pinned assets kept byte-exact, the exporter writes LF on every OS, Git Bash
for the bridge tests. The two float baselines now compare within rounding, and
`test_weather` uses the running interpreter. Fog units (decision 21) and the Gate 6 rework
are unpushed on Windows and unreviewed. Open: E2 E3 real-key half, E5, E6, F1, F2, F4.


## Finishing run, 5 Nov 2026

Supersedes the tables above where they differ. Not accepted yet: a letter counts only when
`pytest -m gate_<L>` is green on the laptop and on CI for the same commit.

| Item | State |
|---|---|
| PASS by state file | A2-A13, B1-B3, C1-C7, D1 D2 D4 D5 D6, E1-E5 |
| B4 | Gate 6 INCOMPLETE: every measured clause passes; the side-by-side has no old footage. Searched the Mac, the laptop's PNGs, Drive by name and the repo; not found |
| E6 | Fresh clone on `cead67ba`: steps 1-7 exit 0, READY. Later launcher fix proved by a forced rerun only. The owner's double-click is open |
| Decision 18 | Confirmed by the owner |
| p51d | Decision 22: owner-cleared, traffic only, its FDM cannot trim. Fetch and convert ran on Windows; the import was killed for low memory, so it is not proved |
| A10 | PASS on `6b69c8dc1d28`; re-proof on the tip not run |
| DHC6 engine render, Gate E newcomer, F1 `ue_host` | Not run |
| F2, F4, F5 | Open |
| CI | Dropped by the owner (decision 23). Last green: `0c68db3e`, run 42128478598. Nothing after it was checked on three operating systems |

Known gap: a traffic clause naming an aircraft outside the vocabulary compiles to no
traffic and no message.
