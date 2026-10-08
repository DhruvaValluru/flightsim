// M_RainSplash's world position offset: SPLASH slots on the ground under the camera,
// each relighting once per period at a new place (core/scene/rain_field.py splash:
// pcg32(slot * 65536 + cycle)), world-fixed through GroundShift.
//
// Inputs:
//   P0         float3  the vertex's position minus the component's (cm; 0 for every vertex)
//   Corner     float2  UV0
//   SlotUV     float2  UV1: the slot's index as (index % 64, index / 64), whole numbers
//                      a half-precision UV holds exactly
//   Time       float   run time, s
//   Splash     float4  period (s), lifetime (s), half side of the splash square (cm), slots
//   GroundShift float2 wrap(-camera, half side), engine cm (east-west/north-south as engine X/Y)
//   GroundRelZ float   the ground under the camera minus the component, cm
//   DropMm     float   the card's D0 (mm): the crown's scale
//   Active     float   the share of slots shown
struct FSplash
{
	uint Pcg(uint v)
	{
		uint state = v * 747796405u + 2891336453u;
		uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
		return (word >> 22u) ^ word;
	}
	float Wrap(float v, float h) { return v - 2.0 * h * floor((v + h) / (2.0 * h)); }
};
FSplash S;
float Slot = SlotUV.x + 64.0 * SlotUV.y;
float period = Splash.x;
float lifetime = Splash.y;
float halfSide = Splash.z;
float cycles = Time / period + frac(Slot * 0.6180339887);
float cycle = floor(cycles);
float age = frac(cycles) * period;
if (age >= lifetime || Slot >= Active * Splash.w)
{
	return -P0;
}
uint h = S.Pcg((uint)Slot * 65536u + (uint)cycle);
float2 xy = (float2(h & 0xFFFFu, h >> 16u) / 65535.0 * 2.0 - 1.0) * halfSide;
xy = float2(S.Wrap(xy.x + GroundShift.x, halfSide), S.Wrap(xy.y + GroundShift.y, halfSide));
float size = DropMm * 0.1 * (2.0 + 6.0 * age / lifetime);
float3 toward = float3(xy, 0.0);
float3 side = dot(toward, toward) > 1.0 ? normalize(float3(-xy.y, xy.x, 0.0)) : float3(1.0, 0.0, 0.0);
float3 target = float3(xy, GroundRelZ) + side * (Corner.x - 0.5) * size
              + float3(0.0, 0.0, Corner.y * size * 0.7);
return target - P0;
