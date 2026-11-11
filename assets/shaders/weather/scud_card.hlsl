// M_ScudCard's opacity: one torn scud card of the beauty rain veil (core/scene/
// rain_veil.py, lane D 2026-11-11). The host (FFlightSimWeather::AdvanceBeautyRainVeil)
// places each camera-facing card per frame and writes its alpha into UV1.x and its
// seed into UV1.y; this shader tears the card into a rag: a 4-octave value fbm over
// the card (stretched 2.5x along it, slowly boiling in time) cut against a radial
// falloff, so the edge is ragged and soft and the middle thin in places, never a
// disc or a square.
//
// Inputs (the Custom node's, named exactly so):
//   UV      float2  UV0: 0..1 across and up the card
//   Card    float2  UV1: the card's alpha, its seed (0..1)
//   Time    float   run time, s
struct FScud
{
	uint Pcg(uint v)
	{
		uint state = v * 747796405u + 2891336453u;
		uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
		return (word >> 22u) ^ word;
	}
	float Lattice(int ix, int iy, int iz, uint seed)
	{
		uint h = Pcg(asuint(iz) + seed);
		h = Pcg(asuint(iy) + h);
		h = Pcg(asuint(ix) + h);
		return h / 4294967296.0;
	}
	float Fade(float t) { return t * t * t * (t * (t * 6.0 - 15.0) + 10.0); }
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
	float Ss(float e0, float e1, float x)
	{
		if (e0 == e1) { return x < e0 ? 0.0 : 1.0; }
		float t = saturate((x - e0) / (e1 - e0));
		return t * t * (3.0 - 2.0 * t);
	}
};
FScud S;
if (Card.x <= 0.0)
{
	return 0.0;
}
uint seed = (uint)(Card.y * 16777216.0);
float2 c = (UV - 0.5) * 2.0;
float3 p = float3(UV.x * 5.0, UV.y * 2.0, Time * 0.05);
float n = 0.0;
float amp = 0.5;
[unroll] for (int k = 0; k < 4; ++k)
{
	n += amp * S.Value(p, seed + (uint)k);
	p *= 2.03;
	amp *= 0.5;
}
n /= 0.9375;
float falloff = 1.0 - dot(c, c);
float rag = S.Ss(0.35, 0.75, n + 0.55 * falloff - 0.3);
return rag * Card.x;
