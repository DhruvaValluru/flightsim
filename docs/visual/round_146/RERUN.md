# r146 rerun on 9ef62483 (p3-windows, 2026-11-16)

The owner asked for a fresh r146: pin 9ef62483, rebuild, scene 9 health check, then the rest.
The owner then chose to stop the rerun after round 146, so the GPU is free for r147.
The rerun covered round_1462 (Prep all plus the scene 9 health check) and round_146 (plus verify).
These arms were SKIPPED in the rerun: 1461, 14622, 1463, 1465, 1464, 1466 and 14662.
Their folders still hold the first-pass results from earlier today, also on 9ef62483 except 1462.
The re-verify that ran for round_1465 (8070c82e) re-checked the old first-pass runs; nothing new was rendered for it.

## Prep and scene 9 health: round_1462 (pushed 9f5bd736)
- Prep all (build, materials, aircraft) completed at 9ef62483, so prep_stamp = 9ef62483.
- Scene 9 rendered in 271.8 s (wall 336 s). First warm-up drain 3.48 s, which counts as healthy (>= 3.0). There was no DEVICE_HUNG.
- Scene 9 has now come out clean in 4 of 4 runs since the reboot: 1462 (da82dc78), 1466, 14662 and 1462 (rerun).

## Round 146: scenes 1,2,6,7,8,13, compared with round_144 (pushed d26db21d, verify f113544b)

The 3rd to 5th columns are frame health; the SSIM and flicker columns compare against round_144.

| # | render s | mean luma | crushed | clipped | SSIM vs 144 | flicker | max GPU drain s | verify |
|---|---|---|---|---|---|---|---|---|
| 1 | 100.8 | 0.178 | 0 | 0 | 0.9917 | 0.007 | 0.74 | FAIL (old store_sta2 bbox) |
| 2 | 90.9 | 0.205 | 0 | 0.00002 | 0.9917 | 0.005 | 0.84 | FAIL (old store_sta2 bbox) |
| 6 | 181.1 | 0.068 | 0 | 0 | 0.6507 | 0.065 | 3.00 | pass |
| 7 | 191.2 | 0.121 | 0 | 0 | 0.8264 | 0.105 | 2.68 | pass |
| 8 | 110.8 | 0.529 | 0.00009 | 0 | 0.7937 | 0.202 | 1.51 | FAIL (old c172p mask 517x103 vs hull 517.5x120.6) |
| 13 | 70.9 | 0.111 | 0.00002 | 0 | 0.9963 | 0.001 | 0.61 | pass |

- The rerun matches the first r146 pass to 3 decimals on every luma, so the render is deterministic at this commit.
- There were no hangs in any run.
- All three verify failures are known old failures, not regressions.
- Wall time for the round was 771 s.
- Run ids: #1 9e291f2d5583, #2 d297663ce610, #6 4322b5b83367, #7 c2c627d9fc0c, #8 43d7b3c3c205, #13 999aa85fc835; #9 (1462) 5bd610d6a68b.

## Next
The GPU is idle and waiting for r147: one rebuild (plus ue_create_materials.py only if p3-mac says so), then one still each of 1,2,6,7,10,12,13,15.
r147 needs an exact commit.
