// cloud_sky_ao.hlsl -- M_FlightSimCloudLayersLit's sky-light occlusion (BEAUTY ONLY;
// -look-cloud-light=on, lit generation 2, 2026-11-16). Custom node body, CMOT_FLOAT1,
// wired to Ambient Occlusion. Inputs: NormAlt (the sample's height in its layer, 0..1),
// SkyBottomOcclusion (the layer's SkyLightCloudBottomOcclusion, set by the bridge),
// BaseDarkening, BaseRise.
// UE 5.7 VolumetricCloud.usf: a connected AO pin multiplies the SKY light only
// (DistantLightLuminance) and REPLACES the engine's bottom gradient
// saturate(SkyLightCloudBottomVisibility + NormAlt). So the gradient is rebuilt here and
// the flat base is the DARKER of the two (min, never a product: the engine's gradient
// and the base are one hemisphere occlusion, counted once). Albedo (Base Color) is the
// material's Albedo exactly, so the sun's single and multiple scattering lose nothing:
// a sunlit flank is as bright as with the light off. Python twin:
// core/scene/world_beauty.py cloud_sky_ao.
float h = saturate(NormAlt);
float engineVis = saturate(1.0 - saturate(SkyBottomOcclusion) + h);
float flatBase = lerp(1.0 - saturate(BaseDarkening), 1.0, smoothstep(0.0, max(BaseRise, 1e-3), h));
return min(engineVis, flatBase);
