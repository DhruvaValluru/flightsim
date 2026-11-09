// M_AircraftHeatHaze: the shimmer behind a hot nozzle, as a 2D screen offset
// (refraction method "2D Offset"). PIXEL-MOVING: it shifts what is seen
// through the cone, so it is OFF unless the render asks (-heat-haze=on, beauty
// only) and render.json aircraft_look.heat_haze says it was drawn. The label
// passes never draw it (beauty-only actor, and they draw no translucency), so
// mask edges behind a nozzle may sit up to Strength * 0.01 of the screen off
// the beauty pixels there: the record states the bound.
//
// Inputs:
//   UV        float2  x along the cone 0..1 (0 at the nozzle), y around it
//   LocalPos  float3  local position, cm
//   TimeS     float   the FDM's time, s (set by the C++: replay-identical)
//   Strength  float   peak offset, in 1/100 of the screen
// Returns float2 the screen offset.
float fade = (1.0 - saturate(UV.x)) * saturate(UV.x * 8.0);
float3 p = LocalPos / 25.0 + float3(TimeS * 6.0, 0.0, TimeS * 1.5);
float a = sin(p.x * 1.7 + sin(p.y * 2.3)) * cos(p.z * 1.9 + p.x * 0.4);
float b = cos(p.y * 1.3 + sin(p.z * 2.9)) * sin(p.x * 2.1 - p.z * 0.6);
return float2(a, b) * (Strength * 0.01 * fade);
