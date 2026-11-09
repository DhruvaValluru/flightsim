// M_AircraftPaint / M_AircraftBareMetal: weathering masks (aircraft lane, V7).
// No baked AO or curvature map exists for these models (FlightGear .ac meshes),
// so the masks are procedural:
//   * edge wear: screen-space curvature (how fast the normal turns per cm of
//     surface, fwidth of each) between EdgeStart and EdgeEnd (1/cm), broken up
//     by noise -- the leading edges, panel corners and intake lips;
//   * grime: noise stretched along the airframe's x (streaks running aft);
//   * roughness breakup: the same noise, centred on 0.
// The noise is a 3-octave value noise of the LOCAL position (it rides with the
// aircraft and is identical frame to frame for the same pose: replay-identical).
// Pixels only (no world position offset).
//
// Inputs:
//   LocalPos   float3  local (object) position, cm
//   NormalWS   float3  vertex normal, world
//   WorldPosCm float3  world position (camera-relative is fine: only fwidth is used), cm
//   NoiseCm    float   the noise's base feature size, cm
//   EdgeStart  float   curvature where wear begins, 1/cm
//   EdgeEnd    float   curvature where wear is full, 1/cm
// Returns float4: x edge wear (0..1), y grime (0..1), z roughness noise (-0.5..0.5), w curvature (1/cm).
float3 n = normalize(NormalWS);
float curvature = length(fwidth(n)) / max(length(fwidth(WorldPosCm)), 1.0e-3);
float edge = saturate((curvature - EdgeStart) / max(EdgeEnd - EdgeStart, 1.0e-5));
float3 p = LocalPos / max(NoiseCm, 1.0);
float total = 0.0;
float amplitude = 0.5;
float norm = 0.0;
for (int o = 0; o < 3; ++o)
{
    float3 i0 = floor(p);
    float3 f = frac(p);
    f = f * f * (3.0 - 2.0 * f);
    float v[8];
    for (int k = 0; k < 8; ++k)
    {
        float3 c = i0 + float3(k & 1, (k >> 1) & 1, (k >> 2) & 1);
        v[k] = frac(sin(dot(c, float3(12.9898, 78.233, 37.719))) * 43758.5453);
    }
    float x00 = lerp(v[0], v[1], f.x);
    float x10 = lerp(v[2], v[3], f.x);
    float x01 = lerp(v[4], v[5], f.x);
    float x11 = lerp(v[6], v[7], f.x);
    total += amplitude * lerp(lerp(x00, x10, f.y), lerp(x01, x11, f.y), f.z);
    norm += amplitude;
    amplitude *= 0.5;
    p *= 2.03;
}
float noise = total / norm;
float3 q = LocalPos * float3(1.0 / 400.0, 1.0 / 30.0, 1.0 / 30.0);
float3 qi = floor(q);
float streak = frac(sin(dot(qi, float3(12.9898, 78.233, 37.719))) * 43758.5453);
float grime = smoothstep(0.55, 0.9, streak) * smoothstep(0.3, 0.7, noise);
float wear = edge * smoothstep(0.35, 0.75, noise);
return float4(wear, grime, noise - 0.5, curvature);
