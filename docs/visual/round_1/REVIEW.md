# Round 1 review (overhaul d4e9c7dd vs round 0), by eye + compare_0_1

12 rendered, 2 refused as before (#11 trim, #14 hurricane). beauty_look on all 12 (look_check.json).

| # | scene | verdict | note |
|---|---|---|---|
| 01 | golden hour A-4 | better | warm light, purple cast mostly gone (luma 37 -> 96) |
| 02 | super bright | WORSE | now differs from 01 but is a heavy indigo/blue cast, and darker than 01 (76 vs 96) |
| 03 | A320 New York | better | sharper, real cloud field |
| 04 | desert, sun behind | much better | haze gone, contrast and colour, clouds |
| 05 | desert backlit | better | warm backlit haze instead of grey wash |
| 06 | A320 SFO rain | mixed | slab replaced by a cloud deck, livery reads; still no ground |
| 07 | tower heavy rain | not fixed | streak wall gone, but frame is flat grey, aircraft invisible |
| 08 | C172 Fuji sunrise | WORSE | fully blown white, mountain gone |
| 09 | 747 thunderstorm | WORSE | plain blue sky: no storm, no cloud, aircraft a dot |
| 10 | C172 tornado | better | black voids and red cast gone; still no tornado |
| 12 | cockpit Grand Canyon | broken | a dark polygon slab covers ~80% of the frame |
| 13 | 747 ocean | much better | level horizon, aircraft, sea, clouds |

Promises: #13 level YES; #07 not a wall yes-but-empty; #06 ground NO; storm visible NO; #02 brighter than #01 NO.
Tally: 6 better, 1 mixed, 5 worse/broken. head2 sheet not done (shot a: J11 material slots; shot b: sky-capture hang).
