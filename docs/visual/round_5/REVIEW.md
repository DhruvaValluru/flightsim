# Round 5 review (p3-mac): f7232cc7, vis-windows d811bb8d

Contact sheet: docs/visual/compare_4_5/contact.jpg. 12 of 14 rendered; #11 fixed in 3bc6fb9b, #14 is the refusal test (pass).

## Verdict: 3 better, 4 same, 5 worse. Round 5 is not an improvement over round 4.

| # | vs r4 | note |
|---|---|---|
| 01 | worse | A-4 gold/brown, darker |
| 02 | same | still blue; probes rule out sky light AND aerial perspective |
| 03 | same | |
| 04 | worse | sun BEHIND camera, yet the A-4 is dark: was white in r4 |
| 05 | better | gold haze gone, neutral; dark backlit A-4 is physically right here |
| 06 | worse | A320 near-black silhouette |
| 07 | worse | A320 dark grey (was light) |
| 08 | worse | C172 black; lower-left ground crushed to black |
| 09 | better | cloud reads better, brighter; rain shaft still a straight column |
| 10 | broken | tan cone with a faceted octagonal skirt fills the frame; no C172 |
| 12 | same | cockpit glass slightly darker |
| 13 | better | ocean deeper blue, 747 fine |

## Findings
1. **Dark aircraft = the L4 PBR masters, not (only) cloud shadow.** #04 (sun behind camera, clear sky) and #06/#13
   (clear sky above) are dark too, so the round 6 deck-cloud-shadow lead can't be the main cause. Check the base colour
   linear/sRGB handling and the metallic/roughness from physically_based/materials.json (a paint with metallic>0 goes
   dark under a sky light that SM5 can't reflect); compare one aircraft with -look-pbr=off (or the gen-3 master).
2. **Label bug (training data): verify annotation.component_box failed** on #01: store_sta2 tight [566,389,594,412]
   isn't inside its hull [568.1,373.8,598.7,419.5] (2 px on x). Either the hull or the tight box uses a different
   pose/CG; this branch still predates the CG label fix f5ac5ed7, so check it after the merge first.
3. look.beauty_not_label_aligned is unmeasured; it needs the covered fraction to pass or fail honestly.
4. #02 blue: with sky light and aerial perspective both excluded, what's left is post (white balance / LUT / exposure
   on super_bright) or the tile albedo. Next probe: #02 with the look LUT and white balance off.
5. DXGI_ERROR_DEVICE_HUNG came back on 4 of 6 single renders after head5 (none in the main pass): a long session
   seems to wear the iGPU; fresh editor per render or the fallback switches are the work-around.
