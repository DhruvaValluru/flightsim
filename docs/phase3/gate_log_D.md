# Gate D log (Windows, letter-gates pass, 2026-11-04)

| Gate line | Result | Evidence |
|---|---|---|
| The new aircraft is available, both places work, payload boxes are present, and the old aircraft still pass. | FAIL | Both places work (runs 5835af44a0de grand_canyon, 16342bb78e61 yosemite). The new aircraft was never rendered and no J-11 or A-4 payload was tested in the matrix: all four cells flew the B747 (packet D6-1). |

Boxes: D1 decided (decision 3); D3 cut. D4 PASS (desert gives grand_canyon, forest gives yosemite, verify ok). D5 PASS (`bake grand_canyon up to date`, `bake yosemite up to date`, exit 0, both runs; the bakes already existed, so the first-run bake path was not seen). D2 FAIL (packet D2-1). D6 FAIL (packet D6-1).

Letter D: FAIL.
