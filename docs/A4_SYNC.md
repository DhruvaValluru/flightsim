# A4: physics <-> model sync

What ties the A-4E visual model (`assets/aircraft_models/A4`) to the A4
flight model, how each link is checked, and what is still not linked.

## Pipeline
`python -m assets_pipeline.a4_sync` builds the JSBSim A4 from the model's
own `aircraft.cfg` (feet from the model datum, +x fwd) into `assets/fdm_root/`
and the Unreal plugin's JSBSim tree. `--check` fails on drift; a test runs it.
`python -m assets_pipeline.a4_mesh_check` decodes the exterior `.mdl` and
compares its geometry with the flight model.

## Taken from the cfg
Span, wing area, empty weight, moments of inertia, CG, gear, scrape points,
eyepoint, engine position, internal fuel tanks, static thrust and TSFC.

## Checked against the decoded mesh (metres in the file, feet here)
| quantity | mesh | flight model | diff |
|---|---|---|---|
| half span | 13.45 | 13.53 | -0.08 |
| top (tail) | 9.75 | 9.70 | +0.05 |
| tail end | -20.54 | -20.55 | +0.01 |
| main gear bottom | -7.29 | -7.20 | -0.09 |
| nose | 21.74 | 18.90 | +2.84 (fixed refuelling probe) |
| wing area | 264 ft2 | 259 ft2 | +2% |
| wing quarter-MAC | +0.5 ft fwd of CG | AERORP at CG | 0.5 ft |

The airplane also rests on its generated gear at 5.2 deg pitch and CG 7.5 ft
up; the cfg states 5.0 deg and 7.0 ft.

## Performance (clean, 15.9k lb, gear up)
Level flight trims at 585 kt CAS at 1000 ft (cfg: 585 kn maximum) and not at
620. Climb and ceiling do not match the cfg's published 8,440 ft/min and
42,250 ft: the model climbs faster (about 14k ft/min at 1000 ft) and reaches
above 44k ft. Those figures give no weight or configuration, so nothing is
tuned to them.

## Not linked
* Aerodynamic coefficients are the stock Aeromatic set; the cfg has none.
  MAC (12.0 ft measured vs 9.8 ft mean chord used) is unchanged because the
  Aeromatic pitching-moment data assumes its own reference chord.
* Flaps stay 0-30 deg (cfg detents go to 50 deg; no lift/drag data past 30).
* Tail hook, wing fold and stores are not modelled in the FDM.
* Animated parts (gear, surfaces) live in node-local space in the `.mdl` and
  are not compared. Gear-up on airborne starts is done in the Python host
  only; the Unreal C++ host does not do it.
* No `.mdl` -> Unreal mesh converter exists, so nothing renders.
