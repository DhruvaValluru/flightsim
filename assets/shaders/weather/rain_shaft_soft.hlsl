// M_RainShaft's soft silhouette (round-2b weather-fx, 2026-11-09). Round 0 #09 drew the
// weather look's rain shafts as hard-edged cones: the opacity was the same across the
// open cone's face up to its silhouette. A shaft is a column of rain, thickest along
// the line of sight through its middle: the opacity is faded where the cone's surface
// turns edge-on to the view (its radial normal perpendicular to the camera vector).
// The radial normal is the pixel's horizontal offset from the shaft's axis (the actor
// sits on the axis), so no mesh normal is read. SoftEdge 0 returns 1: the measure
// path's cones, exactly; FlightSimWeatherLook.cpp ApplyBeautyWeatherLook sets 1 on beauty.
//
// Inputs:
//   Rel      float3  the pixel's world position minus the shaft actor's (cm)
//   CamVec   float3  the camera vector (pixel to camera, world space)
//   SoftEdge float   0 (hard, the measure path's) .. 1 (silhouette faded out)
struct FRainShaftSoft
{
	float Facing(float3 rel, float3 camVec)
	{
		float r = length(rel.xy);
		float3 n = r > 1.0e-3 ? float3(rel.xy / r, 0.0) : float3(1.0, 0.0, 0.0);
		float l = length(camVec);
		return l > 1.0e-6 ? abs(dot(n, camVec / l)) : 1.0;
	}
};
FRainShaftSoft S;
if (SoftEdge <= 0.0)
{
	return 1.0;
}
float facing = S.Facing(Rel, CamVec);
float t = saturate(facing / 0.6);
return lerp(1.0, t * t * (3.0 - 2.0 * t), saturate(SoftEdge));
