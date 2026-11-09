// M_AircraftAfterburner: the reheat plume's emission along its cone
// (FlightSimAircraftFX.cpp: UV.x 0 at the nozzle, 1 at the plume tip; UV.y
// around the cone). Additive, unlit, BEAUTY ONLY: it adds light behind the
// nozzle and hides nothing, so the label passes are unaffected; the plume is
// recorded in render.json aircraft_look.afterburner.
//
// Inputs:
//   UV         float2  x along the plume 0..1, y around it
//   Intensity  float   0..1 reheat glow (from thrust, set by the C++ per frame)
//   CoreColour float3  linear colour at the nozzle
//   TipColour  float3  linear colour at the tip
//   Shocks     float   the number of shock diamonds along the plume
// Returns float3 emissive.
float along = saturate(UV.x);
float body = (1.0 - along) * (1.0 - along);
float diamonds = 0.7 + 0.3 * pow(abs(cos(along * Shocks * 3.14159265)), 6.0);
float3 colour = lerp(CoreColour, TipColour, along);
return colour * (Intensity * body * diamonds);
