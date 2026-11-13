// M_AircraftGlassReflect / M_AircraftGlassReflectFine: the canopy's mirror
// image of the baked sky/sea strip, added to Emissive Color (the opaque
// glass master's graph otherwise unchanged). Rs is the two-face slab
// reflectance the LUT stores as sqrt in R. Gain 0 (the master's default)
// adds exactly nothing; the host sets it only under -canopy-reflect=on
// (FlightSimAircraftFX.cpp; twin aircraft_glass_reflect.canopy_reflect_gain).
// Twin: aircraft_glass_reflect.reflect_emissive.
//
// Inputs:
//   Lut      float3  T_GlassFresnel_LUT sample (linear): R = sqrt(slab reflectance)
//   Env      float3  T_GlassEnv_<W> sample (the sRGB sampler decodes it)
//   EnvScale float   linear radiance = decoded strip x EnvScale (glass_coastal.json env_encode_scale)
//   Gain     float   scene luminance (nits) per unit of strip radiance
//   Tint     float3  the scene's horizon hue over the strip's (white = as baked)
// Returns float3: the emissive radiance added to the pane.
float rs = Lut.r * Lut.r;
return max(Env * EnvScale * rs * max(Gain, 0.0) * max(Tint, 0.0), 0.0);
