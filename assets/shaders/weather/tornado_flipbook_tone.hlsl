// M_TornadoFlipbook's tone and alpha (generation 3, 2026-11-15, hyperreal light lane
// tornado). Round #10 on p3-windows read the vdb look as near-black sooty smoke with a
// soft wispy outline. Two causes, both measured on the committed atlas: the texel's grey
// (median 0.49) shaded the dark generation-2 tint (0.15) down to an albedo about 0.10, the
// wall cloud's own; and a quarter of the plume's texels (alpha > 0.02) sit below alpha
// 0.21, the bake's low-density smoke wisps. A condensation funnel is neither: it is cloud
// (water droplets, single-scattering albedo > 0.999 in the visible, Hansen & Travis 1974)
// bounded by the surface on which the vortex's pressure deficit lifts air to its
// condensation level (Davies-Jones, Trapp & Bluestein 2001, Meteor. Monogr. 28 ch. 5), so
// its edge is a crisp isobar, not a smoke wisp.
//   * the alpha remap: saturate((a - AlphaLo) / (AlphaHi - AlphaLo)): the wisps below
//     AlphaLo gone, the body above AlphaHi solid, the edge a short ramp;
//   * the shade: lerp(ShadeFloor, 1, the texel's grey) x the striation brightness
//     (tornado_flipbook_spin.hlsl), lifted by SheathLift where the remapped alpha is
//     partial (the funnel's thin outer sheath: less cloud above it to self-shade, the
//     lighter condensation edge of a lit funnel). UNCALIBRATED.
// AlphaLo 0, AlphaHi 1, SheathLift 0, Striation 1 is generation 2 exactly. Straight-line
// code, no loop, no texture read: SM5.
//
// Inputs:
//   TexelA      float   the crossfaded texel's straight alpha
//   TexelR      float   the crossfaded texel's grey
//   Weight      float   tornado_flipbook_shape's weight (taper edge x top fade)
//   Striation   float   tornado_flipbook_spin's brightness (1 = none)
//   ShadeFloor  float   the shade at texel grey 0 (generation 2: 0.35)
//   AlphaLo     float   alpha remapped to 0 (generation 2: 0)
//   AlphaHi     float   alpha remapped to 1 (generation 2: 1)
//   SheathLift  float   the edge's brightening at remapped alpha 0 (generation 2: 0)
//   Opacity     float   the card's opacity
// Returns float2(shade, opacity).
float a = saturate((TexelA - AlphaLo) / max(AlphaHi - AlphaLo, 1.0e-3));
float shade = lerp(ShadeFloor, 1.0, TexelR) * Striation * (1.0 + SheathLift * (1.0 - a));
return float2(shade, a * Weight * Opacity);
