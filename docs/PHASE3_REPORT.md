# Phase 3 report

Written 2026-11-04 by the Mac session, in budget mode. Engine: UE 5.7.4 (decision 10).
Every box with Mac code is built and on `phase-2-final`. **Phase 3 is not accepted yet:**
the open items below are real. Verdicts are the Windows runner's messages, as logged in
`docs/phase3/events_mac.log`; the `verdict` fields in `docs/phase3/state/*.json` are blank
on this branch and should not be read as evidence.

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
| PASS | A2 A3 A4 A5 A6 A8 A9 A11 A12, B1 B2 B3, C1 C2 C3 C4 C5 C6 |
| FAIL | A10 (packet A10-3: its own causes are gone; needs one re-proof after C4, plus llm "unknown field 'notes'"), B4 (packet B4-3: Gate 6 clauses; round 3 deferred) |
| No verdict yet | A7, A13, D2 D4 D5 D6, E1-E6, F1 |
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
