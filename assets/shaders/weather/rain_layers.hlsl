// M_RainLayers: the storm's falling rain as three baked layers, no particles
// (-rain-layers=on; tier 0 of swarm lane weather_fx.rain_drops.storm, its
// RainLayers.ush adapted). VISUAL-ONLY, BEAUTY-ONLY: a post-process blendable on
// the beauty capture (FlightSimWeatherBaked.cpp ApplyRainLayers); no label capture
// receives it. UNCOMPILED: written on the Mac, compiled on the Windows box.
//
// D3D11 / SM5: no loop, no derivative (SampleLevel with an analytic LOD, so the
// atan2 seam draws no line), three texture taps. Geometry: scripts/make_rain_layers.py.
// A drop at distance rho from the line through the camera along Axis is seen on the
// ray at angle theta from Axis where its travel z = rho cot(theta); the layer k is
// the shell around rho_k, tiled NREP times round the axis and TileH along it.
//
// Changes from the lane's RainLayers.ush (each reviewed, none compiled):
//  * the bin choice (Sel) and its stretch are uniform per frame: the host computes them;
//  * the travel is a per-layer phase in tiles, wrapped by the host (no float growth,
//    no jump when the stretch changes), SUBTRACTED: a drop's texel is the one whose
//    travel brought it onto this ray (the lane added it: the rain would run upward);
//  * the drops' radiance is the scene's own luminance lifted toward white by Lift (this
//    pass runs after the tonemapper, like M_WindshieldRain, where an absolute radiance
//    has no exposure to meet); neutral grey, no tint.
//
// Inputs (the Custom node's, named exactly so):
//   SceneColor  float3  PostProcessInput0 at the pixel (after the tonemapper)
//   Rel         float3  the pixel's opaque surface minus the camera, world cm
//   Axis        float3  unit, (v_drop(D0) - v_camera) / |..|, world
//   AxisRight   float3  unit, perpendicular to Axis (stable)
//   Sel         float4  one-hot: the bake's bin (channel) nearest the sweep
//   Stretch     float   sweep / that bin's sweep
//   Phase       float3  each layer's travel along Axis, in its tiles, wrapped to [0, 1)
//   PixelAngle  float   one pixel's angle (rad)
//   Opacity     float   rain gain x beauty gain x the shaft's share
//   Lift        float   the streak's luminance lifted toward white by this share
//   RhoK        float3  layers[k].rho_k_m (assets/looks/rain_layers/rain_layers.json)
//   TileH       float3  layers[k].tile_height_m
//   Scale0      float4  layers[0].bins[].alpha_scale
//   Scale1      float4  layers[1].bins[].alpha_scale
//   Scale2      float4  layers[2].bins[].alpha_scale
//   Layer0      Texture2D  T_RainLayer0 (sRGB off, wrap; Layer0Sampler)
//   Layer1      Texture2D  T_RainLayer1
//   Layer2      Texture2D  T_RainLayer2
// Returns the scene colour with the rain over it (float3).
struct FRainLayers
{
	float Alpha(Texture2D Tex, SamplerState Samp, float4 Scale, float4 Bin, float Stretch, float Rho,
	            float Tile, float Phi, float CotT, float SinT, float Ph, float Pixel, float DistCm)
	{
		// The cylinder of radius Rho about the axis is Rho / sin(theta) away (m).
		float visible = step(Rho / SinT * 100.0, DistCm);
		float span = Tile * Stretch;
		// 12 repeats round the axis (NREP); 512 x 1024 texels (NU x NV).
		float2 uv = float2(Phi * (12.0 / 6.28318530718), CotT * Rho / span - Ph);
		float du = Pixel / SinT * (12.0 / 6.28318530718) * 512.0;
		float dv = Pixel * Rho / (SinT * SinT) / span * 1024.0;
		float lod = max(0.0, log2(max(max(du, dv), 1.0e-6)));
		float4 bins = Tex.SampleLevel(Samp, uv, lod);
		return visible * dot(bins * Scale, Bin);
	}
};
FRainLayers R;
// A sky pixel's reconstructed position is ~1e19 cm away (reversed-Z far plane): scaled
// before the squares so length() cannot overflow to inf (dir would then be 0).
float3 relS = Rel * 1.0e-4;
float distS = length(relS);
float dist = distS * 1.0e4;
float3 dir = relS / max(distS, 1.0e-7);
float cosT = dot(dir, Axis);
float sinT = max(sqrt(saturate(1.0 - cosT * cosT)), 1.0e-3);
float cotT = cosT / sinT;
float3 axisUp = cross(Axis, AxisRight);
float px = dot(dir, AxisRight);
float py = dot(dir, axisUp);
// atan2(0, 0) is not defined on every GPU: a ray along the axis takes phi 0 (faded out below).
float phi = atan2(py, (abs(px) + abs(py)) > 1.0e-6 ? px : 1.0);
// The layers vanish toward the axis, where cot(theta) diverges (make_rain_layers.POLE_FADE).
float fade = smoothstep(0.15, 0.35, sinT) * Opacity;
float a0 = R.Alpha(Layer0, Layer0Sampler, Scale0, Sel, Stretch, RhoK.x, TileH.x, phi, cotT, sinT, Phase.x, PixelAngle, dist);
float a1 = R.Alpha(Layer1, Layer1Sampler, Scale1, Sel, Stretch, RhoK.y, TileH.y, phi + 1.7, cotT, sinT, Phase.y, PixelAngle, dist);
float a2 = R.Alpha(Layer2, Layer2Sampler, Scale2, Sel, Stretch, RhoK.z, TileH.z, phi + 3.1, cotT, sinT, Phase.z, PixelAngle, dist);
float alpha = 1.0 - (1.0 - saturate(a0 * fade)) * (1.0 - saturate(a1 * fade)) * (1.0 - saturate(a2 * fade));
float luma = dot(SceneColor, float3(0.2126, 0.7152, 0.0722));
float drop = luma + (1.0 - saturate(luma)) * Lift;
return lerp(SceneColor, float3(drop, drop, drop), alpha);
