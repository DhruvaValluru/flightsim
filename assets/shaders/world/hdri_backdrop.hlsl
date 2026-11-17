// M_FlightSimHdriBackdrop: the photographed sky above a LOW camera (round 148,
// 2026-11-16). The Custom node body scripts/ue_create_materials.py
// (create_hdri_backdrop) pastes into an UNLIT, TRANSLUCENT, two-sided material on
// one sphere centred on the camera (FlightSimHdriSky.cpp; Python twin
// core/scene/hdri_sky.py). BEAUTY ONLY: the sphere is in BeautyOnlyActors (hidden
// on every label capture), writes no depth, no custom depth and no velocity,
// casts no shadow. Height fog and the volumetric clouds draw over it (Apply
// Fogging per pixel, Apply Cloud Fogging). VISUAL ONLY.
//
// The photograph is the 2K Poly Haven original (T_HdriBackdrop_<name>), turned by
// YawDeg about +Z exactly as the sky light turns its own copy
// (USkyLightComponent::SourceCubemapAngle: the source is sampled at R(yaw) x the
// world direction), its sun clamped at ClampLum (the prepared copy's clamp, in
// the original's units) and scaled by Scale (the prepared normalisation x the
// captured sky's irradiance ratio: the sky light's matched radiance). Opacity
// rises from 0 at HorizonLowDeg to Opacity at HorizonHighDeg of elevation, so
// the SkyAtmosphere and the fog own the horizon; around the scene's sun (light 0)
// the sphere opens over SunHoleDeg (+ the photograph's sun offset, SunSpanDeg) so
// the atmosphere's own disk and aureole show and no second sun is drawn.
//
// Where it sits: BackdropRadiusKm (8 km), the distance of a photographed sky's
// clouds, so the engine's own height fog and aerial perspective veil it as they
// would those clouds (a 150 km sphere was fogged into the bare atmosphere colour
// on the Mac look-dev, 2026-11-16). Only SKY pixels take it: an opaque surface
// behind the sphere (the scene depth below SkyDepthCm: terrain, the sea, the
// aircraft) keeps its own colour, so nothing beyond 8 km is covered.
//
// Inputs:
//   Dir            float3  the view ray, world (z up); -CameraVector
//   Sky            TextureCube object (T_HdriBackdrop_<name>), sampler SkySampler
//   SunDir         float3  toward the sun, world (SkyAtmosphereLightDirection 0)
//   SceneDepth     float   the opaque scene's depth at this pixel, cm
//   YawDeg, Scale, ClampLum, HorizonLowDeg, HorizonHighDeg, Opacity,
//   SunHoleDeg, SunSpanDeg, SkyDepthCm  scalars
// Returns float4(luminance, opacity).

float3 d = normalize(Dir);
float yaw = radians(YawDeg);
float sy = sin(yaw);
float cy = cos(yaw);
float3 r = float3(d.x * cy - d.y * sy, d.x * sy + d.y * cy, d.z);
float3 L = TextureCubeSample(Sky, SkySampler, r).rgb;
float lum = dot(L, float3(0.2126, 0.7152, 0.0722));
L *= (lum > ClampLum && lum > 0.0) ? ClampLum / lum : 1.0;
L *= max(Scale, 0.0);
float elevation = degrees(asin(clamp(d.z, -1.0, 1.0)));
float w = smoothstep(HorizonLowDeg, max(HorizonHighDeg, HorizonLowDeg + 0.01), elevation) * saturate(Opacity);
float3 s = normalize(SunDir);
float sunDeg = degrees(acos(clamp(dot(d, s), -1.0, 1.0)));
float hole = max(SunHoleDeg, 0.0) + max(SunSpanDeg, 0.0);
w *= smoothstep(hole, hole * 2.0 + 0.01, sunDeg);
w *= step(SkyDepthCm, SceneDepth);
return float4(L, w);
