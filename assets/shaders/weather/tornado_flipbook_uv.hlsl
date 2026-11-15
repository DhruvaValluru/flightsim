// M_TornadoFlipbook's frame lookup (2026-11-14, the owner's JangaFX tornado). One
// camera-facing card (FlightSimTornadoBeauty.cpp, a UMaterialBillboardComponent element)
// plays the flipbook baked from JangaFX's CC0 "Tornado Looping" VDB by
// scripts/bake_tornado_flipbook.py: Cols x Rows frames in reading order, looping every
// LoopSeconds of SIM time (Time, set per step by FFlightSimScenarioWorld::Step). Returns
// the atlas UVs of the frame now and the next one; tornado_flipbook_blend.hlsl gives the
// crossfade between them (no pop between frames). Straight-line code, no loop: SM5.
//
// Inputs:
//   UV           float2  the card's UV0 (0..1, v down)
//   Time         float   sim seconds
//   Cols         float   frames across the atlas
//   Rows         float   frames down the atlas
//   Frames       float   frames baked (<= Cols x Rows)
//   LoopSeconds  float   one loop of the flipbook, s
// Returns float4(frame A u, v, frame B u, v).
float n = max(Frames, 1.0);
float f = frac(Time / max(LoopSeconds, 1.0e-3)) * n;
float a = floor(f);
float b = fmod(a + 1.0, n);
float2 cell = float2(1.0 / max(Cols, 1.0), 1.0 / max(Rows, 1.0));
float2 uv = clamp(UV, 0.002, 0.998) * cell;
float2 oa = float2(fmod(a, Cols), floor(a / Cols)) * cell;
float2 ob = float2(fmod(b, Cols), floor(b / Cols)) * cell;
return float4(uv + oa, uv + ob);
