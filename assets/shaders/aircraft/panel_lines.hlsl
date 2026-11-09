// M_AircraftPaint / M_AircraftBareMetal: procedural panel lines (aircraft lane,
// visual overhaul V7). Three sets of planes slice the airframe at a regular
// pitch along its OWN axes (frames along x, ribs along y, stringers along z);
// where a plane meets the skin a groove of WidthCm is cut, and the normal leans
// into it. A plane set whose axis is (nearly) along the surface normal lies IN
// the surface (the z planes on a wing top) and draws nothing. Filtered by the
// screen footprint (fwidth) so a groove narrower than a pixel fades out
// instead of aliasing. Python twin: scripts/ue_aircraft_master_materials.py
// panel_groove (tests/test_aircraft_look.py pins the two to each other).
//
// Pixels only: nothing here moves geometry (no world position offset), so the
// label passes, which draw the same mesh, see the same silhouette.
//
// Inputs:
//   LocalPos  float3  the pixel's local (object) position, cm
//   NormalWS  float3  the vertex normal, world
//   AxisX     float3  the object's local x axis in world space
//   AxisY     float3  the object's local y axis in world space
//   AxisZ     float3  the object's local z axis in world space
//   Pitch     float3  the plane spacing along x, y, z, cm
//   WidthCm   float   the groove width, cm
//   Depth     float   how far the normal leans into a groove (0 = flat)
// Returns float4: xyz the world-space normal, w the groove mask (0..1).
float3 n = normalize(NormalWS);
float3 axes[3] = { AxisX, AxisY, AxisZ };
float coords[3] = { LocalPos.x, LocalPos.y, LocalPos.z };
float pitches[3] = { Pitch.x, Pitch.y, Pitch.z };
float grooveMask = 0.0;
float3 bend = float3(0.0, 0.0, 0.0);
for (int i = 0; i < 3; ++i)
{
    float p = max(pitches[i], 1.0);
    float d = (frac(coords[i] / p + 0.5) - 0.5) * p;
    float w = max(WidthCm, 0.01);
    float fw = max(fwidth(coords[i]), 1.0e-4);
    float halfWidth = 0.5 * w + fw;
    float g = saturate(1.0 - abs(d) / halfWidth);
    g *= saturate(1.0 - fw / (2.0 * w));
    float3 a = normalize(axes[i]);
    float3 t = a - dot(a, n) * n;
    float tl = length(t);
    g *= saturate((tl - 0.6) * 5.0);
    grooveMask = max(grooveMask, g);
    float side = d >= 0.0 ? 1.0 : -1.0;
    bend -= side * g * (tl > 1.0e-4 ? t / tl : float3(0.0, 0.0, 0.0));
}
return float4(normalize(n + Depth * bend), grooveMask);
