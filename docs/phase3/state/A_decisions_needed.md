# Letter A: decisions the sub-agents raised (Align, first run, 2026-11-03)

The Windows decision agent was unreachable at align time; each sub-agent's stated default is applied in its note so building is not blocked. None contradicts decisions.md or CLAUDE.md. The owner may overrule any line; the note then changes, not the code.

- A1: does the decision line written by the Windows decision agent stand as the owner's dated decision, or does the owner add a line naming himself? Default applied: it stands (decision 1 cites the plan's [OWNER] recommendation).
- A3: remove the Python-side newest-`UE_5.*` glob in `core/util/platform.py:217-221` (outside A3's file list)? Resolved by Align: yes, under A2 (step 6b), the same fault as A2's "one pin everywhere".
- A5: the plan's "four from the diff plus two bridge additions" is inverted (P1-P4 are upstream fixes, P5-P6 are in the diff). Default applied: the file's meaning; statuses recorded per patch as the file names them.
- A7: "older than" by mtime or by a hash recorded in the manifest? Default applied: mtime.
- A7: may the preview (`render_here`) trigger the import, or only the render? Default applied: only the render; the preview reports "will be imported on render".
- A8: may the `--no-host-flight` argparse help (capture.py:547) stay? Default applied: keep, reworded "developer only"; hiding is E1's.
- C5: which `class_id` numbers do `payload` and `landing_gear` take? Default applied: appended to the taxonomy class list in that order; every consumer uses `class_id_of`, no literal (C3 to confirm when it writes the card).
- C5: the parent's `visible_fraction` denominator: parent alone pass plus children's alone passes (applied) or parent alone pass only.
- C6: the failure keys `annotation.component_box` / `annotation.component_coverage` and the 1 px tolerance were provisional; Align made them final and recorded them in C5.
- A4 (no decision, a note): the build stamp hashes `Source/` only, not `.uplugin` or Content; say so if those should be in.
- A6 (no decision, a note): the plan's "STALE -> CREATED" first run only appears when stale assets pre-exist; on fresh 5.5 Content the first run prints CREATED only.
