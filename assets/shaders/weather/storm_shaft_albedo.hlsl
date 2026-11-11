// M_StormCell's albedo factor: the Custom node body scripts/ue_create_materials.py
// pastes before the volumetric cloud material's base colour (Albedo x this).
// Visual round 6 (2026-11-10). The twin of core/scene/storm_cell.py
// shaft_albedo_scale, constant for constant (tests/test_visual_round6.py).
//
// Round 4's #09 drew the rain shaft brighter than the cloud base and the ground:
// the shaft took the cloud's 0.98 albedo, so the ambient light it scattered made
// a luminous column. Rain is grey: inside the measure shaft's own shape (its
// radial and vertical smoothsteps, no noise) the albedo is scaled by ShaftAlbedo.
// ShaftAlbedo 1 (the parameter's default: every render but beauty) returns exactly
// 1.0 before any shape work, so the measure path's albedo is the parameter's,
// value for value, and the march pays one compare per sample for it.
//
// Inputs (the Custom node's, named exactly so):
//   Rel          float3  the sample's engine position minus the cell centre, cm
//   EastAxis     float3  the engine direction of local east (unit)
//   NorthAxis    float3  the engine direction of local north
//   Geo1         float4  base_m, top_m, overshoot_m, tower_radius_m (base_m read)
//   Sigma        float4  extinction core, anvil, shaft (1/m), shaft radius (m)
//   ShaftAlbedo  float   the shaft's albedo as a share of the cloud's (storm_cell.BEAUTY_SHAFT albedo_scale)
struct FShaftAlbedo
{
	float Ss(float e0, float e1, float x)
	{
		if (e0 == e1) { return x < e0 ? 0.0 : 1.0; }
		float t = saturate((x - e0) / (e1 - e0));
		return t * t * (3.0 - 2.0 * t);
	}
};
FShaftAlbedo A;
if (ShaftAlbedo >= 1.0)
{
	return 1.0;
}
// EDGE_M = 250 (storm_cell.hlsl's Edge); the shaft's own smoothsteps.
const float Edge = 250.0;
float e = dot(Rel, EastAxis) / 100.0;
float n = dot(Rel, NorthAxis) / 100.0;
float u = Rel.z / 100.0;
float r = sqrt(e * e + n * n);
float shaftR = Sigma.w;
float shape = A.Ss(shaftR, shaftR * 0.6, r) * A.Ss(Geo1.x + Edge * 0.5, Geo1.x - Edge * 0.5, u);
return 1.0 + shape * (ShaftAlbedo - 1.0);
