// M_FlightSimCloudImpostor: one pre-rendered impostor cloud on a camera-facing quad
// (-cloud-impostors=pilot|on, FlightSimImpostorClouds.cpp). BEAUTY ONLY: the quads
// are beauty-only actors (VisualScene.BeautyOnlyActors), so no label, depth or mask
// pass draws them and a measure render never builds them.
//
// The cloud was rendered ONCE in Blender Cycles (scripts/bake_cloud_impostors.py,
// JangaFX's CC0 Cloud Pack) into a full-sphere octahedral atlas of VIEWS x VIEWS
// frames with SIX-WAY lighting. Conventions: scripts/cloud_impostor_math.py, which
// tests pin this file against:
//   * cloud object space is Blender's (x east, y north, z up); world -> object is
//     rotate by -Yaw about z, then y -> -y;
//   * d = unit(camera - centre) in object space; oct_encode(d) picks the three
//     frames of its triangle on the grid's vertices, barycentric weights;
//   * the quad's pixel is the point P = (u - 0.5) 2R right + (0.5 - v) 2R up of the
//     current camera's frame basis (forward -d, up from z, y near a pole); each
//     frame samples P projected onto ITS image plane (the virtual-plane impostor);
//   * POS.rgb = light from +x, +y, +z, NEG.rgb = from -x, -y, -z (gamma 2.2 over
//     LightScale, straight), POS.a = opacity, NEG.a = 0.5 + 0.5 x depth offset / R.
// Lighting: a white Lambert plane under unit irradiance bakes to ~1, so the sun's
// share is value x E / pi, and a uniform sky of luminance Ls (an irradiance pi Ls on
// each axis) gives Ls x the six channels' sum. SunGain / AmbientGain UNCALIBRATED.
// SM5: straight code plus one [unroll] loop of exactly 3; SampleLevel, no derivatives.
//
// Inputs:
//   UV              float2     the quad's texture coordinate (u right, v down)
//   CamPos          float3     camera position, world cm
//   ObjPos          float3     the instance's centre, world cm
//   Yaw             float      the instance's turn about world z, radians
//   Views           float      the atlas's VIEWS
//   FramePx         float      one frame's size, px (the atlas is Views x FramePx)
//   SphereRadiusCm  float      the instance's bounding-sphere radius, cm (the quad is 2R)
//   LightScale      float      the bake's light_scale
//   SunDir          float3     the atmosphere light's direction (toward the sun), world
//   SunIlluminance  float3     its illuminance at the cloud
//   SkyLum          float3     the sky's distant scattered luminance
//   SunGain         float      the sun term's gain (1 = the bake's physics)
//   AmbientGain     float      the sky term's gain
//   Opacity         float      the instance's opacity multiplier
//   SceneDepth      float      the opaque scene's depth at this pixel, cm
//   PixelDepth      float      this quad pixel's depth, cm
//   SoftCm          float      the soft intersection's width, cm
//   FadeStartCm     float      the distance fade's start, cm
//   FadeEndCm       float      the distance fade's end (fully gone), cm
//   PosTex          Texture2D  the POS atlas
//   NegTex          Texture2D  the NEG atlas
struct FImpostor
{
	float3 Norm(float3 v) { return v * rsqrt(max(dot(v, v), 1.0e-12)); }
	float3 WorldToObject(float3 v, float yaw)
	{
		float c = cos(-yaw);
		float s = sin(-yaw);
		return float3(c * v.x - s * v.y, -(s * v.x + c * v.y), v.z);
	}
	float2 OctEncode(float3 d)
	{
		d = Norm(d);
		float2 p = d.xy / (abs(d.x) + abs(d.y) + abs(d.z));
		if (d.z < 0.0)
		{
			float2 sgn = float2(p.x >= 0.0 ? 1.0 : -1.0, p.y >= 0.0 ? 1.0 : -1.0);
			p = (1.0 - abs(p.yx)) * sgn;
		}
		return p * 0.5 + 0.5;
	}
	float3 OctDecode(float2 uv)
	{
		float2 p = uv * 2.0 - 1.0;
		float z = 1.0 - abs(p.x) - abs(p.y);
		if (z < 0.0)
		{
			float2 sgn = float2(p.x >= 0.0 ? 1.0 : -1.0, p.y >= 0.0 ? 1.0 : -1.0);
			p = (1.0 - abs(p.yx)) * sgn;
		}
		return Norm(float3(p, z));
	}
	void Basis(float3 d, out float3 right, out float3 up)
	{
		float3 forward = -d;
		float3 upRef = abs(d.z) > 0.999 ? float3(0.0, 1.0, 0.0) : float3(0.0, 0.0, 1.0);
		right = Norm(cross(forward, upRef));
		up = cross(right, forward);
	}
	float Decode(float c, float scale) { return pow(saturate(c), 2.2) * scale; }
};
FImpostor I;
float n = max(Views, 2.0);
float R = max(SphereRadiusCm, 1.0);
float3 d = I.Norm(I.WorldToObject(CamPos - ObjPos, Yaw));
float3 camRight;
float3 camUp;
I.Basis(d, camRight, camUp);
float3 P = (UV.x - 0.5) * 2.0 * camRight + (0.5 - UV.y) * 2.0 * camUp;   // in sphere radii
float3 L = I.Norm(I.WorldToObject(SunDir, Yaw));
float3 Lp = max(L, 0.0);
float3 Ln = max(-L, 0.0);
float2 f = I.OctEncode(d) * (n - 1.0);
float2 b = min(floor(f), n - 2.0);
float2 r = f - b;
bool upper = r.x + r.y >= 1.0;
float2 cells[3];
float wts[3];
cells[0] = upper ? b + float2(1.0, 1.0) : b;
wts[0] = upper ? r.x + r.y - 1.0 : 1.0 - r.x - r.y;
cells[1] = b + float2(1.0, 0.0);
wts[1] = upper ? 1.0 - r.y : r.x;
cells[2] = b + float2(0.0, 1.0);
wts[2] = upper ? 1.0 - r.x : r.y;
float sunTerm = 0.0;
float skyTerm = 0.0;
float alpha = 0.0;
float depthOffset = 0.0;
float inset = 0.5 / max(FramePx, 1.0);
[unroll] for (int k = 0; k < 3; ++k)
{
	float3 df = I.OctDecode(cells[k] / (n - 1.0));
	float3 fr;
	float3 fu;
	I.Basis(df, fr, fu);
	float2 fuv = float2(0.5 + 0.5 * dot(P, fr), 0.5 - 0.5 * dot(P, fu));
	float inside = all(fuv > 0.0) && all(fuv < 1.0) ? 1.0 : 0.0;
	float2 auv = (cells[k] + clamp(fuv, inset, 1.0 - inset)) / n;
	float4 pos = PosTex.SampleLevel(PosTexSampler, auv, 0.0);
	float4 neg = NegTex.SampleLevel(NegTexSampler, auv, 0.0);
	float3 lp = float3(I.Decode(pos.r, LightScale), I.Decode(pos.g, LightScale), I.Decode(pos.b, LightScale));
	float3 ln = float3(I.Decode(neg.r, LightScale), I.Decode(neg.g, LightScale), I.Decode(neg.b, LightScale));
	float a = pos.a * inside;
	float w = wts[k];
	sunTerm += w * a * (dot(lp, Lp) + dot(ln, Ln));
	skyTerm += w * a * (lp.x + lp.y + lp.z + ln.x + ln.y + ln.z);
	alpha += w * a;
	depthOffset += w * a * (neg.a * 2.0 - 1.0);
}
float inv = alpha > 1.0e-4 ? 1.0 / alpha : 0.0;
float3 radiance = SunGain * SunIlluminance * (sunTerm * inv) / 3.14159265 + AmbientGain * SkyLum * (skyTerm * inv);
float surface = PixelDepth - depthOffset * inv * R;
float soft = saturate((SceneDepth - surface) / max(SoftCm, 1.0));
float dist = length(ObjPos - CamPos);
float fade = saturate((FadeEndCm - dist) / max(FadeEndCm - FadeStartCm, 1.0));
return float4(radiance, saturate(alpha * Opacity * soft * fade));
