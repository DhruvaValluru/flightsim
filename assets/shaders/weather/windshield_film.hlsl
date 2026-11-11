// M_WindshieldRain's water film (lane D, 2026-11-11; generation 3): the sheet of
// run-off and beaded water a cockpit camera sees through in heavy rain, on top of
// the procedural drops (windshield.hlsl). The film is ambientCG "Leaking 019 C"
// (CC0, scripts/fetch_weather_textures.py, THIRD_PARTY_VISUAL.md): its OpenGL
// normal map refracts the scene behind the water, its height map says where the
// water stands (rivulets and beads, not an even sheet). The material samples both
// at the screen UV (tiled FILM_TILES = 1.5 per screen height, scrolled up the
// glass by FilmV, the run-off the host integrates) and hands them here.
//
// Film is 0 by default and on every render but -quality=beauty (FFlightSimWeather
// sets it from ApplyBeautyRainVeil only): then this returns Drops exactly, and the
// material is generation 2's drops, value for value.
//
// Inputs (the Custom node's, named exactly so):
//   Drops   float3  windshield.hlsl's (du, dv, mask)
//   Normal  float3  the film's tangent-space normal (the Normal sampler: -1..1)
//   Height  float   the film's height (0..1)
//   Film    float   the film's strength (0: none; 1: the beauty's full film)
//   Aspect  float   view width / height
if (Film <= 0.0)
{
	return Drops;
}
// FILM_REFRACT = 0.012 screen heights at a full normal tilt; FILM_LEVEL 0.35: the
// height above which water stands; FILM_COVER 0.75: the most of the pixel it covers.
float water = saturate((Height - 0.35) * 3.0) * Film;
float2 shift = float2(Normal.x / Aspect, -Normal.y) * 0.012 * Film;
float3 film = float3(shift, water * 0.75);
// The drops sit on the film: where a drop is, it wins; elsewhere the film.
return Drops.z > 0.0 ? float3(Drops.xy + shift * (1.0 - Drops.z), max(Drops.z, film.z)) : film;
