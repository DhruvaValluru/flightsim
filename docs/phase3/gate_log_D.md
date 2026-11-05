# Gate D log (Windows, letter-gates pass, 2026-11-04)

| Gate line | Result | Evidence |
|---|---|---|
First pass, superseded by the re-run below: FAIL. Both places work (runs 5835af44a0de grand_canyon, 16342bb78e61 yosemite). The new aircraft was never rendered and no J-11 or A-4 payload was tested in the matrix: all four cells flew the B747 (packet D6-1).

Boxes: D1 decided (decision 3); D3 cut. D4 PASS (desert gives grand_canyon, forest gives yosemite, verify ok). D5 PASS (`bake grand_canyon up to date`, `bake yosemite up to date`, exit 0, both runs; the bakes already existed, so the first-run bake path was not seen). D2 FAIL (packet D2-1). D6 FAIL (packet D6-1).

Letter D: FAIL.

## Re-run after the fixes (supersedes the FAIL above), 2026-11-04

Fixed: `apply_cell` nesting and J-11 `-text` (Mac, 64a14384, 124bc9da); `core/scenario/card.py` engine-mixture probe used the JSBSim wheel's root, so a repo-vendored airframe could not load (Windows); matrix allow-list now names the place-derived keys, with cameras still compared key by key apart from their scene origin and solved poses (Windows).

| Gate line | Result | Evidence |
|---|---|---|
| The new aircraft is available, both places work, payload boxes are present, and the old aircraft still pass. | PASS on this laptop | `runs/p3/G/D6-matrix-5.log`: A4/desert 2f5fcb4991ab, A4/forest 3c8ae258e11e, J11/desert 57fe18aa0719, J11/forest 82d994bf7935: each its own mesh (A4 283850 tris, J11 11677 tris, payload r27r_left and r27r_right), verify ok, no FAIL, `component_coverage` and `component_boxes` PASS. The J-11 imported itself (`ue/Content/Aircraft/J11`). The card allow-list result was re-judged offline on those four saved cards, not by a fresh matrix run. Old aircraft: the A-4 above and letter C; B747 on the earlier matrix. |

D2 PASS: config tests pass, level flight, self-import. D6 PASS. Letter D: PASS on this laptop.
