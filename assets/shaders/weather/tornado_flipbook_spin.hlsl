// M_TornadoFlipbook's rotation (generation 3, 2026-11-15, hyperreal light lane tornado).
// Round #10 on p3-windows read the vdb look as a smoke plume: no rotation banding. A real
// condensation funnel shows striations, bands of brighter and darker cloud that wrap the
// funnel as helices and, as the funnel turns, slide along it like a barber pole. This
// node draws them on the one card, without re-baking: the card's frame u (after
// tornado_flipbook_shape.hlsl's taper) is read as a point on a cylinder of the plume's
// local half width hw, its visible angle theta = asin(x); a helix of Bands turns over the
// plume's height has phase 2 pi Bands h + theta - Spin Time, so a band moves the way the
// surface does at Spin rad/s. Spin is the Rankine core's solid-body rate, Vmax / Rcore
// (inside the core every radius turns at the same angular rate, so the funnel, narrower
// than the core, turns at exactly that rate: 50 / 150 = 0.33 rad/s at the card's
// defaults, core/environment/tornado.py).
//   * Contrast: the bands' brightness swing, x the limb's foreshortening sqrt(1 - x^2)
//     (a band seen edge-on at the silhouette has no area);
//   * Corrugate: the funnel's radius rippled by the same phase (1 + Corrugate sin), the
//     sample's u scaled about the centre, so the silhouette's edge steps in and out with
//     the bands, as the corrugated edge of a rope funnel does.
// hw(av): the bake's plume full width at alpha > 0.3, measured over all 64 frames of the
// committed atlas (tests/test_tornado_vdb_flipbook.py recomputes it): 0.59 of the frame at
// atlas v 0.35 falling to 0.15 at v 0.75, linear between. Contrast = Corrugate = 0 is
// generation 2 exactly (u passed through, brightness 1). Straight-line code, no loop, no
// texture read: SM5; about 20 ALU on one card (GPU cost flat).
//
// Inputs:
//   Shape       float4  tornado_flipbook_shape's (frame u, frame v, weight, dust)
//   Time        float   sim seconds
//   Spin        float   rad/s; + = the card's near surface moves right
//   Bands       float   helix turns over the plume's height (CropTop..CropBottom)
//   CropTop     float   atlas v of the plume's top
//   CropBottom  float   atlas v of the plume's foot
//   Contrast    float   the bands' brightness swing (0 = generation 2)
//   Corrugate   float   the radius ripple, share of the local half width (0 = generation 2)
// Returns float4(frame u, frame v, brightness, phase sine).
float av = Shape.y;
float h = saturate((av - CropTop) / max(CropBottom - CropTop, 1.0e-3));
float hw = 0.5 * lerp(0.59, 0.15, saturate((av - 0.35) / 0.40));
float x = clamp((Shape.x - 0.5) / max(hw, 1.0e-3), -1.0, 1.0);
float phase = 6.2831853 * Bands * h + asin(x) - Spin * Time;
float s = sin(phase);
float limb = sqrt(saturate(1.0 - x * x));
float u = 0.5 + (Shape.x - 0.5) / max(1.0 + Corrugate * s, 1.0e-3);
return float4(clamp(u, 0.0, 1.0), av, 1.0 + Contrast * s * limb, s);
