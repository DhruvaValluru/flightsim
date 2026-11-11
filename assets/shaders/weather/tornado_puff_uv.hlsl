// M_TornadoPuff's atlas lookup (visual push lane C, 2026-11-11). One camera-facing smoke
// puff (FlightSimTornadoBeauty.cpp, a UMaterialBillboardComponent element) samples one
// tile of assets/looks/tornado/puffs_atlas.png (2 x 2 tiles of Kenney's CC0 puffs), its
// UV turned about the tile's centre by Spin + Turn (Turn = PUFF_TURN_RAD_PER_S x Time)
// so neighbouring puffs never repeat and each one churns slowly. A turned UV outside
// the tile returns inside = 0 (no bleeding into the neighbouring tile).
//
// Inputs:
//   UV       float2  the sprite's UV0 (0..1)
//   Tile     float   0..3, reading order
//   Spin     float   radians, the puff's own seeded turn
//   Turn     float   radians, the slow churn
// Returns float3(atlas u, atlas v, inside 0/1).
float a = Spin + Turn;
float s = sin(a);
float c = cos(a);
float2 d = UV - 0.5;
float2 r = float2(c * d.x - s * d.y, s * d.x + c * d.y) + 0.5;
float inside = (r.x >= 0.0 && r.x <= 1.0 && r.y >= 0.0 && r.y <= 1.0) ? 1.0 : 0.0;
r = clamp(r, 0.004, 0.996);
float t = floor(clamp(Tile, 0.0, 3.0) + 0.5);
float2 origin = float2(fmod(t, 2.0), floor(t / 2.0));
return float3((r + origin) * 0.5, inside);
