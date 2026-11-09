// M_FlightSimTilesBeauty's WORLD-SPACE normal (the material's tangent-space switch is
// off: the tiles' meshes carry no reliable tangents). Visual overhaul, world lane,
// 2026-11-09. BEAUTY ONLY.
//
// A near-field detail normal: the gradient of a two-octave value noise of
// DetailScaleM wavelength over world XY tilts the vertex normal by DetailStrength,
// fading to nothing at DetailFadeM from the camera, so the ground under a low
// aircraft has micro relief while the far photogrammetry is untouched (and never
// tiles). Standing water (the same puddle mask as the base colour) is flat. The
// amounts come from MPC_FlightSimWorld (UNCALIBRATED: set by probe render on the
// render machine).
//
// Inputs (the script's WORLD_TILES_INPUTS["tiles_normal"]):
//   WorldPos        float3  absolute world position, cm
//   CameraPos       float3  absolute camera position, cm
//   NormalWS        float3  the vertex normal, world space
//   DetailStrength  float   0 = Cesium's own normal
//   DetailFadeM     float   the detail is gone at this range
//   DetailScaleM    float   the detail's wavelength
//   PuddleAmount    float   0..1
struct FWorldTilesNormal
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
	float Height(float2 metres, float scale)
	{
		return Value2(metres / scale) + 0.5 * Value2(metres / (0.37 * scale) + float2(5.2, 1.3));
	}
};
FWorldTilesNormal T;
float3 n = normalize(NormalWS);
float rangeM = length(WorldPos - CameraPos) / 100.0;
float fade = saturate(1.0 - rangeM / max(DetailFadeM, 1.0));
float scale = max(DetailScaleM, 0.05);
float2 m = WorldPos.xy / 100.0;
float e = 0.1 * scale;
float dx = (T.Height(m + float2(e, 0.0), scale) - T.Height(m - float2(e, 0.0), scale)) / (2.0 * e);
float dy = (T.Height(m + float2(0.0, e), scale) - T.Height(m - float2(0.0, e), scale)) / (2.0 * e);
float k = DetailStrength * fade * scale;
float3 detailed = normalize(n - k * float3(dx, dy, 0.0));
float puddle = T.Puddles(WorldPos, n, saturate(PuddleAmount));
return normalize(lerp(detailed, float3(0.0, 0.0, 1.0), puddle));
