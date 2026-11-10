# Visual round 2 on 6816852c (Windows, Intel integrated, D3D11 SM5, beauty)

## Counts
- 14 scenes: 12 rendered, 2 refused (#11 envelope.trim_feasible, #14 prompt.unsupported), 0 failed.
- summary.json: new_look_ran true on all 12.
- head2 shots a, b, c, d: all four rendered. Compare: runs/visual/compare_head_vs_head2.png.

## Build and import
- build_ue.ps1: Succeeded. ue_create_materials.py: every asset MATERIAL-EXISTS (the script did not change since d4e9c7dd).
- import_aircraft.py J11 c172p, editor log:
  - "/Game/Aircraft/J11/body: existing mesh deleted before its import (a first import)" (also r27r_left, r27r_right, body_beauty)
  - "BIND /Game/Aircraft/J11: 0 slot(s) rebound, 0 material(s) made"
  - "SLOTS /Game/Aircraft/J11: 52 bound, 0 unbound"
  - IMPORT-OK
- Shot a: no aircraft.material_slots refusal.

## Shot b
- Defaults: rendered. Log: "constrained gpu: yes (integrated yes, SM6 no); sky-capture-restore auto (on),
  gpu-drain auto (on), constrained-supersample cap (stated 2, rendered 1, budget 2073600 px)", 20 gpu drain lines.
- FLIGHTSIM_RENDER_SWITCHES=-constrained-supersample=keep (stated 2, rendered 2): FAILED in the first warm-up capture with
  "LogD3D11RHI: Error: Result failed with error DXGI_ERROR_DEVICE_REMOVED DXGI_ERROR_DEVICE_HUNG" /
  "Unreal Engine is exiting due to D3D device being lost. (Error: 0x887A0006 - 'HUNG')".
  The editor exited by itself within about a minute, no stuck process. So resolution is the trigger.
  Log: runs/visual/round2_logs/b_keep_render.log.
- Event Viewer System log: no Event ID 4101, neither around the round-1 hang nor after this device loss.

## By eye, against the checklist (see brightness_vs_round_1.txt for means)
- #02: brighter than #01 (luma 105 vs 94; round 1 was 75). NOT neutral: strong blue/violet cast (mean rgb 96/102/157).
- #06: SFO ground and coast faintly visible under a dark deck with a few lit clouds. Dark overall (luma 60, was 114).
- #07: FAIL. Flat grey frame with a few rain streaks; no aircraft silhouette visible.
- #08: Fuji's slope is visible and not blown out (luma 181, round 1 was 254 pure white). Sky is still flat white, only the slope shows, no summit.
- #09: dark deck overhead, rain and a rain shaft ahead. The deck reads as a hard-edged flat slab with vertical walls
  (box-shaped, visible corners), not a cloud base. The 747 is small and grey; no livery readable at this size.
- #12: canyon visible through the windscreen, cowl at the bottom. A large propeller blade crosses the middle of the frame.
  Much brighter than round 1 (luma 81 vs 22).
- Shot a: J-11 renders with materials (light grey airframe, dark nozzles). PLAAF markings are not readable at chase distance.
- Shot d: the canopy bow covers the top-left half of the frame.
- #01, #04, #13 did not get darker: #01 94 -> 94, #04 107 -> 122, #13 63 -> 62.
