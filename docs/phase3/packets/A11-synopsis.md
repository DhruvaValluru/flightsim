# A11 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T18:12:33Z

## A11 step 1/8 web: two cameras, three stills each (run 843e5dbe9dcd), POST /run

- log: `runs/p3/A-2/A11-web-post.log`
- exit: 0 (expected 0) -> PASS

```
status 200
{"run_id":"843e5dbe9dcd","digest":"3414edb508e6a6f3c638e5abb872f8ea4325d6aa726f4c45eb6c2df445dbebc0"}
```

## A11 step 8 CLI: capture --render --terrain <absolute> two cameras, three stills (runs/p3/A-2/A11-cli-2)

- log: `runs/p3/A-2/A11-cli-2.log`
- exit: 0 (expected 0) -> PASS

```
spec 525aeb52033a237c valid; running headlessly...
flying the card in the host first, so the labels describe the flight the pixels show ...
  engine pass logging to runs\p3\A-2\A11-cli-2\host_flight\host_flight_pass.log (unattended; stalls are stopped)
    wrote C:\Users\kanth\flightsim\runs\p3\A-2\A11-cli-2\host_flight\host_telemetry.json
  host flight: 200 samples, digest 710cbc16705eb46d -- poses re-solved over it
  instruments: ideal (the recorded channels are the measurement; no telemetry_measured.json written)
  card:     runs\p3\A-2\A11-cli-2\card.json (consume-poses; one commandlet pass per camera via -camera-index=N)
captured: 6 frames across 2 camera(s)
  manifest: runs\p3\A-2\A11-cli-2\capture_manifest.json
  previews: 6 geometry preview(s) under runs\p3\A-2\A11-cli-2\previews
rendering 2 camera pass(es) into runs\p3\A-2\A11-cli-2\frames in the visual scene ...
  engine pass logging to runs\p3\A-2\A11-cli-2\render_pass.log (unattended; stalls are stopped)
    scene flags for every pass: -Visual -shot=showcase -fps=30 -width=1280 -height=720 -sun-elev=50.0 -sun-azim=180.0 -exposure-bias=9.5 -fog-density=0.0012 -labels -deterministic -GeorefTerrain -terrain=C:/Users/kanth/flightsim/runs/terrain/grand_canyon -mesh=C:\Users\kanth\flightsim\assets\generated\A4\mesh_manifest.json -NoSound -NoLoadingScreen
    camera 1/2: chase -> C:\Users\kanth\flightsim\runs\p3\A-2\A11-cli-2\frames\chase
      wrote 15 frames
    camera 2/2: tower -> C:\Users\kanth\flightsim\runs\p3\A-2\A11-cli-2\frames\tower
      wrote 15 frames
    wrote 30 frames across 2 camera(s) under C:\Users\kanth\flightsim\runs\p3\A-2\A11-cli-2\frames
  frames:   6 rendered under runs\p3\A-2\A11-cli-2\frames
  labels:   engine bundle attached on 6 of 6 frames (12 object records; 0 without a bundle)
  overlays: 6 under runs\p3\A-2\A11-cli-2\overlays -- the recorded geometry drawn ON the rendered pixels; the circle (manifest) and the cross (engine) should coincide
  verify:   python -m flightsim.verify runs\p3\A-2\A11-cli-2
  (with pixels present, verification exercises the landmark reprojection and two-view checks that report NOT RUN without them)
```

## A11: every render.json frame record checked for mask, depth_f32 and one alone PNG per aircraft (web and CLI)

- log: `runs/p3/A-2/A11-labels-check.log`
- exit: 0 (expected 0) -> PASS

```
web chase frame 0: mask=frame_0000_mask.png (771705 px>0) depth_f32=frame_0000_depth.f32 (True) alone=[('frame_0000_alone_1.png', True)]
web chase frame 1: mask=frame_0001_mask.png (789106 px>0) depth_f32=frame_0001_depth.f32 (True) alone=[('frame_0001_alone_1.png', True)]
web chase frame 2: mask=frame_0002_mask.png (833091 px>0) depth_f32=frame_0002_depth.f32 (True) alone=[('frame_0002_alone_1.png', True)]
web chase: complete (3 frames)
web tower frame 0: mask=frame_0000_mask.png (53704 px>0) depth_f32=frame_0000_depth.f32 (True) alone=[('frame_0000_alone_1.png', True)]
web tower frame 1: mask=frame_0001_mask.png (58764 px>0) depth_f32=frame_0001_depth.f32 (True) alone=[('frame_0001_alone_1.png', True)]
web tower frame 2: mask=frame_0002_mask.png (137246 px>0) depth_f32=frame_0002_depth.f32 (True) alone=[('frame_0002_alone_1.png', True)]
web tower: complete (3 frames)
cli (render_ue_scenario.ps1) gate5 doublet frame 0: mask=None (-1 px>0) depth_f32=None (True) alone=[]
cli (render_ue_scenario.ps1) gate5 doublet frame 1: mask=None (-1 px>0) depth_f32=None (True) alone=[]
cli (render_ue_scenario.ps1) gate5 doublet frame 2: mask=None (-1 px>0) depth_f32=None (True) alone=[]
cli (render_ue_scenario.ps1) gate5 doublet frame 3: mask=None (-1 px>0) depth_f32=None (True) alone=[]
cli (render_ue_scenario.ps1) gate5 doublet: INCOMPLETE (110 frames)
cli chase frame 0: mask=frame_0000_mask.png (770943 px>0) depth_f32=frame_0000_depth.f32 (True) alone=[('aircraft:A4:0', 'frame_0000_alone_1.png', True)]
cli chase frame 1: mask=frame_0001_mask.png (788733 px>0) depth_f32=frame_0001_depth.f32 (True) alone=[('aircraft:A4:0', 'frame_0001_alone_1.png', True)]
cli chase frame 2: mask=frame_0002_mask.png (832572 px>0) depth_f32=frame_0002_depth.f32 (True) alone=[('aircraft:A4:0', 'frame_0002_alone_1.png', True)]
cli chase: complete (3 frames)
cli tower frame 0: mask=frame_0000_mask.png (53759 px>0) depth_f32=frame_0000_depth.f32 (True) alone=[('aircraft:A4:0', 'frame_0000_alone_1.png', True)]
cli tower frame 1: mask=frame_0001_mask.png (57500 px>0) depth_f32=frame_0001_depth.f32 (True) alone=[('aircraft:A4:0', 'frame_0001_alone_1.png', True)]
cli tower frame 2: mask=frame_0002_mask.png (135201 px>0) depth_f32=frame_0002_depth.f32 (True) alone=[('aircraft:A4:0', 'frame_0002_alone_1.png', True)]
cli tower: complete (3 frames)
```

note: run A-2 on UE 5.7.4: nothing was missing on this engine, so step 2 (engine fix) had nothing to fix; the only CLI defect met was the relative --terrain path handed to the engine (Mac scope, noted)

## verdict

PASS
