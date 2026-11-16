// M_AircraftContrail Normal, WORLD space (LOOK_GENERATION 15): the camera-facing
// ribbon (contrail_facing.hlsl) shades as the near half of the tube it stands for.
// At UV.y's s = 2y - 1 across the strip, the tube's surface normal is
// across x s + n x sqrt(1 - s^2), across = cross(a, v) as the offset builds it and
// n the camera-facing normal (v less its axial part). Under the D3D11 SM5
// translucency lighting volume (TLM_VolumetricDirectional) the sun side of the
// tube is lit and the far side gets only the sky: darker on the shadow side, as a
// real trail is (no emissive anywhere).
//
// Inputs:
//   UV           float2  y across 0..1
//   CameraDir    float3  CameraVectorWS (pixel to camera)
//   AlongXY      float2  UV1: axis x, y
//   AlongZStrip  float2  UV2: axis z, strip
//   VertexNormal float3  VertexNormalWS (generation 14's half-cylinder normals)
//   Facing       float   1 the tube normal; 0 the vertex normal (generation 14)
// Returns float3 a unit world normal.
float s = clamp(UV.y * 2.0 - 1.0, -1.0, 1.0);
float3 axis = float3(AlongXY, AlongZStrip.x);
axis = axis / max(length(axis), 1.0e-4);
float3 v = CameraDir / max(length(CameraDir), 1.0e-4);
float3 n = v - axis * dot(axis, v);
float nl = length(n);
float3 across = cross(axis, v);
float al = length(across);
float3 tube = across / max(al, 1.0e-4) * s + n / max(nl, 1.0e-4) * sqrt(saturate(1.0 - s * s));
// Looking straight down the axis there is no across: the normal is the view line.
tube = (nl > 1.0e-3 && al > 1.0e-3) ? tube : v;
float3 vn = VertexNormal / max(length(VertexNormal), 1.0e-4);
return normalize(lerp(vn, tube, saturate(Facing)) + float3(0.0, 0.0, 1.0e-5));
