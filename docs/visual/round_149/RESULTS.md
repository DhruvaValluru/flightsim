# r149 / 1491 / 1492 on b3174986, no rebuild (p3-windows, 2026-11-16)

There were no TDRs in this round. All three stills rendered.

| Round | Scene | Switches | Seconds | Mean luma | SSIM | Max GPU drain s | First warm-up drain s |
|---|---|---|---|---|---|---|---|
| 149 | #13 | -distant-clouds=off -look-hdri=off | 81.3 | 0.108 | 0.765 vs 148 | 0.84 | 0.84 |
| 1491 | #13 | -distant-clouds=off -cloud-march=probe -look-hdri=off | 221.5 | 0.103 | 0.993 vs 149 | 3.22 | 2.86 |
| 1492 | #9 | -look-hdri=off | 301.9 | 0.091 | 0.992 vs 1466 | 4.07 | 4.07 |

Pushed: 149 487fad63, 1491 e5b0537f, 1492 f42776b5. Verify was not requested for this round.

## clouds.march and distant_clouds.volumetric_trace
The full `clouds.march`, `distant_clouds` and `hdri_sky` sections from each render.json are in `render/<round>_<run>_clouds.json`.

| Round | march tier | view / shadow samples | trace km | distant_clouds.mode | volumetric_trace | hdri_sky.switch |
|---|---|---|---|---|---|---|
| 149 | integrated | 192 / 10 | 80 | off (drawn nothing) | absent (null) | off |
| 1491 | probe | 288 / 20 | 80 | off | absent (null) | off |
| 1492 #9 | integrated | 192 / 10 | 80 | on | tracing_max_distance_km 32 (row 80), shrunk true, fade 24 + 8 km, constrained_gpu true | off |

- With distant clouds off, `volumetric_trace` is not written, and the march keeps its full 80 km row.
- So in 149 and 1491 the volumetric deck is traced to 80 km rather than 32 km.

## Readings
- **#13, distant clouds off:** the frame changes a lot against r148 (SSIM 0.765), while luma barely moves (0.100 to 0.108).
- **#13, probe on top:** it is almost identical to 149 (SSIM 0.993) but costs 2.7x the time (221.5 s against 81.3 s). Drains reach 3.22 s on #13 at probe, against 0.84 s at the integrated tier. So probe costs much more but barely changes the image, even with the full 80 km trace.
- **#9, HDRI off:** it rendered clean at b3174986. The same commit with the HDRI on hung on the first warm-up capture in r148. So the HDRI path is the likely cause of r148's #9 TDR, though that rests on one run each way.
  - Caution: #9's first drain is now 4.07 s, against 3.3-3.5 s on 9ef62483 / da82dc78. Even with the HDRI off, b3174986 makes #9 heavier per capture than before, which leaves less margin below the hang point.
  - The frame matches 1466 (SSIM 0.992, luma 0.091 against 0.091).

## Run ids
149 6f88363cc990, 1491 2478a7e0f805, 1492 437ce0354e24
