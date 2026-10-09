// M_StormCell's extinction (1/m): the Custom node body scripts/ue_create_materials.py
// pastes into the volumetric cloud material. The twin of core/scene/storm_cell.py
// extinction_at, constant for constant (tests/test_weather.py pins the constants).
//
// Inputs (the Custom node's, named exactly so):
//   Rel        float3  the sample's engine position minus the cell centre, cm
//   EastAxis   float3  the engine direction of local east (unit, measured by the host)
//   NorthAxis  float3  the engine direction of local north
//   Geo1       float4  base_m, top_m, overshoot_m, tower_radius_m
//   Geo2       float4  anvil_radius_m, anvil_bottom_m, anvil_offset east, north (m)
//   Sigma      float4  extinction core, anvil, shaft (1/m), shaft radius (m)
//   Noise      float4  seed, billow_m, erosion, updraft_mps
//   Drift      float4  anvil drift east, north (m/s), unused, unused
//   Layer      float4  look.clouds cover (0..1), base_m, top_m, extinction (1/m)
//   Time       float   run time, s
struct FStormCell
{
	uint Pcg(uint v)
	{
		uint state = v * 747796405u + 2891336453u;
		uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
		return (word >> 22u) ^ word;
	}
	float Ss(float e0, float e1, float x)
	{
		if (e0 == e1) { return x < e0 ? 0.0 : 1.0; }
		float t = saturate((x - e0) / (e1 - e0));
		return t * t * (3.0 - 2.0 * t);
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
		float x00 = Lattice(ix, iy, iz, seed) + (Lattice(ix + 1, iy, iz, seed) - Lattice(ix, iy, iz, seed)) * fx;
		float x10 = Lattice(ix, iy + 1, iz, seed) + (Lattice(ix + 1, iy + 1, iz, seed) - Lattice(ix, iy + 1, iz, seed)) * fx;
		float x01 = Lattice(ix, iy, iz + 1, seed) + (Lattice(ix + 1, iy, iz + 1, seed) - Lattice(ix, iy, iz + 1, seed)) * fx;
		float x11 = Lattice(ix, iy + 1, iz + 1, seed) + (Lattice(ix + 1, iy + 1, iz + 1, seed) - Lattice(ix, iy + 1, iz + 1, seed)) * fx;
		float y0 = x00 + (x10 - x00) * fy;
		float y1 = x01 + (x11 - x01) * fy;
		return y0 + (y1 - y0) * fz;
	}
	// NOISE_OCTAVES = 4, NOISE_GAIN = 0.5, NOISE_LACUNARITY = 2.03
	float Fbm(float3 p, uint seed)
	{
		float total = 0.0; float amp = 1.0; float norm = 0.0; float freq = 1.0;
		[unroll] for (int k = 0; k < 4; ++k)
		{
			total += amp * Value(p * freq, seed);
			norm += amp;
			amp *= 0.5;
			freq *= 2.03;
		}
		return total / norm;
	}
	float Eroded(float shape, float value, float erosion)
	{
		return saturate((shape - (1.0 - value) * erosion) / (1.0 - erosion));
	}
};
FStormCell S;
// EDGE_M = 250, TOWER_FLARE = 0.25, OVERSHOOT_RADIUS_FRACTION = 0.5, SHAFT_NOISE_STRETCH = 8
const float Edge = 250.0;
float e = dot(Rel, EastAxis) / 100.0;
float n = dot(Rel, NorthAxis) / 100.0;
float u = Rel.z / 100.0;
float base = Geo1.x; float top = Geo1.y; float over = Geo1.z; float towerR = Geo1.w;
float r = sqrt(e * e + n * n);
float f = saturate((u - base) / (top - base));
float radius = towerR * (1.0 - 0.25 * 0.5 + 0.25 * f);
float tower = S.Ss(radius, radius - Edge * 2.0, r) * S.Ss(base, base + Edge, u)
            * S.Ss(top + Edge, top - Edge, u);
if (u > top - Edge && u < top + over)
{
	float h = (u - top) / over;
	float dome = 0.5 * towerR * sqrt(max(0.0, 1.0 - max(h, 0.0) * max(h, 0.0)));
	tower = max(tower, S.Ss(dome, dome - Edge, r));
}
float bottom = Geo2.y;
float lift = saturate((u - bottom) / (top - bottom));
float ra = length(float2(e - Geo2.z * lift, n - Geo2.w * lift));
float anvilR = Geo2.x;
float anvilFloor = bottom + (top - bottom) * 0.6 * (ra / anvilR) * (ra / anvilR);
float anvil = S.Ss(anvilR, anvilR - Edge * 4.0, ra) * S.Ss(anvilFloor, anvilFloor + Edge, u)
            * S.Ss(top + Edge, top - Edge, u);
float shaftR = Sigma.w;
float shaft = S.Ss(shaftR, shaftR * 0.6, r) * S.Ss(base + Edge * 0.5, base - Edge * 0.5, u);
uint seed = (uint)Noise.x;
float billow = Noise.y;
float erosion = Noise.z;
float rise = (tower > 0.0) ? S.Fbm(float3(e, n, u - Noise.w * Time) / billow, seed) : 0.0;
float drift = (anvil > 0.0) ? S.Fbm(float3(e - Drift.x * Time, n - Drift.y * Time, u) / billow, seed + 1u) : 0.0;
float curtain = (shaft > 0.0) ? S.Fbm(float3(e / billow, n / billow, u / (billow * 8.0)), seed + 2u) : 0.0;
float sigma = Sigma.x * S.Eroded(tower, rise, erosion)
            + Sigma.y * S.Eroded(anvil, drift, erosion)
            + Sigma.z * shaft * (0.6 + 0.4 * curtain);
// The look.clouds layer the storm's material also draws (not in the Python twin:
// the layer is the engine default's job when no storm is on the card).
if (Layer.x > 0.0)
{
	float band = S.Ss(Layer.y, Layer.y + 100.0, u) * S.Ss(Layer.z, Layer.z - 100.0, u);
	float cover = saturate((S.Fbm(float3(e, n, u * 4.0) / 2000.0, seed + 3u) - (1.0 - Layer.x)) / 0.15);
	sigma += Layer.w * band * cover;
}
return sigma;
