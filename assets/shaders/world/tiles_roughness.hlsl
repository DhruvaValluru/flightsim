// M_FlightSimTilesBeauty's roughness. Visual overhaul, world lane, 2026-11-09. BEAUTY ONLY.
//
// Dry ground at ROUGHNESS_DRY (the project's terrain value, scripts/
// ue_create_materials.py ROUGHNESS_DRY), a near-field micro-roughness variation of
// +-MICRO_VARIATION faded with the detail normal, wet ground toward ROUGHNESS_WET
// (the project's value), standing water at ROUGHNESS_PUDDLE (a mirror-ish sheen
// that picks up the sky). MICRO_VARIATION and ROUGHNESS_PUDDLE are UNCALIBRATED:
// set by probe render on the render machine.
//
// Inputs (the script's WORLD_TILES_INPUTS["tiles_roughness"]):
//   WorldPos      float3  absolute world position, cm
//   CameraPos     float3  absolute camera position, cm
//   NormalWS      float3  the vertex normal, world space
//   Wetness       float   0..1
//   PuddleAmount  float   0..1
//   DetailFadeM   float   the micro variation is gone at this range
const float ROUGHNESS_DRY = 0.92;
const float ROUGHNESS_WET = 0.25;
const float ROUGHNESS_PUDDLE = 0.05;
const float MICRO_VARIATION = 0.06;
struct FWorldTilesRoughness
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
	// end shared
};
FWorldTilesRoughness T;
float rangeM = length(WorldPos - CameraPos) / 100.0;
float fade = saturate(1.0 - rangeM / max(DetailFadeM, 1.0));
float micro = (T.Value2(WorldPos.xy / 80.0) - 0.5) * 2.0 * MICRO_VARIATION * fade;
float r = lerp(ROUGHNESS_DRY + micro, ROUGHNESS_WET, saturate(Wetness));
float puddle = T.Puddles(WorldPos, normalize(NormalWS), saturate(PuddleAmount));
return saturate(lerp(r, ROUGHNESS_PUDDLE, puddle));
