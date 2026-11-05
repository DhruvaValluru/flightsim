# Gate B log (Windows, letter-gates pass, 2026-11-04)

| Gate line | Result | Evidence |
|---|---|---|
| A fresh download builds with nothing set except `toolchain.json`, and preflight is all `OK` on all three computers. | this laptop: see E6's fresh-folder launch below; other two computers owner-pending | Preflight 7 OK lines exit 0 on this laptop (runs/p3/A-2/B2-preflight-2.log). |

Boxes: B1, B2, B3 PASS (B1 step 10 CI not read). B4 FAIL: albedo sun invariance now PASS (0.000 %, runs/p3/G/B4-gate6.log), wet surface PASS, golden test 9 passed; `GATE 6: FAIL` on range extinction (1.07), aircraft ground shadow (79 px), exposure metric (4.62/255), extinction follows visibility (0.09), exposure at -12 deg (1.87/255), and the old-footage side-by-side. Those clauses are with the owner; none was loosened.

Letter B: FAIL on B4's owner clauses (first pass). See the re-run below.

## Re-run, 2026-11-05

Gate 6 measure and beauty on one build both exit 3, INCOMPLETE: every measured clause passes, and the side-by-side is NOT RUN (`docs/phase3/packets/B4-4.md`). B1, B2, B3 PASS. Letter B stays open on the owner's footage, the owner's review of the exposure control, and the fresh-download evidence from E6.
