# Visual round 3 on b6a9aff2 (Windows, Intel integrated, D3D11 SM5, beauty, default switches)

## Counts
- 14 scenes: 12 rendered, 2 refused (#11, #14 as before), 0 failed. new_look_ran true on all 12.
- head3 a, b, c, d all rendered. Compare: runs/visual/compare_head2_vs_head3.png.
- Ran in the main checkout C:\Users\kanth\flightsim (it holds head2 and the imported content), not p3-final.

## Build, materials, import
- Build Succeeded. Materials: "MATERIAL-REBUILT: /Game/FlightSim/M_StormCell (... this one is 3 ...)", MATERIAL-CREATED; about 5 min, not 15.
- BUG: `import_aircraft.py c172p` printed "already converted (assets\generated\c172p\mesh_manifest.json)" and made no
  propeller_beauty. stale_manifest_reason does not notice the new hide_objects in c172p.json. Workaround used here: moved
  the manifest aside (mesh_manifest.round2.json.bak) and re-ran; then it converted and imported body_beauty + propeller_beauty.
- Because of that, the first 14-scene pass still had the blade in #12 (runs/visual/round3_logs/round3_pass1_12.jpg).
  #08, #10, #12 were re-rendered after the forced re-convert; the round_3 folder holds the re-rendered ones.
- render_visual_sheet.ps1 -Step head3 re-converted and re-imported the J11 by itself before shot a.

## #02 render.json hero_lighting.sky_light.stated_fill
{"color_linear":{"r":1,"g":0.49693301320075989,"b":0.25015801191329956,"a":1},"intensity_scale":1.940949,
 "intensity_scale_applied_by":"-sky-light-scale= (webapp.runs _render multiplies the lighting block's fill by it)",
 "intensity":4.1924481391906738,
 "basis":"a stated sky fill lit as a neutral fill: the model sky's blue moved to grey, its luminance kept, the ground hemisphere compensated (core/scene/hero_lighting.py stated_fill_tint, plan_sidecar; UNCALIBRATED)"}
lower_hemisphere_color: r 3329.4, g 6327.8, b 11091.1

## By eye (means in brightness_vs_round_2.txt)
- #09: the box slab is gone. NEW ARTEFACT: thin white line-work (a hatched grid band) runs across the frame at wing height
  on both sides of the 747 and a white ribbon climbs to the top-right corner; it reads as wireframe, not cloud. No visible
  storm tower with a billowing outline. Rain and the rain shaft remain. Darker (luma 43 -> 33).
- #07: darker grey sky (125 -> 80) with a soft cloud bank across the lower half. At the centre there is only a tiny
  bright speck, a few pixels, not a recognisable A320 silhouette.
- #02: NOT neutral, unchanged: mean rgb 95/102/159 (round 2: 96/102/157). The shade is still blue/indigo.
- #12: no prop blade. Canyon, sky and the cowl at the bottom.
- head3 d: eye is further back; the HUD/panel now shows at the bottom. The canopy bow is NOT at the top edge: it arches
  across the middle of the frame, over the Matterhorn's sides.
- head3 c: much darker than head2 c; the forest and the J-11 are near-black under a dark deck.
- #06: slightly brighter (60 -> 68), ground detail about the same.
- #08: darker (181 -> 142): the slope is now dark red-brown and the C172 is a near-black silhouette; sky still flat white.
- #10: same brightness, small colour shift (89/76/77 -> 95/75/83) after the c172 re-import.
- #01, #04, #13: identical means to round 2.
