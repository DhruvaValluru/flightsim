// M_AircraftCondensation: the opacity of a condensation site
// (FlightSimCondensation.cpp, core/scene/condensation.py). Lit translucent,
// BEAUTY ONLY: a medium like the clouds, rain and contrails the label captures
// never draw (not in mask, class or depth). No refraction, no vertex motion.
//
// Shape (set once per site's instance):
//   0 ribbon -- a tip vortex trail: UV.x age / lifetime, UV.y across.
//   1 sheet  -- the upper-wing sheet: UV.x 0 leading edge .. 1 aft edge,
//               UV.y 0..1 along the span (soft at both ends).
//   2 cone   -- the transonic cone: UV.x 0 collar .. 1 the recompression
//               shock, where the cloud ENDS sharply; UV.y around.
//   3 tube   -- a LEX vortex: UV.x 0 apex .. 1 aft, fading.
//
// Inputs:
//   UV       float2  per-shape coordinates above
//   Weight   float   vertex colour R: a ribbon sample's opacity when it formed (1 elsewhere)
//   Noise    float   0..1 world-space noise (the material's Noise node)
//   Opacity  float   the site's opacity this step (the C++ drives it)
//   Shape    float   0 ribbon, 1 sheet, 2 cone, 3 tube
// Returns float opacity (the DepthFade node softens it against the airframe).
float lumpy = lerp(0.55, 1.0, saturate(Noise));
float a = 0.0;
if (Shape < 0.5)
{
    float across = 1.0 - abs(UV.y * 2.0 - 1.0);
    across = across * across * (3.0 - 2.0 * across);
    a = across * (1.0 - smoothstep(0.25, 1.0, UV.x));
}
else if (Shape < 1.5)
{
    float onset = smoothstep(0.0, 0.18, UV.x);
    float aft = 1.0 - smoothstep(0.45, 1.0, UV.x);
    float span = smoothstep(0.0, 0.2, UV.y) * (1.0 - smoothstep(0.8, 1.0, UV.y));
    a = onset * aft * span;
}
else if (Shape < 2.5)
{
    // Soft where the expansion begins, dense towards the shock, then gone.
    float grow = smoothstep(0.0, 0.6, UV.x);
    float shock = 1.0 - smoothstep(0.97, 1.0, UV.x);
    a = grow * shock;
}
else
{
    a = smoothstep(0.0, 0.08, UV.x) * (1.0 - smoothstep(0.3, 1.0, UV.x));
}
return saturate(Opacity * Weight * a * lumpy);
