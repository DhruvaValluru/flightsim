// M_TornadoFunnelSoft's opacity (visual push lane C, 2026-11-11). The funnel's sheath
// (FlightSimTornadoBeauty.cpp section 1: a shell around the masked core, its coverage
// UV0.x) is translucent: the condensation's soft, torn edge. Thickest where the line
// of sight crosses the sheath face-on, gone where it grazes it (the silhouette), and
// broken by two noises: the vertical striations (Streaks) and the erosion (Noise).
// No depth: the label captures never see it; the core underneath carries the depth.
//
// Inputs:
//   Coverage float   UV0.x (the sheath's share of the core's coverage)
//   Normal   float3  the vertex normal, world space
//   CamVec   float3  the camera vector (pixel to camera, world space)
//   Noise    float   0..1, the erosion noise over the local position
//   Streaks  float   0..1, the stretched striation noise
//   Opacity  float   the sheath's peak opacity
//   EdgeSoft float   |N.V| at which the silhouette's fade ends
float nl = length(Normal);
float cl = length(CamVec);
float facing = (nl > 1.0e-6 && cl > 1.0e-6) ? abs(dot(Normal / nl, CamVec / cl)) : 1.0;
float edge = saturate(facing / max(EdgeSoft, 1.0e-3));
edge = edge * edge * (3.0 - 2.0 * edge);
float torn = saturate(1.6 * Noise - 0.35);
return saturate(Opacity * Coverage * edge * torn * lerp(0.55, 1.0, Streaks));
