VIS job: build, prove and photograph the visual overhaul (branch claude/vibrant-gauss-olema4, base 355dae64).
Nothing in it has been compiled or rendered; it was written on a Mac that cannot build UE 5.7.4.
Follow docs/visual/RENDER_RUNBOOK.md exactly, in order; it has every flag. Steps:

 1. git fetch origin; git checkout claude/vibrant-gauss-olema4; git pull --ff-only. Note $head = git rev-parse HEAD.
    First copy the decision-25 substitute still out of runs\gate6\ (Gate 6 deletes frame_*.png under --out).
 2. Git Bash: UE_ROOT="/c/Program Files/Epic Games/UE_5.7" bash scripts/check_bridge_api.sh -> every line ok, CesiumRuntime included.
 3. Baseline at the base: git checkout --detach 355dae64; .\scripts\build_ue.ps1;
    Gate 6 measure into runs\gate6_base; borrow HEAD's experiments/visual_contact_sheet.py and gate6_visual.py
    with git restore --source=$head --worktree; render --step base (beauty) and --step base_measure;
    restore the tree to clean; git checkout claude/vibrant-gauss-olema4. Open the PNGs and list what looks fake.
 4. .\scripts\build_ue.ps1 at HEAD (first compile of the look C++; fix ordinary errors in small commits, beauty-gated).
 5. Re-run scripts\ue_create_materials.py through UnrealEditor-Cmd (expect MATERIAL-CREATED for MPC_FlightSimWorld,
    M_FlightSimCloudLayers, M_FlightSimTilesBeauty, M_Aircraft*; no MATERIAL-FAILED), then
    ue_fix_aircraft_materials.py J11 B747 A320 c172p DHC6 p51d A4.
 6. Gate 6 under measure must be UNCHANGED: same clauses and numbers as runs\gate6_base, Gate 10-R
    --against runs\gate6_base\full runs\gate6\full bit-identical or bounded, and no aircraft_look /
    beauty_look / beauty_path / world_beauty key in runs\gate6\full\render.json. If not, STOP and report.
    Then gate6_visual.py --quality beauty --aliasing-baseline runs\gate6 and read render.json.
 7. .\scripts\render_visual_sheet.ps1 -Step head; -Step head_measure -Quality measure; -Step head_ss32 -StillSamples 32 -Shots a.
 8. .\scripts\render_visual_sheet.ps1 -Compare base,head; copy compare_base_vs_head.png and both shots.json into runs\visual\final\.
 9. .\scripts\render_visual_sheet.ps1 -Step final_clip -Shots a -Clip; copy clip.mp4 to runs\visual\final\chase_clip.mp4.
10. python -m flightsim.verify on shot a's beauty run_dir (from runs\visual\head\shots.json); it needs label masks,
    else use the verifier lane's two-server labelled capture. Exit 0; look_record PASS; any look.* refusal is a finding.
11. python -m experiments.look_label_check --measure <head_measure run_dir> --beauty <head run_dir> --camera chase
    --out runs\visual\final\look_label_check.json (0 ALIGNED, 1 NOT ALIGNED, 2 VOID).
12. experiments\gate_v_visual.py: read --help first (it was not on the branch when the runbook was written); if missing, record it.
13. Path-traced hero still: .\scripts\render_visual_sheet.ps1 -Step head_pt -PathTrace -Spp 256 -Shots a; copy a.png to final\.
14. Sweep the uncalibrated constants in the runbook's order: TSR/Lumen/tiles-colour checks, the per-pixel sun check,
    EV100_BANDS, look_label_check controls, world Mie (FLIGHTSIM_WORLD_BEAUTY_OVERRIDES, no rebuild), still samples/TSR.

Rules: Google tiles are never optional (never FLIGHTSIM_GOOGLE_TILES=off); storm weather stays on by default;
labels must match pixels; physics unchanged; no asset without a pinned URL, sha256 and a redistributable non-NC licence.
Record every number in docs/visual/PROBE_LOG.md under "## render-machine" and in ruflo memory (namespace visual,
key visual-overhaul/render-machine/<topic>) before changing a constant. Small commits ending with the
Co-Authored-By line from the session's attribution reminder.
No schedules, no PR or CI polling, no ruflo daemon. Push, open one draft PR, report once, and stop.

(The packet for the Windows session: paste this whole file as one message. The commands and flags are in docs/visual/RENDER_RUNBOOK.md.)
