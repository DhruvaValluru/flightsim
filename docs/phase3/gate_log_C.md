# Gate C log (Windows, letter-gates pass, 2026-11-04)

| Gate line | Result | Evidence |
|---|---|---|
| A web-app A-4 run passes verify with `component_coverage` PASS. | PASS | Run b6fece769aaa (`POST /run {}`, the A-4 default): verify ok, no FAIL; `component_coverage` PASS (6 ID images, 18 component-frames carry their record); `component_boxes` PASS (18 records). runs/p3/G/GateC-E4.log |
| Nobody pressed an extra button or added a flag. | PASS | The request body was `{}`. |

Boxes: C1-C6 PASS. C7 step 6 not run (deferred: budget; optional; not on the go list).

Correction, 2026-11-05: C7 step 6 did run later: run 90a9f2cfb840 on 984487b8, `component_coverage` and `component_boxes` PASS (`events_windows.log`).

Letter C: PASS.
