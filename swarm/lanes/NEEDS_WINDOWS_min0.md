# min0 wave: Windows commands

Every result below is UNMEASURED until its command has run on the Windows laptop.
Generated from workflow run wf_52e4f2fc-ed0 (26 items verified by an honesty skeptic, 0 rejected).

## aircraft_exterior.pbr_materials.alpine

Lane: `swarm/lanes/aircraft_exterior/pbr_materials/alpine`

Gate command:

```
& .\.venv\Scripts\python.exe swarm\lanes\aircraft_exterior\pbr_materials\alpine\measure_gate.py --reference runs\swarm\alpine_pbr\flat\frames --candidate runs\swarm\alpine_pbr\tier0\frames --out runs\swarm\alpine_pbr\gate_tier0.json   (needs two labelled beauty runs of the same alpine card and seed first: reference with -aircraft-materials=on -aircraft-probe=flat, candidate with -aircraft-materials=on -aircraft-alpine-pbr=tier0. The second host word does not exist until the integrator applies INTEGRATION.md changes 1-4, so no exact render line can be given today)
```

Metric: Inside the primary airframe mask (frame_NNNN_mask.png int_id 1, eroded 2 px), per frame: (a) luminance_ratio = mean Rec.709 luma candidate / reference; (b) dark_share = share of mask pixels under 24/255; (c) detail_ratio = variance of the 3x3 Laplacian of luma, candidate / reference

Threshold: On every frame: 0.85 <= luminance_ratio <= 1.15 (no dark-aircraft regression), dark_share <= reference dark_share + 0.02, and detail_ratio >= 1.10 (the improvement). Exit 0 pass, 1 fail, 3 refused (no masks, size mismatch, mask under 400 px).

Other unmeasured items:

- Nothing is wired into the masters or the bridge: the lane is a proposal until an integrator applies INTEGRATION.md changes 1-4 (master material parameters and custom node, aircraft_look.py alpine overlay and -aircraft-alpine-pbr host word, FlightSimAircraftFX ApplyMaterials, texture import)
- Whether the HLSL compiles in the UE 5.7 material translator on D3D11 SM5 (written by reading, never compiled): after integration, run the repo's material build step from docs/visual/RENDER_RUNBOOK.md (UnrealEditor-Cmd -run=pythonscript -script=scripts\ue_create_materials.py)
- The pixel gate itself, for every tier: measure_gate.py command in pixel_gate on two labelled runs of the A-4 over the Matterhorn card
- Stability, device loss, frame time and real VRAM of every tier, including tier 0; all memory figures are arithmetic estimates (8 bpp x 4/3)
- Every look number (frost amount 0.35, frost albedo 0.75, grime 0.10, oil-canning depth 0.8 mm, normal amounts) is UNCALIBRATED
- Visual questions only a frame answers: frost reading as rime rather than noise, a seam at the side/top projection switch in tiers 0-1, BC5 banding of the oil-canning in reflections, texture import time on the laptop
- Dependency on the lighting lane: the sky light's lower hemisphere must carry the snow bounce; with a black lower hemisphere the underside goes dark whatever this material does
- shared_params are this lane's assumptions (sun elevation, exposure, haze, snow albedo from memory), not values read from a scenario card

## aircraft_exterior.pbr_materials.coastal

Lane: `swarm/lanes/aircraft_exterior/pbr_materials/coastal`

Gate command:

```
powershell -ExecutionPolicy Bypass -File swarm\lanes\aircraft_exterior\pbr_materials\coastal\run_gate.ps1    # NOT RUNNABLE YET: exits 3 (REFUSED) until INTEGRATION.md change 6 adds the FLIGHTSIM_COASTAL_WEATHERING switch to scripts\aircraft_look.py. Once merged it renders shot a with the switch at 0 (step coastal_pbr_ref) and at 1 (step coastal_pbr_t0), then runs measure_gate.py on runs\visual\<step>\a.png and runs\visual\coastal_pbr_ref\a_mask.png with --ids 1. The script has never been executed (no PowerShell on the Mac).
```

Metric: Over pixels whose ID-image value is 1 (the primary airframe per core/capture/labels.py; add component ids with -Ids), on 8-bit luma: luma_ratio, dark_share_delta (luma < 24), clip_share_delta (luma >= 250), detail_ratio (mean |Laplacian|, candidate / reference). mean_abs_diff is reported, not gated. Exit 0 PASS, 1 FAIL, 2 REFUSED by the measurement (under 2000 airframe pixels, size mismatch, pixel-identical pair), 3 REFUSED by the script (switch not merged, render failed, frame or mask missing).

Threshold: UNCALIBRATED proposals: detail_ratio >= 1.10, luma_ratio in [0.97, 1.08], dark_share_delta <= 0.01, clip_share_delta <= 0.005. No real frame pair has been through the script.

Other unmeasured items:

- The pixel gate cannot run today. CoastalWeathering exists only in this lane's .ush and Python twin; nothing under ue/ or scripts/ knows it. run_gate.ps1 refuses by name until INTEGRATION.md change 6 (FLIGHTSIM_COASTAL_WEATHERING read by scripts/aircraft_look.py) is merged. Then: powershell -ExecutionPolicy Bypass -File swarm\lanes\aircraft_exterior\pbr_materials\coastal\run_gate.ps1
- Open risk for the integrator: I did not establish whether the aircraft look's material instances are rebuilt per render or cached (ue_aircraft_master_materials.py has FLIGHTSIM_REBUILD_MATERIALS). If cached, the switch must also invalidate them or both renders are still the same scene.
- An unwired switch will usually read as a FAIL (detail_ratio near 1.0), not a refusal, because rain and temporal AA make two renders of one scene differ. A FAIL alone does not say the look is wrong; check mean_abs_diff and the two PNGs.
- run_gate.ps1 itself has never been executed; only its text is checked by a test.
- Whether the airframe has labelled components with their own int_ids in shot a. If so the default --ids 1 covers only part of it; pass -Ids "1,<ids>" from the frame's labels.
- Whether the real renders differ at all, by how much, and whether the thresholds are sensible.
- Material compile under D3D11 / SM5, tier 0 stability on the Intel iGPU (device loss), VRAM and frame cost of every tier: all estimates. Same command as above, after changes 1-6 in INTEGRATION.md are merged.
- Shot a (alpine chase cam, golden hour) stands in for a coastal shot; no coastal scenario card was found under core/scenario. Pass -Shot <key> once one exists.

## aircraft_exterior.pbr_materials.storm

Lane: `swarm/lanes/aircraft_exterior/pbr_materials/storm`

Gate command:

```
$env:FLIGHTSIM_AIRCRAFT_STORM_PBR="off"; .\scripts\render_visual_sheet.ps1 -Step stormpbr_base -Shots a; .\scripts\render_visual_sheet.ps1 -Step stormpbr_base_measure -Quality measure -Shots a; $env:FLIGHTSIM_AIRCRAFT_STORM_PBR="0"; .\scripts\render_visual_sheet.ps1 -Step stormpbr_t0 -Shots a; .\scripts\render_visual_sheet.ps1 -Step stormpbr_t0_measure -Quality measure -Shots a; then .\.venv\Scripts\python.exe swarm\lanes\aircraft_exterior\pbr_materials\storm\measure_aircraft_gate.py --base-frame <stormpbr_base frame_NNNN.png> --base-mask <stormpbr_base_measure frame_NNNN_mask.png> --head-frame <stormpbr_t0 frame_NNNN.png> --head-mask <stormpbr_t0_measure frame_NNNN_mask.png> --out runs\visual\stormpbr_t0\aircraft_gate.json  (the PowerShell helpers that resolve the four paths from shots.json are in INTEGRATION.md; requires the integrator to add the FLIGHTSIM_AIRCRAFT_STORM_PBR switch first, which does not exist yet)
```

Metric: On aircraft-mask pixels, sRGB luma: dark_ratio = head median / base median; floor_ratio = head p05 / base p05; sheen_gain = head (p99 - p50) / base (p99 - p50); clip_share = head share of pixels >= 250

Threshold: dark_ratio >= 0.97 AND floor_ratio >= 0.90 AND sheen_gain >= 1.10 AND clip_share <= 0.02 (exit 0 only when all four hold; thresholds are the lane's choice, uncalibrated)

Other unmeasured items:

- Every visual result: no frame was rendered. Whether the 0.3 paint porosity is the actual cause of a dark aircraft on a storm frame is a source-level hypothesis only
- The pixel gate itself (command above); it cannot run until the integrator adds the proposed FLIGHTSIM_AIRCRAFT_STORM_PBR switch and master-material changes from INTEGRATION.md, none of which exist in shared code yet
- Whether UE 5.7's importer accepts the legacy ATI2 (BC5) DDS with its mip chain, or needs the PNG fallback
- Shader cost and frame time of every tier on the Intel GPU; the claim that tier 0 is cheaper than HEAD's procedural noise is an expectation
- VRAM use of every tier (figures are arithmetic estimates) and device-loss behaviour of tiers 1-3 on the stress ladder
- The effective_albedo model against the real master graph: the graphs were not read node by node; .\scripts\render_visual_sheet.ps1 with -aircraft-probe=basecolor-debug on the laptop would replace the model with a measurement
- Panel pillow, groove, rivet and rivulet amplitudes: guesses with no reference photo behind them
- Cheapest A/B if full integration is too much for one round: ship only the two porosity overrides (INTEGRATION.md item 2) and run the same gate; expect dark_ratio > 1 and no sheen_gain

## aircraft_exterior.pbr_materials.night_ifr

Lane: `swarm/lanes/aircraft_exterior/pbr_materials/night_ifr`

Gate command:

```
BLOCKED - cannot be run today. Needs INTEGRATION.md changes 1-4 integrated and built first: the -aircraft-night-pbr switch does not exist in any C++/Python/PowerShell source, and the round list has 15 scenes with none at night (the lane proposes the row that becomes scene 16). After that: $env:FLIGHTSIM_CAPTURE_PASSES = "albedo"; .\scripts\visual_fix_round.ps1 -Round 90 -Scenes 16 -NoPush -Switches "-aircraft-night-pbr=off"; .\scripts\visual_fix_round.ps1 -Round 91 -Scenes 16 -NoPush -Switches "-aircraft-night-pbr=0"; Remove-Item Env:FLIGHTSIM_CAPTURE_PASSES; .\.venv\Scripts\python.exe swarm\lanes\aircraft_exterior\pbr_materials\night_ifr\measure_gate.py --reference-round 90 --candidate-round 91 --scene 16 --out runs\swarm\night_pbr_gate.json
```

Metric: On pixels of the primary airframe (ID image value 1), candidate vs reference render of the same pinned spec: median luma delta, candidate mean luma, change in share of pixels at luma <= 1, and the share of aircraft pixels whose base colour changed between the two albedo passes and lies outside linear [0.023, 0.9]. Glass, tyres and lights are unchanged between the renders, so they are reported but not gated.

Threshold: median_delta >= 0.0; candidate_mean_luma >= 2.0; crushed fraction does not rise; albedo_changed_outside_fraction <= 0.001. VOID (never a pass) when a file is missing, spec hashes differ, the candidate render.json has no night_pbr record, the aircraft is pixel-identical in both frames, under 400 aircraft pixels, or both aircraft under mean luma 2.

Other unmeasured items:

- The whole pixel gate: blocked until changes 1-4 in INTEGRATION.md are integrated and built, then the command in pixel_gate.
- Whether a visual round really leaves frame_0000_mask.png and frame_0000_albedo.png in runs\webapp\<run_id>\frames\<camera>\ (established from source only).
- Whether proposed scene 16 renders a usable night frame: what the LLM compiler makes of the prompt, whether the aircraft is above mean luma 2, whether runway lighting shows.
- Whether two renders of the same pinned spec are deterministic enough for the zero tolerance on median_delta.
- Whether the proposed material branch compiles under D3D11 / SM5, and whether the importer keeps the hand-built mips.
- Device-lost count, frame time and peak process memory per tier; all VRAM figures are estimates.
- Whether the roughness widening is visible at 1280 wide and whether the 512 groove reads as a panel line.

## aircraft_exterior.glass.coastal

Lane: `swarm/lanes/aircraft_exterior/glass/coastal`

Gate command:

```
NOT RUNNABLE until the integrator applies INTEGRATION.md (the -aircraft-glass-tier switch does not exist yet). Then, PowerShell at repo root, <card> = the coastal scenario run card with the canopy in frame: .\scripts\render_ue_scenario.ps1 <card> runs\swarm\glass_coastal\ref -aircraft-glass-tier=off ; .\scripts\render_ue_scenario.ps1 <card> runs\swarm\glass_coastal\t0 -aircraft-glass-tier=0 ; .\.venv\Scripts\python.exe swarm\lanes\aircraft_exterior\glass\coastal\bake_glass.py measure --ref (Get-ChildItem runs\swarm\glass_coastal\ref\frame_*.png | Select-Object -First 1).FullName --cand (Get-ChildItem runs\swarm\glass_coastal\t0\frame_*.png | Select-Object -First 1).FullName --canopy-roi <x0,y0,x1,y1> --aircraft-roi <x0,y0,x1,y1>   (ROIs are pixel boxes read off the reference frame; exit code 0 = pass)
```

Metric: sRGB luma /255 in two ROIs: canopy contrast gain = (p97 - p5 of canopy ROI, candidate) minus (same, reference); aircraft-ROI p50 drop; fraction of canopy pixels below 8; fraction above 250

Threshold: canopy contrast gain >= 10/255 AND aircraft p50 drop <= 2/255 (no dark-aircraft regression) AND canopy pixels < 8/255 <= 2% (no blacked-out canopy) AND canopy pixels > 250/255 <= 2%

Other unmeasured items:

- How any tier looks: no frame was rendered; the pixel gate has not been run
- Whether the -aircraft-glass-tier switch, master-material parameters and aircraft_look.py block proposed in INTEGRATION.md work: they are written as a proposal, not implemented (shared files are off-limits to this lane)
- Whether the emissive env strip double-counts the sky-light specular on the laptop; GlassEnvGain ships as 0 and must be set by the integrator from the drawn sky's horizon luminance
- Real VRAM, frame time and device-lost behaviour per tier; tiers 2-3 add a translucent pass and are the likeliest to fail on the D3D11 integrated GPU
- Whether the analytic env strip matches the sky actually drawn behind the aircraft in the coastal scenario (depends on the sky lane agreeing with shared_params)
- Canopy and aircraft ROI coordinates for the gate, and the coastal run card path: neither exists in the repo today
- Albedo gate against the project's calibrated range on a rendered frame; only a stated 0.015-0.90 bound was checked in source

## aircraft_exterior.decals_wear.alpine

Lane: `swarm/lanes/aircraft_exterior/decals_wear/alpine`

Gate command:

```
BLOCKED, not runnable today: FLIGHTSIM_AIRCRAFT_WEAR does not exist in the repo (INTEGRATION.md items 1-4 must land first). After that, from the repo root on the laptop: swarm\lanes\aircraft_exterior\decals_wear\alpine\run_gate.cmd <alpine spec.yaml> tier0   -- it refuses with exit 4 if core\render\flags.py does not read the switch, sets the switch with set "FLIGHTSIM_AIRCRAFT_WEAR=off" (quoted, no trailing space), renders off and tier0 with --passes albedo, then runs pixel_gate.py --reference runs\alpine_wear_ref --candidate runs\alpine_wear_tier0 --expect tier0
```

Metric: On the pixels whose albedo pass moved: detail_gain (mean |Laplacian| of albedo luminance, candidate/reference), beauty_ratio (mean linear luminance of the beauty frame), dark_fraction, albedo_p99, changed_fraction. Exit 0 pass, 1 wear failed a threshold, 2 frames missing, 3 not measured (render.json does not state aircraft_wear=off / tier0, or no albedo pixel moved), 4 blocked (switch absent), 5 capture failed. Only 0 and 1 are results about the wear.

Threshold: detail_gain >= 1.25, beauty_ratio >= 0.90, dark_fraction <= 0.03, albedo_p99 <= 0.90, 0.002 <= changed_fraction <= 0.35 on every frame. Thresholds were chosen on synthetic frames and are unvalidated on real renders.

Other unmeasured items:

- Everything render-side: alpine_wear.ush has never been compiled by Unreal or drawn
- The gate itself is blocked: it needs INTEGRATION.md items 1-4 (texture import, master material node, look manifest, the FLIGHTSIM_AIRCRAFT_WEAR switch and the aircraft_wear key in render.json). Command once integrated: swarm\lanes\aircraft_exterior\decals_wear\alpine\run_gate.cmd <alpine spec.yaml> tier0
- run_gate.cmd has never run under cmd.exe
- pixel_gate.py has never read a real capture: the beauty-frame naming (albedo name without _albedo), the location and shape of aircraft_wear in render.json, and run-to-run pixel identity of the albedo pass are assumptions
- The gate thresholds on real frames
- VRAM, frame time and device-loss behaviour of every tier (stress ladder); no tier is claimed sustained
- Wear under the wet layer on a rain scene (the wet layer squares the albedo on top of the wear)

## lighting_exposure.physical_light_units.alpine

Lane: `swarm/lanes/lighting_exposure/physical_light_units/alpine`

Gate command:

```
python scripts\run_test_scenarios.py --still --only 11  (once before and once after the integrator's beauty_look change, copying each frame to runs\alpine_plu_baseline.png and runs\alpine_plu_candidate.png), then: python swarm\lanes\lighting_exposure\physical_light_units\alpine\measure_exposure.py --baseline runs\alpine_plu_baseline.png --baseline-ev100 <exposure.ev100 from the baseline run's beauty_look.json> --candidate runs\alpine_plu_candidate.png --target-ev100 <exposure.ev100 from the candidate run's beauty_look.json>
```

Metric: ev_error_stops = median log2(candidate/baseline) of sRGB-decoded luminance over the baseline's mid-tone pixels (0.02-0.50 linear), minus the expected shift (baseline EV100 - target EV100); plus snow_clip_fraction = share of pixels with every channel >= 250

Threshold: |ev_error_stops| <= 0.3 AND candidate snow_clip_fraction <= 0.01 AND candidate snow_clip_fraction <= baseline's. The script exits 0 on pass, 1 on fail.

Other unmeasured items:

- Every rendered-frame result: no frame was rendered. Run the pixel_gate command on the laptop for scenario 11
- Whether tier 0 renders without device loss, and any VRAM or frame-time figure for tiers 0-3 (all estimates)
- Whether the table's EV100 is the right look: needs the grey-card probe at 5000 m with the sun at 10, 30 and 60 deg (sunlit 18% card near 18% of white after the tonemapper)
- Effective albedo of snow in the Google tiles versus the modelled 0.90, which sets whether the snow guard (ceiling 2.0 scene-linear, cap 1.0 stop) is correct
- The p/p0 scaling of sky diffuse illuminance against the engine's SkyAtmosphere at altitude
- The exact frame file name the runner writes for scenario 11 under runs\test_scenarios\ (the copy step in INTEGRATION.md uses a wildcard)
- Whether local exposure (tier 3) runs at all under D3D11 SM5 on the Intel GPU
- The integration itself is not applied: core/scene/beauty_look.py is a shared file, so the change is only proposed in INTEGRATION.md

## lighting_exposure.physical_light_units.storm

Lane: `swarm/lanes/lighting_exposure/physical_light_units/storm`

Gate command:

```
.venv\Scripts\python.exe scripts\run_test_scenarios.py --only 9 --still   (run once on current code for the reference and once with INTEGRATION.md changes 1-2 applied; confirm with --list that 9 is "747 through a thunderstorm", I counted it from the source rather than running --list)   then: .venv\Scripts\python.exe swarm\lanes\lighting_exposure\physical_light_units\storm\measure_frame.py --frame <candidate frame.png> --reference <reference frame.png>
```

Metric: ev_error = log2(sRGB_eotf(p90 sRGB luma of the frame) / sRGB_eotf(0.40)), in display-referred stops against the storm frame-meter target; plus clipped fraction (luma >= 254/255). Caveat: the host's frame meter already steers p90 toward 0.40, so also compare the meter's recorded stops in look_applied.storm_exposure between the two runs (should shrink in size).

Threshold: |ev_error| <= 0.3 AND clipped fraction <= 0.01 AND |ev_error candidate| <= |ev_error reference| (script exits 0 on pass, 1 on fail)

Other unmeasured items:

- Whether any tier renders without device loss on the laptop: no frame was rendered. Command: .venv\Scripts\python.exe scripts\run_test_scenarios.py --only 9 --still
- The pixel gate itself (ev_error against the 0.40 p90 target, candidate vs reference): measure_frame.py on the two rendered frames, command in pixel_gate
- Whether the drawn storm deck also shadows the directional light (decides 5825 lux outer-space vs 4009 lux at the ground): render with flightsim.capture --render --calibration and read the white quad against 4009 lux on the light's normal
- Whether UE 5.7 on D3D11 honours the 1.2 * 2^EV100 saturation convention and what the tonemapper does to the predicted scene-linear values (grey card 0.103, sky zenith 0.628, horizon 0.209)
- VRAM and frame cost of every tier (figures are RGBA16F cube-with-mips arithmetic, not readings)
- Whether the frame meter's recorded stops in look_applied.storm_exposure shrink with the physical lights applied
- The visual-only choices: directional share 0.15, wet-albedo factor 0.5, sky 7000 K, sheen 6500 K, lightning 8000 K and the 5 km channel length

## lighting_exposure.physical_light_units.coastal

Lane: `swarm/lanes/lighting_exposure/physical_light_units/coastal`

Gate command:

```
BLOCKED today; exits 2 with a named refusal until (1) the integrator adds a coastal location and a coastal sheet shot (proposed key e) and (2) merges the beauty_look.py change on both exposure branches. Then: `.\scripts\render_visual_sheet.ps1 -Step coastal_plu_ref -Shots e` on the commit before the change; `.\scripts\render_visual_sheet.ps1 -Step coastal_plu_t0 -Shots e` on the commit with it; `.\.venv\Scripts\python.exe swarm\lanes\lighting_exposure\physical_light_units\coastal\coastal_gate.py --baseline-step coastal_plu_ref --candidate-step coastal_plu_t0 --shot e`. The third command is the gate; it takes no hand-typed numbers and reads sun elevation and EV100 from each run's beauty_look.json.
```

Metric: table_base_error_ev (candidate sidecar exposure.base_ev100 minus the table's target_ev100 at the sidecar's sun elevation; a sidecar check) and ev_error_stops (median log2(candidate/baseline) linear luminance over the baseline's mid-tones 0.02..0.50, minus baseline exposure.ev100 minus candidate exposure.ev100), plus highlight_clip_fraction (all channels >= 250).

Threshold: |table_base_error_ev| <= 0.01 and |ev_error_stops| <= 0.3 and clip fraction <= 0.02 or not above baseline. Exit 0 pass, 1 fail, 2 refused. Refuses when exposure.ev100 is null, when the candidate's exposure.basis does not name the coastal table (inland shot or unmerged change), when the sun elevations differ, and when the expected shift is 0.3 stop or less.

Other unmeasured items:

- Every render, pixel, VRAM and device-loss result for all tiers. No Windows command was run.
- The pixel gate itself: blocked on a coastal location plus sheet shot and on the beauty_look.py change (both in INTEGRATION.md for the integrator). Commands as in pixel_gate.
- Whether the host's no-Lumen re-meter (sidecar exposure.meter) moves the exposure off the sidecar EV100 on the D3D11 laptop; if it does, tier 0's fixed EV100 does not hold and ev_error_stops will show it. Measured by the same gate command.
- Whether the web path's coastal run takes the band branch or the physical-sky branch of plan_beauty_look, and whether the plan hands over an EV100; if not, the gate refuses with exposure.ev100_null.
- Whether the proposed coastal prompt compiles to a place (not compiled here; no coastal location exists).
- Whether the table is the right look: the grey-card probe at sea level with the sun at 6, 12 and 20 deg.
- UE FogDensity mapping from extinction, against the pinned build.

## lighting_exposure.eye_adaptation.night_ifr

Lane: `swarm/lanes/lighting_exposure/eye_adaptation/night_ifr`

Gate command:

```
Runnable today, no integration needed (web app running on 127.0.0.1:8008; run from the repo root, one line at a time):
.venv\Scripts\python.exe scripts\run_test_scenarios.py --only 6 --still --spec-dir runs\eye_gate\reference
.venv\Scripts\python.exe swarm\lanes\lighting_exposure\eye_adaptation\night_ifr\gate_tool.py stash reference
.venv\Scripts\python.exe swarm\lanes\lighting_exposure\eye_adaptation\night_ifr\gate_tool.py specs --pinned runs\eye_gate\reference\06.json
.venv\Scripts\python.exe scripts\run_test_scenarios.py --only 6 --still --spec-dir runs\eye_gate\bracket_dark
.venv\Scripts\python.exe swarm\lanes\lighting_exposure\eye_adaptation\night_ifr\gate_tool.py stash bracket_dark
.venv\Scripts\python.exe scripts\run_test_scenarios.py --only 6 --still --spec-dir runs\eye_gate\bracket_bright
.venv\Scripts\python.exe swarm\lanes\lighting_exposure\eye_adaptation\night_ifr\gate_tool.py stash bracket_bright
.venv\Scripts\python.exe scripts\run_test_scenarios.py --only 6 --still --spec-dir runs\eye_gate\eye_closed
.venv\Scripts\python.exe swarm\lanes\lighting_exposure\eye_adaptation\night_ifr\gate_tool.py stash eye_closed
.venv\Scripts\python.exe swarm\lanes\lighting_exposure\eye_adaptation\night_ifr\measure_frame.py --frame runs\eye_gate\eye_closed.png --reference runs\eye_gate\reference.png --dark-bracket runs\eye_gate\bracket_dark.png --bright-bracket runs\eye_gate\bracket_bright.png --expected 0.25
Scope: this is scenario 6 (a320 over SFO, moderate rain, DAYTIME) with the eye's close clamp applied as a constant lighting.brightness_ev of -0.25. It tests whether a clamp-sized exposure step reaches the rendered frame inside the gate. It does not test the night look or the eye itself. The night gate proper is BLOCKED until INTEGRATION.md changes 1-5 (no night scenario and no eye in the render path exist); it then uses the same script with the eye-on frame as --frame.
```

Metric: ev_offset: four frames of the same camera and instant (reference at the look, candidate, and two brackets rendered 0.3 EV darker and 0.3 EV brighter). Per usable pixel, the candidate's position between the reference and the bracket on its side, in log2 of sRGB-decoded luma, scaled to 0.3 EV; then the median. Usable = luma 8..235 in all four frames and each bracket at least 2 codes from the reference. The brackets are rendered through the same tonemapper, so no tone curve is modelled. The old two-frame log ratio is printed as display_ev_offset but no longer gated.

Threshold: PASS when |ev_offset| <= 0.3, at least 0.5 % of pixels are usable, the sign agrees with --expected when |expected| >= 0.1, closing adds no clipped pixels (luma >= 254) and opening adds no crushed pixels (luma <= 1). Exit 0 pass, 1 fail, 2 usage.

Other unmeasured items:

- The today-runnable gate on scenario 6: whether a 0.25 EV step via lighting.brightness_ev lands on the rendered frame inside +/-0.3 EV, i.e. that the frame meter, subject meter, tone curve and 8-bit output neither absorb nor double it. Command in pixel_gate.
- Whether four stills replayed from the same pinned spec are identical apart from exposure. Rain and TAA may differ between runs; the per-pixel bracket metric assumes they mostly do not.
- Whether gate_tool.py stash picks the right file on the laptop: it copies the first frames/<camera>/frame_*[0-9].png of the last batch's run, the same pick as run_test_scenarios.py collect(), but was only tested against a mock directory.
- The night gate proper: BLOCKED until INTEGRATION.md changes 1-5 (eye block in the sky plan, per-frame bias in the commandlet, look_applied record, meters held off, a night scenario added). Whether the compiler accepts a night final-approach prompt is untested.
- Whether a night frame has enough mid-range pixels (0.5 %) for the metric to meter at all.
- Any tier on the laptop: device-loss stability, VRAM and frame cost for tiers 0-3; for tiers 1-3 also that UE 5.7 reads Min/MaxBrightness as EV100 and its speeds as stops per second.
- The eye closing on the runway lights: WITHDRAWN, not merely unmeasured. The recalled candela and step figures and the 1164 m closing distance are deleted, because core/scene/runway.py carries no photometry (candela None, 'never invented'). The baked curve has no light term until that lane has sourced intensities; generate.curve(field) accepts them.

## lighting_exposure.sun_time_of_day.coastal

Lane: `swarm/lanes/lighting_exposure/sun_time_of_day/coastal`

Gate command:

```
python scripts\run_test_scenarios.py --still --only N  (N = the coastal scenario INTEGRATION.md asks the integrator to append; run once before and once after the beauty_look change, copy each frame to runs\coastal_tod_baseline.png / runs\coastal_tod_candidate.png) then: python swarm\lanes\lighting_exposure\sun_time_of_day\coastal\measure_exposure.py --baseline runs\coastal_tod_baseline.png --baseline-ev100 <baseline exposure.ev100> --candidate runs\coastal_tod_candidate.png --target-ev100 <candidate exposure.ev100>
```

Metric: ev_error_stops = median log2(candidate/baseline) of linear luminance over the baseline's mid-tone pixels (0.02..0.50) minus (baseline EV100 - candidate EV100); plus clip_fraction (all channels >= 250) and crush_fraction (all channels <= 4)

Threshold: |ev_error_stops| <= 0.3; clip_fraction <= 0.03 and no more than 0.005 above baseline; crush_fraction <= 0.05. Repeat at sun 8 and 15 deg, where the table is 0.84 and 0.72 stop from the current bands (at 12 deg the expected shift is only 0.19 stop).

Other unmeasured items:

- Whether the table EV100 reaches the frame within +/-0.3 EV: run the pixel gate command above on the laptop
- Whether the table is the right look (grey-card probe at sun 8, 12, 20 deg over water)
- Stability / device loss, VRAM and frame cost of every tier, tier 0 included
- The proposed coastal scenario prompt has not been compiled by either interpreter; no coastal scenario exists in scripts/run_test_scenarios.py today
- Colour temperature: this lane's model gives 3716 K for the direct beam at 12 deg, the aircraft_exterior coastal lanes proposed 4300 K; neither is measured and the integrator must pick one
- The white-surface guard never fires under the stated constants (target EV100 equals meter EV100 in every row)

## atmosphere_clouds.volumetric_cloud_types.storm

Lane: `swarm/lanes/atmosphere_clouds/volumetric_cloud_types/storm`

Gate command:

```
.venv\Scripts\python.exe scripts\run_test_scenarios.py --only 9 --still   (once on current code = reference, once with INTEGRATION.md change 1 = candidate), then: .venv\Scripts\python.exe swarm\lanes\atmosphere_clouds\volumetric_cloud_types\storm\measure_frame.py --frame <candidate frame.png> --reference <reference frame.png> --horizon-row <horizon as a fraction of frame height>
```

Metric: under_deck_error_ev = |log2(median sky luma / median ground luma, sRGB-decoded) - 3.559 stops| (Lambert ground of albedo 0.085 under the baked dome); also black_fraction of sky pixels below 0.4267 x sky median, and sky contrast log2(p95/p05) against the baked 0.264 stops. Display-referred: the tone curve's effect is unmeasured.

Threshold: under_deck_error_ev <= 1.0 and no larger than the reference frame's; black_fraction <= 0.02; |sky contrast - 0.264| <= 1.0 stop. Exit code 0 = pass.

Other unmeasured items:

- Any rendered frame: reference and candidate stills of scenario 9 and the measure_frame.py verdict (commands in pixel_gate)
- Whether tier 0 renders without device loss, and whether the VolumetricCloud march was the cause of the 12 device losses on scene 9
- VRAM and frame cost of every tier (all figures are estimates)
- Tier cvar names (r.VolumetricCloud.*, r.VolumetricRenderTarget.*) are from memory of UE 5.x: check each with `help` in the pinned build
- How much the tone curve compresses the sky/ground ratio, and whether the Google tiles' albedo sits near the assumed 0.085
- TGA/HDR import into the pinned UE build (volume texture from the slice atlas, lat-long orientation of the panorama)
- Jendersie & d'Eon fit constants against the PDF before they ship (not a Windows task, but still open)

## atmosphere_clouds.aerial_perspective.alpine

Lane: `swarm/lanes/atmosphere_clouds/aerial_perspective/alpine`

Gate command:

```
powershell -File scripts\visual_fix_round.ps1 -Round 9111 -Scenes 11 -NoPush -Switches "-NoAerialPerspective" && python swarm\lanes\atmosphere_clouds\aerial_perspective\alpine\measure_aerial_perspective.py stash --scenario 11 --as clear && powershell -File scripts\visual_fix_round.ps1 -Round 9112 -Scenes 11 -NoPush && python swarm\lanes\atmosphere_clouds\aerial_perspective\alpine\measure_aerial_perspective.py stash --scenario 11 --as hazed && python swarm\lanes\atmosphere_clouds\aerial_perspective\alpine\measure_aerial_perspective.py measure --clear runs\alpine_ap\clear.png --hazed runs\alpine_ap\hazed.png --clear-json runs\alpine_ap\clear.render.json --hazed-json runs\alpine_ap\hazed.render.json --box-near <x0,y0,x1,y1> --near-km <km> --box-far <x0,y0,x1,y1> --far-km <km> --altitude-m 5000   [UNMEASURED. Uses only switches that exist today (FLIGHTSIM_RENDER_SWITCHES via visual_fix_round.ps1 -Switches). The two boxes and their distances must be picked by a person from the rendered frame. The measure step refuses with ap_gate.clear_frame_not_clear unless the clear run's own render.json records that the atmosphere was hidden; whether the web app beauty path honours -NoAerialPerspective for scenario 11 is not established from the Mac.]
```

Metric: ap_log_t_ratio_error = mean over R,G,B of |ln(slope_far/slope_near) - ln(T_model(far)/T_model(near))|. Each slope is the least-squares fit hazed = slope*clear + offset over a box of mid-tone pixels. Two boxes are used because hiding the atmosphere also changes the lighting, so a single slope is not a transmittance; the ratio cancels that. T_model takes the Mie layer from the hazed run's render.json; Rayleigh and ozone stay assumed. It measures today's engine frame against the model. It is no longer a candidate-versus-baseline gate, because the candidate render pass does not exist. The model omits height fog and multiple scattering, so fog shows up as error.

Threshold: 0.15, PROVISIONAL and not a pass/fail. It was chosen before any engine frame existed. On synthetic frames through a stand-in ACES-fit curve the metric's own bias was 0.015 to 0.086 (0.001 with no curve), so over half the threshold can be tonemap bias. The first Windows run calibrates it. Exit 0/1 only says which side of 0.15 the number fell; 2 is a named refusal.

Other unmeasured items:

- Every rendered frame: none exists. Run the three-step command in pixel_gate on the laptop.
- Whether -NoAerialPerspective takes effect on the web app beauty path for scenario 11. Check: after round 9111, the measure step either proceeds or prints ap_gate.clear_frame_not_clear; render.log's command line shows whether the token arrived.
- The real value of ap_log_t_ratio_error on engine frames and a defensible threshold for it (the pixel_gate command; 0.15 is provisional).
- The engine's actual Rayleigh and ozone constants and Mie values for scenario 11: read mie_scattering_scale_per_km, mie_absorption_scale_per_km, mie_scale_height_km and aerial_perspective_view_distance_scale from runs\alpine_ap\hazed.render.json after step 2; Rayleigh and ozone are not recorded there and need a one-off log of the SkyAtmosphere component.
- Tiers 1 to 3: no console-variable pass-through was found in the runner, so there is no command for them yet (INTEGRATION.md proposal 1). Device loss, frame time and VRAM for any tier are the stress ladder's to measure.
- The baked-texture post-process pass: NOT WRITTEN, shader never compiled, needs a material asset that cannot be authored on the Mac. Its 0.2 MB / 3-tap cost is an estimate.

## atmosphere_clouds.sun_moon_ephemeris.coastal

Lane: `swarm/lanes/atmosphere_clouds/sun_moon_ephemeris/coastal`

Gate command:

```
.\scripts\render_ue_scenario.ps1 <coastal card> runs\swarm\ephem_coastal\ref_lo -calibration -sun-azim=260.9 -sun-elev=12 ; .\scripts\render_ue_scenario.ps1 <coastal card> runs\swarm\ephem_coastal\ref_hi -calibration -sun-azim=260.9 -sun-elev=60 ; (apply INTEGRATION.md changes A-C, rebuild) ; same two renders into cand_lo and cand_hi ; .\.venv\Scripts\python.exe swarm\lanes\atmosphere_clouds\sun_moon_ephemeris\coastal\bake_ephemeris.py measure --ref-low runs\swarm\ephem_coastal\ref_lo\<frame>.png --ref-high runs\swarm\ephem_coastal\ref_hi\<frame>.png --low runs\swarm\ephem_coastal\cand_lo\<frame>.png --high runs\swarm\ephem_coastal\cand_hi\<frame>.png --lit-rect <x,y,w,h> --shadow-rect <x,y,w,h>
```

Metric: chroma_stops: sun-only light on a neutral surface (sunlit patch minus adjacent shadowed patch, linear RGB); its R/G and B/G at 12 deg divided by the same at 60 deg, compared with the SkyAtmosphere reference ratios 1.3229 and 0.6292; the larger |log2(measured/reference)|. Albedo, exposure and cosine cancel. Secondary, not gating: level_g_stops against 0.1463 (needs identical exposure), within 0.25.

Threshold: candidate chroma_stops <= 0.15 and lower than the reference pair's (predicted about 0.67 for the reference if the zenith-tint reading is right; if the reference already scores under 0.15, drop change C)

Other unmeasured items:

- Every visual and performance result: no frame was rendered and no tier is claimed sustained on the laptop
- Whether TransmittanceMinLightElevationAngle = 90 really lights the ground with the zenith tint (predicted 1.25/1.68/2.72 too bright in R/G/B at 12 deg). Engine behaviour is recalled, not read from UE 5.7 source; the gate's reference pair settles it
- Whether a card stating ground lux leaves the sky about 1.3 stops dark (0.41 of the real sun driving the scattering) under an atmosphere sun light
- UE's Rayleigh and ozone defaults against the 5.7 source, and the engine's own 10-sample transmittance LUT against this 2048-step integral
- Whether -calibration frames are linear or tone-mapped, and the exact behaviour of -sun-elev / -sun-azim (flag names found in source only)
- Whether change C brings back the 'ground blacks out at altitude' problem with the Google tiles' georeferenced origin (fallback in INTEGRATION.md)
- VRAM and frame cost of tiers 1 to 3, and device-loss behaviour
- The coastal card's real site and date: none exists yet, so the lane's site is a stated choice; re-bake with --lat --lon --date

## weather_fx.rain_drops.storm

Lane: `swarm/lanes/weather_fx/rain_drops/storm`

Gate command:

```
.venv\Scripts\python.exe swarm\lanes\weather_fx\rain_drops\storm\run_gate.py
```

Metric: orientation_error_deg: the angle between the candidate's streak direction and the reference pair's, each from the structure tensor of the high-passed luma difference (rain gain 4 minus rain gain 0, same card, same frame number). UNMEASURED. The command has no blanks: it takes scenario 9's prompt, renders four legs through scripts/debug_storm_render.py into runs\swarm_gate\weather_fx_rain_drops_storm\{reference,candidate}\{off,on}\procedural\frames\, picks the last frame number present in both legs, and writes gate.json. No angle is assumed; the expected angle is measured on the build's particle rain. Run on today's build it exits 3 (NOT INTEGRATED) and records only the baseline, because FLIGHTSIM_RAIN_TIER and the drawn_as record are proposals in INTEGRATION.md that the build does not have yet.

Threshold: PASS (exit 0) when orientation_error_deg <= 10, coherence >= 0.35, rain_delta in [0.004, 0.10], and coherence no more than 0.05 below the reference's. Exit 1 fail; exit 3 not measurable (not integrated, a leg did not render, no common frame, off leg not recorded at gain 0, or no expected angle), never a pass. Thresholds are stated, not measured.

Other unmeasured items:

- The whole pixel gate: .venv\Scripts\python.exe swarm\lanes\weather_fx\rain_drops\storm\run_gate.py (never run on the laptop)
- The candidate side of the gate cannot be measured until the integrator lands INTEGRATION.md steps 1-5, including FLIGHTSIM_RAIN_TIER and weather.rain.drawn_as; until then the command exits 3
- Baseline alone, runnable on today's build: .venv\Scripts\python.exe swarm\lanes\weather_fx\rain_drops\storm\run_gate.py --only reference
- Whether the gain-0 leg is truly rain-free and whether two runs of one card give the same pose (turbulence, lightning): read from source only; veil_delta in gate.json is where it would show
- Whether the tier 3 reference (262,144 drops) renders at all on this GPU; if not, --reference-tier 1 or 2 after integration, or --expected-deg N with the operator's angle
- That RainLayers.ush compiles under D3D11 SM5
- Frame time, VRAM and device-loss count of every tier (stress ladder)
- WX.1 streak length on a rendered frame and WX.3 splashes at the reduced budgets
- Whether scenario 9's thunderstorm rain rate matches the bake's 50 mm/h at 2000 m; another rate needs another bake

## weather_fx.lightning.storm

Lane: `swarm/lanes/weather_fx/lightning/storm`

Gate command:

```
.venv\Scripts\python.exe scripts\run_test_scenarios.py --only 9 --clip 6 --spec-dir runs\wx_lightning_specs   (once on current code = reference, once with INTEGRATION.md change 1 = candidate; lengthen --clip until the card's weather.lightning.flashes has a kind: cg flash inside it), then: .venv\Scripts\python.exe swarm\lanes\weather_fx\lightning\storm\measure_frame.py --frames <candidate run>\frames\<camera> --reference-frames <reference run>\frames\<camera>
```

Metric: stroke_contrast (WX.5) = 99.95th percentile of the median-removed linear-luma difference of the stroke frame pair, divided by the same for the median (quiet) frame pair. halo_ratio is also printed for tier 2 comparisons, no threshold yet.

Threshold: candidate stroke_contrast >= 3.0 AND >= 0.9 x the reference's, with the render finishing without a device-lost error. Exit 0 pass, 1 fail, 2 NOT EXERCISED (no stroke in the clip). Thresholds are proposals, uncalibrated against a real frame. The gate shows the channel survives dropping the light; it does not show a prettier frame, and it does not measure stability (only the stress ladder completing scene 9 does).

Other unmeasured items:

- Any rendered frame: nothing was rendered; all luminances are arithmetic
- Whether dropping the flash light (tier 0) removes the scene 9 device-lost crashes, and the per-frame GPU cost of every tier: stress ladder on scenario 9
- WX.5 on the candidate vs reference: the pixel_gate command
- Whether the engine's fog already dims the channel ribbon (decides whether RainSigmaPerM = 0.001304 should ever be set): compare the stroke frame's core against the table's 'no rain' and 'rain applied' columns
- The glow quad's look and overdraw cost at tier 2, and G16 import of the LUT PNGs on the pinned UE build
- VRAM figures for all tiers are estimates
- q = 0.9 is the wide end of the paper's stated range for rain, not a measurement; the (1 - e^-T) energy scale is this lane's approximation; the table assumes uniform rain from camera to channel

## weather_fx.windscreen_water.storm

Lane: `swarm/lanes/weather_fx/windscreen_water/storm`

Gate command:

```
.venv\Scripts\python.exe scripts\debug_storm_render.py --prompt "fly the c172 through a thunderstorm at 900 m with 25 mm/h rain, cockpit camera" --seconds 2 --width 1280 --height 720 --out runs\wsw_reference && set FLIGHTSIM_WINDSHIELD=baked&& .venv\Scripts\python.exe scripts\debug_storm_render.py --prompt "fly the c172 through a thunderstorm at 900 m with 25 mm/h rain, cockpit camera" --seconds 2 --width 1280 --height 720 --out runs\wsw_baked && .venv\Scripts\python.exe swarm\lanes\weather_fx\windscreen_water\storm\measure_glass.py --candidate runs\wsw_baked --reference runs\wsw_reference
```

Metric: glass_bandpass_rms: RMS of luma (0..255) between a 1 px and an 8 px Gaussian blur, averaged over the clip's frames (contrast of drop-sized structure); plus p90 luma and a count of device-loss lines in the run logs

Threshold: Pass needs all four: candidate >= 1.25 x reference; candidate <= 14.0; |p90 luma difference| <= 8; zero device-loss lines in both runs. Thresholds are stated, not measured. FLIGHTSIM_WINDSHIELD does not exist until the integrator makes proposed change 3; the metric shows the water is visible, not that it is photoreal, so the frames still need a look.

Other unmeasured items:

- Every visual result: no frame was rendered. Run the pixel_gate command on the laptop after the integrator wires the baked path and the FLIGHTSIM_WINDSHIELD switch.
- windshield_baked.hlsl has not been compiled (no fxc/dxc on the Mac); first compile is the M_WindshieldRain generation 4 build via scripts\ue_create_materials.py on Windows.
- Frame time and VRAM of every tier, and whether tier 0 is cheaper than the current hashed loop: read from the render log of the two debug_storm_render.py runs above.
- Device-loss stability on the scene that crashed 12 times: .venv\Scripts\python.exe scripts\run_test_scenarios.py --only 9 --still with the baked path on.
- Whether debug_storm_render.py's default quality draws the windscreen at all on a cockpit camera (the material is beauty-only); if the reference shows no glass, both runs need the beauty flag.
- Possible strobing: the project's run-off law gives 10.3 m/s up the glass at 100 kt, several glass heights per frame at 30 fps. Passed through unchanged; flagged in INTEGRATION.md.
- WX.1-WX.6 are untouched by this lane (they cover airborne drops, splashes, the cell, lightning and thunder, not the glass); none was re-run.

## weather_fx.fog.alpine

Lane: `swarm/lanes/weather_fx/fog/alpine`

Gate command:

```
From the repository root in cmd.exe, web app running on 127.0.0.1:8008 (no placeholders, no environment variable): python scripts\run_test_scenarios.py --still --only 11 --spec-dir runs\alpine_fog\off & python swarm\lanes\weather_fx\fog\alpine\measure_fog.py keep baseline & python swarm\lanes\weather_fx\fog\alpine\measure_fog.py fog-spec & python scripts\run_test_scenarios.py --still --only 11 --spec-dir runs\alpine_fog\on & python swarm\lanes\weather_fx\fog\alpine\measure_fog.py keep candidate & python swarm\lanes\weather_fx\fog\alpine\measure_fog.py gate
```

Metric: The A/B is two pinned specs differing only in environment.valley_fog (the FLIGHTSIM_VALLEY_FOG switch is deleted: it never existed and a shell variable would not reach the running web app). gate cuts both frames into 32 px blocks and fits fogged = T*clear + S per textured block. fog_t_abs_error = |lower quartile of T over fogged blocks (T<=0.5) - 0.08|; peak_delta = median mean-absolute linear difference over untouched blocks (T>=0.9). Exit 0 pass, 1 fail, 3 blocked (not measured). TODAY it is expected to exit 3: environment.valley_fog is not integrated, so the validator should refuse the candidate spec as an unknown key (read from core/scenario/validate.py:896, not run) and gate reports that refusal instead of a score. It can pass only after INTEGRATION.md steps 1-2 are in.

Threshold: fog_t_abs_error <= 0.10 with at least 4 fogged blocks (a frame with no fog scores 0.92); peak_delta <= 0.02 with at least 4 untouched blocks

Other unmeasured items:

- Everything visual: no fog has been rendered; the look, tier 0 stability (exit code, device-lost lines, frame time) and all tier costs are UNMEASURED. Command: the pixel_gate windows_command, after the integrator ships INTEGRATION.md steps 1-2
- That today's run of the gate exits 3 with the validator's unknown-key refusal: inferred from source, not run
- Whether scenario 11's frame shows any terrain below 1900 m (if not, the gate fails for want of fogged blocks)
- Whether two stills of one pinned spec are the same shot pixel for pixel under severe turbulence, and how much auto-exposure shifts the untouched blocks
- The 32 px block size and texture-variance threshold are uncalibrated choices
- Whether the FogDensity setter clamps 0.104 to the editor's 0.05; UE volumetric fog range for tier 3

## terrain.dem_posting.alpine

Lane: `swarm/lanes/terrain/dem_posting/alpine`

Gate command:

```
python swarm\lanes\terrain\dem_posting\alpine\measure_dem_posting.py --baseline runs\alpine_dem_baseline.png --candidate runs\alpine_dem_candidate.png --camera-lat <deg> --camera-lon <deg> --camera-alt-m <m MSL> --heading-deg <deg> --pitch-deg <deg> --exclude-cols <first:last aircraft columns> --max-detail-px 4.0   (frames from: python scripts\run_test_scenarios.py --still --only 11, baseline at today's defaults, candidate after the integrator's change with FLIGHTSIM_GOOGLE_TILES_SSE=16, FLIGHTSIM_GOOGLE_TILES_BEAUTY_SSE=16, FLIGHTSIM_GOOGLE_TILES_CACHE_MB=128; camera values from that run's compiled spec)
```

Metric: horizon_range_km (95th percentile over image columns of the range of the farthest GLO-90 ridge the rendered skyline reaches), skyline_match_fraction (columns within 0.15 deg of the predicted skyline), detail_px (effective ground sample size in pixels from the image structure function) and effective_gsd_m = detail_px x pixel footprint at the ROI range

Threshold: candidate horizon_range_km >= max(120, baseline) AND skyline_match_fraction >= max(0.80, baseline) AND detail_px <= 4.0 for tier 0 (<= 2.0 for tiers 1-3). All thresholds and the skyline detector are uncalibrated until run on real frames.

Other unmeasured items:

- Everything visual: no frame was rendered. Whether Google tiles already reach the horizon on the laptop (if they do, the far ring adds nothing and the gate passes on equal numbers)
- Whether any tier renders without device loss; all VRAM figures are estimates (cache cap plus ring buffers) and Cesium's cap is soft
- The far ring itself does not exist in the engine yet: it needs the integrator's actor, the FLIGHTSIM_GOOGLE_TILES_CACHE_MB knob and the pixel-depth-offset material described in INTEGRATION.md
- Gate calibration on real frames: skyline edge detector under haze and bright snow, the 0.15 deg tolerance, detail_px under TAA or sharpening, and --roi-range-m (default 6000 m is a guess)
- Ring appearance: height-rule colours are uncalibrated, and pooled maxima may stand 1-2 px proud of coarse tile ridges
- Camera position, heading and pitch for the gate must be read from the scenario 11 run; I did not confirm where that run records them
- Windows command: python scripts\run_test_scenarios.py --still --only 11 (twice, baseline and candidate), then the measure_dem_posting.py command in pixel_gate

## terrain.horizon_lod.alpine

Lane: `swarm/lanes/terrain/horizon_lod/alpine`

Gate command:

```
set FLIGHTSIM_GOOGLE_TILES_SSE= && python scripts\run_test_scenarios.py --still --only 11 && copy runs\test_scenarios\11_*.png runs\alpine_hlod_baseline.png && set FLIGHTSIM_GOOGLE_TILES_SSE=5 && python scripts\run_test_scenarios.py --still --only 11 && copy runs\test_scenarios\11_*.png runs\alpine_hlod_candidate.png && python swarm\lanes\terrain\horizon_lod\alpine\measure_horizon_lod.py --baseline runs\alpine_hlod_baseline.png --candidate runs\alpine_hlod_candidate.png --tier 1 --pitch-deg <camera pitch of the shot> --gsd-box <x0,y0,x1,y1 of textured ground> --columns <c0,c1 clear of the aircraft>   (after INTEGRATION.md change 1, use set FLIGHTSIM_HORIZON_LOD=<tier> instead of the SSE variable; tier 0 needs that change)
```

Metric: gsd_ratio = candidate / baseline effective ground sample distance in the same ground box (0.5 / median radial spatial frequency of luminance, times pixel footprint at the box's slant distance); and horizon_range_km = ground range inverted from the 90th-percentile skyline depression angle (a lower bound that saturates near 179 km and behind ridges above the horizon)

Threshold: gsd_ratio <= 1.10 (tier 0), 0.92 (tier 1), 0.80 (tier 2), 0.65 (tier 3); AND horizon_range_km >= 100 km and >= 95% of baseline (capped at 178.9 km); AND the render finished with no device loss (checked from the run's exit code and render.log, not by the script)

Other unmeasured items:

- Every visual and performance claim: no tier has been rendered. Run the pixel_gate command on the laptop.
- Whether tier 0 (or today's SSE 6 frame) holds without device loss on scenario 11; the model's central estimate puts it at about two thirds of the 491 MB pool
- Tile-count model constants (tile span per geometric error = 16, 0.45 MB per tile) are ASSUMED. Calibrate with FLIGHTSIM_HORIZON_LOD_STATS=1 (proposed LogSelectionStats in INTEGRATION.md change 3) and compare render.log's rendered-tile count with est_tiles_drawn
- Cesium tileset property names were typed from memory; the reflection record on Windows must show which were found
- Whether Cesium fog culling drops anything at 5000 m (from memory it likely does not, so tier 1's 'fog culling off' may be a no-op)
- Whether anything else cuts far terrain (finite sky dome, tile-load timeout)
- Real camera pitch and a ground box for scenario 11: the bake assumes pitch -5 deg; the gate takes the real pitch as an argument. Camera roll is assumed zero.
- That scenario 11 is the Matterhorn shot: taken from the atmosphere lane's notes, not verified here
- frame_NNNN_depth.f32 would give a horizon range that does not saturate; its format was not read, so the gate does not use it

## terrain.detail_normals.alpine

Lane: `swarm/lanes/terrain/detail_normals/alpine`

Gate command:

```
.venv\Scripts\python.exe swarm\lanes\terrain\detail_normals\alpine\run_gate.py
```

Metric: Three stills of scenario 11 from one pinned spec (detail off, off again, tier 0) plus the baseline depth image. Regions are picked from depth, not by hand. Checks: gsd_ratio (candidate / baseline effective GSD from f95 of gradient power, near box), diff_coherence (lag-1 autocorrelation of the difference, rejects per-pixel noise), clip_increase, far_contrast, far_mean_abs, skyline_shift. The off/off pair is the noise floor. Exit 0 provisional_pass, 1 fail (including no_effect), 2 not_applicable, 3 refused before rendering. TODAY IT EXITS 3 (NOT WIRED): the FLIGHTSIM_ALPINE_DETAIL_NORMALS switch does not exist in the engine until INTEGRATION.md changes 1 to 3 are applied. Never run on the laptop.

Threshold: PROVISIONAL, chosen before any frame existed: gsd_ratio <= 0.85; diff_coherence >= 0.10; clip_increase <= 0.005; far_contrast 0.95 to 1.05; far_mean_abs <= 2.0 levels; skyline_shift <= 1 px. Applicability: off/off mean abs <= 1.0 level and GSD within 5 %; nearest 96 px ground box within 1868 m. A pass is a proxy for added fine detail, not a photorealism claim; near_crops.png still needs a person.

Other unmeasured items:

- Everything visual. No frame has been rendered with these maps. Command: .venv\Scripts\python.exe swarm\lanes\terrain\detail_normals\alpine\run_gate.py (only after INTEGRATION.md changes 1 to 3; exits 3 until then).
- Whether run_gate.py itself works on Windows: starting and stopping uvicorn, the app handing its environment to UnrealEditor-Cmd (assumed from how FLIGHTSIM_GOOGLE_TILES is read, not verified), and frame_NNNN_depth.f32 being written beside the frame in a web-app still.
- Whether scenario 11 has any ground within 1868 m. At 5000 m over a roughly 4478 m summit (from memory) it may not; the gate then returns not_applicable and tier 0 does little in this scenario.
- Whether two detail-off stills repeat pixel to pixel with the default storm weather and rain on. If not, the gate returns not_applicable rather than a verdict.
- All thresholds: to be reset from null_gsd_ratio and null_mean_abs after the first real run.
- Device loss, frame time and VRAM for every tier, tier 0 included (run log device-lost count and stat unit from the same runs).
- Whether the pinned UE build imports a DX10-header BC5 DDS unchanged (PNG fallback: bake with --png).
- Tiers 1 to 3: same command with --tier N after baking that tier's JSON.

## terrain.land_cover_splat.coastal

Lane: `swarm/lanes/terrain/land_cover_splat/coastal`

Gate command:

```
.venv\Scripts\python.exe swarm\lanes\terrain\land_cover_splat\coastal\run_gate.py --tier 0
```

Metric: CANNOT RUN ON TODAY'S TREE: the command exits 3 (REFUSED terrain.land_cover_splat.gate.not_integrated) until INTEGRATION.md changes 1 and 3 are merged, then refuses no_coastal_scenario until change 5 adds a scenario whose name contains 'coastal' (no coastal place exists in the repo either). It no longer renders two copies of the same scene. Once integrated, with the web app stopped: it starts its own app with FLIGHTSIM_LAND_COVER_SPLAT=off then =<tier> set in the process environment (no shell quoting), renders one pinned-spec still per side, and measure_ground.py reads the camera from each run's capture_manifest.json (position_alt_m, -pitch_deg, 2 atan(height_px / 2 fy_px)). Metrics: gsd_ratio and range_ratio = candidate / baseline effective_gsd_m (ground band 1 to 3 km) and visible_range_km, candidate visible_range_km, candidate mean linear luminance, device-lost lines in the candidate's render.log. Exit 2 (could not measure) unless the engine's frames/<camera>/render.json carries land_cover_splat.applied == true in the candidate and not in the baseline; also exit 2 for differing cameras, roll over 0.5 deg, or identical pixels. run_gate.py has never been executed on Windows.

Threshold: gsd_ratio <= 1.02; range_ratio >= 0.95; candidate visible_range_km <= max(1.15 x 15.7 km, 1.05 x baseline); candidate mean linear luminance >= 0.005; zero device-lost lines in the candidate render.log; a candidate render that does not end 'done' is a FAIL (exit 1). Thresholds are authored. Frame-to-frame noise on the laptop is unmeasured, so a ratio inside 2 % may be noise, and a tier 0 pass would mean 'drawn and no measurable harm in one frame', not 'looks better'.

Other unmeasured items:

- Everything visual: no frame of this lane has been rendered at any tier. After INTEGRATION.md changes 1-5: .venv\Scripts\python.exe swarm\lanes\terrain\land_cover_splat\coastal\run_gate.py --tier 0 (then --tier 1, 2, 3 up the stress ladder).
- VRAM and per-pixel cost at every tier are estimates; device-lost behaviour is unknown. No tier is claimed sustained.
- run_gate.py end to end on Windows: starting and stopping uvicorn, calling the runner's run_batch in-process, the regex compiler on a coastal prompt. Never executed there.
- The engine side does not exist: the switch, the card's land_cover_splat request, the render.json echo, the texture upload and the material node are all proposals in INTEGRATION.md. The HLSL channel swizzle and world-axis signs are unconfirmed.
- A coastal scenario and a coastal place: neither exists in the repo; the proposed prompt (shared with the sun_time_of_day lane) has not been compiled.
- A real capture_manifest.json of a coastal run has not been read: whether the chase camera is level within 0.5 deg, whether 8+ rows see ground at 1 to 3 km, and which vertical datum position_alt_m is in (sea surface assumed at 0; override with --surface-elevation-m).
- The device-lost log pattern is UE's usual D3D11 wording, not checked against this build's render.log.
- A real WorldCover crop through the bake: .venv/bin/python swarm/lanes/terrain/land_cover_splat/coastal/bake_coastal_splat.py --class-map <cache>/<key>_landcover/class_map.png --landcover-json <cache>/<key>_landcover/landcover.json --extent-m <X> <Y> --tier 0 --out <cache>/<key>_splat_t0 (Mac, once a coastal scene's land cover is baked).
- Run-to-run noise of the two gate metrics on the laptop (rain, temporal AA) is unmeasured.

## hardware_perf.stress_ladder.alpine

Lane: `swarm/lanes/hardware_perf/stress_ladder/alpine`

Gate command:

```
python swarm\lanes\hardware_perf\stress_ladder\alpine\run_ladder.py   (web app serving on 127.0.0.1:8008 and INTEGRATION.md change 1 applied; add --max-tier 0 to try tier 0 alone)
```

Metric: sustained_tier printed by the command (highest tier with 3 consecutive passing runs of test scenario 11, 3 s clip), together with device_lost_total; written to measured\hardware_budget_measured.json

Threshold: sustained_tier >= 0 (exit code 0). Each of the 3 tier-0 runs needs: 0 device-lost/GPU-crash/out-of-memory log lines (reference: 12 device-lost crashes on scene 9); >= 8 frames; p95 wall time between frames <= 1000 ms; free RAM never < 1024 MB; CPU throttle ratio >= 0.80; thermal zone <= 95 C where the counter exists; sampled frames black fraction <= 0.5 and luma stddev >= 2.0. Only then is the budget written with measured=true.

Other unmeasured items:

- Everything the gate is about: frame time, GPU memory, free RAM, throttle/thermals and device-loss count for all 4 tiers. Command: python swarm\lanes\hardware_perf\stress_ladder\alpine\run_ladder.py
- Blocker: the ladder cannot apply a tier until the integrator adds the hook in webapp/runs.py (INTEGRATION.md change 1, reads runs\stress_ladder\active_tier.json). Until then every run is refused as tier_not_applied.
- Whether -DPCVars reaches the FlightSimRender commandlet (fallback given: -ExecCmds); check render.log on the first tier-0 run
- Whether killing typeperf leaves its redirected CSV intact; if not the run is refused as sampler_empty rather than passed blind
- Whether the laptop exposes the Thermal Zone Information counter; without it the thermal check is the CPU throttle ratio only and temperature is recorded as null
- Tileset limits (MaximumScreenSpaceError / MaximumCachedBytes) need INTEGRATION.md change 2 in FFlightSimGoogleTiles; without it the tile-cache term is not controlled by the tier
- hardware_budget.py does not read the measured file until INTEGRATION.md change 3 is applied (the snippet uses REPO, which that module may need to define)
- The 1000 ms p95 limit is a chosen margin (half the default 2 s GPU timeout), and frame time is wall clock between frame files including readback and PNG encode, so a slow disk can fail it

## hardware_perf.vram_budgeting.alpine

Lane: `swarm/lanes/hardware_perf/vram_budgeting/alpine`

Gate command:

```
python swarm\lanes\hardware_perf\vram_budgeting\alpine\measure_vram_gate.py --tier 0
```

Metric: UNMEASURED; never run. Run from the repo root in the venv with the web app stopped. The gate does two passes (reference = today's render path with SSE default 8; tier0 = FLIGHTSIM_GOOGLE_TILES_SSE=24 plus the tier cvars as one -ini:Engine:[SystemSettings]: token in FLIGHTSIM_RENDER_SWITCHES). Each pass samples typeperf GPU Adapter Memory idle, starts its own uvicorn app, runs scripts\run_test_scenarios.py --still --only 11 --compiler regex while sampling about every 2 s, then copies the run's first frame and render.log to runs\alpine_vram_gate\. Metrics: device-lost line count in the tier render.log; peak shared+dedicated GPU memory above idle (a lower bound at 2 s sampling); ground sharpness = median over a 4x8 grid on the lower half of the frame of candidate/reference Laplacian variance. Frame time is not measured by this gate; the -csvprofile path and the measured=true patch were deleted.

Threshold: both renders finish AND 0 device-lost lines AND peak GPU memory above idle <= 491 MB AND ground sharpness ratio >= 0.95 (0.95 is a chosen threshold, not validated)

Other unmeasured items:

- The whole gate: python swarm\lanes\hardware_perf\vram_budgeting\alpine\measure_vram_gate.py --tier 0 (then --tier 1, 2, 3 for the ladder). Its orchestration (typeperf sampling, app start/stop via taskkill, the UE render) has never executed anywhere.
- Whether the pinned UE build honours the -ini:Engine:[SystemSettings]: override in the render commandlet. The gate reports pool_cvar_seen_in_log; false or null means the pass measured SSE 24 only. --no-cvars runs SSE only on purpose.
- The cvar names in the tier blocks (written from memory by the original builder, still unconfirmed against the pinned engine).
- Whether the Thermal Zone Information counter exists on the laptop. If it does not, the gate lists temperature under not_measured and still gives a memory result.
- Whether typeperf -sc 1 output on that Windows build matches the parser (tested only against a synthetic sample with the banner lines I expect).
- Whether the lower half of the matterhorn chase frame is mostly terrain. The metric assumes it; --ground-box x0,y0,x1,y1 overrides it after looking at reference.png.
- Whether --compiler regex compiles scenario 11 on the laptop the same way in both passes (the driver's docstring says every prompt was validated with the offline interpreter; not re-run here because webapp imports need yaml, absent on this Mac).
- Frame time for any tier: not covered by this lane any more. The budget's measured flag stays false until a frame-time lane measures it.
- Peak GPU memory, device-loss count and ground sharpness for every tier.

## hardware_perf.capture_resolution_ladder.alpine

Lane: `swarm/lanes/hardware_perf/capture_resolution_ladder/alpine`

Gate command:

```
Needs INTEGRATION.md changes 1-3 (multi-pass capture, per-tile Cesium camera, --capture-ladder-tier flag) first. Then: typeperf "\GPU Adapter Memory(*)\Shared Usage" "\GPU Adapter Memory(*)\Dedicated Usage" "\Thermal Zone Information(*)\Temperature" -si 1 -sc 20 -f CSV -o runs\ladder_idle.csv -y && python scripts\run_test_scenarios.py --still --only 11 && copy runs\test_scenarios\11_*.png runs\alpine_ladder_t0.png && (start /b typeperf "\GPU Adapter Memory(*)\Shared Usage" "\GPU Adapter Memory(*)\Dedicated Usage" "\Thermal Zone Information(*)\Temperature" -si 1 -f CSV -o runs\ladder_t1.csv -y) && python scripts\run_test_scenarios.py --still --only 11 --capture-ladder-tier 1 && taskkill /im typeperf.exe /f && python swarm\lanes\hardware_perf\capture_resolution_ladder\alpine\measure_capture_gate.py --tier 1 --reference runs\alpine_ladder_t0.png --candidate runs\test_scenarios\11_ladder_t1.png --resolve-report runs\test_scenarios\11_ladder_t1.resolve.json --ridge-box <x0,y0,x1,y1> --ground-box <x0,y0,x1,y1> --typeperf runs\ladder_t1.csv --idle runs\ladder_idle.csv --log <UE log of the run> --frames <CsvProfiler csv of the run> --write-measured docs\hardware\capture_ladder_measured.json   (repeat with tier 2, then 3; boxes are pixels of the 1280x800 tier 0 frame)
```

Metric: alias_ratio: candidate box-averaged down to 1280x800, then the diagonal (HH) share of 2x2 Haar detail energy in the ridge-against-sky box divided by the same share in the tier 0 reference. Reported alongside it: device-lost log lines, max FrameTime (ms), peak GPU memory above idle (MB), peak thermal-zone temperature (C), seam excess (8-bit levels, tiled tiers), sample spread (8-bit levels, multi-sample tiers), and ground sharpness ratio (Laplacian variance of the ground box, candidate vs Lanczos-enlarged reference, tiers 2-3).

Threshold: alias_ratio <= 0.75 AND device-lost lines == 0 AND max frame time <= 1000 ms AND GPU memory above idle <= 491 MB AND peak temperature <= 90 C AND seam excess <= 1.0 level (tiers 2-3) AND sample spread <= 1.0 level (tiers 1, 3) AND ground sharpness ratio >= 1.0 (tiers 2-3). Any missing measurement counts as not passed. measured=true is written only when the tier passed with frame time, memory and temperature all recorded. Thresholds are estimates: 0.75 comes from the synthetic ridge (4 samples gave 0.63-0.67), 90 C and 1000 ms are judgement values.

Other unmeasured items:

- Everything about the real frame: no tier has been rendered. Frame time, VRAM, temperature and device-loss behaviour of tiers 0-3 are unknown; run the pixel_gate command per tier on the laptop
- The C++ custom-projection lines in INTEGRATION.md are uncompiled; the y-offset sign on the D3D11 scene capture must be confirmed by the seam check on the first tier 2 frame
- Whether Google tiles actually refine to 2560-wide detail with a per-tile Cesium camera, and whether the tile cache stays inside the 491 MB pool when they do (ground sharpness ratio >= 1.0 and the memory check decide this)
- Whether the 32 px gutter hides ambient-occlusion and TAA edge differences between tiles (seam excess <= 1.0 level)
- Whether the sim, clouds and exposure really hold still across passes (sample spread <= 1.0 level)
- Whether the laptop exposes a usable thermal zone to typeperf; if not, no tier can set measured=true with this gate
- Whether the laptop has a TdrDelay registry override (the 1000 ms ceiling assumes the 2 s default): reg query HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers /v TdrDelay
- The alias_ratio 0.75 and sharpness thresholds on a real silhouette; they were set from a synthetic scene only
- hardware_budget measured=true: not set. Only measure_capture_gate.py --write-measured on the laptop can produce the patch, and core/render/hardware_budget.py does not read it until INTEGRATION.md change 4 is made

## validation.pixel_metrics.alpine

Lane: `swarm/lanes/validation/pixel_metrics/alpine`

Gate command:

```
python swarm\lanes\validation\pixel_metrics\alpine\run_alpine_gates.py --shot runs\alpine_gates\shot.json --out runs\alpine_gates\report.json --tier 0   (first: copy swarm\lanes\validation\pixel_metrics\alpine\shot.template.json to runs\alpine_gates\shot.json and fill every null; run with Unreal closed)
```

Metric: (1) summary.gates_passed out of summary.gates_total across all alpine lane gates, with gates_unmeasured, gates_error, stale and unlisted all empty; (2) health.penalty_delta = penalty(candidate) - penalty(reference), where penalty = snow_clip/0.02 + crushed/0.05 + snow_chroma/0.12, on the same shot

Threshold: Exit code 0, which requires gates_passed == gates_total with nothing unmeasured, and penalty_delta <= 0.05 with block SSIM >= 0.35, detail_ratio >= 0.95, snow_clip <= 0.02, crushed <= 0.05, snow_chroma <= 0.12, mean linear luminance in [0.05, 0.60] and no blank frame. All thresholds are uncalibrated starting values. Exit 3 means the calibration selfcheck failed and no number from the run is usable.

Other unmeasured items:

- The whole gate run: python swarm\lanes\validation\pixel_metrics\alpine\run_alpine_gates.py --shot runs\alpine_gates\shot.json --out runs\alpine_gates\report.json --tier 0
- Whether the calibration selfcheck passes with the laptop's numpy/Pillow build (first step of the same command; exit 3 if not)
- Every health threshold (snow_clip, crushed, snow_chroma, mean luminance, SSIM, detail_ratio, flicker) against real alpine frames; none has seen a real capture
- Runner RAM use and run time on the laptop; the 40 MB and 120 MB figures are estimates
- Sequence scan for blank frames and flicker: the same command with --tier 2, with the candidate set to the beauty-frame directory
- Whether each sibling gate accepts the arguments as the shot file supplies them. hardware_perf.vram_budgeting.alpine builds some argument names at run time, so those must be added by hand in its lane block.
