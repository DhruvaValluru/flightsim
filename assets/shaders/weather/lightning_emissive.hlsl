// M_LightningChannel's emissive (cd/m^2): a line source of luminous power Phi' (lm/m)
// seen across width w has luminance Phi' / (pi^2 w) (core/scene/lightning.py
// line_luminance), shaped across the ribbon by exp(-4 x^2) normalised to mean 1 over
// [-1, 1] (0.44103 the mean of the unnormalised profile), and cut at the leader's tip.
//
// Inputs:
//   Side       float   UV0.x, interpolated across the ribbon
//   Arc        float   UV0.y: the arc length from the channel's top / its length
//   Kind       float   UV1.x: 0 main, 1 branch
//   Depth      float   PixelDepth, cm
//   PixelAngle float   rad
//   RadiusCm   float
//   Power      float4  main lm/m, branch lm/m, leader progress (0..1), unused
float halfWidth = max(RadiusCm, Depth * PixelAngle * 0.75);
float widthM = 2.0 * halfWidth / 100.0;
float lumensPerM = Kind > 0.5 ? Power.y : Power.x;
float luminance = lumensPerM / (3.14159265 * 3.14159265 * widthM);
float profile = exp(-4.0 * Side * Side) / 0.44103;
float progress = Power.z;
float tip = saturate((progress + 0.02 - Arc) / 0.02);
float3 tint = float3(0.86, 0.92, 1.0) / 0.913;
return tint * (luminance * profile * tip);
