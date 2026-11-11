// M_FlightSimDistantClouds: the 2D distant cloud sheet (visual round 5, lane L3,
// 2026-11-10). The Custom node body scripts/ue_create_materials.py
// (create_world_distant_clouds) pastes into an UNLIT, TRANSLUCENT, two-sided
// material on one large earth-curved disc at the cloud layer's altitude
// (FlightSimClouds.cpp ApplyDistantClouds; Python twin core/scene/world_beauty.py
// DISTANT_*). BEAUTY ONLY: the disc is in BeautyOnlyActors (hidden on every
// label capture), writes no depth and no custom depth, casts no shadow.
//
// Why: round 3's clear and weather frames (#03, #06, #09, #13) drew thin,
// streaky volumetric clouds that ended a few tens of kilometres out and an
// EMPTY horizon; the engine's own sky-sphere panning clouds would cover the
// SkyAtmosphere. This sheet draws the far deck and the horizon with ZERO
// march cost: one shape evaluation per covered pixel (the SAME weather-field
// shape as cloud_layers.hlsl at the layer's mid-altitude slice, the SAME
// quantile cut, so the far sheet continues the near volumetric cells), and
// the normal comes from the shape's screen-space derivatives (ddx/ddy), not
// from more samples. Its lighting is faked cheaply: N.L from that normal with
// a wrap term, the sun's illuminance and the sky's distant scattered
// luminance from the SkyAtmosphere nodes, dark bases seen from below, a
// sun-coloured silver lining on the thin edges when the sun is behind the
// cloud. The material has Apply Fogging per pixel, so the height fog and the
// aerial perspective fade it into the horizon haze.
//
// Every look value here arrives as a parameter from world_beauty.DISTANT_LOOK
// (UNCALIBRATED: set by probe render on the render machine); the noise
// constants are cloud_layers.hlsl's (FBM_MEAN, FBM_SIGMA: the shape noise's own
// moments, pinned by tests/test_world_beauty.py; the shared noise struct is
// pinned text-equal by tests/test_distant_clouds.py).
//
// Inputs (the Custom node's, named exactly so; the script's WORLD_DISTANT_INPUTS):
//   WorldPos         float3  the pixel's absolute world position, cm
//   CameraPos        float3  the camera's absolute world position, cm
//   SunDir           float3  the atmosphere light's direction towards the sun (SkyAtmosphereLightDirection)
//   SunIlluminance   float3  the sun's illuminance at the pixel through the atmosphere (SkyAtmosphereLightIlluminance)
//   SkyLum           float3  the sky's distant scattered luminance (SkyAtmosphereDistantLightScatteredLuminance)
//   Coverage         float   the layer's cover, 0..1 (the volumetric layer's)
//   CoverageContrast float   the shape row's cut hardness (the edge is FBM_SIGMA / contrast wide)
//   ShapeScaleKm     float   the shape row's feature size
//   SliceKm          float   the noise's z: the layer's mid altitude in km plus the seed's z offset
//   ThicknessKm      float   the layer's thickness, km (the relief's height)
//   HandoverKm       float   the sheet is clear nearer than this (the volumetric march draws there)
//   FadeKm           float   the sheet fades in over this past HandoverKm
//   RadiusKm         float   the disc's radius
//   RimFadeShare     float   the sheet fades out over this share of the radius at the rim
//   Albedo           float   the cloud's albedo
//   AmbientGain      float   x the sky's distant scattered luminance
//   SunWrap          float   the N.L wrap (multiple scattering stand-in)
//   BaseDarkening    float   a base's light as a share of a top's ambient
//   BaseSunShare     float   the sun's share reaching a base (through the thin parts)
//   SilverLining     float   the thin edge's forward-scattered sun gain
//   RimPower         float   the forward lobe's exponent
//   NormalStrength   float   the relief's slope per unit shape per km of thickness
//   SheetFade        float   per frame: 0 with the camera inside the layer, 1 clear of it
//   SeedOffsetKm     float3  the card's seeded noise offset (world_beauty.cloud_seed_offset_km)
//   WindOffsetM      float3  the drift since t = 0, engine metres (the scene's drift law)
const float FBM_MEAN = 0.55;
const float FBM_SIGMA = 0.069;
const float PI_DC = 3.14159265;
// shared: world cloud noise (cloud_layers.hlsl FWorldCloud, text-equal)
struct FWorldCloud
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
	float Perlin(float3 p, uint seed)
	{
		float3 i = floor(p);
		int ix = (int)i.x; int iy = (int)i.y; int iz = (int)i.z;
		float fx = p.x - i.x; float fy = p.y - i.y; float fz = p.z - i.z;
		float u = Fade(fx); float v = Fade(fy); float w = Fade(fz);
		float g000 = Grad(Hash3(ix, iy, iz, seed), fx, fy, fz);
		float g100 = Grad(Hash3(ix + 1, iy, iz, seed), fx - 1.0, fy, fz);
		float g010 = Grad(Hash3(ix, iy + 1, iz, seed), fx, fy - 1.0, fz);
		float g110 = Grad(Hash3(ix + 1, iy + 1, iz, seed), fx - 1.0, fy - 1.0, fz);
		float g001 = Grad(Hash3(ix, iy, iz + 1, seed), fx, fy, fz - 1.0);
		float g101 = Grad(Hash3(ix + 1, iy, iz + 1, seed), fx - 1.0, fy, fz - 1.0);
		float g011 = Grad(Hash3(ix, iy + 1, iz + 1, seed), fx, fy - 1.0, fz - 1.0);
		float g111 = Grad(Hash3(ix + 1, iy + 1, iz + 1, seed), fx - 1.0, fy - 1.0, fz - 1.0);
		return lerp(lerp(lerp(g000, g100, u), lerp(g010, g110, u), v),
		            lerp(lerp(g001, g101, u), lerp(g011, g111, u), v), w);
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
	// Inverted cellular noise: 1 at a feature point, 0 a cell away (F1, 27 cells).
	float Worley(float3 p, uint seed)
	{
		float3 i = floor(p);
		int ix = (int)i.x; int iy = (int)i.y; int iz = (int)i.z;
		float best = 9.0;
		for (int dz = -1; dz <= 1; ++dz)
		{
			for (int dy = -1; dy <= 1; ++dy)
			{
				for (int dx = -1; dx <= 1; ++dx)
				{
					uint h = Hash3(ix + dx, iy + dy, iz + dz, seed);
					float3 f = float3((float)(ix + dx), (float)(iy + dy), (float)(iz + dz))
						+ float3((float)(h & 1023u), (float)((h >> 10u) & 1023u), (float)((h >> 20u) & 1023u)) / 1024.0;
					float3 d = f - p;
					best = min(best, dot(d, d));
				}
			}
		}
		return 1.0 - min(sqrt(best), 1.0);
	}
	// The same on the plane (9 cells), ROUNDED (round 10): the nearest
	// distances are blended by a polynomial smooth minimum (width 0.35 cell),
	// so two cells meet in a soft saddle instead of a Voronoi crease (the
	// flat-sided, faceted cells of round 10's #13).
	float SmoothWorley2(float x, float y, uint seed)
	{
		float ix = floor(x); float iy = floor(y);
		int cx = (int)ix; int cy = (int)iy;
		float d = 9.0;
		for (int dy = -1; dy <= 1; ++dy)
		{
			for (int dx = -1; dx <= 1; ++dx)
			{
				uint h = Hash3(cx + dx, cy + dy, 0, seed);
				float ex = (float)(cx + dx) + (float)(h & 1023u) / 1024.0 - x;
				float ey = (float)(cy + dy) + (float)((h >> 10u) & 1023u) / 1024.0 - y;
				float e = sqrt(ex * ex + ey * ey);
				float k = max(0.35 - max(d - e, e - d), 0.0) / 0.35;
				d = min(d, e) - k * k * 0.35 * 0.25;
			}
		}
		return 1.0 - min(max(d, 0.0), 1.0);
	}
	float Remap(float v, float lo, float hi)
	{
		return saturate((v - lo) / max(hi - lo, 1e-4));
	}
	// The weather field (round 7, reworked round 10; world_beauty.cloud_shape).
	// Round 10's #13 drew cubist cauliflower in rows: Voronoi creases, three
	// axis-aligned lattices that lined up into rows, and one size class. Now:
	//   warp:    the plane is displaced by a pair of gradient noises (0.45
	//            cell), so no cell edge is straight and no lattice row survives;
	//   cluster: two octaves of plane gradient noise at ~6x the cell size
	//            (unwarped): the fields and the clear gaps between them;
	//   cells:   ROUNDED Worley at 2.4x, 1x and 0.46x the cell size, the two
	//            smaller lattices rotated 35 and 78.5 degrees, weighted to the
	//            large one (a few big cumulus, many small);
	//   billow:  one octave of 3D gradient noise (bulging sides).
	// Far is the level of detail (0 near, 1 far): the small cells and the
	// billow fade to their means (0.5985, 0.5) and are skipped at 1, so the far
	// field is smoother and cheaper and keeps the same mean and nearly the same
	// spread (the cut, hence the cover, stays the stated one).
	float ShapeLod(float3 p, float far, uint seed)
	{
		float wx = Perlin2(p.x * 0.6 + 1.7, p.y * 0.6 + 9.2, seed + 601u);
		float wy = Perlin2(p.x * 0.6 + 13.1, p.y * 0.6 + 2.3, seed + 613u);
		float qx = p.x + 0.45 * wx;
		float qy = p.y + 0.45 * wy;
		float cluster = 0.5 + 0.5 * (0.667 * Perlin2(p.x * 0.17 + 3.1, p.y * 0.17 + 7.9, seed + 503u)
			+ 0.333 * Perlin2(p.x * 0.35 + 11.3, p.y * 0.35 + 5.1, seed + 557u));
		float big = SmoothWorley2(qx * 0.42 + 2.9, qy * 0.42 + 8.3, seed + 401u);
		float mid = SmoothWorley2(0.8191 * qx - 0.5736 * qy, 0.5736 * qx + 0.8191 * qy, seed + 211u);
		float small = 0.5985;
		float billow = 0.5;
		if (far < 1.0)
		{
			float bx = 0.1994 * qx - 0.9799 * qy;
			float by = 0.9799 * qx + 0.1994 * qy;
			small = lerp(SmoothWorley2(bx * 2.17 + 5.3, by * 2.17 + 1.7, seed + 307u), 0.5985, far);
			billow = lerp(0.5 + 0.5 * Perlin(float3(qx * 1.9, qy * 1.9, p.z * 1.9), seed), 0.5, far);
		}
		float cells = 0.55 * big + 0.3 * mid + 0.15 * small;
		return 0.42 * cluster + 0.5 * cells + 0.08 * billow;
	}
	float Shape(float3 p, uint seed)
	{
		return ShapeLod(p, 0.0, seed);
	}
	// The erosion noise: a two-octave Worley fbm (world_beauty.cloud_detail).
	float Detail(float3 p, uint seed)
	{
		return 0.7 * Worley(p, seed) + 0.3 * Worley(p * 2.03, seed + 97u);
	}
};
// end shared
FWorldCloud C;
// The same kilometre frame as the volumetric layer: the seed's offset, the
// wind's drift (horizontal), and the layer's mid-altitude slice for z (the
// volumetric shader stretches z by 2: so does this, on the same number).
float2 kmxy = (WorldPos.xy / 100.0 - WindOffsetM.xy) / 1000.0 + SeedOffsetKm.xy;
// The volumetric layer's far level of detail (far = 1): the same plane field
// it draws past its LOD_FAR_KM, so the hand-over shows no change of texture.
float shape = C.ShapeLod(float3(kmxy.x, kmxy.y, SliceKm * 2.0) / max(ShapeScaleKm, 1e-3), 1.0, 7u);
// The quantile cut (cloud_layers.hlsl's law): the drawn share of sky is the cover.
float cover = saturate(Coverage);
float soft = FBM_SIGMA / max(CoverageContrast, 1e-3) * 2.0;   // the volumetric far edge (1 + FAR_SOFTEN)
float thr = FBM_MEAN + FBM_SIGMA * C.Probit(1.0 - cover);
float density = C.Remap(shape, thr, thr + soft);
// A thickness proxy: 0 at the edge, 1 a few soft widths inside (the relief
// and the silver lining read it).
float thick = C.Remap(shape, thr, thr + 4.0 * soft);
// The relief's normal from the screen-space derivatives of the thickness
// (free: no second sample). Solve J grad = (ddx, ddy), J the 2x2 of the km
// frame's screen derivatives; the slope is clamped so a grazing row's
// vanishing J cannot blow up.
float2 gx = float2(ddx(kmxy.x), ddx(kmxy.y));
float2 gy = float2(ddy(kmxy.x), ddy(kmxy.y));
float dX = ddx(thick);
float dY = ddy(thick);
float det = gx.x * gy.y - gx.y * gy.x;
float2 grad = abs(det) > 1e-12 ? float2(gy.y * dX - gx.y * dY, -gy.x * dX + gx.x * dY) / det : float2(0.0, 0.0);
float slopeScale = NormalStrength * max(ThicknessKm, 0.05);
float2 slope = -grad * slopeScale;
slope /= max(1.0, length(slope) / 4.0);
float3 V = normalize(CameraPos - WorldPos);
bool fromAbove = CameraPos.z > WorldPos.z;
// Tops bulge up (seen from above), bases hang down (seen from below).
float3 n = normalize(float3(slope, fromAbove ? 1.0 : -1.0));
float ndl = dot(n, SunDir);
float wrap = saturate((ndl + SunWrap) / (1.0 + SunWrap));
float3 sunLambert = SunIlluminance * (Albedo / PI_DC);
float3 ambient = SkyLum * Albedo * AmbientGain;
// The silver lining: the thin edge forward-scatters the sun when it stands
// behind the cloud (the view ray and the sun's direction nearly aligned).
float edge = 1.0 - thick;
float fwd = pow(saturate(dot(V, SunDir)), max(RimPower, 1.0));
float3 lining = sunLambert * SilverLining * edge * fwd;
float3 L;
if (fromAbove)
{
	// Sunlit tops: N.L, the sky's ambient, a little lining on the edges.
	L = sunLambert * wrap + ambient + 0.5 * lining;
}
else
{
	// Bases: mostly the sky's ambient darkened, the sun through the thin
	// parts, the lining when backlit.
	L = ambient * BaseDarkening + sunLambert * BaseSunShare * saturate(SunDir.z) * (1.0 - 0.5 * thick) + lining;
}
// Opacity: the density, boosted at grazing angles as the slant path through a
// sheet of this thickness (Beer along 1 / |cos|), faded in past the volumetric
// march's hand-over, out at the disc's rim, and off with the camera inside the layer.
float3 toPix = WorldPos - CameraPos;
float distKm = length(toPix) / 100000.0;
float horizKm = length(toPix.xy) / 100000.0;
float slant = 1.0 / max(abs(V.z), 0.1);
float opacity = 1.0 - pow(saturate(1.0 - density), slant);
float fadeIn = smoothstep(HandoverKm, HandoverKm + max(FadeKm, 1e-3), distKm);
float rim = 1.0 - smoothstep(RadiusKm * (1.0 - saturate(RimFadeShare)), RadiusKm, horizKm);
float a = opacity * fadeIn * rim * saturate(SheetFade);
return float4(L, a);
