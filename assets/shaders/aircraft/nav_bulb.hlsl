// M_NavLightEmissive: the glow of a navigation / strobe / landing lamp on its
// billboard cross (FlightSimAircraftFX.cpp builds three crossed quads per lamp,
// UV 0..1 across each). Additive, unlit, BEAUTY ONLY: the lamp actor is in
// BeautyOnlyActors, and an additive surface adds light without hiding what is
// behind it, so the label passes (which never draw it) still describe every
// pixel the aircraft covers.
//
// Physical units: Intensity is the core's luminance in cd/m2, derived from the
// lamp's own candela (scripts/aircraft_look.py bulb_luminance_nits: candela x
// LightVisualGain over this falloff's integral over one quad, 0.3271 x the
// half-size squared), so one quad seen face-on emits the candela the lamp's
// light component throws and the frame's exposure meters both together. A
// landing lamp is a beam: seen from outside its cone (BeamCos, the spot
// light's own inner / outer half-angles) the bulb fades out as its light does.
//
// Inputs:
//   UV          float2  the quad's texture coordinate
//   LightColour float3  linear colour
//   Intensity   float   core luminance, cd/m2 (set by the C++ from the look manifest)
//   Strobe      float   0..1, the flash state on the FDM's time (1 for a steady lamp)
//   CameraDir   float3  unit vector from the pixel to the camera, world (CameraVectorWS)
//   BeamDir     float3  the lamp's beam axis, world (any unit vector for an omnidirectional lamp)
//   BeamCos     float2  cos(inner), cos(outer) half-angle; outer <= -1 for an omnidirectional lamp
// Returns float3 emissive.
float2 c = UV * 2.0 - 1.0;
float r2 = dot(c, c);
float core = exp(-r2 * 18.0);
float halo = exp(-r2 * 3.0) * 0.15;
float beam = BeamCos.y <= -1.0 ? 1.0
    : saturate((dot(CameraDir, BeamDir) - BeamCos.y) / max(BeamCos.x - BeamCos.y, 1e-4));
return LightColour * Intensity * Strobe * beam * (core + halo);
