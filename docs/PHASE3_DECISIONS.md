# Phase 3 — owner decisions

The six decisions `tasks/phase3_todo.md` waits on, with the facts each one
was made on. One line per decision is mirrored in `tasks/phase3_checklist.md`.

| # | Decision | Date, who |
|---|---|---|
| 1 | Engine: Unreal Engine 5.7, patch 5.7.4, on all three machines (docs/TOOLCHAIN.md) | 2026-10-27, Dhruva Valluru |
| 2 | A-4 default loadout: centreline drop tank on STA3 + a matched pair on STA2/STA4 | 2026-11-03, Shashank |
| 3 | Chinese airframe: the J-11A from the Su-27SK package; cut if it cannot trim | 2026-11-03, Shashank |
| 4 | Storm weather stays on in the demo default | 2026-11-03, Shashank |
| 5 | Typing the Google tiles key once, in Settings, is acceptable | 2026-11-03, Shashank |
| 6 | Control surfaces stay out of Phase 3 | 2026-11-03, Shashank |

## 2 · A-4 loadout (C1)

* The FDM (`assets/fdm_root/aircraft/A4/A4.xml`) has five store stations,
  STA1–STA5, all 0 lb and `loadable: false` in `assets/aircraft_config/A4.json`
  because their weight drives the stores-drag term; three drop-tank fuel
  tanks (2–4) exist.
* The 2026-10-27 decode measured stations 1–3: STA3 (centreline) load 1 adds
  +14,612 triangles; STA1/STA2 add 1,800–14,600. STA4/STA5 were not measured
  and are presumed mirrors of STA2/STA1.
* Symmetric: the run must trim with the stores' real weight (C1), and a
  one-sided load adds a roll trim. Wing stores also exercise the
  "hidden behind the fuselage" label case (C5 case 3).
* **Fallback:** if C2 shows STA4 does not decode like STA2, the default is
  STA3 alone. STA3 is brought up end to end first either way.

## 3 · Chinese airframe (D1)

* No J-15, J-35 or standalone J-11 in FGAddon (search of 2026-10-27).
* `github.com/yanes19/Su-27SK` (v0.3, January 2017), checked 2026-11-03:
  `LICENSE` and `COPYING` are **GPL-2.0**, the licence family of the
  FlightGear airframes already shipped (`NOTICE.md`). It carries
  `J-11A-set.xml` and a JSBSim FDM `J-11A.xml` (Aeromatic 0.95 based, release
  "ALPHA"; it differs from the Su-27SK FDM by one electrical system line), a
  FlightGear `.ac` airframe (`Models/Su-27.ac`) and separate store models
  (`Models/Stores/Missiles`).
* Risk: maturity ("early development"). D2 starts with a headless trim at the
  default run's altitude and speed; if it cannot trim, D2–D3 are cut and the
  report says so, as the brief allows. Pin the commit in
  `docs/PHASE3_AIRCRAFT_SOURCES.md` at D1.

## 4 · Storm weather in the demo (E4)

* CLAUDE.md (owner's rule, 2026-10-09) makes it the web-app default.
* It is the least-proven render path: first Windows storm render crashed in
  the cloud shadow pass, later ones rendered black until the 8–9 October
  fixes; measured on one machine only (docs/WEATHER.md).
* Labels do not depend on the look, so the risk is to the frames, not the
  label checks. Kept on; if a Gate A run fails because of it, the evidence
  goes to Dhruva before anything changes.

## 5 · Google tiles key (D5, E2–E3)

* Tiles are the ground of every terrain render (CLAUDE.md). The key is read
  from `GOOGLE_MAPS_API_KEY` today; E2/E3 move it to the settings file and
  panel, where it survives a reload.
* A one-time credential is setup, not a per-run intervention. Committing a
  billed key would expose it. The guide (F3) says "enter your key once in
  Settings".

## 6 · Control surfaces

The brief asks for payload (required) and gear (optional). The A-4 mesh is one
rigid body; ailerons, elevator, rudder and flaps would need an articulated
export first. The component mechanism in C supports them later.
