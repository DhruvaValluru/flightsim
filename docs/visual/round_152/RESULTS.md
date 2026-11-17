# r152 on a7d84e6a: #13, one still, default flags (p3-windows, 2026-11-16)

Prep was a rebuild only. The still was pushed as 895cc9e1.

| # | seconds | mean luma | crushed | SSIM vs r151 #13 | flicker | max GPU drain s | TDR |
|---|---|---|---|---|---|---|---|
| 13 | 45.9 | 0.07406 | 0.00001 | **1.000** | 0.000 | 0.36 | none |

## Result: no change from r151
The frame is pixel-identical to r151 #13 on 2afd3525.

## Probable reason, from render.json
- The cut is applied: `sun_shafts.cloud_shadow_on_atmosphere_from_above = 0.15`.
- But in this scene the sun casts no cloud shadow:
  - `sun_shafts.sun.cast_cloud_shadows = false`
  - `atmosphere.sun_cast_cloud_shadows = false`
  - `clouds.deck_shadow.sun_cast_cloud_shadows = false`, with fair_switch off and preset clear.
- render.json itself notes that the sun casts no cloud shadow in this scene, so the cloud-shadow strengths are recorded but have no effect.
- So the atmosphere cloud-shadow strength cannot be what draws #13's streaks.
- Layer 0's cloud_material_auto is still m_SimpleVolumetricCloud_Inst.

Run id: a7cb5275ab59

## Looking at the frame: what the #13 streaks look like
This section is a hypothesis for p3-mac. It is unmeasured; no A/B has been rendered.
- The streaks are BRIGHT bands. Each one starts at a cloud and runs to the bottom edge of the frame.
- They fan out RADIALLY: streaks on the left lean down and left, streaks on the right lean down and right. They converge on a point above the top centre of the frame.
- The sun is at 89.9 deg elevation, almost straight up and off-screen above the camera.
- Radial bands from occluders, pointing away from the sun's screen position, are what UE's screen-space light shafts look like. render.json shows them on:
  - `sun_shafts.sun.light_shaft_occlusion = true`, with occlusion_mask_darkness 0.4 and occlusion_depth_range_m 20000
  - `light_shaft_bloom = true`, with bloom_scale 0.2 and threshold 8
  - `hero_lighting.sun.light_shaft_bloom = true`
  - `show_flags.light_shafts = true`
  - `r.LightShaftQuality 1`
- The same streaks are there, fainter, with OUR cloud material: see round_149/13 (b3174986, distant clouds off). So they come from neither the stock cloud nor the atmosphere cloud-shadow strength, which matches r152 being identical to r151.
- I found no switch at a7d84e6a that turns the light shafts off; there is only `-sun-shafts-tier=still|interactive`. So the A/B to run is #13 with light-shaft occlusion and bloom off. That needs a switch from the Mac.
