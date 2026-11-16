// cloud_albedo.hlsl -- M_FlightSimCloudLayers' albedo (BEAUTY ONLY; sky-clouds lane,
// 2026-11-15, -look-cloud-light). Custom node body, CMOT_FLOAT1, wired to Base Color.
// Inputs: Albedo, Extinction (cloud_layers.hlsl's output, 1/m), NormAlt, WorldPos,
// CameraPos (cm), SunDirWS (unit vector towards the sun, set by the bridge),
// PowderAmount, PowderDepthM, BaseDarkening, BaseRise.
// albedo x powder x base. Powder (Schneider 2015): 1 - exp(-2 sigma L), applied on the
// side facing away from the sun only, so a backlit rim keeps its silver lining. Base:
// the lowest BaseRise of the layer fades from (1 - BaseDarkening) to 1 (flat darker
// bases). PowderAmount 0 and BaseDarkening 0 (the material's defaults, -look-cloud-light
// =off) return Albedo exactly. Python twin: core/scene/world_beauty.py cloud_albedo.
float sigma = max(Extinction, 0.0);
float powder = 1.0 - exp(-2.0 * sigma * max(PowderDepthM, 0.0));
float3 viewDir = normalize(WorldPos - CameraPos + float3(0.0, 0.0, 1e-3));
float cosSun = dot(viewDir, normalize(SunDirWS + float3(0.0, 0.0, 1e-6)));
float w = saturate(PowderAmount) * saturate(0.5 - 0.5 * cosSun);
float base = lerp(1.0 - saturate(BaseDarkening), 1.0, smoothstep(0.0, max(BaseRise, 1e-3), saturate(NormAlt)));
return Albedo * lerp(1.0, powder, w) * base;
