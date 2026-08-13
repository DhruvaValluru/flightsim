# Phase 9 brief — the world beyond mountains

User ask (2026-08-11): "do more than mountains — cities, grasslands,
storms like tornados — everything — and make sure they all are physics
accurate and effect the airplane accordingly." All four features below
were explicitly selected. The standing rule is unchanged: nothing ships
unless the physics has a citable anchor, reaches the FDM measurably, and
carries its limits in VALIDITY. Visual-only things are labeled
visual-only; unmodellable things are refused by name.

## 9.1 Surface types (grassland / desert / ocean / forest / city)

Ground cover changes the air in exactly two modelled ways, both already
in the repository:

* **Roughness** -- LogProfileWind (Stull 1988 Table 9-6 / Davenport-
  Wieringa classes). Extend ROUGHNESS_M with "smooth" 0.005 m (desert)
  and "city" 2.0 m (city centres), same citation.
* **Thermal forcing** -- AllenThermals (NASA/TM-2006-214019). Per-class
  (w*, zi) anchored on the TM's own Table 2 Desert Rock climatology:
  desert = July mean (2.69, 1975) -- the TM's site IS desert;
  grassland = April mean (1.97, 1213) AS A STATED PROXY; forest =
  October mean (1.79, 893) proxy; city = April proxy with "urban heat
  island NOT separately modelled" in the basis string; ocean = no
  thermals (honest zero), roughness "water" 0.0002 m.

Architecture decisions (settled):

* New spec field `environment.surface`, default "unspecified"
  (`Quantity.default`), regex + LLM compiler vocabulary
  (grassland|prairie|plains, desert|dunes, ocean|sea, forest|woods,
  city|urban|downtown). **SPEC_VERSION 1 -> 2** -- from_dict refuses old
  dicts by design; recovery reads provenance.json, not scenario.yaml,
  so completed runs still recover. validate() refuses unknown words
  ("surface.vocabulary").
* New module core/environment/surface.py: SURFACE_CLASSES dataclass
  table (word -> roughness key, z0, (w*, zi) or None, basis string).
* **Wind composition (the subtle one):** when a surface class is
  present and wind > 0, the log profile CARRIES the whole horizontal
  wind: LogProfileWind(reference_speed = spec wind, reference_height =
  SURFACE_LAYER_TOP_M = 300, terrain = class key), attached INSTEAD of
  SteadyWind in environment_for. At/above 300 m AGL the profile is held
  at exactly the spec wind, so cruise flight is unchanged; below 300 m
  the wind honestly decays toward z0. UE side: card log_profile block
  gains `carries_base: true`; Step() then REPLACES the base horizontal
  wind with the profile value instead of adding (default false keeps
  the Phase 7 experiment cards byte-identical). Trim stays TrimInWind
  with the spec wind -- correct at cruise, stated approximation below
  300 m.
* Webapp: surface runs attach log_profile (carries_base) + thermals
  blocks; thermals need seed (derive_seed extends: surface thermal runs
  are stochastic). Conditions strip states the class, z0, w*/zi and
  the proxy basis. Effect report triggers for surface coupling too
  (baseline severs log_profile + thermals exactly like orographic).
* Visuals: v1 is physics + honest labels ("ground-cover visuals not
  modelled; a flat scene renders the labeled slab"). City visuals come
  with 9.4. Do NOT invent palettes without probe-render calibration
  (gotcha 6).
* Interplay: surface + mountains may coexist (forested mountains);
  terrain scenes keep their raster, surface adds roughness/thermals.

## 9.2 Storm-cell vocabulary word

"thunderstorm"/"storm" in a prompt composes EXISTING pieces on the
card: microburst (downburst block, position-coupled), gust-front wind
schedule (1-cosine ramp), severe turbulence word, dark-sky visuals
(existing fog/exposure parameters -- recorded per scene, gotcha 7).
Documented mapping table entry (like "strong crosswind" -> 25 kt);
conditions strip lists every component. Rain/hail/lightning are NOT
part of it until they can be visual-labeled; no wet-runway or wet-wing
aero exists (refused, stated).

## 9.3 Tornado

core/environment/tornado.py: Rankine combined vortex --
v_theta(r) = v_max * r/r_core inside, v_max * r_core/r outside,
plus a core updraft column with height decay; position-coupled per
step following the EXACT downburst pattern (analytic field, card block
carries every parameter, C++ port cross-checked on a grid,
port-difference threshold same as downburst). Cite Rankine vortex /
Davies-Jones tornado literature for the shape; v_max and r_core are
documented middle choices (EF-scale wind bands give v_max). STATED
LIMITS: JSBSim takes one wind vector at the CG -- no span-differential
airloads from the vortex gradient (the wingtip-in-the-core case is
point-sampled); no debris, no pressure-drop cabin effects, no
condensation funnel physics (funnel is visual-only if drawn at all).
Null test: vortex far away = still air; near-core pass measurably
throws the aircraft (telemetry-verified). Effect report covers it.

## 9.4 City with building collision

Depends on 9.1 (city surface class). Procedural city blocks (extruded
boxes, deterministic from seed) added to the PHYSICS collision mesh
exactly like BuildTerrainCollision builds the raster -- so JSBSim's
ground queries and the airframe-contact stations feel buildings; a
wingtip into a tower ends the run as a named impact. Urban z0 + heat
island from 9.1. Visual pass needs probe-render calibration for
materials (gotcha 6); collision correctness does not wait for pretty
visuals. Refusal: no building-resolved CFD (wakes are NOT modelled;
the class's z0 is the only aerodynamic statement about buildings).

## Order

9.1 -> 9.2 -> 9.3 -> 9.4. Each lands with tests + mutation guards +
VALIDITY paragraphs before the next starts. NEXT.md updated per
feature.
