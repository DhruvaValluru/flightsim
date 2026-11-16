// M_FlightSimTilesBeauty's open-water unifier (round 147, 2026-11-16). BEAUTY ONLY:
// only FFlightSimWorldBeauty (-quality=beauty) puts this material on the tileset; the
// label captures never draw it (class, mask and depth unchanged by construction).
// Colour only: no world-position offset, no depth, no pixel moves.
//
// Why. Windows r146 / r14622 #06 ("A320 over SFO, moderate rain") drew the bay as a
// quilt of straight-edged quads and wedges, each a flat colour (sRGB 24/45/93 next to
// 30/54/101 next to 41/64/104 at the same range), the edges straight across the water:
// tile edges. Google's photogrammetry colours every tile's water from its own capture
// and, at range, its own LOD's texture, so neighbouring tiles disagree by about 10
// levels; and tiles_delight's local mean (the same texture at mip +5) is per TEXTURE,
// so a tile holding shore lifts its water toward the land and its neighbour does not.
// Both are a step in the tile's MEAN colour, constant over the tile.
//
// The law: open water is a level face (the face normal from the world position's
// screen derivatives, as tiles_shade_neutral: Cesium's vertex normals are the
// ellipsoid's up), dark in its local mean (AlbedoLow's luma under WATER_DARK_HI) and
// blue-or-teal in that mean (B above R and not below G by much), with little texture
// contrast against it. There the tile's mean is replaced by one WATER_MEAN for every
// tile, keeping the texel's own detail as its luma ratio to the mean (clamped):
//   out = lerp(Albedo, WATER_MEAN x clamp(L / Lm, RATIO_LO, RATIO_HI), mask x amount).
// Runs after the de-light and the shade neutraliser (so it also takes back a de-light
// lift on water). WaterUnifyAmount 0 returns the input exactly (-tiles-water-unify=off).
// Python twin: core/scene/tiles_water_unify.py (tests/test_tiles_water_unify.py pins
// every constant and the input order). UNCALIBRATED: every number below.
//
// Inputs (the script's WORLD_TILES_INPUTS["tiles_water_unify"]):
//   Albedo            float3  the de-lit, shade-neutralised albedo (linear)
//   AlbedoLow         float3  the tile texture at the de-light's mip bias (the tile's local mean)
//   WorldPos          float3  absolute world position, cm (the face normal)
//   WaterUnifyAmount  float   0..1, 0 = exact pass-through (MPC_FlightSimWorld, per preset)
const float3 WATER_LUMA = float3(0.2126, 0.7152, 0.0722);
const float WATER_EPS = 1e-4;
const float3 WATER_MEAN = float3(0.020, 0.040, 0.055);
const float WATER_LEVEL_LO = 0.005;
const float WATER_LEVEL_HI = 0.02;
const float WATER_DARK_LO = 0.07;
const float WATER_DARK_HI = 0.12;
const float WATER_BR_MIN = 1.1;
const float WATER_BR_GAIN = 3.0;
const float WATER_BG_MIN = 0.85;
const float WATER_BG_GAIN = 6.0;
const float WATER_FLAT_KEEP = 0.15;
const float WATER_FLAT_SPAN = 0.30;
const float WATER_RATIO_LO = 0.6;
const float WATER_RATIO_HI = 1.6;
struct FWorldTilesWater
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

// Derivatives first: nothing below may take one inside a branch.
float3 p = WorldPos / 100.0;
float3 face = cross(ddx_fine(p), ddy_fine(p));
float faceUp = abs(face.z) / max(length(face), 1e-8);
float amount = saturate(WaterUnifyAmount);
[branch] if (amount <= 0.0)
{
	return Albedo;
}
float3 a = max(Albedo, 0.0);
float3 m = max(AlbedoLow, 0.0);
float L = dot(a, WATER_LUMA);
float Lm = max(dot(m, WATER_LUMA), WATER_EPS);
float level = 1.0 - smoothstep(WATER_LEVEL_LO, WATER_LEVEL_HI, 1.0 - saturate(faceUp));
float dark = 1.0 - smoothstep(WATER_DARK_LO, WATER_DARK_HI, Lm);
float blue = saturate((m.b / max(m.r, WATER_EPS) - WATER_BR_MIN) * WATER_BR_GAIN)
           * saturate((m.b / max(m.g, WATER_EPS) - WATER_BG_MIN) * WATER_BG_GAIN);
float ratio = L / Lm;
float calm = saturate(1.0 - (abs(ratio - 1.0) - WATER_FLAT_KEEP) / WATER_FLAT_SPAN);
float w = level * dark * blue * calm * amount;
float3 target = WATER_MEAN * clamp(ratio, WATER_RATIO_LO, WATER_RATIO_HI);
return lerp(a, target, w);
