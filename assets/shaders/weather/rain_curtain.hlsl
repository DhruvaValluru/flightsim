// M_RainCurtain's opacity: one shell of the beauty rain veil (core/scene/rain_veil.py,
// lane D 2026-11-11). The shell is an open cylinder round the camera; a pixel on it
// stands for the rain of the slab of air between the previous shell and this one:
// a grey veil (Veil = 1 - exp(-beta x slab), rain_veil.shell_veil_alpha) and the
// streaks falling through it along the drops' path in the wind.
//
// The streaks: drawn in the shell's own surface frame -- s the arc length round
// the cylinder, z the height -- along the fall velocity's projection onto the
// surface at that pixel (the tangential wind and the fall), so every azimuth
// slants with the wind and none smears into wide bars (round 12: a world-fixed
// frame collapsed to one column where the shell faced the wind axis; round 9's
// #07: StreakRad was an angle, 14 px wide through a 250 mm lens). Across the
// streak the lattice is StreakRad x Radius wide, StreakRad set per frame as
// VEIL_STREAK_PIXELS pixels (the same on-screen width at every lens and shell),
// along it VEIL_STREAK_ASPECT = 60 times longer, scrolled at the fall speed. A cell holds a
// streak with probability StreakDensity; each has its own length, phase and brightness
// (a hash of its cell), a Gaussian across and soft ends. No texture: a hashed
// integer lattice (no tile, no repeat).
//
// BEAUTY ONLY: only FFlightSimWeather::ApplyBeautyRainVeil builds a shell (its
// actor in BeautyOnlyActors: no label capture sees it).
//
// Inputs (the Custom node's, named exactly so):
//   Rel        float3  the pixel's world position minus the camera's, cm
//   WindVel    float3  the wind at the camera, engine cm/s
//   FallCmps   float   the drops' fall speed (the median drop's), cm/s
//   Time       float   run time, s
//   Radius     float   this shell's radius, cm
//   StreakRad  float   the streak cell's angular width, rad (rain_veil.VEIL_STREAK_RAD)
//   StreakDensity float the share of cells holding a streak (rain_veil.streak_density)
//   StreakAlpha float  one streak's most coverage (rain_veil.VEIL_STREAK_ALPHA)
//   Veil       float   this shell's grey veil (rain_veil.shell_veil_alpha)
//   GroundRelZ float   the ground under the camera minus the camera, cm
//   Seed       float   the card's rain seed (masked to 24 bits)
//   VeilVary   float   lane D round 26: the veil's share varied by falling curtains (0: uniform)
//   VaryScale  float   round 47: the curtains' cell size as a share of the wide-lens one (1:
//                      generation 5; the C++ sets min(1, pixel angle / the 54 deg reference))
//
// Round 26 (#07: "a flat grey field"): the veil is uniform round the shell, so through a
// long lens the frame is one grey. With VeilVary the veil is x (1 + VeilVary x (2n - 1)),
// n a smooth value noise in (arc, height) with cells a fifth of the radius across and
// 0.8 radius tall, falling at the drops' speed: denser and thinner curtains of rain at
// three depths, the structure a heavy-rain photograph shows. VeilVary 0: unchanged.
//
// Round 47 (round 44's #07 still a flat grey field): the curtain cells were a fifth of
// the radius across and 0.8 of it tall -- 11.3 deg x 38.7 deg at EVERY shell (an angle,
// like round 9's streak bars). Through #07's 250 mm lens (8.2 x 4.6 deg) one cell is
// wider and taller than the frame, so every shell's veil was one value across the
// picture: uniform. VaryScale shrinks the cells with the view's pixel angle (the same
// rule as the streak cap, rain_veil.streak_cap_rad): about 5 curtains across #07's
// frame, unchanged (1) at any lens of 54 deg or wider. -veil-lens-cells=off is the A/B.
struct FCurtain
{
	uint Pcg(uint v)
	{
		uint state = v * 747796405u + 2891336453u;
		uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
		return (word >> 22u) ^ word;
	}
	float U(uint h) { return (h & 0xFFFFFFu) / 16777216.0; }
	float Ss(float e0, float e1, float x)
	{
		if (e0 == e1) { return x < e0 ? 0.0 : 1.0; }
		float t = saturate((x - e0) / (e1 - e0));
		return t * t * (3.0 - 2.0 * t);
	}
};
FCurtain C;
if (Rel.z < GroundRelZ)
{
	return 0.0;   // below the ground: the shell is cut there
}
float3 fallVel = WindVel - float3(0.0, 0.0, FallCmps);
float2 radial = Rel.xy / max(length(Rel.xy), 1.0);
float2 tangent = float2(-radial.y, radial.x);
// The fall velocity on the surface: (tangential, vertical), unit.
float2 v2 = float2(dot(fallVel.xy, tangent), fallVel.z);
float speed = max(length(v2), 1.0);
float2 u2 = v2 / speed;
float arc = atan2(Rel.y, Rel.x) * Radius;
float2 q = float2(arc, Rel.z);
float cellW = max(Radius * StreakRad, 0.5);
float cellL = cellW * 60.0;
float a = (q.x * u2.y - q.y * u2.x) / cellW;
float column = floor(a);
uint h = C.Pcg(asuint((int)column) ^ (uint)Seed);
float along = (dot(q, u2) - speed * Time) / cellL + C.U(h);
float segment = floor(along);
uint hs = C.Pcg(h ^ asuint((int)segment));
float streak = 0.0;
if (C.U(hs) < StreakDensity)
{
	float f = frac(along);
	float len = 0.35 + 0.6 * C.U(C.Pcg(hs + 1u));
	float x = frac(a) - 0.5;
	float across = exp(-16.0 * x * x);
	float ends = C.Ss(0.0, 0.1 * len, f) * C.Ss(len, len * 0.7, f);
	streak = across * ends * (0.4 + 0.6 * C.U(C.Pcg(hs + 2u))) * StreakAlpha;
}
float veil = Veil;
if (VeilVary > 0.0)
{
	float vs = VaryScale > 0.0 ? min(VaryScale, 1.0) : 1.0;
	float2 g = float2(arc / (Radius * 0.2 * vs), (Rel.z + FallCmps * Time) / (Radius * 0.8 * vs));
	float2 gi = floor(g);
	float2 gf = g - gi;
	gf = gf * gf * (3.0 - 2.0 * gf);
	uint sx = (uint)Seed + 17u;
	float n00 = C.U(C.Pcg(asuint((int)gi.x) ^ C.Pcg(asuint((int)gi.y) ^ sx)));
	float n10 = C.U(C.Pcg(asuint((int)gi.x + 1) ^ C.Pcg(asuint((int)gi.y) ^ sx)));
	float n01 = C.U(C.Pcg(asuint((int)gi.x) ^ C.Pcg(asuint((int)gi.y + 1) ^ sx)));
	float n11 = C.U(C.Pcg(asuint((int)gi.x + 1) ^ C.Pcg(asuint((int)gi.y + 1) ^ sx)));
	float n = lerp(lerp(n00, n10, gf.x), lerp(n01, n11, gf.x), gf.y);
	veil = saturate(Veil * (1.0 + VeilVary * (2.0 * n - 1.0)));
}
return saturate(veil + streak * (1.0 - veil));
