// M_AircraftPaint / M_AircraftBareMetal: exhaust soot (visual round 5, lane
// L4). Each nozzle is a float4 in the mesh's LOCAL frame (xyz the exit centre,
// cm; w the exit radius, cm; w <= 0 = no nozzle): the look instance carries
// them from the look manifest (scripts/aircraft_look.py nozzle_vectors). The
// soot lies on the skin aft of each exit (-X is aft), in a lobe that starts
// half a radius ahead of the exit (the petals), is two radii wide at the
// exit, widens one radius per three along, and fades out over LengthRadii
// radii; the lateral falloff is Gaussian in the lobe's width, broken up by
// Noise (the wear noise, 0..1). Python twin: scripts/aircraft_look.py
// soot_mask (tests pin the two to each other).
//
// Pixels only: nothing here moves geometry (no world position offset).
//
// Inputs:
//   LocalPos     float3  the pixel's local (object) position, cm
//   Nozzle0      float4  nozzle 0: xyz exit centre (local cm), w radius cm (<= 0: none)
//   Nozzle1      float4  nozzle 1, as above
//   Nozzle2      float4  nozzle 2, as above
//   Nozzle3      float4  nozzle 3, as above
//   LengthRadii  float   how many radii aft of the exit the soot fades out over
//   Noise        float   breakup noise, 0..1 (aircraft_wear.hlsl z + 0.5)
// Returns float: the soot mask (0..1).
float4 nozzles[4] = { Nozzle0, Nozzle1, Nozzle2, Nozzle3 };
float soot = 0.0;
for (int i = 0; i < 4; ++i)
{
    float r = nozzles[i].w;
    if (r <= 0.0)
    {
        continue;
    }
    float3 c = nozzles[i].xyz;
    float aft = c.x - LocalPos.x;
    float lateral = length(LocalPos.yz - c.yz);
    float lengthCm = max(LengthRadii, 0.5) * r;
    float along = saturate((aft + 0.5 * r) / (lengthCm + 0.5 * r));
    float width = r * (2.0 + max(aft, 0.0) / (3.0 * r));
    float lobe = exp(-(lateral * lateral) / (width * width));
    float fade = (1.0 - along) * (1.0 - along);
    float gate = step(-0.5 * r, aft);
    soot = max(soot, gate * fade * lobe);
}
return soot * lerp(0.6, 1.0, saturate(Noise));
