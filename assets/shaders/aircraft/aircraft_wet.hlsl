// M_AircraftPaint / M_AircraftBareMetal / M_AircraftGlass: the wet airframe
// (visual overhaul, module wet-airframe-canopy; scripts/aircraft_wet_layer.py
// grafts it onto each master). BEAUTY ONLY in effect: the C++ sets Wetness
// only on the beauty look MIDs; at Wetness 0 every output equals its input.
//
// * film: albedo -> lerp(albedo, albedo^2, wet * porosity) (never brighter),
//   roughness -> lerp(r, min(r, WetRoughness), wet) (never rougher);
// * rivulets: thin lines of a tiled hash noise stretched along the flow and
//   panned with it. At or above BeadingMaxKts the flow is the airstream (object
//   -X, StreakSpeedPerKt x airspeed cm/s); below, gravity (world -Z expressed
//   in the object frame, so the pattern stays on the airframe) at a slow run.
//   On smooth surfaces water smooths them; on glass (BeadAmount 1) a streak
//   scatters, so the target roughness goes from WetRoughness/2 to the bead's;
// * beads (gravity regime only): round drops on a jittered 3D lattice.
// The noise is of the LOCAL position and the FDM's time: replay-identical.
// Pixels only (no world position offset): labels are unchanged.
//
// Inputs:
//   LocalPos    float3  local (object) position, cm
//   NormalWS    float3  vertex normal, world
//   AxisX       float3  the object's local X axis in world space
//   AxisY       float3  the object's local Y axis in world space
//   AxisZ       float3  the object's local Z axis in world space
//   Albedo      float3  the master's base colour
//   Roughness   float   the master's roughness
//   Wetness     float   the airframe film, 0..1 (FlightSimAircraftWet.cpp)
//   RainRateMmh float   the rain rate the rivulets see, mm/h
//   AirspeedKts float   true airspeed, kt
//   TimeS       float   the FDM's time, s
//   WetParams   float4  (Porosity, WetRoughness, StreakSpeedPerKt, BeadingMaxKts)
//   WetShape    float4  (BeadAmount, StreakPitchCm, StreakLengthCm, RivuletFullMmh)
// Returns float4: rgb the wet albedo, a the wet roughness.
// Additional output WetCoat (float1): the clear-coat mask, 0..1 (paint only).
#define FSWET_HASH(OUT, P) { float3 fswh_ = frac((P) * 0.1031); fswh_ += dot(fswh_, fswh_.zyx + 31.32); OUT = frac((fswh_.x + fswh_.y) * fswh_.z); }
const float GravityRunCmS = 3.0;
const float BeadRoughness = 0.3;
float wet = saturate(Wetness);
float porosity = saturate(WetParams.x);
float wetRough = WetParams.y;
float speedPerKt = WetParams.z;
float beadMaxKts = WetParams.w;
float beadAmount = saturate(WetShape.x);
float pitch = max(WetShape.y, 0.1);
float segLen = max(WetShape.z, 0.1);
float rivFull = max(WetShape.w, 0.01);

float3 axX = normalize(AxisX);
float3 axY = normalize(AxisY);
float3 axZ = normalize(AxisZ);
float3 nL = normalize(float3(dot(NormalWS, axX), dot(NormalWS, axY), dot(NormalWS, axZ)));
// world -Z in the object frame: (-AxisX.z, -AxisY.z, -AxisZ.z)
float3 gL = normalize(-float3(axX.z, axY.z, axZ.z) + float3(0.0, 0.0, -1.0e-4));
bool airflow = AirspeedKts >= beadMaxKts;
float3 flowDir = airflow ? float3(-1.0, 0.0, 0.0) : gL;
float speed = airflow ? speedPerKt * AirspeedKts : GravityRunCmS;
float3 refAxis = abs(flowDir.z) < 0.9 ? float3(0.0, 0.0, 1.0) : float3(0.0, 1.0, 0.0);
float3 across1 = normalize(cross(flowDir, refAxis));
float3 across2 = cross(flowDir, across1);
float along = dot(LocalPos, flowDir) - speed * TimeS;
float coverage = wet * saturate(RainRateMmh / rivFull);

float riv = 0.0;
float wsum = 0.0;
for (int k = 0; k < 2; ++k)
{
    float3 acrossDir = k == 0 ? across1 : across2;
    // a lattice of lines along the flow: they read on surfaces that contain
    // the across direction (triplanar-style weight by the normal)
    float w = saturate(1.0 - abs(dot(nL, acrossDir)));
    float a = dot(LocalPos, acrossDir) / pitch;
    float cell = floor(a);
    float f = frac(a) - 0.5;
    float h0;
    float h1;
    float h2;
    FSWET_HASH(h0, float3(cell, k, 1.0));
    FSWET_HASH(h1, float3(cell, k, 2.0));
    float offset = (h0 - 0.5) * 0.6;
    float width = 0.08 + 0.12 * h1;
    float profile = saturate(1.0 - abs(f - offset) / width);
    float s = along / segLen + h1 * 7.0;
    float seg = floor(s);
    float t = frac(s);
    FSWET_HASH(h2, float3(cell, seg, 3.0 + k));
    float present = h2 < coverage ? 1.0 : 0.0;
    float shape = smoothstep(0.0, 0.1, t) * (1.0 - smoothstep(0.55, 1.0, t));
    riv += w * profile * shape * present;
    wsum += w;
}
riv = wsum > 1.0e-4 ? riv / wsum : 0.0;
// a surface facing straight into the flow carries impacts, not streaks
riv *= saturate(1.2 - abs(dot(nL, flowDir)));

float bead = 0.0;
if (!airflow && beadAmount > 0.0 && wet > 0.0)
{
    float beadPitch = pitch * 0.6;
    float3 q = LocalPos / beadPitch;
    float3 baseCell = floor(q);
    for (int z = -1; z <= 1; ++z)
    {
        for (int y = -1; y <= 1; ++y)
        {
            for (int x = -1; x <= 1; ++x)
            {
                float3 c = baseCell + float3(x, y, z);
                float3 jitter;
                float hr;
                float hp;
                FSWET_HASH(jitter.x, c + 0.17);
                FSWET_HASH(jitter.y, c + 0.53);
                FSWET_HASH(jitter.z, c + 0.91);
                FSWET_HASH(hr, c + 1.37);
                FSWET_HASH(hp, c + 2.11);
                float radius = 0.15 + 0.25 * hr;
                float d = length(q - (c + jitter));
                float drop = saturate(1.0 - d / radius);
                bead = max(bead, hp < wet ? drop * drop : 0.0);
            }
        }
    }
    bead *= beadAmount;
}

float3 sat = saturate(Albedo);
float3 albedoOut = lerp(Albedo, sat * sat, wet * porosity);
float roughOut = lerp(Roughness, min(Roughness, wetRough), wet);
roughOut = lerp(roughOut, lerp(0.5 * wetRough, BeadRoughness, beadAmount), riv);
roughOut = lerp(roughOut, max(roughOut, BeadRoughness), bead);
WetCoat = saturate(max(wet, riv));
#undef FSWET_HASH
return float4(albedoOut, roughOut);
