// M_AircraftContrail: a condensation trail's opacity along its ribbon
// (FlightSimAircraftFX.cpp: UV.x is the sample's age / the trail's lifetime,
// UV.y runs 0..1 across the ribbon). Lit translucent, BEAUTY ONLY. Like the
// clouds and the rain (which the label captures never draw), a trail is a
// medium, not an occluder: where a trail crosses in front of the aircraft the
// mask still says aircraft. render.json aircraft_look.contrail records this.
//
// Inputs:
//   UV        float2  x age fraction 0..1, y across 0..1
//   LocalPos  float3  local position, cm (noise)
//   Opacity   float   peak opacity
//   Formation float   age fraction before which the trail has not formed yet
// Returns float opacity.
float formed = smoothstep(Formation, Formation + 0.04, UV.x);
float fade = 1.0 - smoothstep(0.35, 1.0, UV.x);
float across = 1.0 - abs(UV.y * 2.0 - 1.0);
across = across * across * (3.0 - 2.0 * across);
float3 cell = floor(LocalPos / 180.0);
float lumpy = 0.75 + 0.25 * frac(sin(dot(cell, float3(12.9898, 78.233, 37.719))) * 43758.5453);
return saturate(Opacity * formed * fade * across * lumpy);
