// M_TornadoFunnel's dithered opacity mask (visual push lane C, 2026-11-11; generation 3).
// Round 5 drew the funnel and the wall cloud as hard opaque shells. A condensation
// funnel and a wall cloud are clouds: their edges are soft and ragged, thinning where
// the line of sight grazes them. The material stays BLEND_MASKED so it keeps writing
// depth (the label depth captures see the beauty's silhouette); the soft edge is a
// per-pixel dither of the opacity, which the beauty's TSR resolves into a soft fringe.
//
// Alpha = Coverage x smoothstep(|N.V| / EdgeSoft) + NoiseAmp x (Noise - 0.5), where
// Coverage is the mesh's own UV0.x (FlightSimTornadoBeauty.cpp: 1 solid, 0 gone: the
// funnel's thin foot, its sheath, the wall cloud's dissolving rim). The return value
// is compared with the material's clip value 0.5: the pixel is kept where Alpha is
// above an interleaved-gradient dither (Jimenez 2014) that turns with the frame index.
// On the scenario world's own markers (measure: the default material) none of this runs.
//
// Inputs:
//   Coverage float   UV0.x
//   Normal   float3  the vertex normal, world space
//   CamVec   float3  the camera vector (pixel to camera, world space)
//   Noise    float   0..1, the erosion noise over the mesh's local position
//   Pixel    float2  the pixel position (ScreenPosition.PixelPosition)
//   EdgeSoft float   |N.V| at which the silhouette's fade ends
//   NoiseAmp float   how far the noise moves the edge
float nl = length(Normal);
float cl = length(CamVec);
float facing = (nl > 1.0e-6 && cl > 1.0e-6) ? abs(dot(Normal / nl, CamVec / cl)) : 1.0;
float edge = saturate(facing / max(EdgeSoft, 1.0e-3));
edge = edge * edge * (3.0 - 2.0 * edge);
float alpha = saturate(Coverage * edge + NoiseAmp * (Noise - 0.5));
float frame = (float)View.StateFrameIndexMod8;
float2 p = Pixel + frame * float2(5.588238, 3.137);
float dither = frac(52.9829189 * frac(dot(p, float2(0.06711056, 0.00583715))));
return alpha + 0.4999 - dither;
