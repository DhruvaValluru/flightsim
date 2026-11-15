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
//   PuffCellCm float  the body puff cell, cm (contrail.PuffCellM x 100); the three
//                     noise octaves have FIXED cells (0.37x, 1x, 5x of it) and
//                     Life only moves the blend weights towards the coarse one
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
// through its axis, soft at its rim) raised to a power that rises with age, with a
// rim softening on top; the texture is three octaves of trilinear value noise in
// WORLD space; a young trail is a dense lumpy tube, an old one breaks into
// separate puffs (the cut rises with Life) and thins out. Every number
// UNCALIBRATED (no frame rendered yet). Bounded: 24 hashes, no loops, SM5-safe.
//
// Review fixes (same generation, before any frame was rendered):
//   * The noise was sampled at WorldPos / (PuffCellCm x (1 + 4 Life)): a scale about
//     the WORLD ORIGIN by a factor that changes every frame, so at cruise (7 km out)
//     the pattern at a fixed point swept ~270 cells/s and the lumps re-rolled every
//     frame (shimmer in clips). Now every octave has a FIXED cell size and only the
//     blend weights move with Life: a fixed world point keeps its noise value (the
//     twin aircraft_look.contrail_puff_noise; tests/test_hyperreal_contrails.py).
//   * across = smoothstep(0, lerp(0.45, 1, life), chord) made a young trail a
//     flat-topped box over 89 % of its width (flatter than the old tent: worse
//     runway stripes). Now across = chord^k x a rim softening, so the profile varies
//     over the whole width at every age (aircraft_look.contrail_across).
//   * The hash wrapped the BASE cell only and added the +1 corners after it, a
//     discontinuity every 512 cells on every axis. Each corner is wrapped after
//     its offset (cA / cB below), so the value at a shared corner is the same from
//     both sides: no seam.
float ramp = FormationRamp > 0.0 ? FormationRamp : 0.04;
float formed = smoothstep(Formation, Formation + ramp, UV.x);
float life = saturate(Life);
// Dense through the vortex regime, then a long thinning tail (a persistent
// trail spends most of its life as a thin veil).
float fade = 1.0 - smoothstep(0.2, 1.0, life);
fade = fade * (0.6 + 0.4 * fade);
// Across: the chord through a cylinder, sqrt(1 - x^2), raised to a power that
// rises with age (a young tube is thickest through its axis and still varies
// right across its width; an old veil is a soft parabola with no core), times a
// rim softening that widens with age. Never a smoothstep OF the chord: that
// flattened the top into a box.
float x = abs(UV.y * 2.0 - 1.0);
float chord = sqrt(saturate(1.0 - x * x));
float acrossPower = lerp(1.0, 2.0, life);
float rim = lerp(0.25, 0.6, life);
float across = pow(max(chord, 1.0e-4), acrossPower) * smoothstep(0.0, rim, chord);
// Puffs: three octaves of trilinear value noise in world space, each with a
// FIXED cell (detail 0.37x, body 1x, coarse 5x of PuffCellCm). Life moves only
// the blend weights towards the coarse octave (turbulent diffusion coarsens a
// trail as it spreads), never the cells: a fixed point in the air keeps its
// lump from frame to frame.
float cell0 = max(PuffCellCm, 50.0);
float wDetail = lerp(0.35, 0.15, life);
float wBody = lerp(0.65, 0.35, life);
float wCoarse = lerp(0.0, 0.5, life);
float3 k = float3(12.9898, 78.233, 37.719);
// Body octave. The cell index is wrapped to 0..512 so the hash's sine argument
// stays small on an Intel iGPU (a 10 km world is 1.7e3 cells of 6 m); EACH
// corner is wrapped after its +1 offset (cA is the low corner, cB the high one),
// so the hash at a shared corner agrees from both sides of the wrap: no seam.
float3 p = WorldPos / cell0;
float3 cell = floor(p);
float3 f = p - cell;
f = f * f * (3.0 - 2.0 * f);
float3 cA = cell - 512.0 * floor(cell / 512.0);
float3 cB = (cell + 1.0) - 512.0 * floor((cell + 1.0) / 512.0);
float h000 = frac(sin(dot(float3(cA.x, cA.y, cA.z), k)) * 43758.5453);
float h100 = frac(sin(dot(float3(cB.x, cA.y, cA.z), k)) * 43758.5453);
float h010 = frac(sin(dot(float3(cA.x, cB.y, cA.z), k)) * 43758.5453);
float h110 = frac(sin(dot(float3(cB.x, cB.y, cA.z), k)) * 43758.5453);
float h001 = frac(sin(dot(float3(cA.x, cA.y, cB.z), k)) * 43758.5453);
float h101 = frac(sin(dot(float3(cB.x, cA.y, cB.z), k)) * 43758.5453);
float h011 = frac(sin(dot(float3(cA.x, cB.y, cB.z), k)) * 43758.5453);
float h111 = frac(sin(dot(float3(cB.x, cB.y, cB.z), k)) * 43758.5453);
float n1 = lerp(lerp(lerp(h000, h100, f.x), lerp(h010, h110, f.x), f.y),
                lerp(lerp(h001, h101, f.x), lerp(h011, h111, f.x), f.y), f.z);
// Detail octave (0.37x cell), its lattice offset from the body's.
float3 p2 = WorldPos / (cell0 * 0.37) + float3(17.0, 29.0, 43.0);
float3 cell2 = floor(p2);
float3 f2 = p2 - cell2;
f2 = f2 * f2 * (3.0 - 2.0 * f2);
float3 dA = cell2 - 512.0 * floor(cell2 / 512.0);
float3 dB = (cell2 + 1.0) - 512.0 * floor((cell2 + 1.0) / 512.0);
float g000 = frac(sin(dot(float3(dA.x, dA.y, dA.z), k)) * 43758.5453);
float g100 = frac(sin(dot(float3(dB.x, dA.y, dA.z), k)) * 43758.5453);
float g010 = frac(sin(dot(float3(dA.x, dB.y, dA.z), k)) * 43758.5453);
float g110 = frac(sin(dot(float3(dB.x, dB.y, dA.z), k)) * 43758.5453);
float g001 = frac(sin(dot(float3(dA.x, dA.y, dB.z), k)) * 43758.5453);
float g101 = frac(sin(dot(float3(dB.x, dA.y, dB.z), k)) * 43758.5453);
float g011 = frac(sin(dot(float3(dA.x, dB.y, dB.z), k)) * 43758.5453);
float g111 = frac(sin(dot(float3(dB.x, dB.y, dB.z), k)) * 43758.5453);
float n2 = lerp(lerp(lerp(g000, g100, f2.x), lerp(g010, g110, f2.x), f2.y),
                lerp(lerp(g001, g101, f2.x), lerp(g011, g111, f2.x), f2.y), f2.z);
// Coarse octave (5x cell): the separate puffs of an aged trail.
float3 p3 = WorldPos / (cell0 * 5.0) + float3(5.0, 11.0, 23.0);
float3 cell3 = floor(p3);
float3 f3 = p3 - cell3;
f3 = f3 * f3 * (3.0 - 2.0 * f3);
float3 eA = cell3 - 512.0 * floor(cell3 / 512.0);
float3 eB = (cell3 + 1.0) - 512.0 * floor((cell3 + 1.0) / 512.0);
float q000 = frac(sin(dot(float3(eA.x, eA.y, eA.z), k)) * 43758.5453);
float q100 = frac(sin(dot(float3(eB.x, eA.y, eA.z), k)) * 43758.5453);
float q010 = frac(sin(dot(float3(eA.x, eB.y, eA.z), k)) * 43758.5453);
float q110 = frac(sin(dot(float3(eB.x, eB.y, eA.z), k)) * 43758.5453);
float q001 = frac(sin(dot(float3(eA.x, eA.y, eB.z), k)) * 43758.5453);
float q101 = frac(sin(dot(float3(eB.x, eA.y, eB.z), k)) * 43758.5453);
float q011 = frac(sin(dot(float3(eA.x, eB.y, eB.z), k)) * 43758.5453);
float q111 = frac(sin(dot(float3(eB.x, eB.y, eB.z), k)) * 43758.5453);
float n3 = lerp(lerp(lerp(q000, q100, f3.x), lerp(q010, q110, f3.x), f3.y),
                lerp(lerp(q001, q101, f3.x), lerp(q011, q111, f3.x), f3.y), f3.z);
float n = wBody * n1 + wDetail * n2 + wCoarse * n3;
// A young trail is one lumpy body (0.7..1); an aged one is cut into puffs:
// the cut rises with Life, so the gaps open as the trail thins.
float cut = saturate(Puff) * smoothstep(0.1, 1.0, life) * 0.75;
float puffs = saturate((n - cut) / max(1.0 - cut, 0.05));
float lumpy = lerp(0.7 + 0.3 * n, 0.25 + 0.75 * puffs, saturate(Puff));
return saturate(Opacity * formed * fade * across * lumpy);
