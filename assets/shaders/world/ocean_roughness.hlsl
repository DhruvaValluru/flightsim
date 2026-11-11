// M_FlightSimOceanBeauty: the roughness: the unresolved Cox-Munk variance as GGX (alpha = rms slope, UE roughness = sqrt(alpha)); foam is rough.
//
// Lane B of the non-urban visual push, 2026-11-11. BEAUTY ONLY: the material
// is M_FlightSimOceanBeauty, drawn only on the beauty sea cap
// (FFlightSimGoogleTiles::ApplyBeautyGround; a beauty-only actor no label, depth
// or mask pass draws, no WPO), so the labels and every measure render are
// untouched. Round 4's #13 (747 at 10 km over the Atlantic) was a flat royal-blue
// plane: two 40 m / 13 m sines that the mips average flat from 10 km, roughness
// 0.04 (a mirror with one pin-point sun), and a bright cyan body colour. Here the
// waves are a Phillips-spectrum tile (scripts/make_ocean_normal.py, CC0) in three
// drifting octaves; what the pixel cannot resolve goes to the roughness by Cox &
// Munk's slope variance, which is what makes the broad sun glitter and the
// Fresnel brightening toward the horizon (the engine's GGX does the Fresnel,
// with specular 0.25: water's F0 0.02); the body colour is the deep ocean's dark
// water-leaving colour, and whitecaps cover Monahan & O'Muircheartaigh's (1980)
// share of the sea at the wind. The sampler note in tiles_detail_surface.hlsl
// applies. UNCALIBRATED: the octave shares and the body colour, set by probe
// render on the render machine (docs/visual/PROBE_LOG.md ## lane-B terrain detail).
//
// Inputs (the script's WORLD_OCEAN_INPUTS["ocean_roughness"], all three nodes alike):
//   WorldPos     float3     absolute world position, cm
//   NormalWS     float3     the vertex normal, world space (the sea cap's: radial)
//   Time         float      seconds (the material's Time node)
//   WindSpeedMS  float      the sea state's wind, m/s (Cox-Munk; Monahan's whitecaps)
//   WindDirX     float      the downwind direction, world x ...
//   WindDirY     float      ... and y (normalised here)
//   OceanN       Texture2D  assets/terrain_detail/ocean/ocean_normal_512.png (OpenGL)
// The deep ocean's body colour (linear; the water-leaving colour of open
// oligotrophic sea, dark and only a little blue: the sky's reflection, not this,
// makes the sea's brightness) and the whitecaps' albedo and roughness.
const float3 WATER_RGB = float3(0.003, 0.010, 0.020);
const float FOAM_ALBEDO = 0.6;
const float FOAM_ROUGHNESS = 0.7;
struct FOceanSurface
{
	// shared: ocean (ocean_normal.hlsl, ocean_roughness.hlsl, ocean_colour.hlsl)
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
	// Cox & Munk (1954), clean sea: the total mean-square slope at wind U m/s.
	float SlopeVariance(float windMs)
	{
		return 0.003 + 0.00512 * max(windMs, 0.0);
	}
	// The wave field at p (metres): three octaves of the Phillips tile
	// (assets/terrain_detail/ocean, 256 m, OpenGL normal whose slopes have RMS
	// 0.35) at 1357 m (swell), 256 m and 54 m, each rotated and drifting
	// downwind at its own deep-water phase speed, each carrying a share of the
	// Cox-Munk variance; an octave whose texels are finer than the pixel
	// footprint fades out and its variance goes to the roughness instead
	// (Toksvig's idea: what the mips average away is still slope). Out:
	// tilt (the world-space normal's horizontal part), the variance left
	// unresolved, the crest measure (|slope| of the resolved field over its
	// own RMS) the foam keys on.
	void Waves(Texture2D tex, float3 p, float3 dpx, float3 dpy, float footprintM, float timeS, float windMs,
	           float2 windDir, out float2 tilt, out float unresolved, out float crest)
	{
		float total = SlopeVariance(windMs);
		float tiles[3] = {1357.0, 256.0, 54.0};
		float shares[3] = {0.25, 0.35, 0.25};
		float angles[3] = {0.35, -0.6, 1.1};
		float2 sum = float2(0.0, 0.0);
		float resolved = 0.0;
		float resolvedEnc = 0.0;
		[unroll] for (int i = 0; i < 3; ++i)
		{
			float texel = tiles[i] / 512.0;
			float seen = 1.0 - smoothstep(texel, 8.0 * texel, footprintM);
			float s, c;
			sincos(angles[i], s, c);
			float2x2 rot = float2x2(c, -s, s, c);
			// The tile's dominant wave is about an eighth of it; deep water c = sqrt(g L / 2 pi).
			float speed = sqrt(9.81 * tiles[i] / 8.0 / 6.2831853);
			float2 drift = windDir * speed * timeS;
			float2 uv = mul(rot, (p.xy - drift) / tiles[i]);
			float2 dx = mul(rot, dpx.xy / tiles[i]);
			float2 dy = mul(rot, dpy.xy / tiles[i]);
			float2 t = float2(0.0, 0.0);
			[branch] if (seen > 0.01)
			{
				t = tex.SampleGrad(View.MaterialTextureBilinearWrapedSampler, uv, dx, dy).rg * 2.0 - 1.0;
				// OpenGL green is toward image-up (-v): back to (u, v), then out of the rotation.
				t = mul(transpose(rot), float2(t.x, -t.y));
			}
			float gain = sqrt(shares[i] * total) / 0.35;
			sum += seen * gain * t;
			resolved += seen * shares[i] * total;
			resolvedEnc += seen * shares[i];
		}
		tilt = sum;
		unresolved = max(total - resolved, 0.0004);
		crest = length(sum) / max(sqrt(resolvedEnc * total), 1e-4);
	}
	// end shared
};
FOceanSurface S;
float3 p = WorldPos / 100.0;
float3 dpx = ddx_fine(p);
float3 dpy = ddy_fine(p);
float footprintM = max(max(length(dpx), length(dpy)), 1e-3);
float2 windDir = normalize(float2(WindDirX, WindDirY) + float2(1e-4, 0.0));
float2 tilt;
float unresolved, crest;
S.Waves(OceanN, p, dpx, dpy, footprintM, Time, WindSpeedMS, windDir, tilt, unresolved, crest);
// Monahan & O'Muircheartaigh 1980: whitecap share W = 3.84e-6 U^3.41; the
// resolved crest measure is Rayleigh-like, so |s| > sqrt(-ln W) covers W.
float cover = clamp(3.84e-6 * pow(max(WindSpeedMS, 0.0), 3.41), 1e-5, 0.2);
float foam = smoothstep(sqrt(-log(cover)), sqrt(-log(cover)) + 0.5, crest);
float r = sqrt(sqrt(unresolved));
return saturate(lerp(r, FOAM_ROUGHNESS, foam));
