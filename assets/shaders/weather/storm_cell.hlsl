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
//   Ragged     float4  BEAUTY ONLY (0 on every other render: the shader below is then
//                      the measure path's, expression for expression): warp_m (the
//                      wall's noise displacement), base_m (the base's and the
//                      deck's lift, upward only), scale_m (the warp noise's size),
//                      soft_m (the softness of the tower's wall and base and the
//                      deck's base, inward / upward only)
//   Curtain    float4  LANE D, BEAUTY ONLY (0 on every other render: the shader is then
//                      generation 5's, expression for expression): flare (the shaft's
//                      radius grows by this share from the base to the ground), ground_thin
//                      (its density falls by this share toward the ground), scud_depth_m
//                      (the ragged scud band under the base and the deck), scud_cover (0..1)
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
// Visual round 3 (beauty only, storm_cell.ragged_*): the tower's smooth shape
// is a cylinder whose 0.19 /m core is opaque at the first few per cent of its
// 500 m edge, so the 600 m erosion moved the silhouette by tens of metres: a
// hard-walled drum with a flat base. Ragged warps the tower's radius by one
// octave of large-scale value noise and lifts the base (and the deck's)
// unevenly, upward only, and softens the wall, the base and the deck's base
// over soft_m (inward / upward only, so the clearances hold).
// Round 4 (round 3's #09 drew thin white hatched lines and a ribbon): every
// transition must stay smooth on the scale of the constrained GPU's march
// (192 view samples over up to 80 km: ~400 m steps). Round 3's warps were one
// octave x RAGGED_WARP_GAIN 2.5, clamped: flat plateaus (the base exactly at
// 0 or 300 m lift over most of its area) joined by risers up to ~1.5 m per m,
// and a wall warp whose slope reached ~1.1 per m (creases, folds); its edges
// were the measure's 250-500 m ramps at 0.19 /m and the deck's base was eroded
// by a 4-octave noise sharpened 1 / (1 - 0.6) = 2.5x. Hard, flat and thin
// features step-sampled at ~400 m draw as contour lines. Now: gain 2 and no
// clamp (no plateaus, no creases), one 5 km noise for both warps (wall slope
// <= 2 x 1.875 x sqrt 2 x warp / scale ~0.85: never folds; base slope ~0.16),
// soft_m-wide ramps, and the deck's base is not eroded.
// RAGGED_WARP_GAIN = 2 (one octave's 0..1 to -1..1), seeds + 4u / + 5u.
// Evaluated only where they can change the shape (the warp inside the
// tower's reach, the lift below the highest lifted base): the constrained
// GPU's march is not made dearer per sample (the deck's erosion noise is gone).
float rt = r;
float baseCut = base;
float deckLift = 0.0;
float wallSoft = Edge * 2.0;
float baseSoft = Edge;
if (Ragged.x > 0.0)
{
	float scale = max(Ragged.z, 1.0);
	wallSoft = max(Ragged.w, Edge * 2.0);
	baseSoft = max(Ragged.w, Edge);
	if (u < max(base, Layer.y) + Ragged.y + max(Ragged.w, 100.0) + Edge)
	{
		float wb = S.Value(float3(e, n, 0.0) / scale, (uint)Noise.x + 5u);
		baseCut = base + Ragged.y * wb;
		deckLift = Ragged.y * wb;
	}
	if (r < towerR * 1.25 + Ragged.x + Edge * 2.0)
	{
		float wr = 2.0 * (S.Value(float3(e, n, u * 0.5) / scale, (uint)Noise.x + 4u) - 0.5);
		rt = max(r + Ragged.x * wr, 0.0);
	}
}
float f = saturate((u - base) / (top - base));
float radius = towerR * (1.0 - 0.25 * 0.5 + 0.25 * f);
float tower = S.Ss(radius, radius - wallSoft, rt) * S.Ss(baseCut, baseCut + baseSoft, u)
            * S.Ss(top + Edge, top - Edge, u);
if (u > top - Edge && u < top + over)
{
	float h = (u - top) / over;
	float dome = 0.5 * towerR * sqrt(max(0.0, 1.0 - max(h, 0.0) * max(h, 0.0)));
	tower = max(tower, S.Ss(dome, dome - Edge, rt));
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
// Lane D (2026-11-11, beauty only, storm_cell.BEAUTY_CURTAIN; round 4's #09 drew the
// shaft as a glowing cylinder under a hard ring). A precipitation curtain is not a
// cylinder: it hangs from the (lifted, ragged) base, spreads as it falls (flare),
// its edge is the wall's warped radius (rt: no circle) fading over 75 % of the
// radius, and it thins toward the ground (ground_thin) where the rain spreads and
// evaporates; the column's water is kept (density / the flared area's radius share).
float fall = 1.0;
if (Curtain.x > 0.0)
{
	float below = saturate((baseCut - u) / max(baseCut, 1.0));
	float rOut = shaftR * (1.0 + Curtain.x * below);
	shaft = S.Ss(rOut, rOut * 0.25, rt) * S.Ss(baseCut + Edge, baseCut - Edge * 2.0, u);
	fall = (1.0 - Curtain.y * below) / (1.0 + Curtain.x * below);
}
uint seed = (uint)Noise.x;
float billow = Noise.y;
float erosion = Noise.z;
float rise = (tower > 0.0) ? S.Fbm(float3(e, n, u - Noise.w * Time) / billow, seed) : 0.0;
float drift = (anvil > 0.0) ? S.Fbm(float3(e - Drift.x * Time, n - Drift.y * Time, u) / billow, seed + 1u) : 0.0;
// Visual round 6 (beauty only, storm_cell.BEAUTY_SHAFT; round 4's #09 drew the
// shaft as a smooth glowing cylinder): the one curtain fbm the shaft already
// pays for is sampled SHAFT_STREAK_SCALE = 0.35 finer across (its 8x vertical
// stretch kept: vertical streaks), the rim is eroded by it (RIM_EROSION 0.5,
// inward only: never a sample outside the measure's radius) and the density
// floor opens to 0.25. Ragged.x == 0: the measure path's shaft, expression for
// expression. The shaft's albedo is storm_shaft_albedo.hlsl's.
float across = Ragged.x > 0.0 ? billow * 0.35 : billow;
float curtain = (shaft > 0.0) ? S.Fbm(float3(e / across, n / across, u / (billow * 8.0)), seed + 2u) : 0.0;
float shaftDensity = Ragged.x > 0.0
	? S.Eroded(shaft, curtain, 0.5) * (0.25 + 0.75 * curtain)
	: shaft * (0.6 + 0.4 * curtain);
shaftDensity *= fall;
float sigma = Sigma.x * S.Eroded(tower, rise, erosion)
            + Sigma.y * S.Eroded(anvil, drift, erosion)
            + Sigma.z * shaftDensity;
// The look.clouds layer the storm's material also draws (not in the Python twin:
// the layer is the engine default's job when no storm is on the card).
if (Layer.x > 0.0)
{
	// Beauty (Ragged.x > 0): the deck's base lifted unevenly (never below the
	// stated base, so the aircraft's clearance holds) and softened over soft_m,
	// not eroded (round 3's eroded fringe drew as contour lines at the march's
	// step), so it reads as a soft cloud base, not a flat slab. Otherwise the
	// measure path's 100 m band.
	float deckBase = Layer.y + deckLift;
	float deckSoft = Ragged.x > 0.0 ? max(Ragged.w, 100.0) : 100.0;
	float band = S.Ss(deckBase, deckBase + deckSoft, u) * S.Ss(Layer.z, Layer.z - 100.0, u);
	float cover = saturate((S.Fbm(float3(e, n, u * 4.0) / 2000.0, seed + 3u) - (1.0 - Layer.x)) / 0.15);
	sigma += Layer.w * band * cover;
}
// Lane D (beauty only): SCUD -- low, ragged fragments in a band scud_depth_m deep
// under the cell's lifted base (inside the anvil's reach) and under the deck,
// drifting at SCUD_DRIFT_SHARE = 0.5 of the anvil's drift, a 4-octave fbm SCUD_SCALE_M
// = 700 m across squashed SCUD_SQUASH = 3x in height (torn, flat-bottomed
// rags), cut at 0.62 - 0.2 x cover over a 0.08 ramp, SCUD_SIGMA_SHARE = 0.1 of the
// core's extinction. Evaluated only inside the band (one fbm there, none elsewhere).
if (Curtain.z > 0.0)
{
	float deckBase = Layer.x > 0.0 ? Layer.y + deckLift : 1.0e9;
	float scudTop = r < Geo2.x ? min(baseCut, deckBase) : deckBase;
	if (u < scudTop && u > scudTop - Curtain.z)
	{
		float band = S.Ss(scudTop - Curtain.z, scudTop - Curtain.z * 0.4, u) * S.Ss(scudTop, scudTop - 60.0, u);
		float3 q = float3(e - 0.5 * Drift.x * Time, n - 0.5 * Drift.y * Time, u * 3.0) / 700.0;
		float rag = saturate((S.Fbm(q, seed + 7u) - (0.62 - 0.2 * Curtain.w)) / 0.08);
		sigma += Sigma.x * 0.1 * band * rag;
	}
}
return sigma;
