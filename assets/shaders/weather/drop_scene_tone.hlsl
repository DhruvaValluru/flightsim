// M_RainDrops's scene-lit term (hyperreal rain, 2026-11-14; M_RainDrops 7). Garg & Nayar:
// a drop's radiance is close to the MEAN radiance of its surroundings -- it is a lens, not a
// white surface. drop_lit draws it as a lit white surface, and under a storm deck the
// translucency lighting volume still carries the sun (the cloud casts no shadow), so every
// streak drew as a bright white line over a dark scene: the round-4 "scratches". The beauty
// takes SceneLit of the drop's radiance from the scene behind the pixel (one SceneColor tap
// at offset 0, as M_RainCurtain's veil_tone.hlsl does: no spatial copy of anything) as
// emissive, and the lit term keeps 1 - SceneLit (the sky's share: a drop over a dark
// aircraft still reads a little brighter than it). SceneLit 0: nothing added, the measure
// path's drop. UNCALIBRATED.
//
// Inputs (the Custom node's, named exactly so):
//   A        float3  the scene colour at this pixel (SceneColor, offset fraction 0)
//   SceneLit float   the share of the drop's radiance taken from the scene behind it
float lum = dot(A, float3(0.2126, 0.7152, 0.0722));
return float3(lum, lum, lum) * SceneLit;
