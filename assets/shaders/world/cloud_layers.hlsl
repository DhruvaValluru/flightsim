// M_FlightSimCloudLayers' extinction (1/m x ExtinctionScale): the Custom node body
// scripts/ue_create_materials.py (world lane block) pastes into the beauty cloud
// material. Visual overhaul, world lane, 2026-11-09. BEAUTY ONLY: only
// FFlightSimWorldBeauty (FlightSimClouds.cpp, -quality=beauty) puts this material
// on a cloud. Every shape number arrives as a parameter from the table in
// core/scene/world_beauty.py CLOUDS (UNCALIBRATED: set by probe render on the
// render machine); nothing in this file is a look value except the octave
// weights and lacunarities of the noise below and the three shaping constants
// (TOP_CUT_SIGMAS, EROSION_CUT_SHARE, WISP_HEIGHT), each UNCALIBRATED and
// pinned equal to world_beauty.py by tests/test_world_beauty.py. FBM_MEAN and
// FBM_SIGMA are the shape noise's own moments (core/scene/world_beauty.py
// CLOUD_FBM_MEAN / CLOUD_FBM_SIGMA, measured on its Python replica
// cloud_shape; tests/test_world_beauty.py re-measures them).
//
// Round 2 (clouds-sky, 2026-11-09), after the first real renders: shot d's
// clouds were smeared paint. The 4-octave VALUE noise (blobby, boxy) with the
// vertical profile multiplied in drew vertical smears; it is now a
// Perlin-Worley shape (Schneider 2015/2017, Horizon Zero Dawn's Nubis): a
// gradient-noise fbm dilated by inverted Worley cells, cut again by a Worley
// fbm, so the cells read as billows. The top is ROUNDED by raising the cut
// with height (domes, flat bases) instead of fading the density; the edges are
// eroded by a 3-octave Worley fbm, wispy at the base and billowy above. No
// texture: every value is a hashed integer lattice (no tile, no repeat), and
// the erosion runs only inside the cloud (a branch, half the cost in clear air).
//
// Inputs (the Custom node's, named exactly so; the script's WORLD_CLOUD_INPUTS):
//   WorldPos         float3  the sample's absolute world position, cm
//   NormAlt          float   0 at the layer's base, 1 at its top (Cloud Sample Attributes)
//   Coverage         float   the layer's cover, 0..1
//   ExtinctionPerM   float   a full cell's extinction, 1/m
//   ExtinctionScale  float   the engine-unit factor (the WX.4-style probe sets it)
//   ShapeScaleKm     float   the base shape's feature size
//   DetailScaleKm    float   the erosion noise's feature size
//   DetailErosion    float   how much the detail eats the edges, 0..1
//   BottomSoftness   float   share of the thickness the base fades over
//   TopRounding      float   share of the thickness the top rounds over
//   CoverageContrast float   how hard the coverage threshold cuts (the edge is FBM_SIGMA / contrast wide)
//   SeedOffsetKm     float3  the card's seeded noise offset (world_beauty.cloud_seed_offset_km)
//   WindOffsetM      float3  the drift since t = 0, engine metres (the scene's drift law)
const float FBM_MEAN = 0.779;
const float FBM_SIGMA = 0.05;
const float TOP_CUT_SIGMAS = 3.5;
const float EROSION_CUT_SHARE = 0.5;
const float WISP_HEIGHT = 0.25;
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
	// Four octaves of gradient noise, weights 1/2..1/16 renormalised, mapped to 0..1.
	float PerlinFbm(float3 p, uint seed)
	{
		float sum = 0.0;
		float amp = 0.5;
		for (int o = 0; o < 4; ++o)
		{
			sum += amp * Perlin(p, seed + (uint)o * 101u);
			p = p * 2.03 + float3(17.1, 31.7, 7.3);
			amp *= 0.5;
		}
		return saturate(0.5 + 0.5 * sum / 0.9375);
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
					float3 f = float3(ix + dx, iy + dy, iz + dz)
						+ float3(h & 1023u, (h >> 10u) & 1023u, (h >> 20u) & 1023u) / 1024.0;
					float3 d = f - p;
					best = min(best, dot(d, d));
				}
			}
		}
		return 1.0 - min(sqrt(best), 1.0);
	}
	float Remap(float v, float lo, float hi)
	{
		return saturate((v - lo) / max(hi - lo, 1e-4));
	}
	// The Perlin-Worley shape: perlin dilated by a Worley cell, then cut by a
	// two-octave Worley fbm (world_beauty.cloud_shape).
	float Shape(float3 p, uint seed)
	{
		float perlin = PerlinFbm(p, seed);
		float cells = Worley(p, seed + 211u);
		float pw = Remap(perlin, cells - 1.0, 1.0);
		float fbm = 0.75 * Worley(p * 2.03, seed + 307u) + 0.25 * Worley(p * 4.1, seed + 401u);
		return Remap(pw, fbm - 1.0, 1.0);
	}
	// The erosion noise: a three-octave Worley fbm (world_beauty.cloud_detail).
	float Detail(float3 p, uint seed)
	{
		return 0.625 * Worley(p, seed) + 0.25 * Worley(p * 2.03, seed + 97u)
			+ 0.125 * Worley(p * 4.1, seed + 193u);
	}
};
FWorldCloud C;
// Kilometres, offset by the seed and carried by the wind (horizontal only).
float3 km = (WorldPos / 100.0 - WindOffsetM) / 1000.0 + SeedOffsetKm;
float h = saturate(NormAlt);
// The base fades over BottomSoftness (a soft, nearly flat base); the top
// ROUNDS: over TopRounding the cut rises to TOP_CUT_SIGMAS above the mean, so
// only a cell's core reaches the top (domes, not a density fade).
float base = smoothstep(0.0, max(BottomSoftness, 1e-3), h);
float top = 1.0 - smoothstep(1.0 - max(TopRounding, 1e-3), 1.0, h);
// The base shape: horizontal features of ShapeScaleKm, vertical ones half as
// tall (towers are taller than wide only at cumulus scales).
float shape = C.Shape(float3(km.x, km.y, km.z * 2.0) / max(ShapeScaleKm, 1e-3), 7u);
// Coverage: the shape kept above the noise's (1 - cover) QUANTILE, so the drawn
// share of sky is the stated cover; the soft edge (FBM_SIGMA / contrast wide)
// starts EROSION_CUT_SHARE x DetailErosion of its width early, which the
// erosion below takes back on average.
float cover = saturate(Coverage);
float soft = FBM_SIGMA / max(CoverageContrast, 1e-3);
float thr = FBM_MEAN + FBM_SIGMA * C.Probit(1.0 - cover) - EROSION_CUT_SHARE * DetailErosion * soft;
float cut = lerp(FBM_MEAN + TOP_CUT_SIGMAS * FBM_SIGMA, thr, top);
float density = C.Remap(shape, cut, cut + soft);
[branch]
if (density > 0.0)
{
	// Erosion by the detail noise: wispy (the noise) under WISP_HEIGHT of the
	// layer, billowy (its inverse) above; a full core is never eroded.
	float detail = C.Detail(km / max(DetailScaleKm, 1e-3), 13u);
	float wisp = lerp(detail, 1.0 - detail, saturate(h / WISP_HEIGHT));
	density = C.Remap(density, DetailErosion * wisp, 1.0);
}
return density * base * ExtinctionPerM * ExtinctionScale;
