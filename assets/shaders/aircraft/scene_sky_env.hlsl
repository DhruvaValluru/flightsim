// M_AircraftPaint / M_AircraftBareMetal / M_AircraftGlassReflect(Fine),
// LOOK_GENERATION 16 (scripts/aircraft_scene_sky.py): what the reflected ray
// sees in THIS scene, instead of the coastal lane's baked noon-over-sea strip.
// Emissive only; the reflect bodies take lerp(strip, rgb, a), so a = 0 is
// generation 13 exactly. Bounded: no loop, no texture fetch here (the two
// Sky View LUT samples are the SkyAtmosphereViewLuminance nodes feeding it).
// Twin: aircraft_scene_sky.sky_env.
//
// Above the horizon: the scene's SkyAtmosphere along the ray (Sky View LUT,
// absolute luminance, sun disk excluded: the sun highlight stays the
// directional light's GGX lobe). Cover c blends it toward the CIE standard
// overcast sky (Moon & Spencer 1942; CIE S 011/E:2003 type 1): achromatic,
// L(e) = Lz (1 + 2 sin e) / 3, Lz = OvercastShare x the clear zenith.
// Below: the scene's ground (the sky light's lower hemisphere, albedo x E / pi)
// through the air under the aircraft, exp(-tau / |r.z|) (Beer-Lambert, plane-
// parallel), plus the LUT's own in-scatter on that ray (UE builds the Sky View
// LUT with Ground = false: in-scatter only), greyed by c.
// The horizon is blurred by the GGX lobe: smoothstep(-w, w, r.z), w = 2 alpha,
// alpha = roughness^2 (Walter et al. 2007).
//
// Inputs:
//   SkyView       float3  SkyAtmosphereViewLuminance(Dir): the scene sky along the ray, cd/m2
//   SkyZenith     float3  SkyAtmosphereViewLuminance(0, 0, 1): 0 = the LUT is not drawn here
//   Ground        float3  the scene's ground radiance, cd/m2 (host: lower hemisphere x sky light)
//   GroundTau     float3  vertical optical depth from the aircraft to the ground (host)
//   Dir           float3  the reflected ray, world (scene_sky_dir.hlsl)
//   Roughness     float   the mirroring layer's roughness (horizon blur)
//   Cover         float   the scene's cloud cover, 0..1 (host)
//   OvercastShare float   the overcast zenith over the clear one (host; 1 - the gain rule's 0.75)
//   SceneScale    float   the level (host: 0.10 / 0.2 = 0.5); 0 = draw the strip
// Returns float4: rgb the radiance the ray sees x SceneScale, a 1 to use it, 0 for the strip.
const float3 Luma = float3(0.2126, 0.7152, 0.0722);
const float ValidZenith = 1.0e-4;
const float MinDown = 0.05;
const float MinW = 0.01;
float yz = dot(max(SkyZenith, 0.0), Luma);
float use = (SceneScale > 0.0 && yz > ValidZenith) ? 1.0 : 0.0;
float c = saturate(Cover);
float rz = clamp(Dir.z, -1.0, 1.0);
float3 view = max(SkyView, 0.0);
float ovc = yz * max(OvercastShare, 0.0) * (1.0 + 2.0 * saturate(rz)) / 3.0;
float3 sky = lerp(view, float3(ovc, ovc, ovc), c);
float3 trans = exp(-max(GroundTau, 0.0) / max(-rz, MinDown));
// Overcast below the horizon: the in-scatter dims to the overcast horizon value
// (L(0) = Lz / 3), not the clear LUT's in-scatter greyed (35x the sky above it).
float ovh = yz * max(OvercastShare, 0.0) / 3.0;
float3 below = max(Ground, 0.0) * trans + lerp(view, float3(ovh, ovh, ovh), c);
float a = saturate(Roughness);
a *= a;
float w = clamp(2.0 * a, MinW, 1.0);
float up = smoothstep(-w, w, rz);
return float4(lerp(below, sky, up) * max(SceneScale, 0.0) * use, use);
