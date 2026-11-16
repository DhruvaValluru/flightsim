// M_AircraftGlassReflect / M_AircraftGlassReflectFine: the canopy's mirror
// image of the baked sky/sea strip, added to Emissive Color (the opaque
// glass master's graph otherwise unchanged). Rs is the two-face slab
// reflectance the LUT stores as sqrt in R. Gain 0 (the master's default)
// adds exactly nothing; the host sets it only under -canopy-reflect=on
// (FlightSimAircraftFX.cpp; twin aircraft_glass_reflect.canopy_reflect_gain).
// Twin: aircraft_glass_reflect.reflect_emissive.
// The LUT's slab reflectance is the exact Fresnel of two faces at n 1.49
// (glass_coastal.json glass.ior; Physically Based "Plastic (Acrylic)" 1.4905):
// 0.04 face-on per face, 1 at grazing, the mirror-like rim of a real canopy.
// Generation 16: the strip radiance is replaced per pixel by the scene's own
// sky above and ground below (Scene) when the host sets GlassEnvSceneScale.
//
// Inputs:
//   Lut      float3  T_GlassFresnel_LUT sample (linear): R = sqrt(slab reflectance)
//   Env      float3  T_GlassEnv_<W> sample (the sRGB sampler decodes it)
//   EnvScale float   linear radiance = decoded strip x EnvScale (glass_coastal.json env_encode_scale)
//   Gain     float   scene luminance (nits) per unit of strip radiance
//   Tint     float3  the scene's horizon hue over the strip's (white = as baked)
//   Scene    float4  generation 16 (scene_sky_env.hlsl): rgb the scene's own sky / ground
//                    radiance along the ray, a 1 to draw it instead of the strip (0 = generation 13)
// Returns float3: the emissive radiance added to the pane.
float rs = Lut.r * Lut.r;
float3 env = max(Env * EnvScale * max(Gain, 0.0) * max(Tint, 0.0), 0.0);
env = lerp(env, max(Scene.rgb, 0.0), saturate(Scene.a));
return env * rs;
