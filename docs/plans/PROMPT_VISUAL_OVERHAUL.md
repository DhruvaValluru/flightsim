# Visual overhaul build session: startup prompt

How to start it, on the MacBook, in the `flightsim` checkout:

```bash
git pull
```
```bash
claude "$(sed -n '/^---8<---$/,$p' docs/plans/PROMPT_VISUAL_OVERHAUL.md | tail -n +2)"
```

That sends everything below the scissors line as the first message. Approve
the `claude-flow` MCP server and the ruflo plugins if asked.

---8<---

ultracode. You are the lead of a **visual overhaul build session** for the
FlightSim project. The pipeline works: Phases 1, 2 and 3 built camera
control, labelled capture, annotation, randomisation and a web app. **The
pictures look bad.** The owner calls the current renders "very, very weak".
This session exists for one thing: make the rendered frames look like a
current, near-photoreal flight game (think Microsoft Flight Simulator 2024 or
a AAA cinematic). Be ambitious. Try new approaches, take big swings, and
don't wait for permission on technical choices. Bring back pictures, not
plans.

## 1. Read first, in this order

1. `CLAUDE.md`. Its rules are hard limits, and they win over everything
   else here, ruflo's agents and commands included.
2. The four phase documents (converted from the owner's Word files):
   - `docs/plans/phase1_camera_implementation_plan.md`: cameras, the pose
     solver, the capture manifest. Pixels must agree with the recorded
     geometry.
   - `docs/plans/phase2_static_code_review.md` and
     `docs/plans/phase2_gate_check_completed.md`: annotations (masks, class,
     depth, boxes), the seven annotation gates and what failed.
   - `docs/plans/phase3_requirements.md`: one simple pipeline, J-35/J-15/J-11
     subjects, desert and forest environments, payload boxes, a demo video.
3. `docs/VISUAL_FIDELITY_PLAN.md`: the existing audit of the renderer (§1),
   the gap to MSFS (§2), phases V0–V9 (§4) and the status table (§8). Only
   V0 and part of V1 were ever written. Treat it as a starting map, not a
   ceiling.
4. `NEXT.md` (all the gotchas), `docs/TOOLCHAIN.md` (UE 5.7.4 pin, Cesium
   for Unreal 2.30.0), `docs/PHASE3_LOG.md` (the Gate 6 `B4` rows show what
   the renders actually measured), and `docs/WEATHER.md`.
5. The renderer itself: `ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/`,
   in particular `FlightSimVisualScene.cpp`, `FlightSimRenderCommandlet.cpp`,
   `FlightSimGoogleTiles.cpp`, `FlightSimSky.cpp`, `FlightSimWeather.cpp`,
   `FlightSimWeatherLook.cpp`, plus `ue/Config/DefaultEngine.ini`,
   `scripts/ue_import_aircraft.py`, `scripts/ue_create_materials.py`,
   `core/scene/` and `experiments/gate6_visual.py`.

## 2. Hard limits (do not break these while chasing the look)

- **Google Photorealistic 3D Tiles are the ground of every terrain render**
  (CLAUDE.md, owner's rule). Improve how they look, light and blend. Never
  make them optional.
- **Storm weather is on by default** in the web app (CLAUDE.md). Make it
  look better; don't turn it off.
- **Labels must still match pixels.** Masks, class, depth and boxes come
  from the same frame as the beauty image. Any effect that moves pixels
  (lens distortion, chromatic aberration, AI upscaling or restyling, heavy
  motion blur) goes on the beauty pass only, and must either keep geometry
  aligned within the gate tolerances or be recorded in the manifest so the
  labels are transformed to match. Re-run `python -m flightsim.verify` after
  every look change.
- **Physics doesn't change.** This is visual-only work, and the manifest says so.
- Every new asset or dataset has a pinned source, sha256 and a licence that
  allows redistribution. No NC licences. No placeholder airframes.
- No scheduled check-ins, no PR subscriptions, no polling (CLAUDE.md).

## 3. Machines

Check what this Mac has before planning: `ls /Users/Shared/Epic\ Games` and
`scripts/ue_preflight.sh`. The project pins **UE 5.7.4**.

- If UE 5.7 runs here, build with `./scripts/build_ue.sh` and render
  locally. Apple Silicon runs Lumen, Nanite and Virtual Shadow Maps on
  Metal, but hardware ray tracing is limited, so tune for software Lumen.
- If it doesn't, write the code here and send render jobs to the Windows
  session (RTX 5080, UE 5.7.4, Cesium 2.30.0) the way
  `docs/phase3/PROMPT_MAC.md` describes: `ListAgents`, `SendMessage`, and
  results read back from the repo. Hardware ray tracing and path tracing
  belong on Windows.

Say which case you're in, in one line, before starting.

## 4. Start with a baseline you can look at

Before changing anything, render a **baseline contact sheet**: the same
3–4 shots before and after every change. Use a chase cam over real terrain
at golden hour, a low pass over desert, a forest scene in rain, and a
cockpit-shoulder view. Use `experiments/gate6_visual.py --quality beauty`
and the capture CLI. Save it under `runs/visual/<step>/` and **open the
PNGs and look at them**. Write down, bluntly, what makes each one look fake:
flat light, plastic aircraft, blurry ground, empty horizon, aliasing, no
clouds, no atmosphere depth, bad exposure, and so on. That list is your
backlog.

## 5. Approaches to try (pick by impact, measure each)

Rank these by how much they fix the baseline's worst problems, then go.
Each one ships as a before/after pair on the contact sheet.

1. **Render quality foundation.** Make the beauty path real. Use Movie
   Render Queue, or the commandlet with warm-up frames, at 1920×1080 or
   higher. Turn on TSR with temporal sample accumulation for stills, Lumen
   GI and reflections (hardware RT on Windows), Virtual Shadow Maps and
   Nanite. Finish V0 in `VISUAL_FIDELITY_PLAN.md` and actually build it.
   On Windows, try the **Path Tracer** for hero frames as an upper bound
   on quality.
2. **Physical light and exposure.** A sun at ~100 klux from the ephemeris
   (`core/environment/sun.py` already exists), sky light from the
   atmosphere, EV100 exposure, a filmic ACES tonemap and a colour grade
   (LUT). Most "video game" quality comes from light, not polygons.
3. **Atmosphere and clouds.** Tune SkyAtmosphere and aerial perspective so
   the distance turns blue and hazy, add UE Volumetric Clouds layered by
   weather (cumulus, overcast, the storm cell), and cast cloud shadows on
   the tiles. Make rain, wet surfaces and lightning read on camera.
4. **The ground.** Google 3D Tiles look smeared up close and flat-lit. Try
   Cesium's lighting options, a detail-normal and micro-roughness overlay
   by land class, horizon fill beyond the tile extent, and PCG-placed
   Nanite trees, rocks and grass over the tiles for the forest and desert
   scenes, so the near ground has real geometry.
5. **Aircraft.** Today's FlightGear meshes with converted materials look
   like plastic. Author proper PBR master materials (painted metal with
   clearcoat, panel-line normals, weathering, glass with reflections,
   emissive nav lights), enable Nanite where the capture handles it
   (NEXT.md gotcha 5), and add heat haze and contrails. Look for
   higher-detail models with redistributable licences for the J-11 and
   the Phase 3 subjects.
6. **Camera feel.** Real lens settings (focal length, aperture, depth of
   field on the cinematic preset), subtle shake, motion blur matched to
   shutter speed, bloom, lens flare off the sun, vignette and film grain.
   All beauty-only.
7. **Something new.** You're encouraged to try approaches nobody has
   planned yet. Examples: Gaussian splats or photogrammetry for hero
   locations, a geometry-preserving neural enhancement pass on the beauty
   frames (measure label alignment before and after), higher-resolution
   open imagery blended under the tiles, or MetaHuman ground crew. If it
   looks dramatically better and keeps the labels honest, keep it.

## 6. How to use ruflo and sub-agents

- Spawn a small team and give each a lane: **look-dev** (lighting,
  exposure, post), **world** (tiles, ground, vegetation, clouds),
  **aircraft** (materials, meshes), **render-path** (MRQ, settings, build),
  and **verifier**, which re-runs `flightsim.verify`, `pytest` and Gate 6
  after each merge and rejects anything that breaks label alignment.
- Use ruflo memory (`mcp__claude-flow__memory_store` / `memory_search`) to
  keep a shared record of what each probe render measured, so lanes don't
  redo each other's experiments.
- Don't use ruflo's daemon, schedules or loops to watch PRs or CI.

## 7. Done means

- A final contact sheet in `runs/visual/final/` with every baseline shot
  next to its final version, plus a 10–20 second beauty clip of a chase-cam
  pass. That's the "almost a hyper-realistic video game" evidence the owner
  asked for.
- `docs/VISUAL_FIDELITY_PLAN.md` §8 updated with what was built and what
  each step measured, and `NEXT.md` updated.
- `python -m flightsim.verify` passes on a labelled render made with the
  new look, and the full `pytest` suite stays green.
- Work is on one branch off `phase-2-final`, in small commits with real
  messages. Push it, open one draft PR, report once, and stop.

When a choice is purely technical, make it and write down why. Ask the
owner only when a choice costs money, needs an account or key, or would
break a rule in §2.
