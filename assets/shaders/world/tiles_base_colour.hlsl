// M_FlightSimTilesBeauty's base colour: the Custom node body scripts/ue_create_materials.py
// (world lane block) pastes into the Google tiles' beauty material. Visual overhaul,
// world lane, 2026-11-09. BEAUTY ONLY: only FFlightSimWorldBeauty (-quality=beauty)
// sets this material on the tileset.
//
// The tiles are photogrammetry: the imagery is baked with the day's haze and
// shadows. A dark-object subtraction takes off a little of the baked haze (Dehaze
// of HazeRgb), a luma-preserving saturation restores colour, and wetness darkens
// porous ground (Lekner & Dorf 1988's order: a wet surface's albedo falls by a
// third) and standing water further. The amounts come from MPC_FlightSimWorld
// (core/scene/world_beauty.py WORLD_MPC_SCALARS, UNCALIBRATED: set by probe render
// on the render machine). HAZE_RGB, WET_DARKENING and PUDDLE_DARKENING below are
// UNCALIBRATED too.
//
// Inputs (the script's WORLD_TILES_INPUTS["tiles_base_colour"]):
//   Albedo        float3  the Cesium base-colour texture times its factor (linear)
//   WorldPos      float3  absolute world position, cm
//   NormalWS      float3  the vertex normal, world space
//   Wetness       float   0..1
//   PuddleAmount  float   0..1
//   Dehaze        float   0..1 share of HAZE_RGB taken off
//   Saturation    float   1 = unchanged
const float3 HAZE_RGB = float3(0.20, 0.24, 0.30);
const float WET_DARKENING = 0.30;
const float PUDDLE_DARKENING = 0.55;
struct FWorldTilesColour
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
FWorldTilesColour T;
float3 c = max(Albedo - Dehaze * HAZE_RGB, 0.0) / max(1.0 - Dehaze * HAZE_RGB, 1e-3);
float luma = dot(c, float3(0.2126, 0.7152, 0.0722));
c = max(lerp(float3(luma, luma, luma), c, Saturation), 0.0);
c *= 1.0 - WET_DARKENING * saturate(Wetness);
float puddle = T.Puddles(WorldPos, normalize(NormalWS), saturate(PuddleAmount));
c *= 1.0 - PUDDLE_DARKENING * puddle;
return saturate(c);
