// M_WindshieldRain: drops on the glass in front of a cockpit camera (core/scene/
// rain_field.py windshield: they impinge at n_r |V| cos(theta) per m^2 of glass,
// hold below the shedding airspeed and run off above it). Returns (du, dv, mask): the
// refraction offset of the scene behind a drop (a spherical cap inverts its view) and
// how much of the pixel the drop covers. The material lerps the scene toward the
// offset sample by the mask.
//
// Inputs:
//   UV       float2  the viewport UV
//   Aspect   float   view width / height
//   Time     float   run time, s
//   Glass    float4  drops impinging per screen per s, run-off (screen heights / s),
//                    static lifetime (s), cells across the height
//   Seed     float
struct FGlass
{
	uint Pcg(uint v)
	{
		uint state = v * 747796405u + 2891336453u;
		uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
		return (word >> 22u) ^ word;
	}
	float U(uint h) { return (h & 0xFFFFFFu) / 16777216.0; }
	float Ss(float e0, float e1, float x)
	{
		if (e0 == e1) { return x < e0 ? 0.0 : 1.0; }
		float t = saturate((x - e0) / (e1 - e0));
		return t * t * (3.0 - 2.0 * t);
	}
};
FGlass G;
float cells = max(Glass.w, 1.0);
float columns = max(floor(cells * Aspect), 1.0);
float perCell = Glass.x / (cells * columns);
float runoff = Glass.y;
float3 result = float3(0.0, 0.0, 0.0);
if (perCell <= 0.0)
{
	return result;
}
float period = runoff > 0.0 ? max(1.0 / perCell, 1.0e-3) : max(Glass.z, 1.0e-3);
float2 p = float2(UV.x * Aspect, UV.y);
float cellSize = 1.0 / cells;
int column = (int)floor(p.x / cellSize);
int row0 = (int)floor(p.y / cellSize);
// A running drop crosses cells upward: look at this cell and the ones below it.
[unroll] for (int k = 0; k < 4; ++k)
{
	int row = row0 + k;
	uint h = G.Pcg(asuint(column) * 73856093u ^ asuint(row) * 19349663u ^ (uint)Seed);
	float cycles = Time / period + G.U(h);
	uint hc = G.Pcg(h + (uint)floor(cycles));
	float age = frac(cycles) * period;
	if (runoff <= 0.0 && G.U(hc ^ 0x5bd1e995u) > saturate(perCell * Glass.z))
	{
		continue;   // static glass: only this share of cells holds a drop
	}
	float radius = cellSize * (0.12 + 0.28 * G.U(hc));
	float2 centre = (float2(column, row) + float2(0.2 + 0.6 * G.U(G.Pcg(hc)), 0.2 + 0.6 * G.U(G.Pcg(hc + 1u)))) * cellSize;
	centre.y -= runoff * age;
	float stretch = 1.0 + 3.0 * saturate(runoff * 2.0);
	float2 q = (p - centre) / radius;
	q.y /= stretch;
	float d2 = dot(q, q);
	if (d2 < 1.0)
	{
		float mask = G.Ss(1.0, 0.8, sqrt(d2));
		float2 normal = q * sqrt(saturate(1.0 - d2));
		result = float3(-normal.x * radius * 2.0 / Aspect, -normal.y * radius * 2.0, mask);
	}
}
return result;
