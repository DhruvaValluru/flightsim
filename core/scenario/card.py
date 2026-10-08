"""The run card: a spec projected into the form the UE hosts read.

Promoted out of ``experiments/gate5_ue_parity.py`` in Phase 8 — it long ago
outgrew "experiment helper": every experiment, the showcase matrix, and now the
web app's run manager write cards through this one function. Pure relocation;
the semantics and the docstrings travelled with the code, and the mutation
guards that target these lines were re-pointed here.

The card is the contract between hosts. One scenario description drives the
headless runner, the render commandlet, the telemetry commandlet, and (Phase 8)
the interactive window; anything a host cannot honour exactly it refuses by
name rather than approximating.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional, Sequence

from core.scenario.spec import ScenarioSpec
from core.scene.weather_look import weather_look_card_block

#: Sampling period asked of the UE recorder. Must match the period the headless
#: runner gives its own Recorder; gate5's main() checks that it does rather
#: than trusting this constant, because the two live in different files.
SAMPLE_INTERVAL_S = 0.1


#: (aircraft, altitude rounded to 100 m) -> verified engine-start mixture.
_MIXTURE_CACHE: Dict[tuple, float] = {}


def discovered_engine_mixture(spec: ScenarioSpec) -> float:
    """The engine-start mixture the UE host must use, verified in ITS sequence.

    A piston force-started full rich above ~2 km density altitude dies
    (VENDORED.json local patch 4; measured on c172p: at 3600 m it dies in
    seconds, at 2600 m it decays through 531 rpm and the trim solves a
    glider). The first version of this discovery swept a CRANK -- and full
    rich CATCHES on the starter at 2600 m while still failing to sustain,
    so four Yosemite cells rendered as gliders before the gap was measured.
    The criterion is now the UE host's own sequence, exactly: RunIC,
    InitRunning(-1), the candidate mixture written to the FCS, a tFull trim,
    and the engine still turning after five settled seconds. The first
    mixture that passes is the card's. Turbines return 1.0 untested -- the
    sweep exists only where magnetos do.
    """
    import jsbsim

    from core.fdm import units as u

    aircraft = str(spec.aircraft.value)
    altitude_m = float(spec.altitude.value)
    key = (aircraft, round(altitude_m / 100.0))
    if key in _MIXTURE_CACHE:
        return _MIXTURE_CACHE[key]

    def attempt(mixture: float):
        fdm = jsbsim.FGFDMExec(jsbsim.get_default_root_dir())
        # Quiet, as core.fdm's own instance is: at the library's default
        # level load_model prints the whole aircraft description (16 KB
        # for the A320, measured in every campaign capture.log) -- the
        # bytes that filled a 4 KB Windows pipe (flightsim/capture.py,
        # quiet_library_banners).
        fdm.set_debug_level(0)
        fdm.load_model(aircraft)
        fdm.set_dt(1.0 / float(spec.rate.value))
        # _IC_PRIORITY's safe order: position, attitude (beta before psi),
        # then speed last (docs/JSBSIM_CORRECTIONS.md §2).
        for name, value in (
                ("ic/lat-geod-deg", float(spec.latitude.value)),
                ("ic/long-gc-deg", float(spec.longitude.value)),
                ("ic/terrain-elevation-ft",
                 u.m_to_ft(float(spec.terrain_elevation.value))),
                ("ic/h-sl-ft", u.m_to_ft(altitude_m)),
                ("ic/beta-deg", 0.0),
                ("ic/psi-true-deg", float(spec.heading.value)),
                ("ic/phi-deg", 0.0), ("ic/gamma-deg", 0.0),
                ("ic/vc-kts", float(spec.airspeed.value))):
            fdm.set_property_value(name, value)
        fdm.run_ic()
        # The catalog decides piston vs turbine; reading a made-up property
        # would silently create it (docs/JSBSIM_CORRECTIONS.md §3).
        if not any("propulsion/magneto_cmd" in entry
                   for entry in fdm.get_property_catalog()):
            return "turbine"
        fdm.get_propulsion().init_running(-1)
        fdm.set_property_value("fcs/mixture-cmd-norm", mixture)
        try:
            fdm.do_trim(1)
        except jsbsim.TrimFailureError:
            return None
        for _ in range(int(5.0 * float(spec.rate.value))):
            fdm.run()
        if fdm.get_property_value("propulsion/engine/engine-rpm") < 500.0:
            return None
        return mixture

    probe = attempt(1.0)
    if probe == "turbine":
        _MIXTURE_CACHE[key] = 1.0
        return 1.0
    mixture = probe
    if mixture is None:
        for candidate in (0.85, 0.75, 0.65, 0.55, 0.45):
            mixture = attempt(candidate)
            if mixture is not None:
                break
    if mixture is None:
        raise RuntimeError(
            f"{aircraft} at {altitude_m:.0f} m: no mixture sustains the "
            f"force-started engine through trim. Refusing to write a card "
            f"that would fly a glider under a powered label.")
    _MIXTURE_CACHE[key] = float(mixture)
    return float(mixture)


def atmosphere_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    """The ``atmosphere_properties`` block for a spec, or None for the
    standard day (no block: the host writes nothing). Keys in the fixed
    order ``core.environment.atmosphere.CARD_KEYS``."""
    from core.environment.atmosphere import CARD_KEYS, NonStandardAtmosphere

    provider = NonStandardAtmosphere.from_spec(spec)
    if provider is None:
        return None
    block = provider.card_block()
    if tuple(block) != CARD_KEYS:
        raise RuntimeError(f"atmosphere card keys {list(block)} are not the "
                           f"fixed order {list(CARD_KEYS)}")
    return block


def loading_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    """The ``loading_properties`` block for a spec (P4), or None for the
    default block (no block: the host writes nothing and flies the XML's
    own loading). The EXACT JSBSim writes -- one entry per stated station
    (name, property, lbs) and per tank (index, property, lbs) -- the CG the
    host must read back within ``tolerance_in`` after the writes and
    BEFORE its trim, and the datum the arms are in, in the fixed key order
    ``core.scenario.loading.CARD_KEYS``. A projection of the spec and the
    airframe's config: no FDM is built here (the run's own read-back is
    the record's)."""
    from core.scenario.loading import CARD_KEYS, LoadingPlan

    plan = LoadingPlan.from_spec(spec)
    if plan is None:
        return None
    problems = plan.problems()
    if problems:
        raise problems[0]
    block = plan.card_block()
    if tuple(block) != CARD_KEYS:
        raise RuntimeError(f"loading card keys {list(block)} are not the fixed order "
                           f"{list(CARD_KEYS)}")
    return block


def gust_table_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    """The ``gust_table`` block for a spec (P6), or None when the model is
    not von_karman (no block: the host writes nothing into the gust
    channel). The table is built exactly as the headless run builds it:
    the spec's environment stack prepared on an FDM at the initial
    conditions (the atmosphere first, then the true airspeed and span
    JSBSim reports), so the rows the card carries are the run's rows
    (pinned equal by test). Keys in the fixed order
    ``core.environment.von_karman.CARD_KEYS``; rows as %.17g strings."""
    from core.environment.von_karman import CARD_KEYS, VonKarmanTurbulence
    from core.scenario.runner import environment_for, fdm_at_initial_conditions

    stack = environment_for(spec)
    providers = [p for p in stack.gust if isinstance(p, VonKarmanTurbulence)]
    if not providers:
        return None
    fdm = fdm_at_initial_conditions(spec)
    stack.prepare(fdm)
    block = providers[0].card_block()
    if tuple(block) != CARD_KEYS:
        raise RuntimeError(f"gust_table card keys {list(block)} are not the fixed order "
                           f"{list(CARD_KEYS)}")
    expected = int(round(float(spec.duration.value) * float(spec.rate.value))) + 1
    if len(block["rows"]) != expected:
        raise RuntimeError(f"gust_table has {len(block['rows'])} rows for {expected} steps")
    return block


def layered_wind_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    """The ``layered_wind`` block for a spec (P6), or None for the uniform
    kind: the profile's own ``card_block`` (layers as [altitude_m,
    speed_kt, direction_deg]; the milspec law sampled at fixed heights
    AGL with its z0; the fixture's layers with its digest as the source)
    in the fixed order ``core.environment.shear.CARD_KEYS``."""
    from core.environment.shear import CARD_KEYS
    from core.scenario.runner import wind_profile_for

    provider = wind_profile_for(spec)
    if provider is None:
        return None
    block = provider.card_block()
    if tuple(block) != CARD_KEYS:
        raise RuntimeError(f"layered_wind card keys {list(block)} are not the fixed order "
                           f"{list(CARD_KEYS)}")
    return block


def failure_schedule_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    """The ``failure_schedule`` block for a spec (P3), or None when no
    failure is scheduled (no block: the host writes nothing). Events in
    the fixed key order ``core.telemetry.failures.CARD_EVENT_KEYS``
    (kind, target, at_s, property, value) and ``count``; ``at_s`` is on
    the host's own run clock (seconds after its first step) and an
    engine property is written with ``propulsion/active_engine`` set to
    the target and restored. A host that cannot apply an event exactly
    refuses ``card.failure_schedule``."""
    from core.telemetry.failures import CARD_KEYS, FailureSchedule

    schedule = FailureSchedule.from_spec(spec)
    if not len(schedule):
        return None
    block = schedule.card_block()
    if tuple(block) != CARD_KEYS:
        raise RuntimeError(f"failure_schedule card keys {list(block)} are not the fixed "
                           f"order {list(CARD_KEYS)}")
    if block["count"] != len(block["events"]):
        raise RuntimeError(f"failure_schedule count {block['count']} for "
                           f"{len(block['events'])} events")
    return block


def icing_schedule_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    """The ``icing_schedule`` block for a spec (P5), or None for the
    default block (no ice: the host flies the stock airframe and writes
    nothing). The severity ramp's numbers (eta_max resolved from the word
    or the number, onset and ramp on the host's own run clock, the alpha
    shift at full eta), the airframe's six k coefficients and their
    source, in the fixed key order ``core.environment.icing.CARD_KEYS``
    with exactly six table entries; the host writes eta(t), the six
    factors 1 + eta k and the shift at the top of every step into the
    derived airframe and refuses ``card.icing_schedule`` otherwise. A
    projection of the spec and the config: no FDM is built here."""
    from core.environment.icing import CARD_KEYS, K_KEYS, IcingProvider

    provider = IcingProvider.from_spec(spec)
    if provider is None:
        return None
    block = provider.card_block()
    if tuple(block) != CARD_KEYS:
        raise RuntimeError(f"icing_schedule card keys {list(block)} are not the fixed order "
                           f"{list(CARD_KEYS)}")
    if tuple(block["k_table"]) != K_KEYS:
        raise RuntimeError(f"icing_schedule k_table keys {list(block['k_table'])} are not "
                           f"the fixed order {list(K_KEYS)}")
    return block


def wake_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    """The ``wake`` block for a spec (P7), or None when no generator is
    stated (no block: the host places no generator and writes nothing).
    Built exactly as the headless run builds it: the spec's environment
    stack prepared on an FDM at the initial conditions (the atmosphere
    first, then the density, the own span and the true airspeed JSBSim
    reports), so Gamma_0, b_0, r_c, the decay, the geometry and the five
    selftest vectors the host port must reproduce to 1e-9 are the run's
    own numbers. Keys in the fixed order ``core.environment.wake.CARD_KEYS``;
    the host refuses ``card.wake`` otherwise."""
    from core.environment.wake import CARD_KEYS, SELFTEST_COUNT, SELFTEST_KEYS, WakeVortexPair
    from core.scenario.runner import environment_for, fdm_at_initial_conditions

    stack = environment_for(spec)
    providers = [p for p in stack.gust if isinstance(p, WakeVortexPair)]
    if not providers:
        return None
    fdm = fdm_at_initial_conditions(spec)
    prepared = stack.prepare(fdm)        # Gamma_0 from the run's own pre-trim numbers
    assert providers[0].name in prepared
    block = providers[0].card_block()
    if tuple(block) != CARD_KEYS:
        raise RuntimeError(f"wake card keys {list(block)} are not the fixed order {list(CARD_KEYS)}")
    vectors = block["selftest"]
    if len(vectors) != SELFTEST_COUNT or any(tuple(v) != SELFTEST_KEYS for v in vectors):
        raise RuntimeError(f"wake selftest is not {SELFTEST_COUNT} vectors of {list(SELFTEST_KEYS)}")
    return block


def world_look_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    """The top-level ``look`` block for a spec (W3), or None when the spec
    states no night, no rain rate and a uniform wind (no block: the host
    draws the look it always drew). Sub-blocks in the fixed order
    ``core.scene.world_record.LOOK_KEYS``, each in its module's fixed key
    order (``core.scene.night.CARD_KEYS``, ``core.scene.precipitation
    .CARD_KEYS``, ``core.scene.weather_visuals.CLOUD_DRIFT_KEYS``). Refuses
    by name through the modules (look.moon, look.stars, night.sun_units,
    look.precipitation_rate)."""
    from core.scene import night, precipitation, weather_visuals
    from core.scene.world_record import LOOK_KEYS, card_look, world_look

    block = card_look(world_look(spec))
    if block is None:
        return None
    if tuple(block) != tuple(k for k in LOOK_KEYS if k in block):
        raise RuntimeError(f"look card keys {list(block)} are not in the fixed order "
                           f"{list(LOOK_KEYS)}")
    for key, keys in (("night", night.CARD_KEYS), ("precipitation", precipitation.CARD_KEYS),
                      ("cloud_drift", weather_visuals.CLOUD_DRIFT_KEYS)):
        if key in block and tuple(block[key]) != keys:
            raise RuntimeError(f"look.{key} card keys {list(block[key])} are not the fixed "
                               f"order {list(keys)}")
    return block


#: The ``derived_aircraft`` block's keys, in the fixed order the UE host
#: reads them (P9; FlightSimScenarioWorld refuses ``card.derived_aircraft``
#: otherwise).
DERIVED_AIRCRAFT_CARD_KEYS = ("name", "base", "injections", "aircraft_root", "xml_sha256")


def derived_aircraft_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    """The ``derived_aircraft`` block for a spec (P9), or None when the
    spec flies the stock airframe (no block: the host loads the plugin's
    staged aircraft exactly as before). The airframe is derived exactly as
    the headless run derives it (``fdm_at_initial_conditions``: the
    failures, icing and gust_rotation injections the spec's blocks select;
    derive.py applies them in its fixed order) less TECS, which the host
    never runs (it refuses ``hold_state``) -- so the two derivations differ
    only by the TECS system. ``aircraft_root`` is the directory holding
    ``<name>/<name>.xml`` (the plugin's patched aircraft path) and
    ``xml_sha256`` the derivation's own hash, which the plugin checks at
    the door before JSBSim reads the file."""
    from core.control.derive import derive
    from core.environment.icing import icing_injections_for
    from core.environment.wake import wake_injections_for
    from core.telemetry.failures import failure_injections_for

    injections = tuple(dict.fromkeys(
        tuple(failure_injections_for(spec)) + tuple(icing_injections_for(spec))
        + tuple(wake_injections_for(spec))))
    injections = tuple(name for name in injections if name != "tecs")
    if not injections:
        return None
    derived = derive(str(spec.aircraft.value), injections=injections)
    block = {
        "name": derived.name,
        "base": derived.base_name,
        "injections": list(derived.injection_names),
        "aircraft_root": str(derived.aircraft_path),
        "xml_sha256": derived.derived_sha256,
    }
    if tuple(block) != DERIVED_AIRCRAFT_CARD_KEYS:
        raise RuntimeError(f"derived_aircraft card keys {list(block)} are not the fixed order "
                           f"{list(DERIVED_AIRCRAFT_CARD_KEYS)}")
    return block


GOOGLE_TILES_ENV = "FLIGHTSIM_GOOGLE_TILES"
GOOGLE_TILES_ON = ("1", "on", "true", "yes")


def google_tiles_requested() -> bool:
    """FLIGHTSIM_GOOGLE_TILES is on: the same words the render host's
    FFlightSimGoogleTiles::Requested accepts."""
    return os.environ.get(GOOGLE_TILES_ENV, "").strip().lower() in GOOGLE_TILES_ON


#: The constraint a Google-tiles render refuses under when the physics
#: ground is not a real elevation bake of the place the tiles draw.
GOOGLE_TILES_TERRAIN_CONSTRAINT = "google_tiles.terrain"


def google_tiles_terrain_refusal(heightfield, latitude_deg: Optional[float] = None,
                                 longitude_deg: Optional[float] = None,
                                 terrain_elevation_m: Optional[float] = None
                                 ) -> Optional[str]:
    """None, or why the render must not draw Google's tiles over this ground.

    The tiles draw the real Earth at the card's coordinates; the physics,
    the labels and the verifier keep the run's own ground. Over a flat
    slab (``heightfield`` None) or a synthesised raster that ground is NOT
    the place the tiles show, so the aircraft would fly through mountains
    it never feels. Only a bake ingested from a real DEM (producer ``dem
    ingestion``: GLO-30 or 3DEP) is accepted under the tiles -- and the
    flat slab at a 0 m datum on a listed open-ocean point
    (core.terrain.ocean), where the sea surface IS that slab.
    """
    if not google_tiles_requested():
        return None
    if heightfield is None:
        from ..terrain.ocean import open_ocean_at

        if (latitude_deg is not None and longitude_deg is not None
                and terrain_elevation_m is not None and float(terrain_elevation_m) == 0.0
                and open_ocean_at(latitude_deg, longitude_deg) is not None):
            return None
        return (f"{GOOGLE_TILES_ENV} is on but the physics ground is the flat slab: "
                f"the tiles would draw real terrain the aircraft never feels. Bake the "
                f"place (scripts/bake_terrain.py, or the page's on-demand bake), say "
                f"'over the ocean' for an open-ocean scene, or turn the tiles off")
    producer = str((heightfield.provenance or {}).get("producer", ""))
    if producer != "dem ingestion":
        return (f"{GOOGLE_TILES_ENV} is on but the physics ground {heightfield.name!r} is "
                f"not a real elevation bake (producer {producer or 'unknown'!r}): the tiles "
                f"would draw a different place from the ground the aircraft flies on. Bake "
                f"the real place or turn the tiles off")
    return None


def google_tiles_card_block(latitude_deg: float, longitude_deg: float) -> Dict[str, object]:
    """The ``google_tiles`` card block: the geoid undulation at the card's
    origin, which places Cesium's georeference origin at ellipsoidal
    height = terrain_elevation_m + N. Evaluated for EVERY scene, since a
    flat or synthesised scene's datum block has no undulation (null) but
    the tiles are still real Earth there: without it they sit ~N metres
    off (+52 m at the Matterhorn). EGM2008 when its grid is cached,
    else the committed EGM96 grid; the model is recorded."""
    from core.terrain.geoid import grid_for_model

    grid = grid_for_model("auto")
    return {
        "geoid_undulation_m": float(grid.undulation(float(latitude_deg), float(longitude_deg))),
        "geoid_model": str(grid.model_key),
    }


def write_run_card(spec: ScenarioSpec, path: Path,
                   control_inputs: Sequence[Dict[str, float]] = (),
                   duration_s: Optional[float] = None,
                   wind_schedule: Optional[Sequence[Dict[str, float]]] = None,
                   orographic: Optional[Dict[str, object]] = None,
                   downburst: Optional[Dict[str, object]] = None,
                   rotor: Optional[Dict[str, object]] = None,
                   log_profile: Optional[Dict[str, object]] = None,
                   thermals: Optional[Dict[str, object]] = None,
                   turbulence_schedule: Optional[Dict[str, object]] = None,
                   orographic_follow_schedule: bool = False,
                   collision_terrain: Optional[str] = None,
                   turbulence_provider=None,
                   reference_speeds: Optional[Dict[str, object]] = None,
                   tornado: Optional[Dict[str, object]] = None,
                   randomization: Optional[Dict[str, object]] = None,
                   scene_crs: Optional[str] = None,
                   cameras: Optional[Sequence[Dict[str, object]]] = None,
                   landmarks: Optional[Sequence[Dict[str, object]]] = None,
                   objects: Optional[Sequence[Dict[str, object]]] = None,
                   taxonomy: Optional[Sequence[str]] = None,
                   traffic: Optional[Sequence[Dict[str, object]]] = None,
                   datum: Optional[Dict[str, object]] = None,
                   world: Optional[Dict[str, object]] = None,
                   georeference: Optional[Dict[str, object]] = None,
                   ) -> Path:
    """Write the spec in the form the UE commandlet reads.

    A projection of the spec, not a second copy of it. Every field is taken
    straight from the spec and the digest travels with them, so the commandlet
    can say which spec it ran and the run record can be checked against the
    headless one. The commandlet refuses -- loudly, with the reason -- any field
    it cannot honour exactly, which is why this can be a flat projection rather
    than a translation layer that decides what to drop.

    Phase 6B additions follow the same rule -- computed once here, applied
    verbatim there:

    * a spec with turbulence gets the EXACT property writes the headless
      Dryden provider produces (``turbulence_properties``), so the UE host
      never derives Dryden parameters from a word;
    * ``wind_schedule`` carries per-step NED wind in fps, precomputed from
      the headless providers (steady + 1-cosine gusts are pure functions of
      time), so the gust model exists exactly once;
    * ``orographic`` carries the terrain path plus every modelling parameter
      (decay height, wavelength, projected origin) so the C++ port derives
      nothing.
    """
    card = {
        "spec_digest": spec.digest(),
        "aircraft": str(spec.aircraft.value),
        "altitude_m": float(spec.altitude.value),
        "airspeed_kt": float(spec.airspeed.value),
        "airspeed_kind": str(spec.airspeed_kind.value),
        "heading_deg": float(spec.heading.value),
        "latitude_deg": float(spec.latitude.value),
        "longitude_deg": float(spec.longitude.value),
        "terrain_elevation_m": float(spec.terrain_elevation.value),
        "duration_s": float(spec.duration.value if duration_s is None else duration_s),
        "rate_hz": float(spec.rate.value),
        "sample_interval_s": SAMPLE_INTERVAL_S,
        "wind_speed_kt": float(spec.wind_speed.value),
        "wind_direction_deg": float(spec.wind_direction.value),
        "turbulence": str(spec.turbulence.value),
        "mass_held": bool(spec.mass_held.value),
        "hold_state": bool(spec.hold_state.value),
        "control_inputs": [dict(entry) for entry in control_inputs],
        # Verified by cranking the same JSBSim at this altitude (patch 4):
        # full rich kills a force-started piston above ~3 km density altitude.
        "engine_mixture": discovered_engine_mixture(spec),
    }
    if turbulence_provider is not None:
        # A Phase 7 turbulence provider (lee rotor, or a scheduled Dryden)
        # supplies its own configure() writes -- e.g. the rotor's pinned
        # severity of 1 with intensity delivered per step through W20 --
        # and its own card word: the UE host applies turbulence_properties
        # only for a word other than "none" (measured the hard way: a rotor
        # card labeled "none" flew in still air while writing W20 into a
        # process that was never switched on).
        card["turbulence_properties"] = turbulence_provider.configure()
        card["turbulence"] = turbulence_provider.card_word
    elif str(spec.turbulence.value) != "none":
        from core.environment.turbulence import DrydenTurbulence

        provider = DrydenTurbulence(str(spec.turbulence.value),
                                    seed=int(spec.seed.value))
        card["turbulence_properties"] = provider.configure()
    if turbulence_provider is None:
        # P6: the turbulence_model block. von_karman: the field rides in
        # the gust_table block below and JSBSim's own Dryden process is
        # switched OFF exactly as the headless stack does (turb-type 0),
        # so the host never runs both. dryden with a stated intensity word
        # or seed: the provider the runner builds, and the card's word is
        # the stated one (the host keys its turbulence writes on the word).
        from core.environment.turbulence import DrydenTurbulence

        model_block = spec.turbulence_model
        intensity = model_block.intensity.value
        seed = spec.seed.value if model_block.seed.value is None else model_block.seed.value
        if str(model_block.model.value) == "von_karman":
            card["turbulence_properties"] = DrydenTurbulence("none").configure()
        elif intensity is not None or model_block.seed.value is not None:
            word = str(spec.turbulence.value) if intensity is None else str(intensity)
            card["turbulence"] = word
            if word != "none":
                card["turbulence_properties"] = DrydenTurbulence(word, seed=int(seed)).configure()
            else:
                card.pop("turbulence_properties", None)
    gust_table = gust_table_card_block(spec)
    if gust_table is not None:
        # P6: the von Karman table, row for row (%.17g), with the digest of
        # its rows; the host applies row i into atmosphere/gust-*-fps at
        # step i (rotating u, v by the card's heading_deg) and into
        # gust/p-equivalent-rad_sec where the airframe declares it, and
        # refuses card.gust_table / gust_table.length otherwise.
        card["gust_table"] = gust_table
    layered_wind = layered_wind_card_block(spec)
    if layered_wind is not None:
        # P6: the wind profile as layers the host interpolates between;
        # it REPLACES the uniform wind (wind_speed_kt / wind_direction_deg
        # stay on the card as what the spec said).
        card["layered_wind"] = layered_wind
    atmosphere = atmosphere_card_block(spec)
    if atmosphere is not None:
        # Gap P1: the EXACT JSBSim property writes the headless provider
        # makes (delta-T in R, P-sl in psf, dew point in R; null = not
        # written), in a fixed key order, so the UE host applies the same
        # numbers before its trim and every step and derives nothing.
        card["atmosphere_properties"] = atmosphere
    loading = loading_card_block(spec)
    if loading is not None:
        # P4: the EXACT point-mass and tank writes the headless run makes
        # once before its trim, with the hand CG the host reads inertia/cg-x-in
        # back against (within tolerance_in) before its trim, and the datum
        # the arms are in; refused card.loading_properties by the host when a
        # key is missing or out of order, an entry is not (name, property,
        # lbs), or the read-back misses.
        card["loading_properties"] = loading
    failure_schedule = failure_schedule_card_block(spec)
    if failure_schedule is not None:
        # P3: the schedule, event for event with the property each
        # writes; the host applies each at the first step with t >= at_s
        # of its run clock and refuses card.failure_schedule otherwise.
        card["failure_schedule"] = failure_schedule
    icing_schedule = icing_schedule_card_block(spec)
    if icing_schedule is not None:
        # P5: the severity ramp and the airframe's k-table; the host
        # writes eta(t), the six factors and the shift at the top of every
        # step of its run clock into the derived airframe (P9 loads it)
        # and refuses card.icing_schedule otherwise.
        card["icing_schedule"] = icing_schedule
    wake = wake_card_block(spec)
    if wake is not None:
        # P7: the generator's pair -- Gamma_0, b_0, r_c, the decay, the
        # geometry and the selftest vectors; the host's port evaluates
        # the same field, checks the vectors to 1e-9 and refuses
        # card.wake otherwise (P9's Windows step).
        card["wake"] = wake
    derived_aircraft = derived_aircraft_card_block(spec)
    if derived_aircraft is not None:
        # P9: the airframe the failure, icing and roll-gust writes go into;
        # the host loads it through the plugin's patched aircraft path and
        # checks its XML sha256 at the door (card.derived_aircraft).
        card["derived_aircraft"] = derived_aircraft
    look = world_look_card_block(spec)
    if look is not None:
        # W3 (absent-canonical): the world look -- look.night (the moon's
        # elevation, azimuth, phase and lux, the star mode, the sun units),
        # look.precipitation (the fitted distribution and the streaks) and
        # look.cloud_drift (the providers' wind at the cloud base), each in
        # its fixed key order; the host (W5) refuses look.moon, look.stars,
        # look.precipitation_particles or look.cloud_drift_parameter by
        # name when it cannot draw one exactly.
        card["look"] = look
    weather_look = weather_look_card_block(spec)
    if weather_look is not None:
        # Visual only (absent-canonical): the ground word, the storm, the
        # rain rate, the wetness, the ice and the seed the host's weather
        # look draws from (core/scene/weather_look.py); a spec stating none
        # of them writes no block.
        card["weather_look"] = weather_look
    if reference_speeds:
        # Display-only (the HUD/panel stall-margin marks): the MODEL's own
        # measured Vs and CLmax with their basis string (§2.4), so the marks
        # are per-aircraft with provenance, never a generic number. Feeds no
        # physics; hosts without the block simply omit the marks.
        card["reference_speeds"] = dict(reference_speeds)
    if wind_schedule:
        card["wind_schedule"] = [dict(entry) for entry in wind_schedule]
    if orographic:
        card["orographic"] = dict(orographic)
        # The vertical datum block rides in from the bake's sidecar
        # through orographic_card_block; it is the card's, not the
        # wind model's, so it is lifted to the top level and the
        # orographic block keeps exactly the keys the C++ port reads.
        if datum is None and isinstance(card["orographic"].get("datum"), dict):
            datum = card["orographic"].pop("datum")
    if datum:
        # P10: which vertical datum the scene's heights are in, the geoid
        # undulation at the origin with its source and bounds, and the
        # ellipsoidal height of the origin (core/terrain/geoid.py). No
        # host converts a height from it; it is the record of what the
        # heights ARE, carried verbatim.
        card["datum"] = dict(datum)
    # Phase 7 blocks: every parameter computed here, in the providers'
    # own modules, and carried verbatim -- the C++ ports derive nothing.
    if downburst:
        card["downburst"] = dict(downburst)
    if rotor:
        card["rotor"] = dict(rotor)
    if tornado:
        # Phase 9.3: the Rankine vortex, every constant computed in Python
        # (core/environment/tornado.py card_block); the host derives nothing.
        card["tornado"] = dict(tornado)
    if scene_crs:
        # Phase 9: a flat scene has no terrain to declare the projected
        # frame the position-coupled blocks (thermals, downburst, tornado)
        # work in; the card declares it (the spec origin's UTM zone).
        card["scene_crs"] = str(scene_crs)
    if cameras:
        # Camera Phase 1: each entry carries the camera's spec fields
        # AND its Python-solved pose track (PoseTrack.card_block) at
        # the card's own sample clock -- computed once here, consumed
        # verbatim by the render host's consume-poses camera mode,
        # which refuses (never extrapolates) a track that does not
        # cover the run.
        card["cameras"] = [dict(entry) for entry in cameras]
    if landmarks:
        # Camera Phase 2: the SAME known static world points the capture
        # manifest records. The commandlet projects them through its own
        # world-to-pixel helper and writes the pixels into render.json;
        # the verifier projects them through the manifest and compares.
        # Two implementations of one projection -- the only reprojection
        # check in this system that is not the manifest talking to itself.
        card["landmarks"] = [dict(entry) for entry in landmarks]
    if log_profile:
        card["log_profile"] = dict(log_profile)
    if thermals:
        card["thermals"] = dict(thermals)
    if turbulence_schedule:
        card["turbulence_schedule"] = dict(turbulence_schedule)
    if orographic_follow_schedule:
        card["orographic_follow_schedule"] = True
    if collision_terrain:
        card["collision_terrain"] = str(collision_terrain)
    if randomization:
        # Phase 10 (package 7): the sampled look the render is given
        # (sun in both conventions, exposure, fog), the livery the host
        # applies (refusing by name when the asset is absent), and each
        # camera field the jitter moved. Computed in
        # core/scenario/randomization.py; the host derives nothing.
        card["randomization"] = dict(randomization)
    if objects:
        # Phase 2 (package B, contracts §2.3): the scene's labelled
        # objects with their integer ids, composed ONCE in Python
        # (core/capture/objects.py). The render host sets every labelled
        # component's Custom Depth Stencil from this list and never
        # invents an id; the ID image holds exactly these integers.
        card["objects"] = [dict(entry) for entry in objects]
    if taxonomy:
        # The class list the class image is written against (class_id =
        # position + 1, 0 = sky); the render.json "classes" sentence is
        # generated from it.
        card["taxonomy"] = [str(name) for name in taxonomy]
    if traffic:
        # Phase 2 (packages B + C, contracts §2.2): each scripted traffic
        # aircraft with its solved position + attitude keyframes
        # (core/capture/poses.py traffic_card_block), the mesh manifest
        # to draw and where its CG sits in the actor frame. The host
        # moves a static-mesh actor along the track with linear
        # interpolation and refuses a track it cannot draw.
        card["traffic"] = [dict(entry) for entry in traffic]
    if world:
        # W2 (absent-canonical): the world the host draws -- the terrain
        # and its sha256, the buildings document and the runway document
        # with their sha256s (core/scene/runway.py world_card_block); a
        # member is null when the scene states none. The host derives
        # nothing and refuses a file whose digest is not the card's.
        card["world"] = dict(world)
    if georeference:
        # The capture's georeference (core/capture/manifest.py
        # georeference_card_block): the manifest frame's projected CRS and
        # origin and the datum's undulation at the origin. The host copies
        # it into render.json beside its own vertical convention and derives
        # nothing; check.georeference grades the copy against the manifest.
        card["georeference"] = dict(georeference)
    if google_tiles_requested():
        # Visual only, and only when the render will draw Google's tiles:
        # the host reads the undulation from here when the georeference
        # block has none (a card without the env var is unchanged).
        card["google_tiles"] = google_tiles_card_block(card["latitude_deg"],
                                                       card["longitude_deg"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(card, indent=1), encoding="utf-8")
    return path
