// M_FlightSimTilesBeauty's terrain detail, base colour half: the Custom node body
// scripts/ue_create_materials.py (create_world_tiles_beauty) runs between
// tiles_delight.hlsl and tiles_base_colour.hlsl. Lane B of the non-urban visual
// push, 2026-11-11. BEAUTY ONLY: only FFlightSimWorldBeauty (-quality=beauty) sets
// this material on the tileset, so a measure render never runs it.
//
// The Google tiles outside cities are low-detail photogrammetry: smeared, soft,
// lit flat. This node keeps the tiles' colour (the ground stays Google's) and adds
//   * an unsharp mask of the tiles' own texture (Albedo against AlbedoMid, the same
//     texture a mip and a half coarser): the smeared imagery is crisped;
//   * CC0 aerial detail (assets/terrain_detail, Poly Haven; THIRD_PARTY_VISUAL.md):
//     each role's albedo LUMINANCE RATIO to its own mean multiplies the tile, so the
//     tile's hue is untouched and only the fine contrast is the texture's. The role
//     is chosen per pixel from the tile itself (FTerrainDetail::Weights): steep ->
//     rock, mid slope -> scree, bright neutral above the snowline -> snow, green ->
//     grass, warm bright -> sand, the rest -> soil; open water (blue, dark) gets none;
//   * range octaves: each role tiles at its real size (PIN.json tile_m) times 4^i,
//     i picked from the pixel's footprint so a texel stays about a pixel at every
//     range (1500 m Yosemite and 5000 m Matterhorn alike), two octaves blended,
//     each octave rotated so the repeats do not align; a 1.5 km macro noise varies
//     the amount so no two hillsides match;
//   * forest canopy: dark green ground gets jittered crown domes CROWN_M apart,
//     darker in the gaps (tiles_detail_normal.hlsl lights the same domes), shown
//     only where a crown spans more than a few pixels;
//   * a far fade (FarFadeStartM .. FarFadeEndM) so the haze's horizon stays clean.
// Explicit gradients (SampleGrad, derivatives taken before any branch) so every
// role's samples sit behind a dynamic branch on its weight: a pixel pays only for
// the one or two roles it shows. The shared sampler is the view's bilinear wrap
// sampler (UNVERIFIED name on UE 5.7: View.MaterialTextureBilinearWrapedSampler;
// a "undeclared identifier" compile error means use the per-texture samplers,
// <Name>Sampler, instead), so the twelve maps cost no sampler slots (SM5: 16).
// Every amount is UNCALIBRATED: set by probe render on the render machine
// (docs/visual/PROBE_LOG.md ## lane-B terrain detail).
//
// Generation 8 (hyperreal terrain detail, 2026-11-15): the detail reads like an
// aerial photograph instead of noise. #02 (super bright Yosemite) drew grey,
// harsh, salt-and-pepper trees and #01 a flat brown; four causes, all here:
//   * the role maps were sampled at ONE texel per pixel (Level picks the octave
//     for it and SampleGrad got the exact gradients, so the hardware took mip 0):
//     the display's Nyquist limit, i.e. pixel noise. An aerial camera resolves
//     coarser than the frame it is shown on, so the gradients are scaled by
//     DETAIL_TEXEL_PX: the sampler filters each map to a texel of that many
//     pixels at every range (footprint-filtered; no sub-pixel content left);
//   * the luminance ratio reached 0.4..1.8 (over two stops of albedo contrast
//     multiplied under a sun already x1.6): it is compressed in log space by
//     DETAIL_CONTRAST and held to DETAIL_RATIO_MIN..MAX;
//   * the unsharp mask added (a - mid) per CHANNEL: an almost neutral offset on
//     a coloured texel, so highlights went grey and shadows crushed to black.
//     It now sharpens the LUMA only and keeps the texel's chromaticity exactly
//     (vegetation keeps its green, the valley floor its ochre);
//   * forest (dark green) took the grass map, aerial_grass_rock, whose grey
//     rocks' ratio speckled the canopy with bright grey: FOREST_TEXTURE_CUT of
//     the map is cut on forest, which the canopy owns instead, and the crowns
//     are shown only where one spans CROWN_M / CANOPY_VISIBLE_PX_LO.. pixels,
//     with a parabolic dome (no vertical rim: a pixel step is bounded) and a
//     milder gap (CANOPY_GAP).
// The haze's depth is the frame's own fog (untouched here; the far fade keeps
// the horizon clean).
//
// Inputs (the script's WORLD_TILES_DETAIL_INPUTS["tiles_detail_surface"]):
//   Albedo              float3  the de-lit tile colour (tiles_delight.hlsl's output)
//   AlbedoMid           float3  the tile texture at SharpenMipBias (the unsharp mask's blur)
//   WorldPos            float3  absolute world position, cm
//   CameraPos           float3  absolute camera position, cm
//   NormalWS            float3  the vertex normal, world space
//   GroundAltitudeM     float   the engine origin's orthometric height (MPC_FlightSimWorld)
//   GroundAltitudeKnown float   1 when the render set it (else the snowline is not applied)
//   TerrainDetailScale  float   the card surface's share (MPC_FlightSimWorld: 0 over a city)
//   DetailAmount        float   0 = the tiles' own texture (and no canopy)
//   SharpenAmount       float   the unsharp mask's gain
//   CanopyAmount        float   the crowns' depth
//   SnowlineM           float   snow detail fades in over +-SNOW_RAMP_M about this altitude
//   FarFadeStartM       float   the detail starts to fade here ...
//   FarFadeEndM         float   ... and is gone here
//   RockD               Texture2D  rocky_terrain_02 albedo
//   ScreeD              Texture2D  aerial_rocks_04 albedo
//   SnowD               Texture2D  snow_field_aerial albedo
//   GrassD              Texture2D  aerial_grass_rock albedo
//   SandD               Texture2D  aerial_sand albedo
//   SoilD               Texture2D  dirt_aerial_02 albedo
static const float SNOW_RAMP_M = 300.0;
static const float CROWN_M = 7.0;
// The roles' real tile sizes (assets/terrain_detail/PIN.json tile_m).
static const float ROCK_TILE_M = 90.0;
static const float SCREE_TILE_M = 80.0;
static const float SNOW_TILE_M = 80.0;
static const float GRASS_TILE_M = 15.0;
static const float SAND_TILE_M = 15.0;
static const float SOIL_TILE_M = 20.0;
// Generation 8: the role maps' texel on screen, pixels (the gradients are scaled
// by it, so the sampler's mip holds no finer frequency: an aerial camera's
// resolution, not the display's); the luminance ratio's log-space contrast and
// its bounds; the share of the grass map cut on forest.
static const float DETAIL_TEXEL_PX = 2.5;
static const float DETAIL_CONTRAST = 0.6;
static const float DETAIL_RATIO_MIN = 0.6;
static const float DETAIL_RATIO_MAX = 1.5;
static const float FOREST_TEXTURE_CUT = 0.75;
// The canopy's gap darkening (a crown's top keeps CANOPY_TOP of the tile), and
// the crown span, pixels, over which the crowns fade in (fully shown at the
// first, absent at the second: a 7 m crown is drawn only from about 0.7 m/px).
static const float CANOPY_GAP = 0.70;
static const float CANOPY_TOP = 1.06;
static const float CANOPY_VISIBLE_PX_LO = 4.0;
static const float CANOPY_VISIBLE_PX_HI = 10.0;
struct FTerrainDetailSurface
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
	float Ratio(Texture2D tex, float2 uv, float2 dx, float2 dy, float meanLum)
	{
		return Lum(tex.SampleGrad(View.MaterialTextureBilinearWrapedSampler, uv, dx, dy).rgb) / meanLum;
	}
	// One role's luminance ratio: two range octaves, top projection, and for the
	// cliff roles (sides = true) a side projection blended in on steep faces.
	// Generation 8: the gradients handed to the sampler are DETAIL_TEXEL_PX times
	// the pixel's, so the mip it filters from has a texel that many pixels wide.
	float Role(Texture2D tex, float tileM, float3 p, float3 dpx, float3 dpy, float footprintM, float3 n, bool sides)
	{
		float meanLum = max(Lum(tex.SampleLevel(View.MaterialTextureBilinearWrapedSampler, float2(0.5, 0.5), 10.0).rgb), 1e-3);
		dpx *= DETAIL_TEXEL_PX;
		dpy *= DETAIL_TEXEL_PX;
		float level = Level(footprintM, tileM);
		float i0 = floor(level);
		float f = level - i0;
		float top = sides ? smoothstep(0.55, 0.80, abs(n.z)) : 1.0;
		bool xSide = abs(n.x) > abs(n.y);
		float r = 0.0;
		[unroll] for (int k = 0; k < 2; ++k)
		{
			float octave = i0 + k;
			float inv = 1.0 / (tileM * exp2(2.0 * octave));
			float weight = k == 0 ? 1.0 - f : f;
			float sum = 0.0;
			[branch] if (top > 0.01)
			{
				sum += top * Ratio(tex, Rot(float2(p.x, -p.y) * inv, octave), Rot(float2(dpx.x, -dpx.y) * inv, octave),
				                   Rot(float2(dpy.x, -dpy.y) * inv, octave), meanLum);
			}
			[branch] if (top < 0.99)
			{
				float2 uv = xSide ? float2(p.y, -p.z) : float2(p.x, -p.z);
				float2 dx = xSide ? float2(dpx.y, -dpx.z) : float2(dpx.x, -dpx.z);
				float2 dy = xSide ? float2(dpy.y, -dpy.z) : float2(dpy.x, -dpy.z);
				sum += (1.0 - top) * Ratio(tex, Rot(uv * inv, octave), Rot(dx * inv, octave), Rot(dy * inv, octave), meanLum);
			}
			r += weight * sum;
		}
		return r;
	}
	// Crown domes crownM apart (jittered Worley F1): 1 at a crown's top, 0 in a gap.
	// Generation 8: a parabolic dome (1 - d^2), whose rim slope is finite, so one
	// pixel's step across it is bounded (the hemisphere's vertical rim aliased).
	float Crowns(float2 pm, float crownM)
	{
		float2 cell = floor(pm / crownM);
		float best = 0.0;
		[unroll] for (int y = -1; y <= 1; ++y)
		{
			[unroll] for (int x = -1; x <= 1; ++x)
			{
				float2 c = cell + float2(x, y);
				float2 centre = (c + float2(Hash2(c), Hash2(c + float2(37.0, 11.0)))) * crownM;
				float radius = crownM * (0.45 + 0.25 * Hash2(c + float2(71.0, 53.0)));
				float d = length(pm - centre) / radius;
				best = max(best, saturate(1.0 - d * d));
			}
		}
		return best;
	}
};
FTerrainDetailSurface T;
// Derivatives first: nothing below may take one inside a branch.
float3 p = WorldPos / 100.0;
float3 dpx = ddx_fine(p);
float3 dpy = ddy_fine(p);
float footprintM = max(max(length(dpx), length(dpy)), 1e-3);
float3 a = max(Albedo, 0.0);
float rangeM = length(WorldPos - CameraPos) / 100.0;
float fade = 1.0 - smoothstep(FarFadeStartM, max(FarFadeEndM, FarFadeStartM + 1.0), rangeM);
// Generation 8: the unsharp mask on the LUMA only; the texel's chromaticity is
// kept exactly (a per-channel mask greyed the highlights and crushed the shadows).
float La = T.Lum(a);
float Lmid = T.Lum(max(AlbedoMid, 0.0));
float Ls = max(La + SharpenAmount * fade * (La - Lmid), 0.5 * La);
float3 sharp = a * (Ls / max(La, 1e-4));
float amount = DetailAmount * TerrainDetailScale * fade;
[branch] if (amount <= 0.001)
{
	return sharp;
}
float3 n = normalize(NormalWS);
float3 w0, w1;
float water, forest;
T.Weights(a, n, GroundAltitudeM + p.z, SnowlineM, SNOW_RAMP_M, GroundAltitudeKnown, w0, w1, water, forest);
float ratio = 0.0;
float shown = 0.0;
[branch] if (w0.x > 0.02) { ratio += w0.x * T.Role(RockD, ROCK_TILE_M, p, dpx, dpy, footprintM, n, true); shown += w0.x; }
[branch] if (w0.y > 0.02) { ratio += w0.y * T.Role(ScreeD, SCREE_TILE_M, p, dpx, dpy, footprintM, n, true); shown += w0.y; }
[branch] if (w0.z > 0.02) { ratio += w0.z * T.Role(SnowD, SNOW_TILE_M, p, dpx, dpy, footprintM, n, false); shown += w0.z; }
[branch] if (w1.x > 0.02) { ratio += w1.x * T.Role(GrassD, GRASS_TILE_M, p, dpx, dpy, footprintM, n, false); shown += w1.x; }
[branch] if (w1.y > 0.02) { ratio += w1.y * T.Role(SandD, SAND_TILE_M, p, dpx, dpy, footprintM, n, false); shown += w1.y; }
[branch] if (w1.z > 0.02) { ratio += w1.z * T.Role(SoilD, SOIL_TILE_M, p, dpx, dpy, footprintM, n, false); shown += w1.z; }
ratio += 1.0 - shown;   // a role under the branch threshold is neutral
// Generation 8: the ratio's contrast compressed in log space and bounded; the
// grass map mostly cut on forest (the canopy below is the forest's texture).
ratio = exp2(DETAIL_CONTRAST * log2(clamp(ratio, 0.25, 4.0)));
ratio = clamp(ratio, DETAIL_RATIO_MIN, DETAIL_RATIO_MAX);
float macro = lerp(0.6, 1.25, T.Value2(p.xy / 1500.0));
float textured = amount * macro * (1.0 - water) * (1.0 - FOREST_TEXTURE_CUT * forest);
float3 c = sharp * lerp(1.0, ratio, saturate(textured));
[branch] if (forest * CanopyAmount * TerrainDetailScale > 0.02)
{
	float visible = 1.0 - smoothstep(CROWN_M / CANOPY_VISIBLE_PX_HI, CROWN_M / CANOPY_VISIBLE_PX_LO, footprintM);
	float h = T.Crowns(p.xy, CROWN_M);
	c *= lerp(1.0, lerp(CANOPY_GAP, CANOPY_TOP, h), saturate(forest * CanopyAmount * TerrainDetailScale * visible * fade));
}
return max(c, 0.0);
