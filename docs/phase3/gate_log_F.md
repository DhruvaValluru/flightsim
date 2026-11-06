# Gate F log (Windows, 2026-11-05)

| Gate line | Result | Evidence |
|---|---|---|
| 1. A new person does a full capture without help or the notes. | owner-pending | Needs a person; see gate_log_E.md. |
| 2. A J-15, J-11 or J-35 is available, and the same pipeline works in Desert and Forest. | PASS | J-11A in Desert: F1, run 027ccd408fe7 and e60762d4364b. Both places: gate_log_D.md re-run. |
| 3. Payload boxes appear automatically wherever the payload is visible. | PASS | F1's zip clause passed: a payload box wherever verify found payload pixels. C's gate run also. |
| 4. One full run (configure, capture, label) with no manual steps, on locked tool versions. | PASS | F1 on this laptop from a fresh clone, 247 s; the F2 row carries the versions and hash. One machine only. |
| 5. A short video and a short guide exist. | PASS | docs/demo/demo.mp4, 89 s; docs/GUIDE.md, 899 words. |
| 6. Nothing a user does needs the command line. | owner-pending | No step in the guide uses it and the agent used none of the app's own, but no person has confirmed it, and the double-click is open. |

Boxes: F1, F3, F4 PASS. F2 PASS on one machine only, decision 26: rows 2 and 3 waived, not run.
F5 PASS: docs/PHASE3_REPORT.md, acceptance sheet; the box has no run of its own.

CI: not run, owner decision 23.
