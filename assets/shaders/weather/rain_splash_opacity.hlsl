// M_RainSplash's opacity: a crown sheet rising and thinning over its lifetime
// (core/scene/rain_particles.py SPLASH_LIFETIME_S), times the slot weight, clamped.
//
// Inputs:
//   Corner  float2  UV0 (x across, y up)
//   SlotUV  float2  UV1: (index % 64, index / 64)
//   Time    float   run time, s
//   Splash  float4  period (s), lifetime (s), half side (cm), slots
//   Weight  float   the card's splash weight
struct FCrown
{
	float Ss(float e0, float e1, float x)
	{
		if (e0 == e1) { return x < e0 ? 0.0 : 1.0; }
		float t = saturate((x - e0) / (e1 - e0));
		return t * t * (3.0 - 2.0 * t);
	}
};
FCrown C;
float Slot = SlotUV.x + 64.0 * SlotUV.y;
float cycles = Time / Splash.x + frac(Slot * 0.6180339887);
float a = saturate(frac(cycles) * Splash.x / Splash.y);
float2 q = (Corner - float2(0.5, 0.0)) * float2(2.0, 1.6);
float d = length(q);
// The crown: a thin wall at the rim of a growing cup, and the sheet lifting off it.
float wall = C.Ss(0.55, 0.85, d) * C.Ss(1.0, 0.9, d);
float sheet = C.Ss(0.9, 0.2, d) * C.Ss(0.0, 0.1, Corner.y) * 0.35;
float fade = (1.0 - a) * (1.0 - a);
return saturate((wall + sheet) * fade * 0.6 * Weight);
