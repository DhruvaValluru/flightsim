// M_FlightSimCloudLayers' extinction (1/m x ExtinctionScale): the Custom node body
// scripts/ue_create_materials.py (world lane block) pastes into the beauty cloud
// material. Visual overhaul, world lane, 2026-11-09. BEAUTY ONLY: only
// FFlightSimWorldBeauty (FlightSimClouds.cpp, -quality=beauty) puts this material
// on a cloud. Every shape number arrives as a parameter from the table in
// core/scene/world_beauty.py CLOUDS (UNCALIBRATED: set by probe render on the
// render machine); nothing in this file is a look value except the octave
// weights of the noise below.
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
//   CoverageContrast float   how hard the coverage threshold cuts
//   SeedOffsetKm     float3  the card's seeded noise offset (world_beauty.cloud_seed_offset_km)
//   WindOffsetM      float3  the drift since t = 0, engine metres (the scene's drift law)
struct FWorldCloud
{
	uint Pcg(uint v)
	{
		uint state = v * 747796405u + 2891336453u;
		uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
		return (word >> 22u) ^ word;
	}
	float Fade(float t) { return t * t * t * (t * (t * 6.0 - 15.0) + 10.0); }
	float Lattice(int ix, int iy, int iz, uint seed)
	{
		uint h = Pcg(asuint(iz) + seed);
		h = Pcg(asuint(iy) + h);
		h = Pcg(asuint(ix) + h);
		return h / 4294967296.0;
	}
	float Value(float3 p, uint seed)
	{
		float3 i = floor(p);
		int ix = (int)i.x; int iy = (int)i.y; int iz = (int)i.z;
		float fx = Fade(p.x - i.x); float fy = Fade(p.y - i.y); float fz = Fade(p.z - i.z);
		float x00 = lerp(Lattice(ix, iy, iz, seed), Lattice(ix + 1, iy, iz, seed), fx);
		float x10 = lerp(Lattice(ix, iy + 1, iz, seed), Lattice(ix + 1, iy + 1, iz, seed), fx);
		float x01 = lerp(Lattice(ix, iy, iz + 1, seed), Lattice(ix + 1, iy, iz + 1, seed), fx);
		float x11 = lerp(Lattice(ix, iy + 1, iz + 1, seed), Lattice(ix + 1, iy + 1, iz + 1, seed), fx);
		return lerp(lerp(x00, x10, fy), lerp(x01, x11, fy), fz);
	}
	// Four octaves, weights 1/2, 1/4, 1/8, 1/16 renormalised to 0..1.
	float Fbm(float3 p, uint seed)
	{
		float sum = 0.0;
		float amp = 0.5;
		for (int o = 0; o < 4; ++o)
		{
			sum += amp * Value(p, seed + (uint)o * 101u);
			p = p * 2.03 + float3(17.1, 31.7, 7.3);
			amp *= 0.5;
		}
		return sum / 0.9375;
	}
	float Remap(float v, float lo, float hi)
	{
		return saturate((v - lo) / max(hi - lo, 1e-4));
	}
};
FWorldCloud C;
// Kilometres, offset by the seed and carried by the wind (horizontal only).
float3 km = (WorldPos / 100.0 - WindOffsetM) / 1000.0 + SeedOffsetKm;
float h = saturate(NormAlt);
// The vertical profile: a soft base, a rounded top (cumulus rounds high,
// stratiform decks are flat).
float base = smoothstep(0.0, max(BottomSoftness, 1e-3), h);
float top = 1.0 - smoothstep(1.0 - max(TopRounding, 1e-3), 1.0, h);
float profile = base * top;
// The base shape: horizontal features of ShapeScaleKm, stretched vertically
// less (towers are taller than wide only at cumulus scales).
float shape = C.Fbm(float3(km.x, km.y, km.z * 2.0) / max(ShapeScaleKm, 1e-3), 7u);
// Coverage: the shape kept where it beats 1 - cover, hardened by the contrast.
float cover = saturate(Coverage);
float density = C.Remap(shape * profile, 1.0 - cover, 1.0 - cover + 1.0 / max(CoverageContrast, 1e-3));
// Erosion by the detail noise, strongest at the cell's edges.
float detail = C.Fbm(km / max(DetailScaleKm, 1e-3), 13u);
density = C.Remap(density, DetailErosion * (1.0 - detail) * (1.0 - density), 1.0);
return density * ExtinctionPerM * ExtinctionScale;
