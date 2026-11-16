// M_FlightSimCirrus: the high cirrus sheet (sky step 6 of the owner's X-Plane-12
// brief, 2026-11-15). The Custom node body scripts/ue_create_materials.py
// (create_world_cirrus) pastes into an UNLIT, TRANSLUCENT, two-sided material on
// one large earth-curved disc at 10-13 km, ABOVE the flight (FlightSimClouds.cpp
// ApplyCirrus; Python twin core/scene/cirrus.py). BEAUTY ONLY: the disc is in
// BeautyOnlyActors (hidden on every label capture), writes no depth, no custom
// depth and no velocity, casts no shadow. VISUAL ONLY.
//
// Why: UE draws one volumetric cloud layer, and the reference photograph's upper
// sky is thin cirrus / cirrostratus: long translucent wisps and streaks with
// feathered ends, brighter white where thicker, the blue reading through
// everywhere (veils, not blobs). This sheet draws that with no march: one field
// evaluation per covered pixel (about 32 lattice hashes), no texture.
//
// The field: the seeded kilometre frame is turned onto the streak axis (the
// card's drift bearing, or a seeded one) and stretched StreakAspect x along it;
// a slow flow warp curves the streaks (cirrus uncinus hooks); three gradient
// noise octaves make the field; it is cut at the cover's quantile with a soft
// edge EdgeSigmas wide (a veil, never a hard cut-out); fine filaments along the
// stream (Fibres) modulate the thickness and never add cover; a slow
// along-stream noise's zero crossings thin each streak to nothing (its
// feathered ends). Opacity is Beer's law on the slant path through a veil of
// vertical optical depth OpticalDepth x thickness, capped at MaxOpacity.
//
// The light: ice crystals scatter strongly forward, so the veil is brightest
// near the sun and sun-tinted at a low sun (the sun's illuminance arrives
// through the atmosphere from the SkyAtmosphere node): a normalised
// Henyey-Greenstein lobe (g ForwardG, capped) blended ForwardShare with an
// isotropic term, times the albedo over pi, plus the sky's distant scattered
// luminance x AmbientGain. The material applies the height fog and the aerial
// perspective per pixel, so the far sheet fades into the horizon haze.
//
// Every look value arrives as a parameter from core/scene/cirrus.py CIRRUS_LOOK
// (UNCALIBRATED: set by probe render on the render machine); FBM_MEAN / FBM_SIGMA
// are the streak field's own moments, measured on the Python replica and pinned
// by tests/test_cirrus.py; the noise members of FCirrusNoise are FWorldCloud's
// (cloud_layers.hlsl), text for text, pinned by the same test. UNMEASURED:
// nothing here has been rendered.
//
// Inputs (the Custom node's, named exactly so; the script's WORLD_CIRRUS_INPUTS):
//   WorldPos         float3  the pixel's absolute world position, cm
//   CameraPos        float3  the camera's absolute world position, cm
//   SunDir           float3  the atmosphere light's direction towards the sun (SkyAtmosphereLightDirection)
//   SunIlluminance   float3  the sun's illuminance at the pixel through the atmosphere (SkyAtmosphereLightIlluminance)
//   SkyLum           float3  the sky's distant scattered luminance (SkyAtmosphereDistantLightScatteredLuminance)
//   Coverage         float   the cirrus cover, 0..1 (the plan's cirrus_coverage, or the stated default)
//   StreakDirDeg     float   the streaks' compass bearing (engine X east, Y north: a bearing b points along (sin b, cos b))
//   RadiusKm         float   the disc's radius
//   SheetFade        float   per frame: 1 with the full clearance below the sheet, 0 with the camera at the cap
//   StreakScaleKm    float   the cross-stream feature size, km
//   StreakAspect     float   the along-stream stretch
//   EdgeSigmas       float   the cut's soft edge in sigmas of the field
//   FibreStrength    float   how deeply the fine filaments modulate the thickness
//   FeatherWidth     float   the ends noise width over which a streak thins to nothing
//   OpticalDepth     float   the veil's vertical optical depth at full thickness
//   MaxOpacity       float   the opacity cap
//   Albedo           float   the ice's albedo
//   AmbientGain      float   x the sky's distant scattered luminance
//   ForwardG         float   the Henyey-Greenstein asymmetry
//   ForwardShare     float   the lobe's share against the isotropic term
//   ForwardCap       float   the lobe's cap
//   RimFadeShare     float   the sheet fades out over this share of the radius at the rim
//   SunDirSign       float   1: SunDir points towards the sun (as read in the 5.7 source); -1 flips it (the A/B)
//   SeedOffsetKm     float3  the card's seeded noise offset (world_beauty.cloud_seed_offset_km)
//   WindOffsetM      float3  the drift since t = 0, engine metres (the scene's drift law x CIRRUS_WIND_GAIN)
const float FBM_MEAN = 0.5;
const float FBM_SIGMA = 0.077;
const float PI_CI = 3.14159265;
// The hashed field's fixed lattice seed (the material is seeded through SeedOffsetKm).
const uint NOISE_SEED = 17u;
// shared: world cloud noise members (cloud_layers.hlsl FWorldCloud, text-equal per member)
struct FCirrusNoise
{
	// The normal quantile (Tukey's lambda, world_beauty.probit_approx).
	float Probit(float p)
	{
		p = clamp(p, 1e-4, 1.0 - 1e-4);
		return 4.91 * (pow(p, 0.14) - pow(1.0 - p, 0.14));
	}
	uint Pcg(uint v)
	{
		uint state = v * 747796405u + 2891336453u;
		uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
		return (word >> 22u) ^ word;
	}
	// One PCG round over a multiply-xor mix of the cell (world_beauty._hash3).
	uint Hash3(int ix, int iy, int iz, uint seed)
	{
		return Pcg((asuint(ix) * 0x8DA6B343u) ^ (asuint(iy) * 0xD8163841u) ^ (asuint(iz) * 0xCB1AB31Fu) ^ seed);
	}
	float Fade(float t) { return t * t * t * (t * (t * 6.0 - 15.0) + 10.0); }
	// Perlin's improved gradient set (12 edges, 16 entries).
	float Grad(uint h, float x, float y, float z)
	{
		h = h & 15u;
		float u = h < 8u ? x : y;
		float v = h < 4u ? y : ((h == 12u || h == 14u) ? x : z);
		return ((h & 1u) == 0u ? u : -u) + ((h & 2u) == 0u ? v : -v);
	}
	// Gradient noise on the plane (the z = 0 lattice row, 4 corners).
	float Perlin2(float x, float y, uint seed)
	{
		float ix = floor(x); float iy = floor(y);
		int cx = (int)ix; int cy = (int)iy;
		float fx = x - ix; float fy = y - iy;
		float u = Fade(fx); float v = Fade(fy);
		float g00 = Grad(Hash3(cx, cy, 0, seed), fx, fy, 0.0);
		float g10 = Grad(Hash3(cx + 1, cy, 0, seed), fx - 1.0, fy, 0.0);
		float g01 = Grad(Hash3(cx, cy + 1, 0, seed), fx, fy - 1.0, 0.0);
		float g11 = Grad(Hash3(cx + 1, cy + 1, 0, seed), fx - 1.0, fy - 1.0, 0.0);
		return lerp(lerp(g00, g10, u), lerp(g01, g11, u), v);
	}
	// end shared
	// The streak field, 0..1 about FBM_MEAN (core/scene/cirrus.py cirrus_streaks):
	// on the stretched frame (qa along the stream, qc across), a slow flow warp
	// (0.35 of a unit) curves the streaks, then three octaves. 20 hashes.
	float Streaks(float qa, float qc, uint seed)
	{
		float wa = Perlin2(qa * 0.7 + 3.3, qc * 0.7 + 1.1, seed + 701u);
		float wc = Perlin2(qa * 0.7 + 8.9, qc * 0.7 + 6.2, seed + 719u);
		float a = qa + 0.35 * wa;
		float c = qc + 0.35 * wc;
		float f = 0.5 * Perlin2(a + 1.3, c + 7.1, seed + 101u)
			+ 0.3 * Perlin2(a * 2.1 + 5.7, c * 2.1 + 2.9, seed + 113u)
			+ 0.2 * Perlin2(a * 4.3 + 9.1, c * 4.3 + 4.4, seed + 127u);
		return 0.5 + 0.5 * f;
	}
	// The fine filaments along the stream, 0..1 about 0.5: two octaves, 4x and 8x
	// finer across the stream than along it (cirrus_fibres). 8 hashes.
	float Fibres(float qa, float qc, uint seed)
	{
		return 0.5 + 0.5 * (0.6 * Perlin2(qa * 1.5 + 2.2, qc * 6.0 + 3.7, seed + 211u)
			+ 0.4 * Perlin2(qa * 3.0 + 7.5, qc * 12.0 + 1.9, seed + 223u));
	}
	// A slow along-stream noise whose zero crossings thin a streak to nothing:
	// the feathered ends (cirrus_ends). 4 hashes.
	float Ends(float qa, float qc, uint seed)
	{
		return Perlin2(qa * 0.3 + 4.1, qc * 1.0 + 2.6, seed + 307u);
	}
	float Remap(float v, float lo, float hi)
	{
		return saturate((v - lo) / max(hi - lo, 1e-4));
	}
};
FCirrusNoise N;
// The seeded kilometre frame (the volumetric layer's: the seed's offset, the
// wind's drift), turned onto the streak axis and stretched along it.
float2 kmxy = (WorldPos.xy / 100.0 - WindOffsetM.xy) / 1000.0 + SeedOffsetKm.xy;
float ang = radians(StreakDirDeg);
float2 dir = float2(sin(ang), cos(ang));
float along = dot(kmxy, dir);
float across = kmxy.x * dir.y - kmxy.y * dir.x;
float scale = max(StreakScaleKm, 1e-3);
float qa = along / (scale * max(StreakAspect, 1.0));
float qc = across / scale;
// The quantile cut: the drawn share of the sheet is the cover; the edge is a
// veil's, EdgeSigmas wide.
float field = N.Streaks(qa, qc, NOISE_SEED);
float cover = saturate(Coverage);
float thr = FBM_MEAN + FBM_SIGMA * N.Probit(1.0 - cover);
float soft = FBM_SIGMA * max(EdgeSigmas, 0.1);
float thick = N.Remap(field, thr, thr + soft);
// The filaments modulate the thickness (never add cover); the ends thin it to nothing.
thick *= lerp(1.0 - saturate(FibreStrength), 1.0, N.Fibres(qa, qc, NOISE_SEED));
thick *= smoothstep(0.0, max(FeatherWidth, 1e-3), abs(N.Ends(qa, qc, NOISE_SEED)));
// Opacity: Beer's law on the slant path through the veil, capped so the blue
// reads through everywhere; out at the disc's rim; off as the camera reaches the cap.
float3 toPix = WorldPos - CameraPos;
float3 D = normalize(toPix);                      // camera -> pixel
float slant = 1.0 / max(abs(D.z), 0.15);
float tau = thick * max(OpticalDepth, 0.0) * slant;
float opacity = min(saturate(MaxOpacity), 1.0 - exp(-tau));
float horizKm = length(toPix.xy) / 100000.0;
float rim = 1.0 - smoothstep(RadiusKm * (1.0 - saturate(RimFadeShare)), RadiusKm, horizKm);
float a = opacity * rim * saturate(SheetFade);
// Light: the scattering angle between the sun's light (travelling along -SunDir
// when SunDir points towards the sun; SunDirSign flips a wrong reading) and the
// view ray; the forward lobe makes the veil brightest near the sun.
float3 toSun = normalize(SunDir) * sign(SunDirSign + 1e-6);
float mu = dot(D, toSun);                         // 1: looking through the veil at the sun
float g = clamp(ForwardG, 0.0, 0.95);
float hg = (1.0 - g * g) / pow(max(1.0 + g * g - 2.0 * g * mu, 1e-4), 1.5);
float phase = lerp(1.0, min(hg, max(ForwardCap, 1.0)), saturate(ForwardShare));
float3 L = SunIlluminance * (Albedo / PI_CI) * phase + SkyLum * Albedo * AmbientGain;
return float4(L, a);
