// M_WindshieldRainBaked (-windscreen-baked=on; tier 0 of swarm lane
// weather_fx.windscreen_water.storm, its windshield_baked.hlsl verbatim below this
// paragraph). VISUAL-ONLY, BEAUTY-ONLY: a post-process blendable on a cockpit
// camera's beauty capture (FlightSimWeatherBaked.cpp ApplyWindscreenBaked).
// UNCOMPILED here; SM5: straight-line code, no loop, no array, no SM6 intrinsic.
// Lens is LensH x Aspect in the graph (LensH = TAN_MAX / (2 tan(hfov / 2)), set
// per frame by the host): TAN_MAX / (2 tan(vfov / 2)) without a vertical fov.
//
// The lane's header:
// the Custom node body that replaces windshield.hlsl's hashed loop on an
// integrated GPU. No loop, no hash, no branch: the two texels the material
// sampled carry the optics (generate.py baked them; shade_texels there is this
// file's Python twin and the test pins the constants).
//
// Inputs (the Custom node's, named exactly so):
//   Drop    float4  T_WSDrops at float2(UV.x * Aspect, UV.y) * Tiles
//   Riv     float4  T_WSRivulets at the same UV
//   RivV    float   UV.y * Tiles (the track coordinate, tiles)
//   Aspect  float   view width / height
//   Time    float   run time, s
//   Wet     float4  drop density, rivulet density, head rate (tiles/s), trail (tiles)
//   Lens    float   TAN_MAX / (2 tan(vfov / 2)): 0.763326 at 60 degrees
// Returns (du, dv, mask, shade). The material draws
//   lerp(Scene(UV), Scene(saturate(UV + (du, dv))) * shade, mask).
// EDGE_GAIN = 16.0
float dropOn = saturate((Drop.a - (1.0 - Wet.x)) * 16.0);
float rivOn = saturate((Riv.a - (1.0 - Wet.y)) * 16.0);
float s = frac(RivV + Riv.b + Time * Wet.z);
rivOn *= saturate(1.0 - s / max(Wet.w, 1.0e-3));
float2 dDrop = (Drop.rg * 2.0 - 1.0) * Lens;
float dRivX = (Riv.r * 2.0 - 1.0) * Lens * rivOn;
float du = lerp(dRivX, dDrop.x, dropOn);
float dv = dDrop.y * dropOn;
float shade = lerp(lerp(1.0, Riv.g, rivOn), Drop.b, dropOn);
return float4(du / Aspect, dv, max(dropOn, rivOn), shade);
