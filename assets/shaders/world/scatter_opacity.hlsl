// M_FlightSimScatter's opacity mask. Visual overhaul, world lane fix pass, 2026-11-09.
// BEAUTY ONLY. The mask is the SAME in the beauty and the label passes (the scatter
// is in the labels: class, mask and depth see exactly the instances the beauty
// draws, so this is a label-safe mask, not a beauty-only effect).
//
// The glTF alpha (leaf cards), times a dithered fade on the instance's
// PerInstanceFadeAmount (1 = drawn, falling to 0 between the ISM's start and end
// cull distances: FFlightSimGroundDetail sets start = cull_start_share x cull_end_m),
// so an instance dissolves into the tile ground instead of popping at a fixed range.
// The dither is a per-pixel hash of the screen position (no temporal term: the same
// pixel in the label passes of the same frame keeps the same answer). UNVERIFIED
// compile (no engine on the authoring machine): Parameters.SvPosition is the
// material template's pixel position.
//
// Inputs (the script's WORLD_SCATTER_INPUTS["scatter_opacity"]):
//   Alpha       float  the glTF base colour alpha (1 for opaque meshes)
//   FadeAmount  float  PerInstanceFadeAmount
float2 p = floor(Parameters.SvPosition.xy);
float n = frac(52.9829189 * frac(dot(p, float2(0.06711056, 0.00583715))));
return saturate(Alpha) * (saturate(FadeAmount) > n ? 1.0 : 0.0);
