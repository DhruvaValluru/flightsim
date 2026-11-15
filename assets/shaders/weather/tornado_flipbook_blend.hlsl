// M_TornadoFlipbook's crossfade weight (2026-11-14): how far the loop is from frame A
// toward frame B (tornado_flipbook_uv.hlsl), smoothstepped so a frame holds a moment
// before it dissolves into the next. Straight-line code: SM5.
//
// Inputs:
//   Time         float   sim seconds
//   Frames       float   frames baked
//   LoopSeconds  float   one loop of the flipbook, s
// Returns float: 0 = frame A, 1 = frame B.
float t = frac(frac(Time / max(LoopSeconds, 1.0e-3)) * max(Frames, 1.0));
return t * t * (3.0 - 2.0 * t);
