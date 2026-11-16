// M_FlightSimRainbow: the beauty-only rainbow (high-sky effects lane, 2026-11-15).
// The Custom node body scripts/ue_create_materials.py (create_world_rainbow)
// pastes into an UNLIT, ADDITIVE, two-sided material on the engine sphere
// FlightSimSkyFx.cpp ApplyBeautySkyFx puts about the scene origin (radius
// core/sky/sky_fx.py RAINBOW_RADIUS_KM). BEAUTY ONLY: the sphere is in
// BeautyOnlyActors, writes no depth and no custom depth, casts no shadow; it is
// built only with rain on the card and the sun above the horizon.
//
// The bow is the real one's geometry: each of nine 400-700 nm bands is a
// gaussian ring (sigma SIGMA_DEG: the sun's 0.533 deg disc and the Airy width of
// 0.5-1 mm drops, Lee 1998) about the antisolar point at the Descartes radius of
// water's n(lambda) (Hale & Querry 1973): primary 41.3-42.3 deg, red outside;
// secondary 50.4-52.3 deg, red inside, at 0.43 of the primary (Lee 1998). The
// band colours are CIE 1931 (Wyman 2013 fit) in linear sRGB, each channel
// summing to 1 over the bands. Inside the primary the inner skirt brightens
// towards the bow; Alexander's dark band between the bows is the absence of
// both (additive: nothing is darkened). Tables pinned to the Python twin by
// tests/test_sky_fx.py.
//
// Inputs (the Custom node's, named exactly so; the script's WORLD_RAINBOW_INPUTS):
//   WorldPos       float3  the pixel's absolute world position, cm
//   CameraPos      float3  the camera's absolute world position, cm
//   SunDir         float3  the atmosphere light's direction towards the sun
//   SunIlluminance float3  the sun's illuminance through the atmosphere, lux
//   Strength       float   1 - exp(-tau) of the rain path (sky_fx.rainbow_strength); 0 draws nothing
//   PrimaryPeak    float   the primary's peak radiance as a share of E / pi
//   InnerGlow      float   the inner skirt at the bow, as a share of the peak
//   InnerFoldDeg   float   the skirt's e-folding angle inside the bow, deg
//   RainTopCm      float   the rain's top (the cloud base), engine z, cm
//   TopFadeCm      float   the fade above it, cm
static const float SIGMA_DEG = 0.4215;
static const float SECONDARY_RATIO = 0.43;
static const float PRIMARY_DEG[9] = { 41.2984, 41.5119, 41.6865, 41.8312, 41.9523, 42.0548, 42.1684, 42.2617, 42.3391 };
static const float SECONDARY_DEG[9] = { 52.2978, 51.9122, 51.5970, 51.3360, 51.1175, 50.9328, 50.7280, 50.5600, 50.4205 };
static const float3 BAND_RGB[9] = {
    float3(0.01177, 0.00000, 0.05973),
    float3(0.05970, 0.00000, 0.50679),
    float3(0.00000, 0.01009, 0.37311),
    float3(0.00000, 0.17418, 0.06037),
    float3(0.00000, 0.41264, 0.00000),
    float3(0.09551, 0.35642, 0.00000),
    float3(0.54434, 0.04667, 0.00000),
    float3(0.26835, 0.00000, 0.00000),
    float3(0.02033, 0.00000, 0.00000)
};
if (Strength <= 0.0)
{
    return float3(0.0, 0.0, 0.0);
}
float3 V = normalize(WorldPos - CameraPos);
float theta = degrees(acos(clamp(dot(V, -normalize(SunDir)), -1.0, 1.0)));
// Outside 25-56 deg nothing of the bows or the skirt is left: one compare.
if (theta < 25.0 || theta > 56.0)
{
    return float3(0.0, 0.0, 0.0);
}
float3 ring = float3(0.0, 0.0, 0.0);
[unroll] for (int i = 0; i < 9; ++i)
{
    float tp = (theta - PRIMARY_DEG[i]) / SIGMA_DEG;
    float ts = (theta - SECONDARY_DEG[i]) / SIGMA_DEG;
    ring += BAND_RGB[i] * (exp(-0.5 * tp * tp) + SECONDARY_RATIO * exp(-0.5 * ts * ts));
}
float skirt = theta < PRIMARY_DEG[0] ? InnerGlow * exp(-(PRIMARY_DEG[0] - theta) / max(InnerFoldDeg, 0.1)) : 0.0;
// No rain above the cloud base: the bow fades out over TopFadeCm above it.
float x = saturate((WorldPos.z - RainTopCm) / max(TopFadeCm, 1.0));
float top = 1.0 - x * x * (3.0 - 2.0 * x);
return SunIlluminance * (Strength * PrimaryPeak * top / 3.14159265) * (ring + skirt / 3.0);
