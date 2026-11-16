// M_AircraftContrail World Position Offset (LOOK_GENERATION 15, #13's "four
// straight light beams"): the crossed ribbon becomes ONE camera-facing ribbon.
// The view weight of generation 14 still left the second strip a thin, bright
// line down the middle of the first whenever the camera looked along the trail
// (a chase view looks along it: (a.v)^2 ~ 0.8, so both strips kept a real
// weight and the edge-on one drew its whole profile in a few pixels). A tube of
// ice projects to the same chord profile from every azimuth about its axis, so
// the honest proxy is a strip that always faces the camera across the axis
// (the standard camera-facing ribbon), carrying that chord profile.
//
// Inputs:
//   UV          float2  y 0..1 across the strip (FlightSimAircraftFX.cpp RebuildTrail)
//   ToCamera    float3  CameraPositionWS - WorldPosition (cm, this vertex to the camera)
//   AlongXY     float2  UV1: the ribbon's unit axis, world x, y
//   AlongZStrip float2  UV2: x the axis's world z, y the strip (0 Up-normal, 1 Side-normal)
//   HalfCm      float   UV3 x: the half width at this sample, cm (the C++ writes it)
//   Facing      float   1: -contrail-facing=on (the default); 0: generation 14's
//                       crossed ribbon, no offset
// Returns float3 the offset, cm. Strip 0 is turned about the axis until its across
// direction is cross(a, v) (v the line to the camera from the strip's centre); strip
// 1 folds onto the axis (zero area: no pixels, no overdraw). No loop, no texture.
float s = UV.y * 2.0 - 1.0;
float3 axis = float3(AlongXY, AlongZStrip.x);
axis = axis / max(length(axis), 1.0e-4);
float3 side = cross(axis, float3(0.0, 0.0, 1.0));
side = length(side) > 1.0e-4 ? side / length(side) : float3(0.0, 1.0, 0.0);
float3 upN = cross(side, axis);
float3 across = AlongZStrip.y < 0.5 ? side : upN;
float3 own = across * (HalfCm * s);
float3 toCentre = ToCamera + own;
float3 facingAcross = cross(axis, toCentre);
float fl = length(facingAcross);
facingAcross = fl > 1.0e-3 ? facingAcross / fl : side;
float3 target = AlongZStrip.y < 0.5 ? facingAcross * (HalfCm * s) : float3(0.0, 0.0, 0.0);
return (target - own) * saturate(Facing);
