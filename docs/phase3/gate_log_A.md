# Gate A log (Windows, letter-gates pass, 2026-11-04, tip 5213bba4)

Gate lines verbatim from tasks/phase3_checklist.md.

| Gate line | Result | Evidence |
|---|---|---|
| Tests pass on all three operating systems. | owner-pending | CI: not run, owner decision 23. Last finished green run: 0c68db3e, 42128478598, three jobs, as reported by the Mac. |
| **On the reviewer's computer, from a fresh download:** Generate gives pictures from both cameras and 7 of 7 label checks pass, with no hand import, no flag and no old program. | owner-pending | Needs the reviewer's computer. Measured on this laptop only: both cameras 200 frames (run 473b9e1ecfff), 7 of 7 on 7237db488652, A-4 import with no hand step (A7). |
| The same on the other two computers. | owner-pending | Decision 9. |

Boxes: A2-A9, A11, A12, A13 PASS. A1 cut (rows 2-3 owner-pending). A10 FAIL (packet A10-4: campaign finishes, 12 of 12 verified; download refused by aircraft.licence_dataset, owner decision).

Letter A: FAIL until A10's decision and the pending rows land.

## Re-run, 2026-11-05

A10 re-proved on 03bc3bac: campaign d39d37055bf5, llm tier, 12 of 12 verified, card 200,
download 200, 19.9 MB, 12 images. A fresh clone launched to READY. Letter A's laptop
gate test passes with the two rows above still owner-pending. CI: not run, owner decision 23.
