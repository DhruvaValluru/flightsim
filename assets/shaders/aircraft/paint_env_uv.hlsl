// M_AircraftPaint / M_AircraftBareMetal: where the airframe's mirror image of
// the baked sky/sea strip is looked up (scripts/aircraft_paint_reflect.py).
// OPAQUE masters, beauty only: no translucency, no SSR, nothing that moves a
// pixel. Returns N.V and the baked lat-long strip's uv (u = 0.5 faces the
// sun, v = 0 the zenith), the same strip and the same convention as the
// canopy's glass_reflect_uv.hlsl. The lookup normal is leaned by the wet
// layer's rivulet bulge (aircraft_wet.hlsl WetLean, object frame) scaled by
// LeanStrength: a streak then mirrors a different part of the sky than the
// paint around it, which is what a rain streak on a fuselage looks like. The
// material's own Normal output is untouched (the normal label pass reads the
// same surface with the reflection on or off).
// Twin: aircraft_paint_reflect.env_uv.
//
// Inputs:
//   NormalWS     float3  vertex normal, world
//   CameraVec    float3  surface -> camera, world (CameraVectorWS)
//   SunDir       float3  toward the sun, world (only xy is read)
//   Lean         float3  the wet layer's WetLean: rivulet lean, object frame (0 = flat)
//   LeanStrength float   how far the lean tilts the lookup normal, 0..1
//   AxisX        float3  the object's local X axis in world space
//   AxisY        float3  the object's local Y axis in world space
//   AxisZ        float3  the object's local Z axis in world space
// Returns float4: x N.V (0..1), y 0, zw the env strip uv.
float3 n = normalize(NormalWS);
float3 ax = normalize(AxisX);
float3 ay = normalize(AxisY);
float3 az = normalize(AxisZ);
float3 leanWS = Lean.x * ax + Lean.y * ay + Lean.z * az;
n = normalize(n + saturate(LeanStrength) * leanWS);
float3 v = normalize(CameraVec);
float ndv = saturate(dot(n, v));
float3 r = reflect(-v, n);
float2 sd = SunDir.xy;
float sl = length(sd);
sd = sl > 1.0e-4 ? sd / sl : float2(1.0, 0.0);
float azim = atan2(r.x * sd.y - r.y * sd.x, r.x * sd.x + r.y * sd.y);
float2 envUv = float2(azim / 6.2831853 + 0.5, 0.5 - asin(clamp(r.z, -1.0, 1.0)) / 3.14159265);
envUv.y = clamp(envUv.y, 0.0078125, 0.9921875);
return float4(ndv, 0.0, envUv.x, envUv.y);
