// M_FlightSimScatter's base colour: the Custom node body scripts/ue_create_materials.py
// (world lane block) pastes into the ground scatter's master material. Visual overhaul,
// world lane fix pass, 2026-11-09. BEAUTY ONLY: only FFlightSimGroundDetail (under
// FFlightSimWorldBeauty, -quality=beauty) draws the scatter.
//
// The scatter stands on the Google tiles, so it takes the SAME ground state as the
// tiles under it, from the same MPC_FlightSimWorld scalars and the same laws as
// tiles_base_colour.hlsl: the tileset's Saturation (the scatter's Poly Haven albedo
// is de-lit and carries no baked haze, so no Dehaze), then the wet darkening
// (WET_DARKENING x Wetness: a wet run's trees are wet with the ground). WET_DARKENING
// is core/scene/world_beauty.py's (pinned by tests/test_world_beauty.py), UNCALIBRATED:
// set by probe render on the render machine.
//
// Inputs (the script's WORLD_SCATTER_INPUTS["scatter_base_colour"]):
//   Albedo      float3  the imported glTF base colour texture times its factor (linear)
//   Wetness     float   0..1 (MPC_FlightSimWorld, the tiles' own)
//   Saturation  float   1 = unchanged (MPC_FlightSimWorld, the tiles' own)
const float WET_DARKENING = 0.30;
float3 c = max(Albedo, 0.0);
float luma = dot(c, float3(0.2126, 0.7152, 0.0722));
c = max(lerp(float3(luma, luma, luma), c, Saturation), 0.0);
c *= 1.0 - WET_DARKENING * saturate(Wetness);
return saturate(c);
