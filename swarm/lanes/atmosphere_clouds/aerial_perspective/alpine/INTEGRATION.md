# atmosphere_clouds.aerial_perspective.alpine -- integration

Visual-only. Written and source-tested on the Mac.
**No render, pixel or performance result exists: everything here is
UNMEASURED until the Windows commands below have run on the laptop.**

## What changed in this repair

- The measurement now needs only switches that exist in the repo today. The
  three environment variables the first version asked for never existed and
  are gone.
- The baked-texture render pass is NOT WRITTEN. It is no longer a tier and no
  longer part of the measurement. It stays below as a proposal.
- The atmosphere constants are labelled ASSUMED everywhere. They are not the
  engine's defaults as far as anyone has checked, and they are not what this
  project renders.
- The 0.15 threshold is PROVISIONAL. Nothing passes or fails on it yet.

## Files

| File | Role |
| --- | --- |
| `measure_aerial_perspective.py` | `stash` (collect a run's frame and render.json) and `measure` (two frames, two boxes) |
| `bake_alpine_ap.py` | Mac bake (0.2 s) and the model the measurement compares against |
| `alpine_ap_a/b/c.rgba16f` | Rayleigh in-scatter, transmittance, Mie in-scatter; 32 x 240 RGBA float16, 61 440 bytes each. Used by nothing yet |
| `alpine_ap.json` | axes, layout, the assumed constants, model values at 5 / 10 / 20 / 40 / 80 km |
| `PROVENANCE.json` | sources and their status, sha256 of generated files, candidates not adopted |

## What was checked in source on the Mac (not rendered)

- Scenario 11 of `scripts/run_test_scenarios.py` is "A-4 over the matterhorn,
  strong wind, severe turbulence", at 5000 m; `--only` is 1-based.
- `FLIGHTSIM_RENDER_SWITCHES` is the existing pass-through:
  `webapp/runs.py with_render_switches` puts every token on the engine
  command line, and `scripts/visual_fix_round.ps1 -Switches` sets it.
- `-NoAerialPerspective` is read from the command line in
  `FlightSimRenderCommandlet.cpp`, hides the SkyAtmosphere and the height fog
  (`FlightSimVisualScene.cpp`), and is recorded twice in render.json:
  `aerial_perspective_off` and an atmosphere record starting
  `nothing: no visible sky atmosphere`.
- The engine's Mie layer is set by `FFlightSimWorldBeauty::ApplyAtmosphere`
  per preset and visibility and recorded in render.json
  (`mie_scattering_scale_per_km`, `mie_absorption_scale_per_km`,
  `mie_scale_height_km`, `aerial_perspective_view_distance_scale`).

Not established from the Mac: whether the web app's beauty render path
honours `-NoAerialPerspective` for scenario 11. The measurement does not
assume it. It refuses with `ap_gate.clear_frame_not_clear` unless the clear
run's own render.json carries both records above.

## Measurement (UNMEASURED; run on the Windows laptop)

```bat
rem 1. clear frame: atmosphere and height fog hidden
powershell -File scripts\visual_fix_round.ps1 -Round 9111 -Scenes 11 -NoPush -Switches "-NoAerialPerspective"
python swarm\lanes\atmosphere_clouds\aerial_perspective\alpine\measure_aerial_perspective.py stash --scenario 11 --as clear

rem 2. hazed frame: what the engine draws today
powershell -File scripts\visual_fix_round.ps1 -Round 9112 -Scenes 11 -NoPush
python swarm\lanes\atmosphere_clouds\aerial_perspective\alpine\measure_aerial_perspective.py stash --scenario 11 --as hazed

rem 3. measure. Open runs\alpine_ap\hazed.png, pick two sunlit textured terrain boxes, read their distances off the map.
python swarm\lanes\atmosphere_clouds\aerial_perspective\alpine\measure_aerial_perspective.py measure --clear runs\alpine_ap\clear.png --hazed runs\alpine_ap\hazed.png --clear-json runs\alpine_ap\clear.render.json --hazed-json runs\alpine_ap\hazed.render.json --box-near <x0,y0,x1,y1> --near-km <km> --box-far <x0,y0,x1,y1> --far-km <km> --altitude-m 5000
```

Round numbers 9111 and 9112 are arbitrary; `-NoPush` keeps both local. Both
rounds replay the scene's pinned spec (`runs\visual\specs\11.json`), one
still each, so the two frames share camera and time. Step 3 still needs a
person: the two boxes and their distances are not known until a frame exists.

Metric: `ap_log_t_ratio_error` = mean over R, G, B of
`|ln(slope_far / slope_near) - ln(T_model(far) / T_model(near))|`, where each
slope is the least-squares fit `hazed = slope * clear + offset` over a box.
Two boxes because hiding the atmosphere also brightens the sun and removes
the sky light: one slope is transmittance times an unknown lighting ratio;
the ratio of two slopes cancels it when both boxes are lit the same way.
`T_model` uses the Mie values the hazed run recorded; Rayleigh and ozone stay
assumed, and the printout says which is which.

Threshold: **0.15, PROVISIONAL.** It was chosen before any engine frame
existed. On synthetic frames through a stand-in filmic curve (ACES fit, 0.5x
to 2x exposure) the metric's own bias was 0.015 to 0.09, over half the
threshold at worst, against 0.001 with no curve. That is arithmetic on
made-up images with a curve that is not the engine's. The first Windows run
calibrates the threshold; it is not a pass or a fail. Exit code 0 / 1 only
says which side of 0.15 the number fell; 2 is a named refusal.

What the number cannot show:

- The model has no height fog and no multiple scattering; the frame has
  both. A large error may be fog, not a wrong constant.
- Google tiles are the ground. Their photographs already contain real haze,
  present in both frames; it cancels in the fit only to first order.
- 8-bit tonemapped PNGs, mid-tones only (0.02 to 0.60 decoded).
- Two distances in one frame. Nothing about other altitudes or sun angles.
- Device loss, frame time and VRAM are the stress ladder's to measure.

## Tiers (VRAM and cost are ESTIMATES; none is claimed sustained)

This lane adds no render code, so tier 0 is the frame scenario 11 already
makes. Tiers 1 to 3 raise the engine's aerial-perspective volume for the
stress ladder. They need a console-variable pass-through that I did not find
in the runner (proposal 1). Volume sizes assume the engine default of 32 x 32
x 16, quoted from memory.

| Tier | Render side | Est. added VRAM | Est. cost |
| --- | --- | --- | --- |
| 0 | unchanged: the SkyAtmosphere aerial perspective as the beauty path sets it today (per-pixel apply, `FlightSimRenderCommandlet.cpp` near line 4045) | 0 | none added |
| 1 | `r.SkyAtmosphere.AerialPerspectiveLUT.SampleCountMaxPerSlice` doubled | 0 | about 2x the volume fill |
| 2 | tier 1 + `r.SkyAtmosphere.AerialPerspectiveLUT.DepthResolution=32` | about 0.3 MB | about 4x the volume fill |
| 3 | tier 2 + `r.SkyAtmosphere.AerialPerspectiveLUT.Width=64` | about 1.8 MB | about 16x the volume fill |

## Proposals for the integrator (this lane edits no shared file)

1. **Console variables for tiers 1 to 3.** Either confirm that UE's
   `-dpcvars=name=value,...` token, sent through `FLIGHTSIM_RENDER_SWITCHES`,
   survives the beauty path's own `SetBeautyCvar` calls (it probably does
   not: those run later), or add a switch that sets the three variables
   after them.

2. **Baked aerial-perspective pass. NOT WRITTEN.** It would replace the
   per-frame volume fill with three texture taps in one post-process pass.
   Do not build it before the measurement above has run: the textures are
   baked from assumed constants, and the Mie layer must first be re-baked
   from the values render.json records. What it needs:
   - a post-process material asset (Before Tonemapping) that cannot be
     authored on the Mac, with the Custom node below;
   - the three `.rgba16f` files loaded as transient `PF_FloatRGBA` textures,
     32 x 240, bilinear, clamped, no mips, not sRGB;
   - `AerialPespectiveViewDistanceScale = 0` on the SkyAtmosphere component
     (the engine spells it that way) and the height fog hidden or accepted;
   - a switch to turn it on, off by default.

```hlsl
// inputs: SceneColor, WorldPos (cm), CamPos, SunDir (towards the sun), TileRow, SunLux, MsGain, PreExposure
float3 ray = WorldPos - CamPos;
float dKm = length(ray) * 1e-5;
if (dKm > 127.0) return SceneColor;                 // sky and far plane: the sky dome owns them
float3 dir = ray / max(length(ray), 1.0);
float mu = clamp(dir.z, -0.5, 0.5);
float u = (sqrt(dKm / 128.0) * 31.0 + 0.5) / 32.0;
float v = (TileRow + (mu + 0.5) * 15.0 + 0.5) / 240.0;
float3 iR = Texture2DSample(TexA, TexASampler, float2(u, v)).rgb;
float3 T  = Texture2DSample(TexB, TexBSampler, float2(u, v)).rgb;
float3 iM = Texture2DSample(TexC, TexCSampler, float2(u, v)).rgb;
float c = dot(dir, SunDir);
float pR = 0.0596831 * (1.0 + c * c);
float pM = 0.0286479 / pow(1.64 - 1.6 * c, 1.5);    // Henyey-Greenstein, g = 0.8
float3 L = SunLux * MsGain * (pR * iR + pM * iM);
return SceneColor * T + L * PreExposure;
```

   This shader has never been compiled. Its estimated cost (0.2 MB, one
   full-screen pass, 3 taps) is an argument, not a measurement. Limits of the
   bake behind it: single scattering only (`ms_gain` 1.0, UNCALIBRATED), no
   terrain or planet shadow on the air, lowest sun 15 degrees, tile row
   `(sun * 5 + altitude) * 16` with sun in 15 / 30 / 50 degrees and altitude
   in 2000..6000 m.

## Model values (the bake's assumed constants, not a render)

5000 m camera, level ray: transmittance R / G / B is 0.969 / 0.929 / 0.837 at
10 km, 0.939 / 0.864 / 0.701 at 20 km, 0.881 / 0.747 / 0.493 at 40 km and
0.780 / 0.564 / 0.248 at 80 km. These move as soon as the Mie layer is
replaced by the recorded one.
