// M_AircraftPaint / M_AircraftBareMetal: the airframe's mirror image of the
// baked sky/sea strip, added to Emissive Color (scripts/aircraft_paint_reflect.py).
// The engine's own specular IBL stays; this is the MIRROR component the
// render laptop cannot draw (D3D11 SM5: no Lumen or HW RT, SSR off on the
// constrained GPU, no reflection capture in the scene), so a glossy or wet
// panel reads as painted metal under a sky, not as a lit grey plastic.
// Gain 0 (the master's default) adds exactly nothing; the host sets it each
// step from the scene's sun (FlightSimAircraftFX.cpp, the canopy's rule:
// aircraft_glass_reflect.canopy_reflect_gain). Twin: aircraft_paint_reflect.reflect_emissive.
//
// Physically: the mirrored radiance is Fresnel(N.V) x L_env(reflect(V, N)).
// Fresnel is Schlick's about the surface's F0 (UE's: lerp(0.08 x Specular,
// BaseColor, Metallic) -- 0.04 for paint, the measured metal for bare metal
// and worn edges), with the grazing term capped by (1 - roughness) so a
// rough surface shows no mirror rim. The clear coat (paint only) is a second
// dielectric at n 1.5 (F0 0.04) on top: its own mirror by CoatAmount, and
// the base sees (1 - coat Fresnel) of the sky. Each layer's mirror fades with
// its roughness as gloss = (1 - roughness / RoughCutoff)^2: at RoughCutoff and
// above the lobe is wide enough that the engine's IBL already is the look.
// Matte paint (coat 0, roughness 0.5) therefore adds nothing dry; wet, the wet
// layer takes the coat to 1 at WetCoatRoughness and the roughness to
// WetRoughness, and the same panel mirrors the sky: the rain sheen.
// Amount is the class's double-count hedge (UNCALIBRATED).
// Generation 16: the strip's radiance is replaced, per pixel, by the scene's
// own sky above and ground below (Scene, scripts/aircraft_scene_sky.py) when
// the host sets PaintEnvSceneScale and the Sky View LUT is drawn; the Fresnel
// and gloss below are unchanged.
//
// Inputs:
//   Env           float3  T_GlassEnv_64 sample (the sRGB sampler decodes it)
//   EnvScale      float   linear radiance = decoded strip x EnvScale (glass_coastal.json env_encode_scale)
//   Gain          float   scene luminance (nits) per unit of strip radiance
//   Tint          float3  the scene's horizon hue over the strip's (white = as baked)
//   Scene         float4  generation 16 (scene_sky_env.hlsl): rgb the scene's own sky / ground
//                         radiance along the ray, a 1 to draw it instead of the strip (0 = generation 13)
//   NdotV         float   the leaned lookup normal . view, 0..1 (paint_env_uv.hlsl x)
//   F0            float3  the surface's normal-incidence reflectance (lerp(0.08 Specular, BaseColor, Metallic))
//   Roughness     float   the surface's roughness after the wet layer
//   CoatAmount    float   the clear coat after the wet layer (0 on bare metal)
//   CoatRoughness float   the clear coat's roughness after the wet layer
//   Amount        float   the class's share of the mirror, 0..1 (PaintEnvAmount)
// Returns float3: the emissive radiance added to the panel.
const float RoughCutoff = 0.5;
const float CoatF0 = 0.04;
float3 env = max(Env * EnvScale, 0.0) * max(Gain, 0.0) * max(Tint, 0.0);
env = lerp(env, max(Scene.rgb, 0.0), saturate(Scene.a));
float ndv = saturate(NdotV);
float fw = pow(1.0 - ndv, 5.0);
float rough = saturate(Roughness);
float3 f0 = saturate(F0);
float3 fBase = f0 + (max(1.0 - rough, f0) - f0) * fw;
float gBase = saturate(1.0 - rough / RoughCutoff);
gBase *= gBase;
float coat = saturate(CoatAmount);
float coatRough = saturate(CoatRoughness);
float fCoat = CoatF0 + (max(1.0 - coatRough, CoatF0) - CoatF0) * fw;
float gCoat = saturate(1.0 - coatRough / RoughCutoff);
gCoat *= gCoat;
float3 mirror = coat * fCoat * gCoat + (1.0 - coat * fCoat) * fBase * gBase;
return env * saturate(mirror) * saturate(Amount);
