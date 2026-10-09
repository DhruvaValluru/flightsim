// M_RainDrops's world position offset: each drop of the rain box at its place in
// the air, stretched into the streak the shutter sees (core/scene/rain_field.py).
//
// The mesh (FlightSimWeather.cpp BuildRainMesh): four vertices per drop, all at the
// drop's seed position p0 (component space, cm; the component sits at the camera),
// so the vertex's own position minus the component's IS p0.
//
// Inputs:
//   P0       float3  the vertex's position minus the component's (cm)
//   Corner   float2  UV0: (0|1 across, 0|1 along)
//   Drop     float2  UV1: diameter (mm), fall speed (m/s, the card's density factor applied)
//   Extra    float2  UV2: presented width (mm), phase
//   Index    float   UV3.x: the drop's index / particle count
//   Shift    float3  wrap(air displacement - camera), engine cm (the host wraps in double)
//   FallTime float   run time, s
//   BoxHalf  float3  the box's half extent, engine cm
//   WindVel  float3  the wind at the camera, engine cm/s
//   CamVel   float3  the camera's velocity, engine cm/s
//   Shutter  float   the exposure, s
//   PixelAngle float the angle of one pixel, rad
//   Active   float   the share of drops shown here (weather.rain ambient_fraction .. 1)
struct FRainDrop
{
	float3 Wrap(float3 v, float3 h) { return v - 2.0 * h * floor((v + h) / (2.0 * h)); }
};
FRainDrop R;
if (Index >= Active)
{
	return -P0;   // collapsed onto the component origin: zero area, nothing drawn
}
float3 rel = P0 + Shift;
rel.z -= Drop.y * 100.0 * FallTime;
rel = R.Wrap(rel, BoxHalf);
float3 vel = WindVel - float3(0.0, 0.0, Drop.y * 100.0) - CamVel;
float speed = length(vel);
float3 along = speed > 1.0e-3 ? vel / speed : float3(0.0, 0.0, -1.0);
float diameterCm = Drop.x * 0.1;
float streak = max(speed * Shutter, diameterCm);
float dist = max(length(rel), 1.0);
float3 side = cross(along, rel / dist);
side = dot(side, side) > 1.0e-8 ? normalize(side) : normalize(cross(along, float3(1.0, 0.0, 0.0)));
float width = max(Extra.x * 0.1, dist * PixelAngle);
float3 corner = along * (Corner.y - 0.5) * streak + side * (Corner.x - 0.5) * width;
return rel + corner - P0;
