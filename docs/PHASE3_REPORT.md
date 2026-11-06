# Phase 3 report

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
