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
// Round 7 (visual push lane E, 2026-11-11), after round 4's #03, #04, #12,
// #13: the fair cumulus still read as smeared brush strokes and #13's field
// as a uniform carpet. The 3D Perlin-Worley shape had ONE cell size (2.5 km
// Worley cells, all alike) and varied as much with height as across, so the
// march sliced 3D blobs into streaks. The shape is now a Nubis-style WEATHER
// FIELD on the plane (FWorldCloud::Shape): a cluster term (fields and clear
// gaps tens of km across), three Worley scales (clouds of many sizes) and a
// single 3D octave (bulging sides). A column whose footprint clears the cut
// stands on the layer's flat base and rises until the cut (raised with
// height over TopRounding) catches it, so big clouds tower and small ones
// stay low domes. It is also CHEAPER per sample on the constrained GPU (43
// lattice hashes for the shape, 54 for the in-cloud erosion, against 113 and
// 81), which pays for the shorter shadow march that gives the cells their
// self-shadowed, darker bases (world_beauty.cloud_shadow_tracing_km_for).
//
// Round 52 (2026-11-11), after round 51's #04, #12 and #13: the cumulus bases
// and sides were sliced into flat horizontal tiers with straight edges. The
// view march is blue-noise jittered (round 6) but the engine's SHADOW march
// is not (VolumetricCloud.usf: ShadowJitterNorm = 0.5, "Disabled jittering"):
// on the constrained GPU it is 10 quadratic samples over 6 km, segments of
// 60 m to 1.1 km, and at 0.05 /m each segment is opaque (optical depth 3 to
// 57). The sun's transmittance at a point is a product of on/off steps, one
// per shadow sample, each switching where that FIXED offset towards the sun
// crosses the cloud's surface; on a field that is mostly a plane pattern cut
// by a height-only threshold those crossings are iso-altitude lines, the same
// on every cloud and every capture, so TSR has nothing to average. Fix (no
// sample added): a SHADOW sample (the engine's ShadowSampleDistance > 0) is
// the average over its segment's footprint (ShadowFootprintKm x sqrt of its
// distance, the quadratic march's segment length; FlightSimClouds.cpp sets it
// from the march, 0 = round 51): the sample point is dithered over the
// footprint (round 61: by interleaved gradient noise of the pixel and the
// capture, stratified along the ray: see below; round 52 hashed the position
// and white noise drew r58's grain), the soft edge widens by the footprint, and a sample whose footprint is
// wider than the erosion noise reads the noise at its mean (cheaper: it would
// average away).
// A view sample (ShadowDist 0) is unchanged. The second half: the plane field
// made every cell an extrusion with vertical walls, which the march lit in
// tiers; its warp now grows with height (SideBulge, ShapeLodBulge: no hash
// added), so the walls lean and bulge. -look-cloud-tiers=off sets both to 0.
//
// Inputs (the Custom node's, named exactly so; the script's WORLD_CLOUD_INPUTS):
//   WorldPos         float3  the sample's absolute world position, cm
//   NormAlt          float   0 at the layer's base, 1 at its top (Cloud Sample Attributes)
//   CameraPos        float3  the camera's absolute world position, cm (the far field's level of detail)
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
//   ShadowDist       float   the shadow sample's distance from its view sample, cm; 0 for a view sample (Cloud Sample Attributes)
//   ShadowFootprintKm float  a shadow sample's footprint per sqrt(km) of distance; 0 = the round-51 march (round 52)
//   LayerThicknessKm float   the layer's thickness, km (the footprint's share of NormAlt)
//   SideBulge        float   the sides' bulge, cells (round 52; 0 = round 51's vertical walls)
//   FarFadeStartKm   float   the distant sheet's hand-over: the march fades out from here (round 61)
//   FarFadeKm        float   over this; 0 = no fade (no sheet drawn, or the switch off)
//   HeightDensity    float   round 82: the base's density deficit, 0..1 (density x lerp(1 - it, 1,
//                            smoothstep(0, HEIGHT_DENSITY_RISE, h))); 0 = round 81
// and the engine's Parameters.SvPosition and View.StateFrameIndexMod8 (the dither's pixel and capture).
const float FBM_MEAN = 0.55;
const float FBM_SIGMA = 0.069;
const float TOP_CUT_SIGMAS = 3.5;
const float EROSION_CUT_SHARE = 0.5;
// Round 10: the far field's level of detail, by the sample's distance from
// the camera (km): full detail nearer than LOD_NEAR_KM, the plane field only
// (no small cells, no billow, no erosion) past LOD_FAR_KM, and a soft edge
// (1 + FAR_SOFTEN) x as wide there, so the far rows do not stack into hard
// strata. UNCALIBRATED (world_beauty.CLOUD_LOD_*).
const float LOD_NEAR_KM = 6.0;
const float LOD_FAR_KM = 20.0;
const float FAR_SOFTEN = 1.0;
// Round 52: a shadow sample's dither, in footprints (a cube that many footprints
// wide; round 61: 1, stratified, after 2 white drew r58's grain), and its soft
// edge's widening per cell of footprint.
// UNCALIBRATED (world_beauty.CLOUD_SHADOW_DITHER / CLOUD_SHADOW_SOFTEN).
const float SHADOW_DITHER = 1.0;
const float SHADOW_SOFTEN = 1.0;
// Round 61: the R3 low-discrepancy sequence's steps (Roberts 2018: 1 / phi3^k).
const float R3_X = 0.8191725134;
const float R3_Y = 0.6710436067;
const float R3_Z = 0.5497004779;
// The erosion noise's own mean (world_beauty.CLOUD_DETAIL_MEAN, measured on
// its Python replica cloud_detail; tests/test_cloud_tiers.py re-measures it).
const float DETAIL_MEAN = 0.479;
// The bulge's turn over the layer (world_beauty.CLOUD_BULGE_TURN). UNCALIBRATED.
const float BULGE_TURN = 3.0;
// Round 82 (the owner, 2026-11-13: "the clouds dont look that realistic"; r69's
// #03/#13 flat, smeared cumulus, soft blobby edges, no lit tops or dark bases):
// a cumulus is thin and ragged at its base and dense in its upper body (Nubis's
// density-height gradient), so the sun's light dies in the body above and the
// base reads darker and the top brighter. The density rises over this share of
// the layer from (1 - HeightDensity) to 1 (world_beauty.CLOUD_HEIGHT_DENSITY_RISE).
// UNCALIBRATED.
const float HEIGHT_DENSITY_RISE = 0.7;
// Round 92 (r82's #11/#13 slabs with vertical walls): with HeightDensity > 0 the cut
// also rises towards the top cut over the whole layer, HeightDensity x DOME_TAPER x
// h^DOME_POWER of the way, so the sides slope in (world_beauty.CLOUD_DOME_*). UNCALIBRATED.
const float DOME_TAPER = 1.0;
const float DOME_POWER = 1.5;
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
	// Round 52: bulge (cells) adds to the warp's 0.45, so a height-varying
	// bulge moves the cells' outlines with altitude along the same warp vectors
	// (no hash added); 0 is round 51's ShapeLod exactly.
	float ShapeLodBulge(float3 p, float far, float bulge, uint seed)
	{
		float wx = Perlin2(p.x * 0.6 + 1.7, p.y * 0.6 + 9.2, seed + 601u);
		float wy = Perlin2(p.x * 0.6 + 13.1, p.y * 0.6 + 2.3, seed + 613u);
		float qx = p.x + (0.45 + bulge) * wx;
		float qy = p.y + (0.45 + bulge) * wy;
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
	float ShapeLod(float3 p, float far, uint seed)
	{
		return ShapeLodBulge(p, far, 0.0, seed);
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
FWorldCloud C;
// Kilometres, offset by the seed and carried by the wind (horizontal only).
float3 km = (WorldPos / 100.0 - WindOffsetM) / 1000.0 + SeedOffsetKm;
float h = saturate(NormAlt);
// Round 52: a shadow sample's footprint (0 for a view sample, and with the
// filter off), dithered over it.
// Round 61 (r58's grain): the dither was a white hash of the sample's position,
// independent per pixel and per capture, which 12 TSR captures leave as grain.
// It is now interleaved gradient noise (Jimenez 2014: the pattern TAA/TSR is
// built to resolve) of the pixel, advanced per capture (View.StateFrameIndexMod8),
// stratified along the shadow ray by the R3 sequence over the sample's index
// (2 sqrt(d) / ShadowFootprintKm: 0, 1, 2 ... for the quadratic march), so the
// ten samples of one ray cover the cube evenly instead of at random.
float footKm = ShadowFootprintKm * sqrt(max(ShadowDist, 0.0) / 100000.0);
[branch]
if (footKm > 0.0)
{
	float ignX = Parameters.SvPosition.x + 5.588238 * (float)View.StateFrameIndexMod8;
	float ignY = Parameters.SvPosition.y + 5.588238 * (float)View.StateFrameIndexMod8;
	float u0 = frac(52.9829189 * frac(0.06711056 * ignX + 0.00583715 * ignY));
	float idx = floor(2.0 * sqrt(max(ShadowDist, 0.0) / 100000.0) / ShadowFootprintKm);
	float3 u = frac(u0 + float3(R3_X, R3_Y, R3_Z) * (idx + 1.0)) - 0.5;
	float3 dKm = u * (SHADOW_DITHER * footKm);
	km += dKm;
	h = saturate(NormAlt + dKm.z / max(LayerThicknessKm, 1e-3));
}
// The base fades over BottomSoftness (a soft, nearly flat base); the top
// ROUNDS: over TopRounding the cut rises to TOP_CUT_SIGMAS above the mean, so
// only a cell's core reaches the top (domes, not a density fade).
float base = smoothstep(0.0, max(BottomSoftness, 1e-3), h);
float top = 1.0 - smoothstep(1.0 - max(TopRounding, 1e-3), 1.0, h);
// The weather field: cells of ShapeScaleKm on the plane; its one 3D octave
// varies twice as fast with height (the sides bulge every few hundred m).
float far = smoothstep(LOD_NEAR_KM, LOD_FAR_KM, length(WorldPos - CameraPos) / 100000.0);
// Round 52: the sides bulge. The weather field is a plane pattern, so a cell's
// outline was the same at every height (vertical walls, flat shelves where the
// cut barely moves): its warp grows by SideBulge x sin(BULGE_TURN (h - 0.5))
// cells, so the outline moves with height (0 at mid-layer, the distant sheet's
// slice; 0 with SideBulge 0: round 51).
float bulge = SideBulge * sin(BULGE_TURN * (h - 0.5));
float shape = C.ShapeLodBulge(float3(km.x, km.y, km.z * 2.0) / max(ShapeScaleKm, 1e-3), far, bulge, 7u);
// Coverage: the shape kept above the noise's (1 - cover) QUANTILE, so the drawn
// share of sky is the stated cover; the soft edge (FBM_SIGMA / contrast wide)
// starts EROSION_CUT_SHARE x DetailErosion of its width early, which the
// erosion below takes back on average.
float cover = saturate(Coverage);
float soft = FBM_SIGMA / max(CoverageContrast, 1e-3) * (1.0 + FAR_SOFTEN * far);
float thr = FBM_MEAN + FBM_SIGMA * C.Probit(1.0 - cover) - EROSION_CUT_SHARE * DetailErosion * soft;
float cut = lerp(FBM_MEAN + TOP_CUT_SIGMAS * FBM_SIGMA, thr, top);
// Round 92: heaps, not extrusions (0 with HeightDensity 0: round 81).
cut = lerp(cut, FBM_MEAN + TOP_CUT_SIGMAS * FBM_SIGMA, saturate(HeightDensity) * DOME_TAPER * pow(h, DOME_POWER));
// Round 52: a shadow sample's edge widens by its footprint (after the cut, so
// the cut and the drawn cover stay the stated ones); + 0 for a view sample.
soft += SHADOW_SOFTEN * footKm / max(ShapeScaleKm, 1e-3);
float density = C.Remap(shape, cut, cut + soft);
[branch]
if (density > 0.0 && far < 1.0)
{
	// Erosion by the detail noise: wispy (the noise) under WISP_HEIGHT of the
	// layer, billowy (its inverse) above; a full core is never eroded.
	// Round 52: a shadow sample whose footprint is wider than the noise reads
	// the noise's mean (DETAIL_MEAN) instead of evaluating it (54 hashes saved).
	float detail = DETAIL_MEAN;
	[branch]
	if (footKm < max(DetailScaleKm, 1e-3))
	{
		detail = C.Detail(km / max(DetailScaleKm, 1e-3), 13u);
	}
	float wisp = lerp(detail, 1.0 - detail, saturate(h / WISP_HEIGHT));
	density = C.Remap(density, DetailErosion * (1.0 - far) * wisp, 1.0);
}
// Round 61 (r58's distant band of block columns): where the distant sheet is
// drawn its fade-in (distant_clouds.hlsl: HandoverKm .. + FadeKm by the
// distance) overlaid this march's far walls up to the trace's end, so the
// sheet's gaps showed the volumetric walls as dark rectangles cut by the
// sheet's edges. The march now fades out over the same range (FarFadeKm > 0
// only when the sheet is drawn; 0 = round 52, unchanged): a cross-fade.
float fadeOut = 1.0;
[branch]
if (FarFadeKm > 0.0)
{
	fadeOut = 1.0 - smoothstep(FarFadeStartKm, FarFadeStartKm + FarFadeKm, length(WorldPos - CameraPos) / 100000.0);
}
// Round 82: thin, ragged base, dense upper body (1 everywhere with HeightDensity 0).
float body = lerp(1.0 - saturate(HeightDensity), 1.0, smoothstep(0.0, HEIGHT_DENSITY_RISE, h));
return density * base * body * ExtinctionPerM * ExtinctionScale * fadeOut;
