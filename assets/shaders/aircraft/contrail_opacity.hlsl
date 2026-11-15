// M_AircraftContrail: a condensation trail's opacity along its ribbon
// (FlightSimAircraftFX.cpp: UV.x is the sample's age / contrail.LifetimeS,
// UV.y runs 0..1 across the ribbon). Lit translucent, BEAUTY ONLY. Like the
// clouds and the rain (which the label captures never draw), a trail is a
// medium, not an occluder: where a trail crosses in front of the aircraft the
// mask still says aircraft. render.json aircraft_look.contrail records this.
//
// Inputs:
//   UV        float2  x age / contrail.LifetimeS (the formation clock), y across 0..1
//   WorldPos  float3  absolute world position, cm (the puffs stay in the air the
//                     aircraft flew through; LOOK_GENERATION 12 used the position
//                     relative to the newest sample, so every lump slid along with
//                     the aircraft)
//   Life      float   vertex colour R: age / THIS sample's lifetime 0..1 (the
//                     persistence gate stretches a sample's lifetime in
//                     ice-supersaturated air; the C++ writes it per sample)
//   Opacity   float   peak opacity
//   Formation float   age fraction before which the trail has not formed yet
//   FormationRamp float age fraction over which it forms (0.04: generation 6; the C++ sets
//                 contrail.FormationRampS / LifetimeS)
//   Puff      float   0..1 how far an aged trail breaks into puffs (0: generation 12's
//                     even lumpiness; -contrail-puffs=off; contrail.PuffBreakup)
//   PuffCellCm float  a young trail's puff cell, cm (contrail.PuffCellM x 100); the
//                     cell grows x5 over the trail's life (diffusion coarsens it)
// Returns float opacity.
//
// Round 47 (#13's "four straight light lines on the sea", rounds 5-44): the ramp was
// 0.04 of the LIFETIME, 1 s (250 m at a 747's cruise) for a 25 s trail, so from a
// chase camera 110 m back every trail was still forming where the frame shows it: four
// faint, thin, engine-less lines that read as marks on the sea. FormationRamp states
// the ramp in seconds (LOOK_GENERATION 7); -contrail-formation-ramp=off is the A/B.
//
// LOOK_GENERATION 13 (hyperreal contrails; #13's "four bright runway stripes"): the
// old body was a flat tent across (uniform brightness edge to edge), one 1.8 m
// hash lump pattern that moved with the aircraft, and no change of texture with
// age. Now: the across profile is a cylinder's chord (a tube of ice is thickest
// through its axis, soft at its rim), softening further with age; the texture is
// two octaves of trilinear value noise in WORLD space whose cell coarsens with age;
// a young trail is a dense lumpy tube, an old one breaks into separate puffs
// (the cut rises with Life) and thins out. Every number UNCALIBRATED (no frame
// rendered yet). Bounded: 16 hashes, no loops, SM5-safe.
float ramp = FormationRamp > 0.0 ? FormationRamp : 0.04;
float formed = smoothstep(Formation, Formation + ramp, UV.x);
float life = saturate(Life);
// Dense through the vortex regime, then a long thinning tail (a persistent
// trail spends most of its life as a thin veil).
float fade = 1.0 - smoothstep(0.2, 1.0, life);
fade = fade * (0.6 + 0.4 * fade);
// Across: the chord through a cylinder, sqrt(1 - x^2), soft at the rim; an
// old trail has no core left, the whole width is rim.
float x = abs(UV.y * 2.0 - 1.0);
float chord = sqrt(saturate(1.0 - x * x));
float soft = lerp(0.45, 1.0, life);
float across = smoothstep(0.0, soft, chord);
// Puffs: two octaves of trilinear value noise in world space, cells growing
// with age (turbulent diffusion coarsens a trail as it spreads).
float cellCm = max(PuffCellCm, 50.0) * (1.0 + 4.0 * life);
float3 p = WorldPos / cellCm;
float3 cell = floor(p);
float3 f = p - cell;
f = f * f * (3.0 - 2.0 * f);
// The cell index is wrapped so the hash's sine argument stays small on an
// Intel iGPU (a 10 km world is 1.7e3 cells of 6 m).
cell = fmod(cell + 4096.0, 512.0);
float3 k = float3(12.9898, 78.233, 37.719);
float h000 = frac(sin(dot(cell + float3(0, 0, 0), k)) * 43758.5453);
float h100 = frac(sin(dot(cell + float3(1, 0, 0), k)) * 43758.5453);
float h010 = frac(sin(dot(cell + float3(0, 1, 0), k)) * 43758.5453);
float h110 = frac(sin(dot(cell + float3(1, 1, 0), k)) * 43758.5453);
float h001 = frac(sin(dot(cell + float3(0, 0, 1), k)) * 43758.5453);
float h101 = frac(sin(dot(cell + float3(1, 0, 1), k)) * 43758.5453);
float h011 = frac(sin(dot(cell + float3(0, 1, 1), k)) * 43758.5453);
float h111 = frac(sin(dot(cell + float3(1, 1, 1), k)) * 43758.5453);
float n1 = lerp(lerp(lerp(h000, h100, f.x), lerp(h010, h110, f.x), f.y),
                lerp(lerp(h001, h101, f.x), lerp(h011, h111, f.x), f.y), f.z);
float3 p2 = WorldPos / (cellCm * 0.37) + float3(17.0, 29.0, 43.0);
float3 cell2 = fmod(floor(p2) + 4096.0, 512.0);
float3 f2 = p2 - floor(p2);
f2 = f2 * f2 * (3.0 - 2.0 * f2);
float g000 = frac(sin(dot(cell2 + float3(0, 0, 0), k)) * 43758.5453);
float g100 = frac(sin(dot(cell2 + float3(1, 0, 0), k)) * 43758.5453);
float g010 = frac(sin(dot(cell2 + float3(0, 1, 0), k)) * 43758.5453);
float g110 = frac(sin(dot(cell2 + float3(1, 1, 0), k)) * 43758.5453);
float g001 = frac(sin(dot(cell2 + float3(0, 0, 1), k)) * 43758.5453);
float g101 = frac(sin(dot(cell2 + float3(1, 0, 1), k)) * 43758.5453);
float g011 = frac(sin(dot(cell2 + float3(0, 1, 1), k)) * 43758.5453);
float g111 = frac(sin(dot(cell2 + float3(1, 1, 1), k)) * 43758.5453);
float n2 = lerp(lerp(lerp(g000, g100, f2.x), lerp(g010, g110, f2.x), f2.y),
                lerp(lerp(g001, g101, f2.x), lerp(g011, g111, f2.x), f2.y), f2.z);
float n = 0.65 * n1 + 0.35 * n2;
// A young trail is one lumpy body (0.7..1); an aged one is cut into puffs:
// the cut rises with Life, so the gaps open as the trail thins.
float cut = saturate(Puff) * smoothstep(0.1, 1.0, life) * 0.75;
float puffs = saturate((n - cut) / max(1.0 - cut, 0.05));
float lumpy = lerp(0.7 + 0.3 * n, 0.25 + 0.75 * puffs, saturate(Puff));
return saturate(Opacity * formed * fade * across * lumpy);
