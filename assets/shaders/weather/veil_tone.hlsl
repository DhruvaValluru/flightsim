// M_RainCurtain's colour (lane D, round 26; generation 4): the veil is NEUTRAL GREY at
// the brightness of the scene behind it, never coloured by the light that reaches it.
//
// Round 26 (r31 / r32 on b51e22ab): #10's green was the rain veil's, not the volumetric
// fog's (-rain-veil=off: funnel 46/48/57, neutral; -look-volumetric-fog=off: 28/43/34,
// still green). The curtain was a LIT translucent surface: forward shading took the sky
// light, whose captured lower hemisphere is the tiles (green prairie), and under the
// deck that bounce dominated. Rain's veil is the scattered light of the whole scene,
// grey; so the veil is now UNLIT and its colour is the luminance of the scene behind it
// averaged over four taps a VEIL_TAP = 0.08 screen fraction apart (a local mean, so the
// veil flattens contrast as haze does, not a per-pixel copy), times Shade (the host's
// rain_veil.veil_shade: under a deck a little darker than the scene's mean). No light,
// no tint, no green: whatever the sky light or the fog carries.
//
// Inputs (the Custom node's, named exactly so):
//   A        float3  the scene colour at offset (-VEIL_TAP, -VEIL_TAP) (SceneColor, offset fraction)
//   B        float3  ... at (+VEIL_TAP, -VEIL_TAP)
//   C        float3  ... at (-VEIL_TAP, +VEIL_TAP)
//   D        float3  ... at (+VEIL_TAP, +VEIL_TAP)
//   Shade       float   the veil's tone relative to the local mean
float3 mean = 0.25 * (A + B + C + D);
float lum = dot(mean, float3(0.2126, 0.7152, 0.0722));
return float3(lum, lum, lum) * Shade;
