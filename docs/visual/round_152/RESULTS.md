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
