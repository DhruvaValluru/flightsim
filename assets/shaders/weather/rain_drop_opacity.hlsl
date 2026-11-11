// M_RainDrops's opacity: Garg & Nayar's coverage of a streak (core/scene/rain_field.py
// streak_opacity): a point of the streak is covered by the drop for D / (|v| t) of the
// exposure; a streak widened to a pixel keeps its light (times D / width); the weight
// (how many drops a drawn one stands for) raises it, clamped at opaque. Faded at the
// box's faces (no popping where the wrap folds a drop over) and in the first 30 cm
// (a drop on the lens is the glass's job) -- not the first metre, which faded out
// exactly the drops wide enough to see (the owner's frame, 2026-10-09).
//
// The beauty rain shape (round-2b weather-fx, core/scene/weather_look.py
// beauty_rain_shape): MaxStreak is the offset's streak cap (the coverage follows the
// streak drawn), MaxCoverage caps one streak below opaque (no sheet), DepthFade fades
// the coverage by exp(-range / DepthFade). Defaults (0, 1, 0) are the measure path's.
//
// Inputs:
//   Rel      float3  the pixel's engine position minus the component's (cm)
//   Drop     float2  UV1: diameter (mm), fall speed (m/s)
//   Extra    float2  UV2: presented width (mm), phase
//   Index    float   UV3.x
//   WindVel  float3  the wind at the camera, engine cm/s
//   CamVel   float3  the camera's velocity, engine cm/s
//   Shutter  float   the exposure, s
//   PixelAngle float the angle of one pixel, rad
//   Weight   float   the drops a drawn one stands for
//   Active   float   the share of drops shown here
//   BoxHalf  float3  the box's half extent, engine cm
//   GroundRelZ float the ground under the camera minus the component, cm
//   MaxStreak float  the beauty streak's longest angular length, rad (0: no cap)
//   MaxCoverage float the beauty cap on one streak's coverage (1: none)
//   DepthFade float  the beauty coverage fade range, cm (0: none)
//   Corner   float2  lane D: UV0 (0|1 across, 0|1 along)
//   Soft     float   lane D: the beauty streak's softness (0: the hard quad)
//   Vary     float   lane D: the beauty per-drop length and brightness spread (0: none)
//
// Lane D (2026-11-11, the round-4 review's "thin straight white lines that read as
// scratches"): Soft widens the streak (the offset's twin) and draws a Gaussian
// across it and tapered ends, each profile normalised to a mean of 1 (exp(-4 x^2)
// over |x| <= 1 averages 0.441; sqrt(sin(pi t)) averages 0.763), so the soft
// streak carries the hard one's light spread out; Vary scales each drop's length
// (the offset's hash) and its coverage by 0.4..1.0 (a second hash). Both 0: the
// measure path's coverage, value for value.
struct FRainPixel
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
};
FRainPixel R;
if (Index >= Active || Rel.z < GroundRelZ)
{
	return 0.0;
}
float3 vel = WindVel - float3(0.0, 0.0, Drop.y * 100.0) - CamVel;
float speed = length(vel);
float diameterCm = Drop.x * 0.1;
float streak = max(speed * Shutter, diameterCm);
float bright = 1.0;
if (Vary > 0.0)
{
	float h = (R.Pcg(asuint(Index) ^ 0x68E31DA4u) & 0xFFFFFFu) / 16777216.0;
	streak *= lerp(1.0, 0.45 + 1.1 * h, Vary);
	float hb = (R.Pcg(asuint(Index) ^ 0x1B56C4E9u) & 0xFFFFFFu) / 16777216.0;
	bright = lerp(1.0, 0.4 + 0.6 * hb, Vary);
}
float dist = max(length(Rel), 1.0);
if (MaxStreak > 0.0)
{
	streak = max(min(streak, MaxStreak * dist), diameterCm);
}
float widthCm = Extra.x * 0.1;
float width = max(widthCm, dist * PixelAngle);
if (Soft > 0.0)
{
	width *= 1.0 + Soft;
}
float coverage = (diameterCm / streak) * (widthCm / width) * Weight;
if (Soft > 0.0 || Vary > 0.0)
{
	float x = 2.0 * (Corner.x - 0.5);
	float across = lerp(1.0, exp(-4.0 * x * x) / 0.441, saturate(Soft));
	float along = lerp(1.0, sqrt(sin(3.14159265 * saturate(Corner.y))) / 0.763, saturate(Soft));
	coverage *= across * along * bright;
}
float3 a = abs(Rel) / BoxHalf;
float edge = (1.0 - R.Ss(0.8, 1.0, a.x)) * (1.0 - R.Ss(0.8, 1.0, a.y)) * (1.0 - R.Ss(0.8, 1.0, a.z));
float nearFade = R.Ss(5.0, 30.0, dist);
float shown = min(saturate(coverage), MaxCoverage);
if (DepthFade > 0.0)
{
	shown *= exp(-dist / DepthFade);
}
return shown * edge * nearFade;
