// M_NavLightEmissive: the glow of a navigation / strobe / landing lamp on its
// billboard cross (FlightSimAircraftFX.cpp builds three crossed quads per lamp,
// UV 0..1 across each). Additive, unlit, BEAUTY ONLY: the lamp actor is in
// BeautyOnlyActors, and an additive surface adds light without hiding what is
// behind it, so the label passes (which never draw it) still describe every
// pixel the aircraft covers.
//
// Inputs:
//   UV          float2  the quad's texture coordinate
//   LightColour float3  linear colour
//   Intensity   float   emissive scale (the lamp's candela x LightVisualGain, set by the C++)
//   Strobe      float   0..1, the flash state on the FDM's time (1 for a steady lamp)
// Returns float3 emissive.
float2 c = UV * 2.0 - 1.0;
float r2 = dot(c, c);
float core = exp(-r2 * 18.0);
float halo = exp(-r2 * 3.0) * 0.15;
return LightColour * Intensity * Strobe * (core + halo);
