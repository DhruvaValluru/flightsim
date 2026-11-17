# r150 / 1501 / 1502 on da0bf843, and the superseded r151 on 7917055d (p3-windows, 2026-11-16)

There were no TDRs. Every still rendered.
The first attempt at 150 (run 7980c7b38414) failed on a Google-tiles ConnectionError: the view was still 0 % loaded after 180 s. That was a network problem, not the GPU, so I reran it once and it rendered.

## r150: `-cloud-material=engine` on da0bf843 (pushed 140834d9, 57c36f1e, a1e14770)

| Round | Scene | Switches | Seconds | Mean luma | SSIM | Max GPU drain s | layer 0 cloud_material | cloud_material_drawn |
|---|---|---|---|---|---|---|---|---|
| 150 | #13 | -cloud-material=engine | 61.8 | 0.092 | 0.905 vs 148 | 0.38 | engine | /Engine/EngineSky/VolumetricClouds/m_SimpleVolumetricCloud_Inst |
| 1501 | #3 | -cloud-material=engine | 122.0 | 0.143 | 0.730 vs 1465 | 1.10 | engine | m_SimpleVolumetricCloud_Inst |
| 1502 | #13 | -cloud-material=engine -distant-clouds=off | 82.1 | 0.074 | 0.759 vs 149 | 0.43 | engine | m_SimpleVolumetricCloud_Inst |

- Each scene has 1 layer, cumulus (cloud_type_source plan).
- `cloud_light_material` stays /Game/FlightSim/M_FlightSimCloudLayers.
- hdri_sky.switch shows off in all of these runs.
- The stock cloud is cheaper on the GPU: the #13 drain is 0.38 s, against 0.60 s in r148 with our material.

## Superseded r151 on 7917055d: scenes 3, 12, 13 at default flags (pushed 01d2bc15)
This round was replaced by r151 on 2afd3525, which will overwrite docs/visual/round_151. Its cloud json is kept here, in `render_151_7917055d/`.

Prep: rebuilt, then materials. The materials step had 8 HDRI-EXISTS, 4 MATERIAL-CREATED and 0 failures.

| Scene | Seconds | Mean luma | Max GPU drain s | cloud_material | drawn |
|---|---|---|---|---|---|
| #3 | 96.5 | 0.143 | 0.57 | auto | m_SimpleVolumetricCloud_Inst |
| #12 | 146.7 | 0.094 | 1.13 | auto | m_SimpleVolumetricCloud_Inst |
| #13 | 81.9 | 0.092 | 0.42 | auto | m_SimpleVolumetricCloud_Inst |

At 7917055d, auto drew the stock cloud on all three scenes. Scenes #3 and #13 match their `engine` runs (luma 0.1433 and 0.09197).

Full layer and march json per run: `render/<run>_clouds.json` and `render_151_7917055d/`.
