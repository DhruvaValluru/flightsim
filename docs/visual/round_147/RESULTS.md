# r147 on 536f7d33 (p3-windows, 2026-11-16)

## Prep
- Rebuilt FlightSimEditor at 536f7d33.
- `ue_create_materials.py` rebuilt 4 stale assets with 0 errors:
  - MPC_FlightSimWorld (world 5)
  - M_FlightSimTilesBeauty (world 13)
  - M_FlightSimOceanBeauty (world 7)
  - M_FlightSimDistantClouds (world 6)
- Aircraft step skipped, as asked.

## Round 147: one still per scene, default flags (pushed 0f613c81, verify 08b05119)

Wall time 1173 s. There were no hangs or TDRs in any scene.
SSIM is against round 146; scenes 10 and 15 had no round 146 frame to compare with.

| # | scene | seconds | mean luma | crushed | SSIM vs 146 | max GPU drain s | verify |
|---|---|---|---|---|---|---|---|
| 1 | golden hour A-4 | 141.2 | 0.172 | 0.0001 | 0.970 | 0.75 | FAIL (old store_sta2 bbox) |
| 2 | super-bright preset | 116.0 | 0.205 | 0 | 0.999 | 0.74 | FAIL (old store_sta2 bbox) |
| 6 | A320 SFO rain | 196.1 | 0.130 | 0 | 0.660 | 3.06 | pass |
| 7 | tower heavy rain | 226.5 | 0.220 | 0 | 0.839 | 3.59 | pass |
| 10 | C172 near tornado | 141.8 | 0.054 | 0.0054 | n/a | 1.73 | pass |
| 13 | 747 ocean cruise | 90.9 | 0.101 | 0 | 0.963 | 0.93 | pass |
| 15 | 747 hurricane | 186.4 | 0.058 | 0 | n/a | 1.21 | pass |

- Both verify failures are the known payload-box failure in scenes 1 and 2; it is old, not a regression.
- Compared with round 146, scene 6 got brighter (0.068 to 0.130) and so did scene 7 (0.121 to 0.220).

## Round 1471: scene 13 with -cloud-march=probe (pushed e059326a)
- It rendered in 96.1 s (wall 106 s) with no hang or TDR. Max drain was 1.08 s, against 0.93 s at default.
- Luma was 0.0997 and SSIM against round 147 #13 was 0.9986, so the frame is almost the same as the default.
- The render log shows no cloud-related line that differs from the default run (4af29b286dc4).
- The only sign of the switch is the command line, so check that probe actually took effect on this GPU class.

## Run ids
- Round 147: #1 cd5fca09373b, #2 64e8a33e6349, #6 565a4ef05ddd, #7 96ea02fb8e0d, #10 c43e25f26a1c, #13 4af29b286dc4, #15 f56f4feb7403
- Round 1471: a0d4fa54c6be
