# A4: physics <-> model sync

How the A-4E visual model (`assets/aircraft_models/A4`) and the A4 flight
model are tied together, how each link is checked, and what is still not
linked. Everything below is regenerated or asserted by tests.

## Pipeline
* `python -m assets_pipeline.a4_sync` builds the JSBSim A4 from the model's own
  `aircraft.cfg` (feet from the model datum, +x forward) into `assets/fdm_root/`
  and the Unreal plugin's JSBSim tree. `--check` fails on drift.
* `python -m assets_pipeline.a4_mesh_check` measures the decoded `.mdl` against
  the flight model.
* `assets_pipeline/mdl_scene.py` decodes the exterior `.mdl`;
  `a4_mdl_convert.py` turns it into the pipeline's mesh manifest for Unreal
  (`assets/aircraft_config/A4.json`, `"converter": "mdl"`).
* `a4_performance.py` and `a4_calibrate.py` measure and fit climb performance.

## Taken from the cfg
Span, wing area, empty weight, moments of inertia, CG, gear, scrape points,
eyepoint, engine position, three drop-tank and two internal fuel tanks, the
pilot and five pylon stations, static thrust, TSFC, flap travel (0-50 deg in
3 s) and the tail hook position.

## Taken from the mesh
Horizontal tail area (43.5 ft2) and arm (15.2 ft) replace the stock guess
(52 ft2, 16.7 ft). Elevator power scales with tail area x arm (x0.76) and pitch
damping with area x arm^2 (x0.69); static stability is left alone.

## Checked against the decoded mesh (feet)
| quantity | mesh | flight model | diff |
|---|---|---|---|
| half span | 13.45 | 13.53 | -0.08 |
| top (fin) | 9.75 | 9.70 | +0.05 |
| tail end | -20.54 | -20.55 | +0.01 |
| main gear bottom | -7.29 | -7.20 | -0.09 |
| nose | 21.74 | 18.90 | +2.84 (fixed refuelling probe) |
| wing area | 264 ft2 | 259 ft2 | +2% |

The airplane rests on its generated gear at 5.2 deg pitch, CG 7.5 ft up; the
cfg states 5.0 deg and 7.0 ft.

## Performance (loaded 18,300 lb, gear up)
| | model | cfg text |
|---|---|---|
| max speed, clean, 1000 ft | trims at 585 kt CAS, not at 620 | 585 kn |
| best rate of climb, 500 ft | 8,492 ft/min | 8,440 ft/min |
| service ceiling | 42,363 ft | 42,250 ft |

The stock model climbed at ~12,600 ft/min and reached ~50,000 ft. Two
constants were fitted (`a4_calibrate.py`): a stores drag of 0.001756 ft2 per lb
on the pylons (the cfg's "loaded" weight includes stores; the clean airframe is
untouched and keeps the 585 kn) and an Oswald efficiency of 0.918 for induced
drag. That efficiency is at the high end for this wing, so part of the ceiling
fit is absorbed there; treat the two figures as fitted, not predicted. Rate of
climb is by excess power (steady-climb approximation).

## Behaviour that is modelled
* Flaps 0-50 deg. Lift and drag are linear in flap angle, so past the stock
  30 deg they are an extrapolation of that line, not data.
* Tail hook: stow/deploy in 1.5 s; with the hook down, the wire engaged
  (`systems/hook/wire-engaged`, set by whatever models the wire) and the wheels
  on the deck, a 2.2 g arrestment force acts along the axis. The cable is not
  modelled.
* Stores: `inertia/pointmass-weight-lbs[1..5]` are STA1-5; the drag proxy above
  follows their total weight. Drop tanks are tanks 2-4 (empty until filled).
* Airborne starts are gear-up (Python host, and the Unreal host in C++, for
  repo-owned airframes only; stock aircraft keep JSBSim's gear-down default).

## Mesh for Unreal
Decoded by measurement (the PV44 layout is not published): scene tree,
transforms, visibility rules, vertex/index buffers. The default configuration
is a parked, clean A-4E, gear stowed, VA-12 livery: 266,886 triangles, one
rigid body, 2 x 2048 px textures. Checked by re-parsing the written OBJ and
rasterising it from three views, and by the bounds test against the FDM.

## Not linked, or unverified
* **Aerodynamic coefficients** are the stock Aeromatic set corrected as above;
  the cfg has none. Measured, not validated: static margin ~5% of mean chord;
  short-period 1.1-1.7 rad/s at damping ~0.33 (350 kt, 10,000 ft). The mesh
  wing quarter-chord sits 0.5 ft ahead of the CG and the model's neutral point
  0.5 ft behind it. That 1.0 ft (about 9% of the mesh mean chord) is the same
  order as the neutral-point shift a tail of the mesh's size gives (~11%), so
  the pieces are mutually plausible and the aerodynamic reference point is
  left at the CG (moving it to the wing quarter-chord would remove nearly all
  the static margin). Real A-4E data would replace all of this.
* **Not articulated.** Control surfaces, gear and speed brakes do not move in a
  render: the exterior is one rigid body. Their animation drivers are in the
  file (`ANIB`) but are not decoded.
* **Not built in Unreal.** No engine is available here. The C++ gear change and
  the OBJ import are unbuilt and unrun; the render commandlet's handling of an
  empty `surfaces` list was checked by reading it.
* Other liveries, the hump/no-hump variants, open canopy and store loads exist
  in the model but are not exposed.
* The cfg's `cable_force_adjust` and MSFS `flight_tuning` scalars are not
  applied.
