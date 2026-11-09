// M_FlightSimTilesBeauty's tile de-lighting: the Custom node body
// scripts/ue_create_materials.py (world lane block, tiles-delight hook) pastes into
// the Google tiles' beauty material, AHEAD of tiles_base_colour.hlsl (its output is
// that node's Albedo). Visual overhaul, module tiles-delight, 2026-11-09. BEAUTY
// ONLY: only FFlightSimWorldBeauty (-quality=beauty) sets this material on the
// tileset; the label captures never draw it (class, mask and depth unchanged by
// construction). Colour only: no world-position offset, no depth, no pixel moves.
//
// The tiles are photogrammetry captured on one day under one sun: their texture
// carries that day's cast shadows, darker than their surroundings and tinted blue
// by the skylight that alone lit them. Under a simulated sun at another time those
// shadows point the wrong way and double the engine's own (VSM plus Lumen AO). This
// node estimates, per pixel and per frame, where the texture holds such a shadow and
// lifts it toward the local mean:
//   * the local mean is the same texture at a coarse mip (AlbedoLow, sampled with
//     MipBias = DelightMipBias, about +5: a 32x32 texel neighbourhood);
//   * a pixel is a shadow candidate when it is darker than DelightRatioKnee of that
//     mean AND bluer than it is red (B/R above 1, gated by DelightBlueGate), so dark
//     neutral asphalt or a black roof is left almost alone;
//   * the candidate is scaled toward the mean's luma and its chroma pulled toward the
//     mean's chroma by the same weight (shadow x DelightAmount);
//   * the result is clamped to [0, 1] and never brighter, channel by channel, than
//     the larger of the pixel and the mean (a lift never overshoots its neighbourhood).
// Google Map Tiles policy forbids storing derived content: this is a per-frame shader
// operation only. Nothing is baked, cached or written; the attribution is untouched;
// nothing here can disable the tiles (the owner's rule: the tiles are the ground).
//
// The Python twin is core/scene/tiles_delight.py delight(); tests/test_tiles_delight.py
// pins DELIGHT_LUMA, DELIGHT_EPS and the input order below to it. Every amount is
// UNCALIBRATED: set by probe render on the render machine (docs/visual/PROBE_LOG.md
// ## tiles-delight).
//
// Inputs (the script's WORLD_TILES_INPUTS["tiles_delight"]):
//   Albedo            float3  the Cesium base-colour texture times its factor (linear), mip as drawn
//   AlbedoLow         float3  the same texture at MipBias DelightMipBias, times the factor (the local mean)
//   DelightAmount     float   0..1, 0 = exact pass-through (MPC_FlightSimWorld, per preset)
//   DelightRatioKnee  float   a pixel under this share of the local luma is a shadow candidate
//   DelightBlueGate   float   gain on (B/R - 1): how blue a candidate must be to count fully
const float3 DELIGHT_LUMA = float3(0.2126, 0.7152, 0.0722);
const float DELIGHT_EPS = 1e-4;
struct FWorldTilesDelight
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
float3 a = max(Albedo, 0.0);
float3 m = max(AlbedoLow, 0.0);
float L = dot(a, DELIGHT_LUMA);
float Lm = dot(m, DELIGHT_LUMA);
float knee = max(DelightRatioKnee, DELIGHT_EPS);
float ratio = L / max(Lm, DELIGHT_EPS);
float darker = saturate((knee - ratio) / knee);
float bluer = saturate((a.b / max(a.r, DELIGHT_EPS) - 1.0) * DelightBlueGate);
float w = darker * bluer * saturate(DelightAmount);
float3 lifted = a * lerp(1.0, Lm / max(L, DELIGHT_EPS), w);
float3 pulled = m / max(Lm, DELIGHT_EPS) * dot(lifted, DELIGHT_LUMA);
float3 c = lerp(lifted, pulled, w);
return min(saturate(c), max(a, m));
