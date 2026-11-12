# Round 0 review (Mac, 2026-11-09)

Frames: phase-2-final 1a62d557, rendered on the Windows laptop (Intel GPU, D3D11
SM5: no Lumen, no VSM, no Nanite). 12 of 14 rendered; #11 refused
envelope.trim_feasible, #14 refused as intended. Reviewed by eye, one frame each.

| # | Scene | Verdict | What is wrong |
|---|---|---|---|
| 01 | A-4, Yosemite, golden hour | Close | Real tiles and a real aircraft. Cliffs carry a purple-blue cast; golden hour reads as cold midday |
| 02 | Same, super bright preset | Bug | Pixel-identical to 01 to the eye: the preset has no visible effect |
| 03 | A320, New York, wide lens | Good | Best frame. Clouds a little smeared |
| 04 | A-4, desert, sun behind | Fair | Haze washes the lower half to flat grey |
| 05 | A-4, desert, backlit | Fair | Same haze; the aircraft goes dark grey but backlighting is plausible |
| 06 | A320, SFO, moderate rain | Broken | No terrain: blue sky over a flat grey slab with vertical streaks |
| 07 | Tower view, heavy rain | Broken | Grey wall of vertical streaks, aircraft a dot; reads as a render fault, not rain |
| 08 | C172, Fuji, sunrise, light rain | Poor | Washed to near-white; purple slope at right |
| 09 | 747, thunderstorm | Broken | Uniform blue wash; two hard-edged light cones under the aircraft; no storm |
| 10 | C172, tornado, Flint Hills | Poor | Ground saturated red with pure-black voids (tile holes or shadow crush); no tornado visible |
| 12 | C172 cockpit, Grand Canyon | Broken | White slab fills the lower third; struts float |
| 13 | 747 cruise, ocean | Broken | Near-black blue frame, no aircraft, horizon at about 35 degrees |

Across frames: a blue-purple cast in shadows (01, 02, 08, 13), and rain drawn as
full-frame vertical streaks (06, 07). Overlaps the overhaul's round-2 list (black
storm, cockpit slab, banding); 02, 06, 10 and 13 look new.

Round 0 also showed a tool bug: visual_round.py took stale frames from earlier
batches in runs/test_scenarios. Fixed: it now takes only the frames whose names
match this batch's summary.
