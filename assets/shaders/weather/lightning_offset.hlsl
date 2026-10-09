// M_LightningChannel's world position offset: the channel drawn as a camera-facing
// ribbon whose half-width is the channel's luminous radius, floored at three quarters
// of a pixel so a channel kilometres away is still one pixel wide
// (core/scene/lightning.py: the line source's energy is conserved by the emissive).
//
// Inputs:
//   Side       float   UV0.x: -1 | +1
//   Dir        float3  the vertex normal: the channel's direction here (unit, engine)
//   Rel        float3  the vertex's engine position minus the camera's, cm
//   PixelAngle float   the angle of one pixel, rad
//   RadiusCm   float   the channel's luminous radius, cm
float dist = max(length(Rel), 100.0);
float3 side = cross(Dir, Rel / dist);
side = dot(side, side) > 1.0e-8 ? normalize(side) : normalize(cross(Dir, float3(0.0, 0.0, 1.0) + float3(1.0e-3, 0.0, 0.0)));
float halfWidth = max(RadiusCm, dist * PixelAngle * 0.75);
return side * Side * halfWidth;
