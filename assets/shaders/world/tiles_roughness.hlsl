// M_FlightSimTilesBeauty's roughness. Visual overhaul, world lane, 2026-11-09. BEAUTY ONLY.
//
// Dry ground at ROUGHNESS_DRY (the project's terrain value, scripts/
// ue_create_materials.py ROUGHNESS_DRY), a near-field micro-roughness variation of
// +-MICRO_VARIATION faded with the detail normal, wet ground toward ROUGHNESS_WET
// (the project's value), standing water at ROUGHNESS_PUDDLE (a mirror-ish sheen
// that picks up the sky). MICRO_VARIATION and ROUGHNESS_PUDDLE are UNCALIBRATED:
// set by probe render on the render machine.
//
// Wet ground, generation 7 (2026-11-14, #15 / #09 / #10 heavy rain over Kansas farmland):
// the frames drew near-black ground scratched with fine white streaks. Read from the code
// at Wetness 1: PuddleAmount was 0.5 x Wetness, so the shared Puddles() threshold
// smoothstep(0.5, 0.58, n) on a value noise centred on 0.5 marked about half of all flat
// ground (normal z > 0.96: nearly all prairie) as standing water at roughness 0.05, a
// mirror. A mirror under the tiles' detail normal picks up the bright sky in sub-pixel
// glints at kilometres of range on D3D11 / SM5 (no specular anti-aliasing), the white
// streaks along field and road edges; and the colour took 0.70 x 0.45 = 0.32 of the
// albedo there, the black. Now: puddles at PUDDLE_AMOUNT_SCALE of PuddleAmount (~4 % of
// flat ground at Wetness 1), faded out by PUDDLE_FADE_M of range; standing water at a
// wet-asphalt sheen (ROUGHNESS_PUDDLE 0.15, not a mirror); and the wet specular widened
// with range toward ROUGHNESS_WET_FAR over WET_SPEC_FADE_M, so a far pixel's sub-pixel
// slopes read as a broad sheen, not glints. Every change rides on Wetness / PuddleAmount:
// at Wetness 0 (PuddleAmount 0) the output is the dry roughness, unchanged.
// ROUGHNESS_WET_FAR, WET_SPEC_FADE_M and PUDDLE_FADE_M are UNCALIBRATED.
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
const float ROUGHNESS_PUDDLE = 0.15;
const float ROUGHNESS_WET_FAR = 0.55;
const float WET_SPEC_FADE_M = 2500.0;
const float PUDDLE_FADE_M = 3000.0;
const float PUDDLE_AMOUNT_SCALE = 0.5;
// Generation 11 (core/scene/world_beauty.py, WET_GROUND_MODEL): the specular AA clamp.
const float WET_SPEC_AA_MAX = 0.02;
// 1 = generation 11; 0 = generation 7. Opt-in until the Windows A/B: the script pastes
// 1.0 under FLIGHTSIM_WET_GROUND=film.
const float WET_GROUND_MODEL = 0.0;
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
bool film = WET_GROUND_MODEL > 0.5;
// Generation 7 widened the wet lobe with range; generation 11 keeps ROUGHNESS_WET and
// widens it only by the normal's own screen-space variance (sub-pixel facets).
float farSpec = film ? 0.0 : saturate(rangeM / WET_SPEC_FADE_M);
float3 nW = normalize(NormalWS);
float3 dnx = ddx(nW);
float3 dny = ddy(nW);
float kernel = film ? min(0.5 * (dot(dnx, dnx) + dot(dny, dny)), WET_SPEC_AA_MAX) : 0.0;
float rWet = lerp(ROUGHNESS_WET, ROUGHNESS_WET_FAR, farSpec);
rWet = sqrt(sqrt(rWet * rWet * rWet * rWet + kernel));
float r = lerp(ROUGHNESS_DRY + micro, rWet, saturate(Wetness));
float puddle = T.Puddles(WorldPos, normalize(NormalWS), saturate(PuddleAmount) * PUDDLE_AMOUNT_SCALE)
               * saturate(1.0 - rangeM / PUDDLE_FADE_M);
float rPuddle = lerp(ROUGHNESS_PUDDLE, rWet, farSpec);
rPuddle = film ? sqrt(sqrt(ROUGHNESS_PUDDLE * ROUGHNESS_PUDDLE * ROUGHNESS_PUDDLE * ROUGHNESS_PUDDLE + kernel)) : rPuddle;
return saturate(lerp(r, rPuddle, puddle));
