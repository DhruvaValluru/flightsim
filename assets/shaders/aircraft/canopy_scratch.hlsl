// M_AircraftGlass: canopy micro-scratches (visual overhaul, module
// wet-airframe-canopy; scripts/aircraft_wet_layer.py add_canopy_scratch).
// A wiped canopy is covered in fine scratches running on circles (the wipe
// swirls); into the sun each one lights where it is perpendicular to the
// light's reflection, so the highlight smears ACROSS the scratches -- along
// the radial. The tangent returned is on the circle about the canopy centre
// (in the surface); the anisotropy is NEGATIVE so the GGX lobe stretches
// along the bitangent (the radial). Scratches clump on rings about the
// centre (hash per ring), scaled by ScratchDensity.
// Needs r.AnisotropicMaterials (1 at ShadingQuality@Cine in 5.7.4's
// BaseScalability.ini) and a WORLD-space tangent: the glass master's normal is
// world space with the vertex normal wired. Legacy Default Lit; Substrate off.
// The glass stays OPAQUE. Pixels only (no world position offset).
//
// Inputs:
//   LocalPos          float3  local (object) position, cm
//   NormalWS          float3  vertex normal, world
//   AxisX             float3  the object's local X axis in world space
//   AxisY             float3  the object's local Y axis in world space
//   AxisZ             float3  the object's local Z axis in world space
//   CanopyCentre      float3  the swirl centre in the local frame, cm
//   ScratchDensity    float   how much of the glass is scratched, 0..1
//   ScratchAnisotropy float   how strongly the scratches stretch the highlight, 0..1
// Returns float4: xyz the scratch tangent (world, unit, in the surface), w the anisotropy (-1..0).
#define FSCS_HASH(OUT, P) { float3 fsch_ = frac((P) * 0.1031); fsch_ += dot(fsch_, fsch_.zyx + 31.32); OUT = frac((fsch_.x + fsch_.y) * fsch_.z); }
const float RingCm = 0.8;
float3 n = normalize(NormalWS);
float3 d = LocalPos - CanopyCentre;
float3 dW = d.x * AxisX + d.y * AxisY + d.z * AxisZ;
float3 t = cross(n, dW);
float len = length(t);
if (len < 1.0e-3)
{
    // at the centre (or a radial along the normal): any tangent in the surface
    t = cross(n, normalize(AxisX));
    len = length(t);
}
t = len > 1.0e-6 ? t / len : normalize(AxisY);
float ring = floor(length(d) / RingCm);
float h;
FSCS_HASH(h, float3(ring, 0.37, 5.0));
float clump = saturate(ScratchDensity * (0.35 + 1.3 * h));
#undef FSCS_HASH
return float4(t, -saturate(ScratchAnisotropy) * clump);
