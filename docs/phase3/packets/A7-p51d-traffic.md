Cause: in the code (verifier), not the render or the machine.

p51d as traffic beside the c172p primary, Windows, df5c48b0-based tip.

Run 64cb84d761a2: formation, 40 m abeam, camera 120 m back, 1 s. The p51d's alone
pass has 971 px, visible_fraction 1.0, 126.6 m, labelled, tiles on. Verify was
33 PASS, 2 FAIL, both on the p51d: mask_vs_geometry and box_vs_mask, mask 119x41
against a hull of 154.7x46.8. The mask was right: 11.3 m span at 126.6 m is
117.5 px. core/capture/verify.py took the mesh hull for the primary only, so
traffic was graded on the extents box, whose corners stand off the wings.

Fix: traffic takes its mesh by the digest its object record carries
(_mesh_asset). No threshold moved. No citation, or a wrong digest, stays on the
box. Same run re-verified: 35 PASS, 0 FAIL, lowest IoU 0.950. The re-verify graded
the existing frame; no new render ran on the fixed code.

The fix exposed a fixture leak: fabricated_manifest says it reads nothing from
this machine's assets, but compose_objects put the machine's real A320 digest on
its traffic. It now clears that. 12 tests failed until then. Files touching the
verifier: 1008 passed, 15 skipped.

Known gaps:
- Run 319faa821a87, formation at 150 m under the default chase camera: 35 PASS
  with the p51d out of frame, 0 px. Verify does not flag traffic with no pixels.
  Left unchanged by the Mac's ruling.
- First attempt, c7309d6eab57, was killed for low memory during import. The
  retry imported the model alone first and passed. TEX_wing and TEX_fus are
  8192x8192 with about 4.5 GB build estimates each. That these caused the kill
  is not proven.
