// M_FlightSimTilesBeauty's baked sky-shade neutraliser: the Custom node body
// scripts/ue_create_materials.py (world lane block) pastes in right after
// tiles_delight.hlsl (its output is the terrain detail's and the grade's Albedo).
// 2026-11-11, #02 super bright's blue shade. BEAUTY ONLY: only
// FFlightSimWorldBeauty (-quality=beauty) sets this material on the tileset.
//
// The photogrammetry's shade is the capture day's sky: violet-blue. The beauty
// frame draws its own sun on the tiles, so a texel that bakes that sky is moved
// toward the grey of its own luma by
//   w = violet x dark x (1 - level) x ShadeNeutralAmount,
//   violet = saturate((B / max(R, G) - 1) x SHADE_BLUE_GATE),
//   dark   = saturate(1 - luma / SHADE_LUMA_KNEE)  (absolute: a wall wholly in
//            shade is its own neighbourhood, which tiles_delight cannot see),
//   level  = open water's flatness (slope = 1 - normal.z under SHADE_LEVEL_LO..HI).
// ShadeNeutralAmount 0 returns the input exactly (the -tiles-shade-neutral=off A/B).
// The Python twin is core/scene/tiles_shade_neutral.py shade_neutral();
// tests/test_tiles_shade_neutral.py pins the constants and the input order to it.
// Every amount is UNCALIBRATED.
//
// Inputs (the script's WORLD_TILES_INPUTS["tiles_shade_neutral"]):
//   Albedo              float3  the de-lit tile colour (tiles_delight.hlsl's output), linear
//   NormalWS            float3  the vertex normal, world space (Z up)
//   ShadeNeutralAmount  float   0..1, 0 = exact pass-through (MPC_FlightSimWorld, per preset)
const float3 SHADE_LUMA = float3(0.2126, 0.7152, 0.0722);
const float SHADE_EPS = 1e-4;
const float SHADE_LUMA_KNEE = 0.30;
const float SHADE_BLUE_GATE = 4.0;
const float SHADE_LEVEL_LO = 0.005;
const float SHADE_LEVEL_HI = 0.02;
struct FWorldTilesShade
{
	// shared: world noise (tiles_base_colour.hlsl, tiles_normal.hlsl, tiles_roughness.hlsl)
	float Hash2(float2 p)
	{
		uint2 q = (uint2)(int2)floor(p);
		uint h = q.x * 1597334677u ^ q.y * 3812015801u;
		h = (h ^ (h >> 16u)) * 2246822519u;
		return (h ^ (h >> 13u)) / 4294967296.0;
	}
	float Value2(float2 p)
	{
		float2 i = floor(p);
		float2 f = p - i;
		float2 u = f * f * (3.0 - 2.0 * f);
		float a = Hash2(i);
		float b = Hash2(i + float2(1.0, 0.0));
		float c = Hash2(i + float2(0.0, 1.0));
		float d = Hash2(i + float2(1.0, 1.0));
		return lerp(lerp(a, b, u.x), lerp(c, d, u.x), u.y);
	}
	float Puddles(float3 worldPos, float3 normalWS, float amount)
	{
		float level = saturate((normalWS.z - 0.96) / 0.03);
		float n = Value2(worldPos.xy / 2500.0) * 0.7 + Value2(worldPos.xy / 600.0) * 0.3;
		return level * smoothstep(1.0 - amount, 1.0 - amount + 0.08, n);
	}
	// end shared (kept identical in every tiles shader; tests/test_world_beauty.py pins it; unused here)
};
float amount = saturate(ShadeNeutralAmount);
[branch] if (amount <= 0.0)
{
	return Albedo;
}
float3 a = max(Albedo, 0.0);
float L = dot(a, SHADE_LUMA);
float rg = max(max(a.r, a.g), SHADE_EPS);
float violet = saturate((a.b / rg - 1.0) * SHADE_BLUE_GATE);
float dark = saturate(1.0 - L / SHADE_LUMA_KNEE);
float slope = 1.0 - saturate(normalize(NormalWS).z);
float water = 1.0 - smoothstep(SHADE_LEVEL_LO, SHADE_LEVEL_HI, slope);
float w = violet * dark * (1.0 - water) * amount;
return lerp(a, float3(L, L, L), w);
