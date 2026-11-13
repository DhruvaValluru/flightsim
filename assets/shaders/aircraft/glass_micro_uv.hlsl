// M_AircraftGlassReflectFine (tier 1): the tiled micro-scratch / salt-film
// coordinate, a planar projection of the local position on the two local
// axes most in the surface (the axis the vertex normal leans on most is
// dropped; the same choice as glass_reflect_uv.hlsl). Object space, so the
// pattern rides with the airframe; no mesh tangents (the FlightGear meshes'
// tangents are legacy, gotcha 5). Twin: aircraft_glass_reflect.micro_uv.
//
// Inputs:
//   LocalPos float3  local (object) position, cm
//   NormalWS float3  vertex normal, world
//   AxisX    float3  the object's local X axis in world space
//   AxisY    float3  the object's local Y axis in world space
//   AxisZ    float3  the object's local Z axis in world space
//   TileCm   float   one texture repeat, cm
// Returns float2: the micro uv.
float3 n = normalize(NormalWS);
float3 ln = abs(float3(dot(n, normalize(AxisX)), dot(n, normalize(AxisY)), dot(n, normalize(AxisZ))));
float2 p = LocalPos.xy;
if (ln.x >= ln.y && ln.x >= ln.z)
{
    p = LocalPos.yz;
}
else if (ln.y >= ln.z)
{
    p = LocalPos.xz;
}
return p / max(TileCm, 1.0);
