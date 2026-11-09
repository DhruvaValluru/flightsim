// M_FlightSimScatter's roughness. Visual overhaul, world lane fix pass, 2026-11-09.
// BEAUTY ONLY.
//
// The imported glTF roughness, pulled toward ROUGHNESS_WET by the tiles' own
// Wetness (MPC_FlightSimWorld), the law of tiles_roughness.hlsl: one wet ground for
// the tiles and everything standing on them. ROUGHNESS_WET is core/scene/
// world_beauty.py's (pinned by tests/test_world_beauty.py), UNCALIBRATED: set by
// probe render on the render machine.
//
// Inputs (the script's WORLD_SCATTER_INPUTS["scatter_roughness"]):
//   Roughness  float  the imported glTF roughness (texture channel times factor)
//   Wetness    float  0..1
const float ROUGHNESS_WET = 0.25;
return saturate(lerp(saturate(Roughness), ROUGHNESS_WET, saturate(Wetness)));
