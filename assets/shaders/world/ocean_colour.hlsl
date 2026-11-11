// M_FlightSimOceanBeauty: the base colour: the deep ocean's body colour, a soft 3 km variation, the foam.
//
// Lane B of the non-urban visual push. BEAUTY ONLY: the material is
// M_FlightSimOceanBeauty, drawn only on the beauty sea cap
// (FFlightSimGoogleTiles::ApplyBeautyGround; a beauty-only actor no label, depth
// or mask pass draws, no WPO), so the labels and every measure render are
// untouched.
//
// Round 10 (2026-11-11) drew generation 1 on #13 (747 at 10 km): a flat blue sea
// with a rectangular grid and bright streaks below the horizon. Two causes, both
// gone here: (1) the engine's own reflection on a 0.44-rough surface, i.e. the
// screen-space reflections' blocky, streaky trace of the cloud deck on the
// D3D11 / SM5 path, and (2) a 1357 m octave of the wave tile still drawn at
// 10 km through the shared bilinear (point-mip) sampler, its repeats a grid.
// Generation 2 turns the engine specular OFF (Specular 0, roughness 1: no SSR, no
// reflection capture, no sky-light specular) and draws the sea's reflection
// itself, as emissive, from the same atmosphere the sky is drawn with:
//   * the sky in the mirror direction: SkyLum shaped from the bright, pale
//     horizon to the darker, bluer zenith by the reflected ray's elevation,
//     times Schlick's Fresnel (F0 0.02) and the slopes' Smith shadowing -> dark
//     blue straight down, brightening smoothly toward the horizon;
//   * the sun glint: GGX with the Cox & Munk (1954) slope variance as its width
//     (a soft lobe several degrees wide at 7 m/s), the sun's illuminance at the
//     sea, varied by a 6 km wind-streak field so the lobe is patchy like a photo;
//   * the waves' texture only where the pixel resolves its texels (the 256 m and
//     54 m octaves, a low camera), with the tile's own trilinear sampler.
// The body colour (lit by the engine's diffuse) is the deep sea's dark
// water-leaving colour. UNCALIBRATED: HORIZON_GAIN, ZENITH_TINT, PATCHINESS and
// the body colour, set by probe render on the render machine
// (docs/visual/PROBE_LOG.md ## lane-B terrain detail, round-10 ocean).
//
// Inputs (the script's WORLD_OCEAN_INPUTS["ocean_colour"], every node alike):
//   WorldPos        float3     absolute world position, cm
//   CameraPos       float3     absolute camera position, cm
//   NormalWS        float3     the vertex normal, world space (the sea cap's: radial)
//   TimeS           float      seconds (the material's Time node)
//   SunDir          float3     the atmosphere light's direction (toward the sun)
//   SunIlluminance  float3     its illuminance at the sea (after the atmosphere)
//   SkyLum          float3     the sky's distant scattered luminance
//   WindSpeedMS     float      the sea state's wind, m/s (Cox-Munk; Monahan's whitecaps)
//   WindDirX        float      the downwind direction, world x ...
//   WindDirY        float      ... and y (normalised here)
//   OceanN          Texture2D  assets/terrain_detail/ocean/ocean_normal_512.png (OpenGL)
// The deep ocean's body colour (linear; the water-leaving colour of open
// oligotrophic sea: dark and only a little blue) and the whitecaps' albedo.
const float3 WATER_RGB = float3(0.003, 0.010, 0.020);
const float FOAM_ALBEDO = 0.6;
// The reflected sky relative to SkyLum: the horizon's pale brightness and the
// zenith's darker blue (the shape of a clear sky's radiance with elevation).
const float HORIZON_GAIN = 1.5;
const float3 ZENITH_TINT = float3(0.35, 0.55, 0.95);
struct FOceanSurface
{
	// shared: ocean (ocean_normal.hlsl, ocean_emissive.hlsl, ocean_colour.hlsl)
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
	// A smooth 0..1 field with features of about `metres`: three value-noise
	// octaves, each rotated and offset, so no lattice axis or repeat shows.
	float Macro(float2 pm, float metres)
	{
		float2 q = pm / metres;
		float a = Value2(q);
		float b = Value2(float2(0.8 * q.x - 0.6 * q.y, 0.6 * q.x + 0.8 * q.y) * 2.03 + float2(17.1, 3.7));
		float c = Value2(float2(0.28 * q.x + 0.96 * q.y, -0.96 * q.x + 0.28 * q.y) * 4.11 + float2(5.3, 29.9));
		return (a + 0.5 * b + 0.25 * c) / 1.75;
	}
	// Cox & Munk (1954), clean sea: the total mean-square slope at wind U m/s.
	float SlopeVariance(float windMs)
	{
		return 0.003 + 0.00512 * max(windMs, 0.0);
	}
	// The sea state at p (metres). The Cox-Munk variance, varied +-PATCHINESS
	// by a 6 km field (real seas carry wind streaks and slicks: the glint
	// lobe is patchy, never a flat disc). Only the wave octaves whose texels
	// the pixel resolves are drawn from the Phillips tile (256 m and 54 m,
	// assets/terrain_detail/ocean, OpenGL normal with slope RMS 0.35), with
	// the tile's own trilinear sampler, rotated and drifting downwind; from a
	// high camera they are gone (no tile grid) and all the variance is the
	// glint lobe's width. Out: tilt (the normal's horizontal part from the
	// resolved octaves), variance (what the lobe draws: the unresolved
	// slopes), crest (the resolved slope over its RMS: the foam's key).
	void Waves(Texture2D tex, SamplerState samp, float3 p, float3 dpx, float3 dpy, float footprintM, float timeS,
	           float windMs, float2 windDir, out float2 tilt, out float variance, out float crest)
	{
		float total = SlopeVariance(windMs) * lerp(0.65, 1.35, Macro(p.xy, 6000.0));
		float tiles[2] = {256.0, 54.0};
		float shares[2] = {0.35, 0.3};
		float angles[2] = {-0.6, 1.1};
		float2 sum = float2(0.0, 0.0);
		float resolved = 0.0;
		float resolvedShare = 0.0;
		[unroll] for (int i = 0; i < 2; ++i)
		{
			float texel = tiles[i] / 512.0;
			float seen = 1.0 - smoothstep(2.0 * texel, 6.0 * texel, footprintM);
			float s, c;
			sincos(angles[i], s, c);
			float2x2 rot = float2x2(c, -s, s, c);
			// The tile's dominant wave is about an eighth of it; deep water c = sqrt(g L / 2 pi).
			float speed = sqrt(9.81 * tiles[i] / 8.0 / 6.2831853);
			float2 drift = windDir * speed * timeS;
			float2 uv = mul(rot, (p.xy - drift) / tiles[i]);
			float2 t = float2(0.0, 0.0);
			[branch] if (seen > 0.01)
			{
				t = tex.SampleGrad(samp, uv, mul(rot, dpx.xy / tiles[i]), mul(rot, dpy.xy / tiles[i])).rg * 2.0 - 1.0;
				// OpenGL green is toward image-up (-v): back to (u, v), then out of the rotation.
				t = mul(transpose(rot), float2(t.x, -t.y));
			}
			sum += seen * sqrt(shares[i] * total) / 0.35 * t;
			resolved += seen * shares[i] * total;
			resolvedShare += seen * shares[i];
		}
		tilt = sum;
		variance = max(total - resolved, 0.0004);
		crest = length(sum) / max(sqrt(resolvedShare * total), 1e-4);
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
float variance, crest;
S.Waves(OceanN, OceanNSampler, p, dpx, dpy, footprintM, TimeS, WindSpeedMS, windDir, tilt, variance, crest);
float3 up = normalize(NormalWS);
float3 n = normalize(up + float3(tilt, 0.0));
// Monahan & O'Muircheartaigh 1980: whitecap share W = 3.84e-6 U^3.41; the
// resolved crest measure is Rayleigh-like, so |s| > sqrt(-ln W) covers W.
float cover = clamp(3.84e-6 * pow(max(WindSpeedMS, 0.0), 3.41), 1e-5, 0.2);
float foam = smoothstep(sqrt(-log(cover)), sqrt(-log(cover)) + 0.5, crest);
float3 body = WATER_RGB * lerp(0.9, 1.1, S.Macro(p.xy, 3000.0));
return lerp(body, float3(FOAM_ALBEDO, FOAM_ALBEDO, FOAM_ALBEDO), foam);
