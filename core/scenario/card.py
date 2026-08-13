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
from pathlib import Path
from typing import Dict, Optional, Sequence

from core.scenario.spec import ScenarioSpec

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
                   scene_crs: Optional[str] = None) -> Path:
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(card, indent=1))
    return path
