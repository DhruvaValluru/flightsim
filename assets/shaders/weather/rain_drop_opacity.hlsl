// M_RainDrops's opacity: Garg & Nayar's coverage of a streak (core/scene/rain_field.py
// streak_opacity): a point of the streak is covered by the drop for D / (|v| t) of the
// exposure; a streak widened to a pixel keeps its light (times D / width); the weight
// (how many drops a drawn one stands for) raises it, clamped at opaque. Faded at the
// box's faces (no popping where the wrap folds a drop over) and in the first 30 cm
// (a drop on the lens is the glass's job) -- not the first metre, which faded out
// exactly the drops wide enough to see (the owner's frame, 2026-10-09).
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
struct FRainPixel
{
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
float dist = max(length(Rel), 1.0);
float widthCm = Extra.x * 0.1;
float width = max(widthCm, dist * PixelAngle);
float coverage = (diameterCm / streak) * (widthCm / width) * Weight;
float3 a = abs(Rel) / BoxHalf;
float edge = (1.0 - R.Ss(0.8, 1.0, a.x)) * (1.0 - R.Ss(0.8, 1.0, a.y)) * (1.0 - R.Ss(0.8, 1.0, a.z));
float nearFade = R.Ss(5.0, 30.0, dist);
return saturate(coverage) * edge * nearFade;
