// M_TornadoFlipbook's card shape (2026-11-15, hyperreal tornado-shape). The bake
// (assets/looks/tornado_vdb, JangaFX's CC0 Tornado Looping) is a top-heavy smoke plume
// floating in its frame: nothing above atlas v CropTop or below CropBottom, a wide
// rounded cap in its upper quarter and a column that narrows toward its foot. A real
// tornado is a narrow condensation funnel hanging DOWN from the storm's cloud base, so
// without re-baking this remaps the card's UV before tornado_flipbook_uv.hlsl samples
// the atlas:
//   * the crop: the card's v spans CropTop..CropBottom of the frame, so the plume's
//     foot stands on the ground contact and its cap reaches up into the wall cloud;
//   * the taper: the card's u is squeezed about the centre by a width that falls from
//     TopWidth at the top to BottomWidth at the foot (pow(v, TaperPower)), so the lower
//     funnel is drawn narrow (a rope) and the cap keeps its width; a squeezed u outside
//     the frame is weight 0 (no edge smear);
//   * the top fade: the weight rises from 0 at the card's top over TopFade of its
//     height (smoothstep), so the cap dissolves into the wall cloud's dark base
//     instead of ending on a rounded smoke lid;
//   * the dust share: 0 above, rising to 1 over the lowest DustShare of the card
//     (smoothstep), the material's lerp toward its ground-dust tint.
// Straight-line code, no loop, no texture read: SM5.
//
// Inputs:
//   UV           float2  the card's UV0 (0..1, v down)
//   CropTop      float   atlas v of the plume's top (0..1)
//   CropBottom   float   atlas v of the plume's foot (CropTop..1)
//   TopWidth     float   the width scale at the card's top (1 = the bake's)
//   BottomWidth  float   the width scale at the card's foot (< TopWidth: narrower)
//   TaperPower   float   how the width falls from top to foot (pow(v, TaperPower))
//   TopFade      float   share of the card's height the top fade spans
//   DustShare    float   share of the card's height the dust tint rises over
// Returns float4(frame u, frame v, weight 0..1, dust 0..1).
float v = saturate(UV.y);
float w = lerp(TopWidth, BottomWidth, pow(v, max(TaperPower, 1.0e-3)));
float du = (UV.x - 0.5) / max(w, 1.0e-3);
float inside = (abs(du) <= 0.5) ? 1.0 : 0.0;
float u = clamp(du + 0.5, 0.0, 1.0);
float av = lerp(saturate(CropTop), saturate(CropBottom), v);
float fade = saturate(v / max(TopFade, 1.0e-3));
fade = fade * fade * (3.0 - 2.0 * fade);
float dust = saturate((v - (1.0 - DustShare)) / max(DustShare, 1.0e-3));
dust = dust * dust * (3.0 - 2.0 * dust);
return float4(u, av, inside * fade, dust);
