// M_FlightSimTilesBeauty's base colour: the Custom node body scripts/ue_create_materials.py
// (world lane block) pastes into the Google tiles' beauty material. Visual overhaul,
// world lane, 2026-11-09. BEAUTY ONLY: only FFlightSimWorldBeauty (-quality=beauty)
// sets this material on the tileset.
//
// The tiles are photogrammetry: the imagery is baked with the day's haze and
// shadows. A soft-toe dark-object correction takes off the baked haze (Dehaze of
// HAZE_RGB: removal h x a / (a + k), k = h / (1 - DEHAZE_TOE), renormalised so white
// stays white: about h off a bright texel, a dark one keeps at least DEHAZE_TOE of
// itself in every channel, so a shadow never clips to black), a luma-preserving saturation
// restores colour, and wetness darkens porous ground (Lekner & Dorf 1988's order:
// a wet surface's albedo falls by a third) and standing water further. Dehaze and
// Saturation are the tileset's imagery correction (world_beauty.TILES_DEHAZE,
// TILES_SATURATION: one value for every weather). The amounts come from
// MPC_FlightSimWorld (core/scene/world_beauty.py WORLD_MPC_SCALARS, UNCALIBRATED:
// set by probe render on the render machine). HAZE_RGB (a dark-object level,
// world_beauty.TILES_HAZE_RGB), WET_DARKENING and PUDDLE_DARKENING below are
// world_beauty's (pinned by tests/test_world_beauty.py) and UNCALIBRATED too.
//
// Inputs (the script's WORLD_TILES_INPUTS["tiles_base_colour"]):
//   Albedo        float3  the Cesium base-colour texture times its factor (linear)
//   WorldPos      float3  absolute world position, cm
//   CameraPos     float3  absolute camera position, cm (the puddles' range fade)
//   NormalWS      float3  the vertex normal, world space
//   Wetness       float   0..1
//   PuddleAmount  float   0..1
//   Dehaze        float   0..1 share of HAZE_RGB taken off
//   Saturation    float   1 = unchanged
const float3 HAZE_RGB = float3(0.010, 0.015, 0.022);
const float DEHAZE_TOE = 0.5;
const float WET_DARKENING = 0.30;
const float PUDDLE_DARKENING = 0.30;
// Generation 11 (core/scene/world_beauty.py, WET_GROUND_MODEL): Lekner & Dorf 1988's
// water film, A_wet = (1 - r_e)(1 - r_i) A / (1 - r_i A), per channel.
const float WET_FILM_RE = 0.066;
const float WET_FILM_RI = 0.474;
// 1 = the film; 0 = WET_DARKENING (the script pastes 0.0 under FLIGHTSIM_WET_GROUND=legacy).
const float WET_GROUND_MODEL = 1.0;
// Generation 7 (tiles_roughness.hlsl's header): the puddles fade out by this range.
const float PUDDLE_FADE_M = 3000.0;
const float PUDDLE_AMOUNT_SCALE = 0.5;
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
float3 a = max(Albedo, 0.0);
float3 h = max(Dehaze, 0.0) * HAZE_RGB;
float3 k = h / (1.0 - DEHAZE_TOE);
float3 c = (a - h * a / max(a + k, 1e-6)) / (1.0 - h / (1.0 + k));
float luma = dot(c, float3(0.2126, 0.7152, 0.0722));
c = max(lerp(float3(luma, luma, luma), c, Saturation), 0.0);
float3 film = (1.0 - WET_FILM_RE) * (1.0 - WET_FILM_RI) * c / (1.0 - WET_FILM_RI * saturate(c));
float3 wetLegacy = c * (1.0 - WET_DARKENING * saturate(Wetness));
c = WET_GROUND_MODEL > 0.5 ? lerp(c, film, saturate(Wetness)) : wetLegacy;
float rangeM = length(WorldPos - CameraPos) / 100.0;
float puddle = T.Puddles(WorldPos, normalize(NormalWS), saturate(PuddleAmount) * PUDDLE_AMOUNT_SCALE)
               * saturate(1.0 - rangeM / PUDDLE_FADE_M);
c *= 1.0 - PUDDLE_DARKENING * puddle;
return saturate(c);
