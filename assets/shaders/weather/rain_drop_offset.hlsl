// M_RainDrops's world position offset: each drop of the rain box at its place in
// the air, stretched into the streak the shutter sees (core/scene/rain_field.py).
//
// The mesh (FlightSimWeather.cpp BuildRainMesh): four vertices per drop, all at the
// drop's seed position p0 (component space, cm; the component sits at the camera),
// so the vertex's own position minus the component's IS p0.
//
// The beauty rain shape (round-2b weather-fx, core/scene/weather_look.py
// beauty_rain_shape; set only by FFlightSimWeather::ApplyBeautyRainReadability under
// -quality=beauty): Density thins the drawn drops with the rate, NearThin thins the
// drops near the lens by (range / NearThin)^2 on the drop's own phase, MaxStreak
// caps the streak's angular length so a near drop never crosses the frame. Their
// defaults (1, 0, 0) leave every drop exactly where the measure path draws it.
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
//   Density  float   the beauty share of the drops drawn (1: all)
//   NearThin float   the beauty near-lens thinning range, cm (0: none)
//   MaxStreak float  the beauty streak's longest angular length, rad (0: no cap)
//   Soft     float   lane D: the beauty streak drawn (1 + Soft) x wider (0: the hard quad)
//   Vary     float   lane D: the beauty per-drop length spread, 0.45..1.55 at 1 (0: none)
//   Aperture float   hyperreal rain: the beauty's defocus smear of a drop, cm (0: a pinhole)
//
// Hyperreal rain (2026-11-14, M_RainDrops 8; weather_look.beauty_rain_defocus_cm): a drop a
// few metres from a lens focused on the scene is OUT OF FOCUS; its image is the pupil's
// disc (f / N: 9 mm on the 35 mm f/4 beauty lens, 62 mm on a 250 mm one) convolved with
// the streak, so a near drop is a wide soft smear and a far one a thin line -- the depth
// layering a photograph of rain shows. Aperture is the smear the beauty draws (the pupil
// x BEAUTY_RAIN_DEFOCUS_SHARE: the standard lens draws the scene with no depth of field,
// so a full-pupil disc would make the rain the one defocused thing in a sharp frame),
// held to RainDefocusMaxPx pixels at the drop's range (a long lens's 6 cm pupil would
// otherwise smear a near drop over 60 px into nothing). The quad grows by it ALONG the
// streak; ACROSS, the blur is the greater of the soft profile's width and the sharp width
// plus the smear, not their sum (the soft widening is the same blur drawn once). The
// opacity (its twin) spreads the same light over it. Aperture 0: unchanged. Calibrated
// numerically against generation 6 by core/scene/rain_drop_twin.py (tests/test_hyperreal_rain.py).
//
// Lane D (2026-11-11, weather_look.BEAUTY_RAIN_SOFTNESS / _VARIATION): the opacity
// (rain_drop_opacity.hlsl) carries the matching profile and the same hash, so the
// coverage follows the streak drawn. Both 0: the expressions below are the measure
// path's, value for value.
struct FRainDrop
{
	float3 Wrap(float3 v, float3 h) { return v - 2.0 * h * floor((v + h) / (2.0 * h)); }
	uint Pcg(uint v)
	{
		uint state = v * 747796405u + 2891336453u;
		uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
		return (word >> 22u) ^ word;
	}
};
FRainDrop R;
if (Index >= Active * Density)
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
if (Vary > 0.0)
{
	// The drop's own length factor (the opacity's twin hash): a sheet of varied streaks.
	float h = (R.Pcg(asuint(Index) ^ 0x68E31DA4u) & 0xFFFFFFu) / 16777216.0;
	streak *= lerp(1.0, 0.45 + 1.1 * h, Vary);
}
float dist = max(length(rel), 1.0);
if (NearThin > 0.0)
{
	float keep = dist / NearThin;
	if (Extra.y >= keep * keep)
	{
		return -P0;   // thinned near the lens (the phase is the drop's own uniform draw)
	}
}
if (MaxStreak > 0.0)
{
	streak = max(min(streak, MaxStreak * dist), diameterCm);
}
float3 side = cross(along, rel / dist);
side = dot(side, side) > 1.0e-8 ? normalize(side) : normalize(cross(along, float3(1.0, 0.0, 0.0)));
float sharp = max(Extra.x * 0.1, dist * PixelAngle);
float width = sharp;
if (Soft > 0.0)
{
	width *= 1.0 + Soft;   // a soft streak is wider; its profile (opacity) keeps its light
}
if (Aperture > 0.0)
{
	// Defocus: the smear at the drop (the scene behind is in focus, the drop is not), at
	// most RainDefocusMaxPx pixels (weather_look.BEAUTY_RAIN_DEFOCUS_MAX_PX) at its range.
	const float RainDefocusMaxPx = 2.0;
	float blur = min(Aperture, RainDefocusMaxPx * dist * PixelAngle);
	streak += blur;
	width = max(width, sharp + blur);
}
float3 corner = along * (Corner.y - 0.5) * streak + side * (Corner.x - 0.5) * width;
return rel + corner - P0;
