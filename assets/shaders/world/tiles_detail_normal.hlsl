// M_FlightSimTilesBeauty's terrain detail, normal half: the WORLD-SPACE normal
// (the material's tangent-space switch is off) that tiles_normal.hlsl then takes
// as its NormalWS. Lane B of the non-urban visual push, 2026-11-11. BEAUTY ONLY.
//
// Three reliefs on the tiles' smooth normal, all fading with FarFadeStartM ..
// FarFadeEndM and none on open water:
//   * the tile's own relief: the tile luminance against its local mean
//     (AlbedoLow) as a height scaled by the pixel footprint (Mikkelsen 2010's
//     surface gradient from the screen derivatives): the photogrammetry's ridges,
//     gullies and crowns catch today's sun instead of only the baked one; doubled
//     (1 + FOREST_BUMP_GAIN) on forest so the canopy reads with depth;
//   * the CC0 aerial normals (assets/terrain_detail, OpenGL convention) of the
//     same roles, octaves and projections as tiles_detail_surface.hlsl (the
//     shared block below is pinned equal to its copy there);
//   * the forest crowns' domes (the same jittered cells as the surface node).
// The normal never tilts more than ~78 degrees from the vertex normal. Every
// amount is UNCALIBRATED: set by probe render on the render machine
// (docs/visual/PROBE_LOG.md ## lane-B terrain detail). The sampler note in
// tiles_detail_surface.hlsl applies here too.
//
// Inputs (the script's WORLD_TILES_DETAIL_INPUTS["tiles_detail_normal"]):
//   Albedo              float3  the de-lit tile colour (tiles_delight.hlsl's output)
//   AlbedoLow           float3  the tile texture at DelightMipBias (the local mean)
//   WorldPos            float3  absolute world position, cm
//   CameraPos           float3  absolute camera position, cm
//   NormalWS            float3  the vertex normal, world space
//   GroundAltitudeM     float   the engine origin's orthometric height (MPC_FlightSimWorld)
//   GroundAltitudeKnown float   1 when the render set it (else the snowline is not applied)
//   TerrainDetailScale  float   the card surface's share (MPC_FlightSimWorld: 0 over a city)
//   DetailAmount        float   0 = the tiles' smooth normal
//   NormalAmount        float   the aerial normals' share
//   BumpAmount          float   the tile relief's height per footprint
//   CanopyAmount        float   the crowns' depth
//   SnowlineM           float   snow detail fades in over +-SNOW_RAMP_M about this altitude
//   FarFadeStartM       float   the detail starts to fade here ...
//   FarFadeEndM         float   ... and is gone here
//   RockN               Texture2D  rocky_terrain_02 normal (OpenGL)
//   ScreeN              Texture2D  aerial_rocks_04 normal (OpenGL)
//   SnowN               Texture2D  snow_field_aerial normal (OpenGL)
//   GrassN              Texture2D  aerial_grass_rock normal (OpenGL)
//   SandN               Texture2D  aerial_sand normal (OpenGL)
//   SoilN               Texture2D  dirt_aerial_02 normal (OpenGL)
const float SNOW_RAMP_M = 300.0;
const float CROWN_M = 7.0;
// The roles' real tile sizes (assets/terrain_detail/PIN.json tile_m).
const float ROCK_TILE_M = 90.0;
const float SCREE_TILE_M = 80.0;
const float SNOW_TILE_M = 80.0;
const float GRASS_TILE_M = 15.0;
const float SAND_TILE_M = 15.0;
const float SOIL_TILE_M = 20.0;
// The forest's extra tile relief (the canopy's depth).
const float FOREST_BUMP_GAIN = 1.0;
struct FTerrainDetailNormal
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
	// shared: terrain detail (tiles_detail_surface.hlsl, tiles_detail_normal.hlsl)
	float Lum(float3 c)
	{
		return dot(c, float3(0.2126, 0.7152, 0.0722));
	}
	// The role weights from the tile's colour, the slope and the altitude:
	// w0 = (rock, scree, snow), w1 = (grass, sand, soil), summing to 1; water is
	// the share of open water (no detail there); forest the dark-green share.
	void Weights(float3 a, float3 n, float altM, float snowlineM, float snowRampM, float altKnown,
	             out float3 w0, out float3 w1, out float water, out float forest)
	{
		float lum = Lum(a);
		float mx = max(max(a.r, a.g), max(a.b, 1e-4));
		float mn = min(min(a.r, a.g), a.b);
		float chroma = (mx - mn) / mx;
		float slope = 1.0 - saturate(n.z);
		float steep = smoothstep(0.30, 0.50, slope);
		float mid = smoothstep(0.10, 0.25, slope) * (1.0 - steep);
		float green = smoothstep(0.0, 0.06, (a.g - a.r) / mx);
		float warm = smoothstep(0.0, 0.10, (a.r - a.b) / mx);
		float bright = smoothstep(0.08, 0.22, lum);
		float gate = altKnown > 0.5 ? smoothstep(snowlineM - snowRampM, snowlineM + snowRampM, altM) : 1.0;
		float snow = smoothstep(0.28, 0.45, lum) * (1.0 - smoothstep(0.10, 0.22, chroma)) * gate * (1.0 - 0.7 * steep);
		water = smoothstep(0.02, 0.10, (a.b - a.r) / mx) * (1.0 - bright) * (1.0 - smoothstep(0.02, 0.08, slope));
		float rest = 1.0 - snow;
		float rock = rest * steep;
		rest -= rock;
		float scree = rest * mid * (1.0 - green);
		rest -= scree;
		float grass = rest * green;
		rest -= grass;
		float sand = rest * warm * bright;
		float soil = rest - sand;
		w0 = float3(rock, scree, snow);
		w1 = float3(grass, sand, soil);
		forest = grass * (1.0 - smoothstep(0.05, 0.12, lum));
	}
	// The range octave: tile = tileM x 4^level, level from the footprint (m/pixel),
	// so one of the map's 1024 texels spans about a pixel.
	float Level(float footprintM, float tileM)
	{
		return max(0.0, 0.5 * log2(footprintM * 1024.0 / tileM));
	}
	float2 Rot(float2 v, float octave)
	{
		float s, c;
		sincos(octave * 1.7, s, c);
		return float2(c * v.x - s * v.y, s * v.x + c * v.y);
	}
	// end terrain detail
	// The decoded OpenGL normal's tilt (x toward +u, y toward image-up) in world
	// space: uv' = Rot(uv), so the uv' frame's (x, -y) goes back through Rot's
	// inverse to (du, dv) and out along the projection's world axes eu, ev.
	float3 Tilt(Texture2D tex, float2 uv, float2 dx, float2 dy, float octave, float3 eu, float3 ev)
	{
		float2 t = tex.SampleGrad(View.MaterialTextureBilinearWrapedSampler, uv, dx, dy).rg * 2.0 - 1.0;
		float2 d = Rot(float2(t.x, -t.y), -octave);
		return d.x * eu + d.y * ev;
	}
	// One role's world-space tilt: the same octaves and projections as
	// tiles_detail_surface.hlsl's Role.
	float3 Role(Texture2D tex, float tileM, float3 p, float3 dpx, float3 dpy, float footprintM, float3 n, bool sides)
	{
		float level = Level(footprintM, tileM);
		float i0 = floor(level);
		float f = level - i0;
		float top = sides ? smoothstep(0.55, 0.80, abs(n.z)) : 1.0;
		bool xSide = abs(n.x) > abs(n.y);
		float3 r = float3(0.0, 0.0, 0.0);
		[unroll] for (int k = 0; k < 2; ++k)
		{
			float octave = i0 + k;
			float inv = 1.0 / (tileM * exp2(2.0 * octave));
			float weight = k == 0 ? 1.0 - f : f;
			float3 sum = float3(0.0, 0.0, 0.0);
			[branch] if (top > 0.01)
			{
				sum += top * Tilt(tex, Rot(float2(p.x, -p.y) * inv, octave), Rot(float2(dpx.x, -dpx.y) * inv, octave),
				                  Rot(float2(dpy.x, -dpy.y) * inv, octave), octave,
				                  float3(1.0, 0.0, 0.0), float3(0.0, -1.0, 0.0));
			}
			[branch] if (top < 0.99)
			{
				float2 uv = xSide ? float2(p.y, -p.z) : float2(p.x, -p.z);
				float2 dx = xSide ? float2(dpx.y, -dpx.z) : float2(dpx.x, -dpx.z);
				float2 dy = xSide ? float2(dpy.y, -dpy.z) : float2(dpy.x, -dpy.z);
				float3 eu = xSide ? float3(0.0, 1.0, 0.0) : float3(1.0, 0.0, 0.0);
				sum += (1.0 - top) * Tilt(tex, Rot(uv * inv, octave), Rot(dx * inv, octave), Rot(dy * inv, octave), octave,
				                          eu, float3(0.0, 0.0, -1.0));
			}
			r += weight * sum;
		}
		return r;
	}
	// The crown domes' tilt (tiles_detail_surface.hlsl's Crowns, the same cells):
	// a dome of height crownM x 0.8 over the nearest crown, its normal's
	// horizontal part 0.8 d / h, capped at the rim.
	float2 CrownTilt(float2 pm, float crownM)
	{
		float2 cell = floor(pm / crownM);
		float best = 0.0;
		float2 tilt = float2(0.0, 0.0);
		[unroll] for (int y = -1; y <= 1; ++y)
		{
			[unroll] for (int x = -1; x <= 1; ++x)
			{
				float2 c = cell + float2(x, y);
				float2 centre = (c + float2(Hash2(c), Hash2(c + float2(37.0, 11.0)))) * crownM;
				float radius = crownM * (0.45 + 0.25 * Hash2(c + float2(71.0, 53.0)));
				float2 d = (pm - centre) / radius;
				float h = sqrt(saturate(1.0 - dot(d, d)));
				if (h > best)
				{
					best = h;
					tilt = d * min(0.8 / max(h, 0.1), 1.5);
				}
			}
		}
		return tilt;
	}
};
FTerrainDetailNormal T;
// Derivatives first: nothing below may take one inside a branch.
float3 p = WorldPos / 100.0;
float3 dpx = ddx_fine(p);
float3 dpy = ddy_fine(p);
float footprintM = max(max(length(dpx), length(dpy)), 1e-3);
float3 a = max(Albedo, 0.0);
// The tile's own relief: its luminance against the local mean (AlbedoLow) as a
// height of BumpAmount x footprint x ratio, so the bump is the same few degrees
// at every range; Mikkelsen 2010's surface gradient from the screen derivatives.
float relief = T.Lum(a) / max(T.Lum(max(AlbedoLow, 0.0)), 0.01);
float dBs = ddx_fine(relief);
float dBt = ddy_fine(relief);
float3 n = normalize(NormalWS);
float rangeM = length(WorldPos - CameraPos) / 100.0;
float fade = 1.0 - smoothstep(FarFadeStartM, max(FarFadeEndM, FarFadeStartM + 1.0), rangeM);
float amount = DetailAmount * TerrainDetailScale * fade;
[branch] if (amount <= 0.001)
{
	return n;
}
float3 w0, w1;
float water, forest;
T.Weights(a, n, GroundAltitudeM + p.z, SnowlineM, SNOW_RAMP_M, GroundAltitudeKnown, w0, w1, water, forest);
float land = 1.0 - water;
float bump = BumpAmount * TerrainDetailScale * footprintM * fade * land * (1.0 + FOREST_BUMP_GAIN * forest);
float3 r1 = cross(dpy, n);
float3 r2 = cross(n, dpx);
float det = dot(dpx, r1);
float3 surfGrad = sign(det) * (bump * dBs * r1 + bump * dBt * r2);
float3 nb = normalize(abs(det) * n - surfGrad);
nb = dot(nb, nb) > 0.5 ? nb : n;   // a degenerate quad keeps the vertex normal
float3 tilt = float3(0.0, 0.0, 0.0);
[branch] if (w0.x > 0.02) { tilt += w0.x * T.Role(RockN, ROCK_TILE_M, p, dpx, dpy, footprintM, n, true); }
[branch] if (w0.y > 0.02) { tilt += w0.y * T.Role(ScreeN, SCREE_TILE_M, p, dpx, dpy, footprintM, n, true); }
[branch] if (w0.z > 0.02) { tilt += w0.z * T.Role(SnowN, SNOW_TILE_M, p, dpx, dpy, footprintM, n, false); }
[branch] if (w1.x > 0.02) { tilt += w1.x * T.Role(GrassN, GRASS_TILE_M, p, dpx, dpy, footprintM, n, false); }
[branch] if (w1.y > 0.02) { tilt += w1.y * T.Role(SandN, SAND_TILE_M, p, dpx, dpy, footprintM, n, false); }
[branch] if (w1.z > 0.02) { tilt += w1.z * T.Role(SoilN, SOIL_TILE_M, p, dpx, dpy, footprintM, n, false); }
float macro = lerp(0.6, 1.25, T.Value2(p.xy / 1500.0));
float3 detailed = nb + tilt * saturate(amount * macro * land) * NormalAmount;
[branch] if (forest * CanopyAmount * TerrainDetailScale > 0.02)
{
	float visible = 1.0 - smoothstep(CROWN_M / 4.0, CROWN_M / 2.0, footprintM);
	float2 crown = T.CrownTilt(p.xy, CROWN_M);
	detailed += float3(crown, 0.0) * saturate(forest * CanopyAmount * TerrainDetailScale * visible * fade);
}
// Never tilted past the horizon of the vertex normal (no black facets).
float3 outN = normalize(detailed);
return dot(outN, n) > 0.2 ? outN : normalize(outN + n);
