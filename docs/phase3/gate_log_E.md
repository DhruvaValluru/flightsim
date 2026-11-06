# Gate E log (Windows, 2026-11-05)

| Gate line | Result | Evidence |
|---|---|---|
| Someone new uses only the launcher and the app and gets a passing run. They don't read NEXT.md, open a terminal or ask you anything. | owner-pending | Needs a person. An agent (haiku) with only docs/GUIDE.md and a page helper got run d24c496c5872, verify 35 PASS, 0 FAIL, on the fresh install at cf41ce35; its first attempt failed on a real bug, fixed. See docs/PHASE3_LOG.md. |
| Their questions are written in `docs/PHASE3_LOG.md`. | PASS | The agent's questions are there, under Gate E, with what became of each. They are an agent's, not a person's. |

Boxes: E1 to E6 as on the sheet. E6 PASS, 2026-11-06: the owner's double-click in a fresh
clone, p3-final at 995275e0, reached READY with no prompt and the browser
opened (docs/phase3/packets/E6-materials.md). The second-launch check was proved on an
earlier clone, 16 s, not on this one.

The first gate line stays owner-pending: no person has done the newcomer run. CI: not run,
owner decision 23.
