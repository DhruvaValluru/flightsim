# Visual round 5 on f7232cc7 (Windows, Intel integrated, D3D11 SM5, beauty, FLIGHTSIM_BEAUTY_POST=on)

Replaces the round 5 request at 83849e24 (that pass was stopped at 7 of 14 and set aside).

## Counts
- 14 scenes: 12 rendered, 2 refused, 0 failed. Refusals by name: #11 envelope.trim_feasible
  (fixed in 3bc6fb9b; rendered in round 6), #14 prompt.unsupported (the hurricane refusal test: a pass).
- Seconds per still (scene start to done, includes host flight + post): #1 122, #2 111, #3 141, #4 116,
  #5 121, #6 172, #7 161, #8 162, #9 862 (first compile of the new storm-cell volumetric shaders; single
  shader jobs 55-117 s), #10 176, #12 151, #13 121. Typical 110-175 s.
- Batches: #1-#7 then #8-#14 with --resume; no memory stop.
- head5 a-d rendered (552 s for the four); compare: runs/visual/compare_head4_vs_head5.png.
- Post frames: NN_<name>_post.jpg and contact_post.jpg; tools fetched once and sha256-checked
  (ffmpeg n8.1.3, OIDN 2.5.1; Real-ESRGAN not fetched: upscale off).

## Prep
- Build Succeeded. Materials: M_TornadoFunnel, M_StormCell created; M_FlightSimDistantClouds, M_AircraftGlassThin and the
  gen-4 aircraft masters made in the same session; 0 MATERIAL-FAILED.
- First materials run failed: assets/looks/physically_based/materials.json sha256 mismatch because core.autocrlf=true checked
  it out with CRLF. Restored the repo bytes locally (assets/looks, assets/aircraft_config/look, 4 shaders); nothing committed.
  p3-mac's .gitattributes fix (0abca495) makes this permanent.
- import_aircraft J11 c172p B747 A320: MI_<slot>_thin instances written (J11 x2, c172p x2, B747, A320).

## Device lost (DXGI_ERROR_DEVICE_HUNG)
- The 14-scene pass and head5 had none. After head5, 4 of 6 single-scene renders lost the device ("Unreal Engine is exiting
  due to D3D device being lost (0x887A0006 HUNG)"): A/B sun_shadows_off (twice), A/B post_off (once; plain retry rendered),
  probe r5a (once; plain retry rendered), probe r5b (once). sun_shadows_off and r5b rendered on the requested fallback
  (+ -look-sun-shadows=off -look-fog-grid=off), so those two folders are named *_fallback.

## A/B on #01 (runs/visual/round5_ab/)
- default (all looks on, post on) = the main pass #01, run ed8b25d0ffee.
- post_off (1f312f9e0511), sun_shadows_off_fallback (bb0320f8cee7; fog grid also off). round5_ab_devicelost/ holds the failed tries.

## #02 probes (runs/visual/round5_probes/)
- r5a -sky-fill-probe=red: light_color_linear r1 g0 b0, processed_texture true. Shade did NOT go red: lost green but stayed blue
  (frame mean 92/99/155 -> 91/78/135; lower-right 78/91/161 -> 77/71/143).
- r5b -sky-fill-probe=off -aerial-perspective-scale=0 (fallback): light colour 0/0/0. Still blue (66/73/130; lower-right 53/67/140).
- So the blue shade comes from neither the sky light nor aerial perspective.

## verify (#01, ed8b25d0ffee): FAILED, 35 passed, 2 failed, 33 not run
- annotation.component_box: payload store_sta2 bbox_2d_tight [566,389,594,412] not inside its bbox_2d_hull [568.1,373.8,598.7,419.5].
- look.beauty_not_label_aligned: beauty-only actors may cover the subject where the mask shows it; covered fraction not measured.
- look_record PASS.

## By eye (means in brightness_vs_round_4.txt)
- REGRESSION: aircraft much darker on the gen-4 masters. A320 #06 and C172 #08 near-black silhouettes, #07 A320 dark grey,
  A-4 #01/#02/#04/#05 gold-brown/dark; head5 J-11 near-black in a, b, c (white in head4).
- head5 d: canopy frame darker with a checker pattern on the bow; edge aliasing 0.285 -> 0.731.
- #10: a tan cone funnel fills the frame on a faceted octagonal base; the C172 is not visible.
- #09: brighter (47 -> 72); rain shaft still a straight-sided column.
- #02: still blue (92/99/155).
