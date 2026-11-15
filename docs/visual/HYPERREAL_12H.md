# Hyper-realism push: Monolith MCP + a 12-hour Opus/Fable run (Windows)

Owner request, 2026-11-14: every frame should look photographic. **All building happens on the Mac; the
Windows laptop only tests** (renders, verify, frames, and Monolith for inspecting the editor). Today the clouds look
rubbery, the tornado has no structure, the rain is not convincing, and the rest of the
project lags behind. Opus leads the visual build; Fable agents do the engineering; every
change is tested on this laptop, using the Monolith MCP for the editor.

## Part A: set up Monolith (p3-windows does this, confirming each install with the owner)

The repo is `C:\Users\kanth\flightsim`, and the UE project folder is `C:\Users\kanth\flightsim\ue`
(`ue\FlightSim.uproject`). Below, `<UEPROJ>` = `C:\Users\kanth\flightsim\ue`.

0. **Checkpoint.** `git status`. Commit only what belongs in git (no `runs\`, no caches), on a local
   branch `pre-mcp-checkpoint`, and do not push junk. Monolith can modify and delete assets.
1. **Prereqs.** UE 5.7.4, VS 2022 (Game development with C++), git, Claude Code.
2. **Plugin, from source:** `cd <UEPROJ>\Plugins`, then
   `git clone https://github.com/tumourlove/monolith.git Monolith` (the folder name must be exactly `Monolith`).
   Pin it: `git -C Monolith checkout <latest release tag>` and record the tag and commit in
   THIRD_PARTY_VISUAL.md (MIT, beta). `ue/Plugins/Monolith/` is gitignored and never committed.
   Build: `scripts\build_ue.ps1` (or Generate VS project files, then Development Editor Win64).
   This needs no running Unreal; if a stale UnrealEditor holds the FlightSimBridge DLLs, reboot first.
3. **Firewall, before launching** (Administrator):
   `netsh advfirewall firewall add rule name="Block Monolith MCP 9316 inbound" dir=in action=block protocol=TCP localport=9316`.
   The server listens on every interface; loopback is not filtered, so Claude Code on this box still connects.
4. **`<UEPROJ>\.mcp.json`** (gitignored):
   `{"mcpServers":{"monolith":{"command":"Plugins/Monolith/Binaries/monolith_proxy.exe"}}}`.
   Check the exe exists after step 2; use its absolute path if Claude Code cannot find it.
5. **Render pipeline unchanged?** Render one scene with the commandlet (`visual_fix_round.ps1 -Scenes "4"`)
   with the plugin installed, and compare it against the last frame of that scene. Check:
   - the plugin does not start its server in UnrealEditor-Cmd, or does so harmlessly;
   - start-up time and peak RAM change by less than 10 %.

   If renders break, disable Monolith in the uproject for commandlet runs before going on.
6. **Launch the editor** (`ue\FlightSim.uproject`). Wait 30-60 s for the first index, then check that
   Output Log > `LogMonolith` says it is listening on 9316. **Never render while the editor is open:**
   7.2 GB is free, and the harness has killed rounds for low memory. Close the editor before each round.

## Part B: the owner starts the lead session ON THE MAC

```
cd ~/flightsim-old
claude --model claude-opus-5-5
/remote-control           (then /rename p3-hyperreal)
```
Then paste the prompt below. The Windows tester stays p3-windows. To use Monolith there, it needs a Claude Code
session started in `<UEPROJ>` (`cd C:\Users\kanth\flightsim\ue; claude`, `/mcp` shows monolith, `/remote-control`).
The Mac lead sends it render and inspection requests over the bridge.

## Part C: the prompt

```
You are the visual lead for FlightSim's hyper-realism push (12 hours, owner-authorised for this run only;
not a standing exception). You run ON THE MAC. Work only in git worktrees of origin/claude/vibrant-gauss-olema4 (in your scratchpad); do
NOT touch ~/flightsim-old's own working tree (it is on max-push with someone's uncommitted local changes). ALL BUILDING IS ON THE MAC: code, shaders, material scripts, bake scripts, tests. NEVER build or
run Unreal on the Mac. The Windows laptop (session p3-windows over the bridge) ONLY TESTS: it pulls, builds
the plugin, runs the materials prep and Blender bakes, renders rounds, runs verify, pushes frames to
vis-windows, and inspects the editor through the Monolith MCP and the owner's "Unreal Engine Skills" MCP
skill (installed there) when you ask: material compile errors, Niagara/actor state, viewport checks. Give
p3-windows exact commands and wait for its report; you can't call those MCPs yourself. Take
inspiration from X-Plane 12 / MSFS for sky, clouds, weather and lighting, using techniques and published
talks, never their assets. Then read
docs/visual/HYPERREAL_12H.md, docs/visual/MAXPICK_ROUNDS.md and the latest round frames on vis-windows.

GOAL: every one of the 15 test scenes (scripts/run_test_scenarios.py) should look photographic in the BEAUTY
pass. The owner names: clouds (rubbery, boxy, smeared), the tornado (no structure), the rain (not
convincing), wet ground (black and scratched), the sea, the sky/horizon bands, the contrails, the aircraft
lighting. Judge every frame by eye against real reference photos of the same subject and say what is still
fake.

TEAM: you (Opus) decide what to build and judge every frame. Use the Workflow tool for the engineering, with
agents on model "fable" (the owner asked for this): one builder per item in its own worktree, then 2
adversarial Fable reviewers (labels/measure safety; realism and iGPU fit). You make the final call. Batches
of <= 6 items. After each batch: push, then ask p3-windows for build + materials prep + ONE round of only the touched
scenes, pull its frames from vis-windows, look at every frame, keep or revert by name, record it in docs/visual/HYPERREAL_ROUNDS.md, push frames to
vis-windows.

ALREADY ON THE BRANCH, untested: b79c6433 tornado flipbook (needs the JangaFX Tornado Looping VDB fetched
plus scripts/bake_tornado_flipbook.py in Blender, then -tornado-look=vdb); f628f74c wet-ground gen 7;
12cb1846 baked windscreen gen 3 (default on); the impostor clouds (scripts/bake_cloud_impostors.py, JangaFX
Cloud Pack, -cloud-impostors=pilot) once p3-mac pushes them. flightsim-83 is building X-Plane-style
live clouds/sky on claude/xplane-sky; do not edit its files (FlightSimClouds*, FlightSimSky.cpp clouds
block, cloud_layers/distant_clouds/cirrus hlsl, FlightSimVisualScene atmosphere/fog, core/sky/plan.py,
world_beauty.py cloud parts, weather_visuals.py cloud keys, tests/test_sky*/test_cloud*/test_world_beauty*).
Send it any hook you need. Test its PR in your rounds, A/B against the impostors, and let the frames decide.

HARD RULES:
- Beauty only. Labels (boxes, keypoints, masks, depth) and every measure render stay byte-identical; run
  verify on every touched scene; never claim PASS without a real result.
- Physics does not change.
- Free assets only (no paid plugins, no cloud GPU), licence + sha256 pinned in THIRD_PARTY_VISUAL.md, CC0/MIT
  preferred, no share-alike in training data.
- iGPU: D3D11 SM5, no Lumen/Nanite/VSM/HW RT/path tracer. Never one long GPU submission (TDR, 887a0006);
  split work into accumulated captures. RAM is the limit: editor closed during renders, one render at a
  time, never kill Unreal mid-render (it has rebooted the laptop twice).
- Monolith / UE Skills (Windows side): inspection first. Any editor change must also be written on the Mac
  as a scripted, reproducible change (scripts/ue_create_materials.py etc.), so a fresh checkout rebuilds the
  same result. Commit before any editor mutation, never delete assets, nothing outside /Game/FlightSim.
- Git: work on claude/vibrant-gauss-olema4 (or claude/hyperreal-* branches merged after tests); no force push,
  no history rewrite, no deleting owner data; tag commits [skip ci]; trailers:
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>; do not run CI.
- Google tiles stay on unless FLIGHTSIM_GOOGLE_TILES=off. Every amount is UNCALIBRATED until a frame shows it.
- Every 2 hours, post a short progress note to p3-mac and the owner: what changed, before/after frames, what
  is still fake.
END: the full 15-scene sweep with verify, a before/after contact sheet per scene, and a list of what still
does not look real and why (hardware vs software).
```

## Part D: ready on the branch for the lead's first rounds (exact Windows commands)

**Impostor clouds (0deddc6d), the Cloud Pack is already downloaded (sha 3676ba4c…):**
1. `.venv\Scripts\python.exe scripts\fetch_cloud_vdbs.py --zip <path>\CloudPackVDB.zip`
2. `$env:BLENDER="C:\Users\kanth\flightsim_assets\blender-5.2.3-windows-x64\blender.exe"`, then
   `& $env:BLENDER -b -P scripts\bake_cloud_impostors.py -- --vdb-dir C:\Users\kanth\flightsim_assets\jangafx_clouds\CloudPack\CloudPackVDB --out assets\looks\clouds\impostors --clouds 4 --views 8 --px 128`
   This is CPU work, roughly 1 to a few hours. Run it while the editor is closed. It is not Unreal.
3. Commit and push `assets/looks/clouds/impostors`. Build the plugin, then the materials prep (expect M_FlightSimCloudImpostor and MI_..._cloud00-03).
4. Pilot: scenes 13, 3 and 11 with `$env:FLIGHTSIM_RENDER_SWITCHES="-cloud-impostors=pilot"`, plus the same scenes unset as the comparison.
   Risks: double clouds over flightsim-83's volumetric layer (ask it for a thinning hook), weak silver linings
   (six-way lighting), and untested Blender 5.2 and C++ APIs.

**Tornado flipbook (b79c6433, pin 8697095f), the zip is at C:\Users\kanth\Downloads\TornadoLoopingVDB.zip:**
1. `.venv\Scripts\python.exe scripts\fetch_tornado_vdb.py --zip C:\Users\kanth\Downloads\TornadoLoopingVDB.zip`
2. `& $env:BLENDER -b -P scripts\bake_tornado_flipbook.py -- --out assets\looks\tornado_vdb`
   (128 source frames; the bake picks its own spread). Commit the atlas, JSON, PIN and LICENSE.
3. Build, materials prep, then scene 10 with `-tornado-look=vdb` against `-tornado-look=mesh`.

**Wet ground (f628f74c, tiles generation 7):** materials prep, then scenes 15, 9 and 10, plus 1 as the dry control.
