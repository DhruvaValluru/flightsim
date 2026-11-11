// M_RainCurtain's opacity: one shell of the beauty rain veil (core/scene/rain_veil.py,
// lane D 2026-11-11). The shell is an open cylinder round the camera; a pixel on it
// stands for the rain of the slab of air between the previous shell and this one:
// a grey veil (Veil = 1 - exp(-beta x slab), rain_veil.shell_veil_alpha) and the
// streaks falling through it along the drops' path in the wind.
//
// The streaks: the pixel's offset from the camera in a frame whose third axis is the
// fall direction (WindVel minus the fall speed); across it the lattice is
// StreakRad x Radius wide (the same angular size on every shell), along it
// VEIL_STREAK_ASPECT = 60 times longer and scrolled at the fall speed, so the
// streaks fall at the drops' own speed and slant with the wind. A cell holds a
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
float speed = max(length(fallVel), 1.0);
float3 dir = fallVel / speed;
float3 side = cross(dir, float3(0.0, 0.0, 1.0));
side = dot(side, side) > 1.0e-6 ? normalize(side) : float3(1.0, 0.0, 0.0);
float3 other = cross(dir, side);
float cellW = max(Radius * StreakRad, 1.0);
float cellL = cellW * 60.0;
float a = dot(Rel, side) / cellW;
float b = dot(Rel, other) / (cellW * 4.0);
float column = floor(a);
uint h = C.Pcg(asuint((int)column) ^ C.Pcg(asuint((int)floor(b)) ^ (uint)Seed));
float along = (dot(Rel, dir) - speed * Time) / cellL + C.U(h);
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
return saturate(Veil + streak * (1.0 - Veil));
