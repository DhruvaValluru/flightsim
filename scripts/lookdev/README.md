# Look-dev harness

A test scene's beauty frame, built in the ONE Mac editor so a look lane can
change a material / look JSON / bridge C++ and see a 1280x720 still without a
render-commandlet run. Windows still renders the frames that count.

## Commands

`S` is the session scratchpad, `W` the editor's checkout (`$S/mac-ue`), `PY`
`/Users/dhruva/flightsim-old/.venv/bin/python`.

1. Host, from the editor's checkout (so paths match the editor's project):

       cd $W && $PY scripts/lookdev/prepare.py 1 3 7 9 10 13 15 --out $S/lookdev/prep \
           [--switches "-tornado-look=vdb -cloud-impostors=pilot"] [--spec-dir <pinned specs>]

   It compiles each prompt through the web app's `/compile` (regex compiler,
   in-process), applies the batch's lighting edits, and runs the web app's
   own render flow with the commandlet launch replaced by a recorder. Output
   is `$S/lookdev/prep/<NN>/lookdev.json`: the card, sky/beauty-look/
   hero-lighting sidecars and the exact commandlet argument list. No engine
   process is started. The aircraft import is only recorded.

2. Editor (Monolith `editor_query run_python`), once per editor session:

       exec(open("<W>/scripts/lookdev/lookdev.py").read()); setup()

   This runs `scripts/ue_create_materials.py` and `scripts/ue_import_aircraft.py`
   in the editor (the round's "materials" and "aircraft" prep).

3. Per scene:

       exec(open("<W>/scripts/lookdev/lookdev.py").read())
       build(1); capture(1, "base")      # -> $S/lookdev/base/1.png

   `build` opens a blank unsaved map, then runs `FlightSim.LookDev.Build`
   (ue/Plugins/FlightSimBridge/.../FlightSimLookDev.cpp). The beauty camera is
   the actor `LookDev_BeautyCamera`, and the level viewport is moved to it.
   `capture` waits for the tiles to stream (FFlightSimGoogleTiles::WaitForView),
   runs 8 warm-up captures, then writes the PNG. `FLIGHTSIM_LOOKDEV_DIR`
   changes the output root.

## What it builds

These run with the commandlet's own arguments (and on the process command line
while each command runs): georeference as `FFlightSimScenarioWorld::Populate`
sets it, the airframe via the commandlet's own `BuildMeshAirframe`, the scene
options (sun, fog, X-Plane lighting, card look, weather look, sky plan),
`FFlightSimVisualScene::Build`, ice overlay, `FFlightSimWeather`, impostor
clouds, Google tiles via Cesium plus `ApplyBeautyGround` (the sea),
`FFlightSimBeautyFallback`, the exposure (sky plan / card camera / look.ev100 /
bias), `ApplyBeautyPostProcess` (and so `FFlightSimBeautyLook::Apply`),
`FFlightSimHeroLighting::Apply` and `FFlightSimBeautyLook::ApplyEngineLook`.

## How it differs from a Windows render

- The renderer is Metal SM5 with Lumen and VSM off. Windows is D3D11 SM5 on an
  Intel iGPU, so shader precision, the cloud march budget (`ConstrainedGpu`)
  and the shadows differ.
- The aircraft is placed at the card's initial condition, with the actor origin
  on the stated point. The JSBSim CG offset is not applied, so the frame can be
  off by a few metres; for the B747 the datum is about 30 m off.
  The aircraft does not fly, so it has trim attitude 0 and no gear or surface
  animation.
- The camera is the first pose of the card's solved track. prepare.py skips
  the host pre-flight, so the poses are solved over the Python flight, as on a
  machine without the engine. Windows solves them over the host flight.
- The spec comes from the regex compiler unless `--spec-dir` gives the round's
  pinned specs. Windows rounds pin specs from the LLM compiler.
- The still is 1280x720 at the camera's own field of view. Beauty quality
  renders 1920x1080. Supersampling, the TSR still accumulation, motion blur,
  the per-frame sun animation and lightning timing, the commandlet's
  sky-capture sequence and `scripts/beauty_post.py` are not run.
- Things it leaves out: the beauty tornado (`BuildBeautyTornado`, scene 10),
  AircraftFX (contrails and wet airframe), traffic, the stress/probe overrides,
  the shadow shot and `-cloud-cover/-cloud-base` flags.
