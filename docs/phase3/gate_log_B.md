# Gate B log (Windows, letter-gates pass, 2026-11-04)

| Gate line | Result | Evidence |
|---|---|---|
| A fresh download builds with nothing set except `toolchain.json`, and preflight is all `OK` on all three computers. | owner-pending: other two computers; this laptop built from a fresh clone, preflight all OK (runs/p3/G/F2-preflight.txt) | Preflight 7 OK lines exit 0 on this laptop (runs/p3/A-2/B2-preflight-2.log). |

Boxes: B1, B2, B3 PASS (B1 step 10 CI not read). B4 FAIL: albedo sun invariance now PASS (0.000 %, runs/p3/G/B4-gate6.log), wet surface PASS, golden test 9 passed; `GATE 6: FAIL` on range extinction (1.07), aircraft ground shadow (79 px), exposure metric (4.62/255), extinction follows visibility (0.09), exposure at -12 deg (1.87/255), and the old-footage side-by-side. Those clauses are with the owner; none was loosened.

Letter B: FAIL on B4's owner clauses (first pass). See the re-run below.

## Re-run, 2026-11-05

Gate 6 measure and beauty on one build both exit 3, INCOMPLETE: every measured clause passes, and the side-by-side is NOT RUN (`docs/phase3/packets/B4-4.md`). B1, B2, B3 PASS. Letter B stays open on the owner's footage, the owner's review of the exposure control, and the fresh-download evidence from E6.

## Gate 6 with a substitute baseline, 2026-11-05 (decision 25)

Measure and beauty at e6a60f75 both exit 0, `GATE 6: PASS`, every clause measured
(runs/p3/B-1/B4-gate6-sub-measure.log, B4-gate6-sub-beauty.log). The left panel of
runs/p3/B-1/gate6_sub_measure/side_by_side.png is the 6 October runs/gate6 still, this
project's own render. So this pass shows change since then and says nothing about
likeness to the old footage, which is lost. Nobody has judged the side-by-side; on
the right the plain reads much brighter than on the left. The A12 golden test
passed in the verifier-touching files. CI: not run, owner decision 23.
