# Visual round 4 on 14da9437 (Windows, Intel integrated, D3D11 SM5, beauty, default switches)

## Counts
- 14 scenes: 12 rendered, 2 refused (#11 envelope.trim_feasible, #14 prompt.unsupported, as before), 0 failed in the final set.
  new_look_ran true on all 12.
- head4 a, b, c, d all rendered. Compare: runs/visual/compare_head3_vs_head4.png.
- Server started with FLIGHTSIM_RENDER_QUALITY=beauty set explicitly; runs\test_scenarios (round 3) moved to
  runs\test_scenarios_round3_pre4 first.

## Build, materials, import
- build_ue.ps1: Target is up to date, Succeeded (built before the laptop shut down).
- ue_create_materials.py: exit 0, "Success - 0 error(s)"; 50 MATERIAL-EXISTS, 0 CREATED/REBUILT, 0 FAILED.
- import_aircraft.py c172p J11: both "already converted", imported 2; c172p body_beauty + propeller_beauty and
  J11 body_beauty re-imported (no forced re-convert needed this time).

## How the 14 were gathered (three batches)
- Batch 1 (runs/visual/round4_scen.log): #1-#8 DONE; killed by the harness for low memory while #9 was rendering
  (server killed with it). test_scenarios.json is written only at the end, so #1-#8's rows were rebuilt from this log's
  run ids and the scenario table (number, name, prompt, lighting, outcome, run_id are exact).
- Batch 2 (round4_scen2.log, --only 9-14): #9, #12, #13 DONE; #11, #14 REFUSED; #10 FAILED.
- #10 failure = 1 timeout: terrain.google_tiles "view was still 0.0 % loaded after 180 s and 4 reload(s)".
  Cause: the home router's DNS (10.0.0.1) returned api.cesium.com's CNAME with no address ("Could not resolve
  hostname"); 1.1.1.1 resolved it. Transient; resolved a few minutes later.
- Batch 3 (round4_scen3.log, --only 10): #10 DONE (run c7dadaf363ad). The failed run is aaed68dec667.

## By eye (means in brightness_vs_round_3.txt)
- #09: the round 3 white line-work / wireframe band is GONE. The frame now shows a dark storm-cloud underside with a soft
  billowing edge above the 747 and the rain. The rain shaft below is still a straight-sided column. Brighter (33 -> 47).
- #07: brighter grey (80 -> 108); the A320 now reads as an aircraft (wings, tail), not a speck.
- #08: brighter (143 -> 162); the C172 reads as a lit aircraft, no longer a near-black silhouette; sky still flat white.
- #10: slightly darker and redder (82 -> 73).
- #02: unchanged, still blue/indigo (rgb 95/102/159).
- #12: unchanged (no prop blade; canopy frame across the bottom).
- #01, #03, #04, #05, #06, #13: same or within 2 luma of round 3.
- head4 c: much brighter than head3 c; the valley, river, forest and the J-11 are readable instead of near-black.
- head4 a, b, d: unchanged from head3 (edge aliasing 0.207, 1.039, 0.285). d's canopy bow still arches mid-frame.
