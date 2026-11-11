// M_TornadoFunnel's opacity mask (visual push lane C; generation 4, 2026-11-11).
// The funnel's and the wall cloud's CORE stay BLEND_MASKED so they keep writing depth
// (the label depth captures see exactly the beauty's silhouette). Round 7 rendered
// generation 3's per-pixel dither as a stipple, not a soft edge, so the core's edge is
// now a plain clip -- ragged, not dithered -- and the softness is the funnel's sheath,
// a translucent second section (M_TornadoFunnelSoft, tornado_funnel_soft.hlsl) that
// writes no depth.
//
// Alpha = Coverage x smoothstep(|N.V| / EdgeSoft) + NoiseAmp x (Noise - 0.5), where
// Coverage is the mesh's UV0.x (FlightSimTornadoBeauty.cpp: 1 solid, 0 gone: the
// funnel's thin foot, the wall cloud's dissolving rim). The material clips at 0.5: the
// noise moves the silhouette in and out, so the edge is torn, not a lathe's.
//
// Inputs:
//   Coverage float   UV0.x
//   Normal   float3  the vertex normal, world space
//   CamVec   float3  the camera vector (pixel to camera, world space)
//   Noise    float   0..1, the erosion noise over the mesh's local position
//   EdgeSoft float   |N.V| at which the silhouette's fade ends
//   NoiseAmp float   how far the noise moves the edge
float nl = length(Normal);
float cl = length(CamVec);
float facing = (nl > 1.0e-6 && cl > 1.0e-6) ? abs(dot(Normal / nl, CamVec / cl)) : 1.0;
float edge = saturate(facing / max(EdgeSoft, 1.0e-3));
edge = edge * edge * (3.0 - 2.0 * edge);
return saturate(Coverage * edge + NoiseAmp * (Noise - 0.5));
