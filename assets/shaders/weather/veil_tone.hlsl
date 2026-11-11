// M_RainCurtain's colour (lane D; generation 5): the veil is NEUTRAL GREY at the
// brightness of the scene behind THIS pixel, never coloured by the light that reaches it.
//
// Round 26 (r31 / r32): the LIT veil carried #10's green (the sky light's captured
// lower hemisphere is the prairie tiles). Generation 4 made it unlit and took its tone
// from four SceneColor taps 0.08 of the screen apart -- round 36: that pasted four
// shifted copies of the scene (ghost aircraft round the real one in #07, #09, #15).
// Now ONE tap at the pixel's own UV (offset 0): the translucent blend gives
// lerp(scene, lum(scene) x Shade, alpha) -- the scene desaturated and toned toward grey
// by the veil's own opacity, no spatial copy of anything.
//
// Inputs (the Custom node's, named exactly so):
//   A        float3  the scene colour at this pixel (SceneColor, offset fraction 0)
//   Shade    float   the veil's tone relative to the scene behind it (rain_veil.veil_shade)
float lum = dot(A, float3(0.2126, 0.7152, 0.0722));
return float3(lum, lum, lum) * Shade;
