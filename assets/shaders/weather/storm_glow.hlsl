// M_StormCell's emissive: a lightning flash glowing through the cloud. The twin of
// core/scene/storm_cell.py glow_illuminance_lux: E = I / max(d, EDGE_M)^2 exp(-d / L),
// scattered isotropically by the cloud's own extinction and albedo:
// emitted radiance per metre = sigma albedo E / (4 pi).
//
// Inputs:
//   Rel        float3  the sample's engine position minus the cell centre, cm
//   FlashRel   float3  the flash centroid's engine position minus the cell centre, cm
//   Flash      float4  intensity (cd), glow diffusion length (m), albedo, unused
//   Extinction float   the cell's extinction here (storm_cell.hlsl), 1/m
const float Edge = 250.0;
float d = max(length(Rel - FlashRel) / 100.0, Edge);
float illuminance = Flash.x / (d * d) * exp(-d / Flash.y);
// The flash's colour: (0.86, 0.92, 1.0) normalised to unit Rec.709 luminance.
float3 tint = float3(0.86, 0.92, 1.0) / 0.913;
return tint * (Extinction * Flash.z * illuminance / (4.0 * 3.14159265));
