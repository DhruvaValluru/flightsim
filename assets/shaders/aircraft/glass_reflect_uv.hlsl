// M_AircraftGlassReflect / M_AircraftGlassReflectFine: where the canopy's
// mirror image is looked up (scripts/aircraft_glass_reflect.py, tiers 0-1 of
// swarm lane aircraft_exterior.glass.coastal). OPAQUE masters, beauty only
// (-canopy-reflect=on): no translucency, no SSR, nothing that moves a pixel.
// Returns the Fresnel LUT's coordinate (u = N.V) and the baked sky/sea
// lat-long strip's (u = 0.5 faces the sun, v = 0 the zenith). Tier 1 leans
// the lookup normal by the tiled micro-scratch normal (MicroStrength > 0);
// tier 0 wires MicroN (0.5, 0.5, 1) and MicroStrength 0 (no tap). The
// material's own Normal output is untouched (the normal and base-colour
// label passes read the same surface with the switch on or off).
// Twin: aircraft_glass_reflect.reflect_uv.
//
// Inputs:
//   NormalWS      float3  vertex normal, world
//   CameraVec     float3  surface -> camera, world (CameraVectorWS)
//   SunDir        float3  toward the sun, world (only xy is read)
//   MicroN        float3  tier-1 micro normal sample, 0..1 (xy = 0.5 is flat)
//   MicroStrength float   how far the micro normal leans the lookup, 0..1
//   AxisX         float3  the object's local X axis in world space
//   AxisY         float3  the object's local Y axis in world space
//   AxisZ         float3  the object's local Z axis in world space
// Returns float4: xy the LUT uv, zw the env strip uv.
float3 n = normalize(NormalWS);
float3 ax = normalize(AxisX);
float3 ay = normalize(AxisY);
float3 az = normalize(AxisZ);
float3 ln = abs(float3(dot(n, ax), dot(n, ay), dot(n, az)));
float3 t = ax;
float3 b = ay;
if (ln.x >= ln.y && ln.x >= ln.z)
{
    t = ay;
    b = az;
}
else if (ln.y >= ln.z)
{
    b = az;
}
float2 m = MicroN.xy * 2.0 - 1.0;
n = normalize(n + saturate(MicroStrength) * (m.x * t + m.y * b));
float3 v = normalize(CameraVec);
float ndv = saturate(dot(n, v));
float3 r = reflect(-v, n);
float2 sd = SunDir.xy;
float sl = length(sd);
sd = sl > 1.0e-4 ? sd / sl : float2(1.0, 0.0);
float azim = atan2(r.x * sd.y - r.y * sd.x, r.x * sd.x + r.y * sd.y);
float2 envUv = float2(azim / 6.2831853 + 0.5, 0.5 - asin(clamp(r.z, -1.0, 1.0)) / 3.14159265);
envUv.y = clamp(envUv.y, 0.0078125, 0.9921875);
float lutU = clamp(ndv, 0.0078125, 0.9921875);
return float4(lutU, 0.5, envUv.x, envUv.y);
