// M_AircraftPaint / M_AircraftBareMetal / M_AircraftGlassReflect(Fine),
// LOOK_GENERATION 14 (scripts/aircraft_scene_sky.py): the reflected ray back
// from the strip uv the lookup node already returned (paint_env_uv.hlsl /
// glass_reflect_uv.hlsl zw: u = 0.5 faces the sun, v = 0 the zenith), so the
// scene's Sky View LUT is read along the SAME leaned / micro-scratched ray the
// strip is. Those nodes write azim = atan2(r x s, r . s) = minus the angle from
// the sun's azimuth to r, so r.xy is the sun's azimuth rotated by -azim. The
// strip's v clamp (1/128) bends only the last 1.4 deg at the zenith and nadir.
// Twin: aircraft_scene_sky.sky_dir.
//
// Inputs:
//   EnvUv   float2  the strip uv (paint_env_uv / glass_reflect_uv zw)
//   SunDir  float3  toward the sun, world (only xy is read; the uv node's own)
// Returns float3: the reflected ray, world, unit length.
float2 sd = SunDir.xy;
float sl = length(sd);
sd = sl > 1.0e-4 ? sd / sl : float2(1.0, 0.0);
float azim = (EnvUv.x - 0.5) * 6.2831853;
float elev = (0.5 - EnvUv.y) * 3.14159265;
float ca = cos(azim);
float sa = sin(azim);
float2 h = float2(sd.x * ca + sd.y * sa, -sd.x * sa + sd.y * ca);
float ce = cos(elev);
return float3(h * ce, sin(elev));
