// Alpine aircraft detail layer (visual-only). Custom-node body for the class
// masters (M_AircraftPaint, M_AircraftBareMetal). D3D11 / SM5: plain texture
// samples and arithmetic, no loops, no derivatives beyond the sampler's own.
// Python twin: ../alpine_pbr_look.py shade(); tests pin the constants below
// to it. Tier 0 calls AlpineDetail only; tier >= 1 also AlpineNormal.
//
// Inputs the graph supplies:
//   Base            float3  the master's base colour after its own AlbedoMax
//   Detail          float4  T_AlpineDetail sample (see AlpineUV)
//   Roughness, Metallic, ClearCoat   the class values
//   FrostGeo        float   saturate(dot(N_local, float3(1,0,0)))^2  (forward-facing skin)
//   AlbedoLo/Hi     float   the class's albedo range
//   GrimeAmount, AlbedoModAmount, FrostAmount, FrostOpacity, RoughnessBreakup
#define ALPINE_TILE_CM 240.0
#define ALPINE_ALBEDO_MOD_MIN 0.88
#define ALPINE_GRIME_DARKEN_MAX 0.40
#define ALPINE_GRIME_AMOUNT_MAX 0.25
#define ALPINE_FROST_ALBEDO 0.75
#define ALPINE_FROST_ROUGHNESS 0.85
#define ALPINE_FROST_SOFTNESS 0.08
#define ALPINE_ROUGHNESS_MIN 0.045
#define ALPINE_GRIME_ROUGHNESS_ADD 0.20
#define ALPINE_NORMAL_STORE_GAIN 6.0
#define ALPINE_TOP_PROJECTION_NZ 0.7

// Object-space projection, U along body X (the airflow). Tiers 0-1: ONE
// sample per texture, the side or the top plane picked per pixel. The pick
// is a hard switch, so sample with the gradients of the picked plane (pass
// ddx/ddy of this UV to SampleGrad) or the mip seam shows as a 1 px line.
float2 AlpineUV(float3 LocalPosCm, float3 LocalNormal)
{
    float top = step(ALPINE_TOP_PROJECTION_NZ, abs(LocalNormal.z));
    return lerp(LocalPosCm.xz, LocalPosCm.xy, top) / ALPINE_TILE_CM;
}

struct FAlpineDetail
{
    float3 Base;
    float Roughness;
    float Metallic;
    float ClearCoat;
    float Frost;
};

FAlpineDetail AlpineDetail(float3 Base, float4 Detail, float Roughness, float Metallic,
                           float ClearCoat, float FrostGeo, float AlbedoLo, float AlbedoHi,
                           float GrimeAmount, float AlbedoModAmount, float FrostAmount,
                           float FrostOpacity, float RoughnessBreakup)
{
    FAlpineDetail o;
    float grime = saturate(Detail.g) * clamp(GrimeAmount, 0.0, ALPINE_GRIME_AMOUNT_MAX);
    float mod = lerp(1.0, lerp(ALPINE_ALBEDO_MOD_MIN, 1.0, saturate(Detail.a)), saturate(AlbedoModAmount));
    float mult = mod * (1.0 - ALPINE_GRIME_DARKEN_MAX * grime);

    float cover = saturate(FrostAmount) * saturate(FrostGeo);
    float edge = 1.0 - cover;
    float frost = cover > 0.0 ? smoothstep(edge, edge + ALPINE_FROST_SOFTNESS, Detail.b) : 0.0;
    frost *= saturate(FrostOpacity);

    float3 c1 = clamp(Base, AlbedoLo, AlbedoHi) * mult;
    // frost only ever brightens: rime never greys a white livery
    float3 c2 = max(c1, lerp(c1, ALPINE_FROST_ALBEDO, frost));
    o.Base = clamp(c2, AlbedoLo, AlbedoHi);

    float r = Roughness + (Detail.r - 0.5) * 2.0 * RoughnessBreakup + grime * ALPINE_GRIME_ROUGHNESS_ADD;
    o.Roughness = lerp(clamp(r, ALPINE_ROUGHNESS_MIN, 1.0), ALPINE_FROST_ROUGHNESS, frost);
    o.Metallic = Metallic * (1.0 - frost);
    o.ClearCoat = ClearCoat * (1.0 - frost);
    o.Frost = frost;
    return o;
}

// Tier >= 1. NormalTexel is the raw RG of T_AlpineNormal (0..1, sampled as a
// linear colour, NOT through UE's normal-map unpack, which would renormalise
// before the gain is divided out). Returns a tangent-space normal whose z is
// always > 0.98: the perturbation cannot turn a shading normal away from the
// light (round 23). Fade Amount to 0 with distance in the graph:
//   Amount *= saturate(1 - fwidth(uv.x) * TextureSize / 4)
float3 AlpineNormal(float2 NormalTexel, float Amount)
{
    float2 s = (NormalTexel * 2.0 - 1.0) * (Amount / ALPINE_NORMAL_STORE_GAIN);
    return normalize(float3(s, 1.0));
}
