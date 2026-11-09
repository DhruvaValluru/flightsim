# Visual overhaul probe log

Each lane keeps its own `## <lane>` section. Everything below was written
on 2026-11-09 on a Mac that cannot compile or render UE 5.7.4 (Xcode above
the engine's cap, no Cesium): nothing here has been rendered or measured.
Every look constant is UNCALIBRATED: set by probe render on the render
machine.

## aircraft

**What exists (code only).** Look configs `assets/aircraft_config/look/<NAME>.json`
(all seven airframes), resolved by `scripts/aircraft_look.py` into
`assets/generated/<NAME>/look_manifest.json`; master materials built by
`scripts/ue_aircraft_master_materials.py` (called from the aircraft block of
`scripts/ue_create_materials.py`); per-model look instances
`/Game/Aircraft/<NAME>/Look/MI_<slot>` made at import
(`scripts/ue_aircraft_materials.py create_look_instances`, called by
`ue_import_aircraft.py` and `ue_fix_aircraft_materials.py`); the beauty-only
C++ `FlightSimAircraftFX.cpp/.h`; candidate model table
`scripts/fetch_aircraft_models.py`. Tests: `tests/test_aircraft_look.py`.

**Decisions.**
- Look config lives in its own folder, not in `<NAME>.json`: that file's
  sha256 is label provenance in every run manifest, and a look tweak must
  not move it.
- Everything is gated on `-Visual -quality=beauty` with a mesh airframe
  drawn and no `-HideAircraft`. `-quality=measure` constructs nothing, so
  Gate 6's path and its `render.json` are byte-identical (`aircraft_look` is
  absent there).
- The imported Interchange instances (what measure draws) are never edited;
  beauty swaps each slot to `Look/MI_<slot>`. A card livery other than
  `default` is kept, not repainted (recorded).
- Legacy shading only (Substrate off, gotcha 32). `M_AircraftPaint` is Clear
  Coat through `MakeMaterialAttributes` (the 5.7 Python hides
  `MP_CUSTOM_DATA0/1`: UMETA(Hidden) in SceneTypes.h, and M_AirframePaint's note records the miss on the owner's machine); bare metal, glass and
  rubber are Default Lit. Normals are world space (MikkTSpace is off on these
  meshes, gotcha 5).
- Paint metallic is 0.15, not 0.6-0.9: a painted panel is a dielectric under
  a clear coat. The 0.6-0.9 band is the `bare_metal` class (0.9; the P-51D
  defaults to it).
- **Glass is opaque.** The label captures draw no translucency and a
  translucent canopy writes no custom depth, so translucent glass would show
  sky where the mask says aircraft. Opaque dark glass keeps beauty, mask,
  class and depth on one silhouette. (In beauty the canopy is therefore IN
  the mask; if an imported glass slot was translucent before, measure masks
  had a hole there that beauty masks do not.)
- No master uses World Position Offset; custom depth/stencil is set per
  component by the commandlet after the swap; every class master is opaque.
  So the label passes see the beauty's geometry.
- Nanite stays OFF for airframes (`ue_import_aircraft.py` comment): the asset
  is shared with measure, the capture drew the fallback when it was on, VSM
  shadows non-Nanite meshes, and these meshes are too small to gain. The
  `FinishAllCompilation` guard (gotcha 4) is untouched.
- FX are separate actors attached to the aircraft and listed in
  `BeautyOnlyActors`, never components of the aircraft actor (the stencil loop
  labels every primitive of that actor). Lights move no geometry; bulbs and
  the afterburner plume are additive (hide nothing); trails are translucent
  media, which by the clouds/rain convention do not occlude in masks (a
  trail in front of the aircraft leaves the mask as aircraft; recorded in
  `render.json aircraft_look.contrail.label_convention`).
- Heat haze refracts (moves pixels): OFF unless `-heat-haze=on`, beauty
  only, recorded as `aircraft_look.heat_haze.pixel_moving: true` with
  `max_offset_screen_fraction` = Strength/100.
- All FX run on the FDM's time (strobe phase, trails, reheat glow, haze
  phase): replay-identical.
- Lamps sit on measured body-vertex extremes (wingtips at -y/+y, tail at
  -x) plus a stated `offset_m`; nozzles are the FDM thruster line (y, z) with
  x snapped to the aftmost body vertex within `snap_radius_m` and 4 m aft
  (without the window the B747 outboard snap took the wing trailing edge,
  6.1 m aft, measured here on the converted model).
- J-11 slot names were not measurable here (source not fetched on this
  machine); its glass/rubber come from the automatic rules (MTL `d` < 0.95,
  untextured Kd <= 0.06).

**Uncalibrated constants and the probe that should set each** (values in
`scripts/aircraft_look.py`, copied into every look manifest and into
`render.json aircraft_look.constants`):
- class scalars/vectors (`CLASS_SCALARS`, `CLASS_VECTORS`, per-aircraft
  overrides in the look configs): roughness, clear coat, panel pitch / width /
  depth, wear, grime, glass tint. Probe: V7 side-by-side of each type against
  a reference photo at matched sun (reader's judgment).
- `lights`: LightVisualGain, BulbRadiusCm, BulbEmissivePerCd,
  BulbEmissiveMax, StrobePeriodS, StrobeFlashS, LandingMaxAglM,
  LandingConeDeg, NavAttenuationM, LandingAttenuationM. Probe: dusk and noon
  beauty of the type at chase range. (Candela values are 14 CFR 25.1391 /
  25.1401 minimums from memory, not uncalibrated look numbers.)
- `contrail`: MaxTemperatureK 233.15, MinAltitudeM 7500, LifetimeS,
  FormationDelayS, StartWidthM, SpreadMPerS, Opacity, PreseedS. Probe: cruise
  beauty above 9 km, chase and side views.
- `vapour`: MinNz 4, LifetimeS, StartWidthM, SpreadMPerS, Opacity. Probe:
  a 5 g pull-up.
- `afterburner`: PlumeLengthRadii, AfterburnerCandela, GlowGain,
  AttenuationM; core/tip colours in `M_AircraftAfterburner`. Probe: full
  reheat take-off, rear quarter.
- `heat_haze`: LengthRadii, Strength. Probe: `-heat-haze=on` at idle, rear
  view.
- `GLASS_MAX_DISSOLVE` 0.95, `RUBBER_MAX_KD` 0.06, `SNAP_MAX_AFT_M` 4.0,
  and each look config's `snap_radius_m` / `radius_m` / `offset_m`.

**Engine symbols verified** against the UE 5.7.4 headers on the Mac
(`scripts/check_bridge_api.sh`, block "AIRCRAFT LANE"; all ok on 2026-11-09,
the only FAIL is the pre-existing CesiumRuntime module). Python enum
spellings (`RM_2D_OFFSET`, `TLM_VOLUMETRIC_NON_DIRECTIONAL`,
`MP_MATERIAL_ATTRIBUTES`, `CMOT_FLOAT2/4`) are tried and a miss raises with
the engine's own names. No Cesium API is used by this lane.

**Hooks in other lanes' files.**
- `ue/.../FlightSimRenderCommandlet.cpp`: one `#include`; the build block
  after `ApplyIceOverlay` (gated `bVisual && bBeauty && MeshAirframe.bLoaded
  && !bHideAircraft`, appends to `BeautyOnlyActors` before the label captures
  are configured); a 4-line per-step `AircraftFX.Advance(...)` before the
  weather view; the `render.json aircraft_look` record (absent unless built).
  All marked `AIRCRAFT LANE`.
- `scripts/ue_create_materials.py`: the `AIRCRAFT LANE` block (one creator
  that imports `ue_aircraft_master_materials.build_all`) and its call.
- `scripts/check_bridge_api.sh`: the `AIRCRAFT LANE` block.
- `core/messages/catalog.yaml`: one entry, `aircraft_look.manifest` (a look manifest that exists but cannot be read).

**Model candidates** (`python scripts/fetch_aircraft_models.py --list`):
Su-27 by andertan on Sketchfab, CC-BY-4.0, 28.8k triangles (J-11 parent;
sha256 not pinnable without an account download); FlightGear FGAddon
Sukhoi-Su-33 by helijah, GPLv2+, SVN r18942 (J-15 parent; tree sha256 not
pinned, nothing downloaded; needs a J-15 FDM to be a J-15 subject). No
redistributable J-35/FC-31 model was found. Nothing is usable until pinned.

**Render-machine commands, in order** (Windows is the maintained render
platform; the `.sh` twins take the same arguments):
1. `scripts/check_bridge_api.sh` (the AIRCRAFT LANE block must be all ok).
2. `scripts\build_ue.ps1` (first compile of `FlightSimAircraftFX.cpp`).
3. `UnrealEditor-Cmd ue/FlightSim.uproject -run=pythonscript -script=scripts/ue_create_materials.py`
   (expect `MATERIAL-CREATED: /Game/FlightSim/Aircraft/M_Aircraft*` and no
   `MATERIAL-FAILED`).
4. `UnrealEditor-Cmd ue/FlightSim.uproject -run=pythonscript -script="scripts/ue_fix_aircraft_materials.py J11 B747 A320 c172p DHC6 p51d A4"`
   (writes `Look/MI_*` and `assets/generated/<NAME>/look_manifest.json`;
   read `runs/fix_aircraft_materials.txt` for `LOOK-PROBLEM` lines).
5. `python experiments/gate6_visual.py` -- must pass unchanged (measure
   untouched), and its `render.json` must carry no `aircraft_look` key.
6. Beauty probes: web app with `FLIGHTSIM_RENDER_QUALITY=beauty`, prompts
   "fly the J-11 at 3000 m" (materials, nav/strobe lamps), "fly the J-11 at
   10000 m" (contrails), and the B747 at cruise. Read
   `runs/<id>/.../render.json` `aircraft_look` (slots_applied, slots_absent,
   contrail_frames, peak_glow, constants) and look at the frames.
7. Heat haze, once: re-render a beauty run's card with
   `scripts\render_ue_scenario.ps1 <runs\<id>\card.json> <out> -Visual -quality=beauty -mesh=<abs path to assets\generated\J11\mesh_manifest.json> -heat-haze=on`
   and compare mask edges behind the nozzles against the beauty frame
   (bound: `aircraft_look.heat_haze.max_offset_screen_fraction`).
