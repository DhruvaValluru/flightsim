# Phase 3 aircraft sources (letter D: D1 search, D2 build)

One row per candidate airframe of the Phase 3 "new aircraft" search
(2026-10-27 plan text; D1's decision packet of 2026-11-03). Every cell is a
fact with a place it was read, or `none found`. Owner decision 3
(docs/phase3/decisions.md) chose the J-11A; D2 built it.

| candidate | mesh source | licence | pinned commit | FDM source | payload / gear separable | keypoint provenance |
|---|---|---|---|---|---|---|
| J-11A (Shenyang; FlightGear SU-27SK package by Yanes Bechir / FGUK, Sidi Liang) | `github.com/yanes19/SU-27SK`, `Models/Su-27.ac` (944 KB, shared with the Su-27SK variant; 43 objects: hull, canopy, pylons, UC_* gear, doors, surfaces), fetched at import time into the git-ignored `assets/aircraft_src/J11` by `assets_pipeline.importer.fetch_source` | GPL-2.0 (repository `LICENSE`, sha256 `db296f2f…c2fc73`, saved verbatim at `docs/phase3/packets/D1-SU-27SK-LICENSE.txt`; vendored beside the FDM at `assets/fdm_root/aircraft/J11/LICENSE`) | `925cb5317f3c66fa323a9e186e24d574e0b0881d` (master, 2020-11-24), pinned in `assets/aircraft_config/J11.json` `license.commit` | the package's root `J-11A.xml` (`<fdm_config name="Su-27SK" version="2.0" release="ALPHA">`, Aeromatic 0.95 derived) vendored as `assets/fdm_root/aircraft/J11/J11.xml` with `Engines/{Saturn-AL-31,GTDE-117_T,direct}.xml` and `Systems/{fuel,SDU-10}.xml`; five recorded edits in its provenance header (header, licence element, pylon2/3 weights, SDU-10 dropped, fuel.xml pump switches); loads and trims in JSBSim 1.2.4 | payload: yes, stores are separate `.ac` files (`Models/Stores/Missiles/R-27R/R-27R.ac`, R-27ER, R-73, …) the package attaches at the `-set.xml` station offsets, which equal the FDM's `pylonN-load` pointmass locations; D2 hangs two R-27R on `pylon2-load` / `pylon3-load` (x 14.0, y ±4.836, z −0.24 m) as `SM_J11_r27r_left` / `SM_J11_r27r_right` (manifest v4 `components[]`). gear: the `UC_*` objects are separate in `Su-27.ac` (`gear_geometry.objects`), attached as `mesh: null` landing_gear components | nose and tail: measured from `Models/Su-27.ac` at the pinned commit (centreline vertices at model-frame x 0.006 m and 22.083 m; the .ac origin taken as the FDM's structural origin, argued in `J11.json`); wingtips: the FDM `<wingspan>` half-span (fdm-approximation; the FDM's `LEFT_WING`/`RIGHT_WING` contacts are wing-root points at y ±0.61 m); nose_gear / left_main_gear / right_main_gear: the FDM's `NOSE` / `LEFT_MAIN` / `RIGHT_MAIN` contacts (the `NOSE` contact sits 5 m ahead of the mesh's nose gear, an FDM fact the label keeps) |
| J-15 (Shenyang, carrier variant) | none found (2026-10-27 search: no public mesh under an open licence) | none found | none found | none found | none found | none found |
| J-35 (Shenyang) | none found (2026-10-27 search: no public mesh under an open licence) | none found | none found | none found | none found | none found |
| standalone J-11 (not the SU-27SK package's variant) | none found (2026-10-27 search: every J-11 model located is a Su-27 re-skin without its own FDM) | none found | none found | none found | none found | none found |

Notes.

- The J-11A row's masses: `J11.xml` `<emptywt>` 36118 lb, pointmass `Payload`
  8563 lb at the CG, pilot 80 kg, the two R-27R 230.21 lb each (the package's
  own `J-11A-set.xml` store figure; the published R-27R launch mass, 253 kg,
  is from memory `[unverified here]`). Gross on the default run 55,680 lb.
- The default run (`fly the J-11 at 3000 m for 10 seconds`) compiles to
  `J11` at `CRUISE_DEFAULT_KT["J11"]` = 350 kt, validates with no envelope
  refusal and trims at alpha 1.46 deg, throttle 0.45 (measured 2026-11-04,
  JSBSim 1.2.4).
- The pinned mesh measures 22.08 m nose to tail against the cited 21.94 m
  (0.7 % over, inside the converter's 5 % extent tolerance).

2026-11-03 owner decision 3: J-11A go, D3 cut.
