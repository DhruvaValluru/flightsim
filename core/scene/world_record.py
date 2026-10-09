"""The world look a render is handed, and the record it returns (``scene.world``).

W3 (docs/ADVANCEMENTS_BLUEPRINT.md section 4, "Data each variable
returns"). One place assembles what the card's top-level ``look`` block
carries -- ``night`` (core/scene/night.py), ``precipitation``
(core/scene/precipitation.py) and ``cloud_drift`` (the run's own wind
providers at the cloud base, core/scene/weather_visuals.py) -- and the
record the capture manifest's ``applied_variables`` gains for it.

The look is ABSENT-CANONICAL: it exists only when the spec states
``scene.night`` or ``environment.precipitation_rate_mmh``, or a wind
profile whose wind aloft is not the uniform wind (``wind_profile.kind``
not ``uniform``); a spec that states none of them gets no card key, no
manifest key and no record, byte for byte.

The record's null tests come in BOTH kinds (core/records.py), and none
of them is measured here, because every effect is on the RENDER and no
engine runs in this container. Every prediction is a NUMBER computed
here; every measurement is a NAMED Windows clause (:data:`WINDOWS_CLAUSES`):

* ``reached`` -- render-side predictions: the moon on / off (the K&S sky
  luminance in the sky band with and without the moonlit term, the
  threshold the dark sky itself: the moon must at least double the band);
  the stars on / off at -18 deg (stars above the horizon brighter than V
  6.5, threshold one star; zero when the sun is not below -6 deg); the
  streaks on / off (the first camera's relative streak in px, threshold
  1 px); the drift doublet (the cloud offset after 30 s with the drift
  against without, threshold 1 m). A prediction whose numbers do not
  reach its threshold (a moon below the horizon, a calm base) is recorded
  as predicted silent -- the honest prediction, not a failure;
* ``bounded`` -- the invariance: the label passes (mask, class, depth)
  are predicted byte-identical with the world look on and off (0 bytes
  differ, threshold 0) while the beauty differs.

The registry's pairs for ``scene.night`` and
``environment.precipitation_rate_mmh`` are bounded invariances on
recorded columns (nothing here reaches an equation of motion); the
render-side effect is this record's, stated so.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..records import AppliedVariable, Model, NullTest

#: The Windows clause that measures each prediction (the blueprint's
#: "Verification on Windows" steps 9-11, and the label invariance).
WINDOWS_CLAUSES: Dict[str, str] = {
    "moon": "W3.9 moon on/off at -18 deg: the sky-band mean with the moon light against "
            "without, exposure holding at the EV100 of record (check.night_exposure grades "
            "each frame); night.sun_units exercised on the bias path",
    "stars": "W3.9 stars on/off at -18 deg: point sources detected in the sky band with the "
             "starfield against without",
    "streaks": "W3.10 streaks on/off against the wet control: both bands change with the "
               "streaks, only the terrain band with wetness; the relative streak length "
               "within 30 % of the prediction",
    "drift": "W3.11 cloud drift doublet: two 30 s renders, drift against none, the cloud "
             "texture offset by the predicted distance (Gate 10-R run with drift on both sides)",
    "labels": "W3.12 labels invariance: mask, class and depth byte-identical with the world "
              "look on and off while the beauty differs",
}
#: The sky band a prediction is evaluated in: this far above the horizon
#: along the initial heading (the band a chase camera frames), stated.
SKY_BAND_ELEVATION_DEG = 10.0
#: The doublet's length and the thresholds of the reached predictions.
DRIFT_DOUBLET_S = 30.0
DRIFT_THRESHOLD_M = 1.0
STREAK_THRESHOLD_PX = 1.0
STAR_THRESHOLD = 1.0
#: The card's top-level look block keys, in their fixed order (each only
#: when present).
LOOK_KEYS = ("night", "precipitation", "cloud_drift")
RECORD_NAME = "scene.world"


def _stated(q) -> bool:
    return q is not None and q.value is not None


def world_stated(spec) -> bool:
    """Whether the spec asks for a world look at all (absent-canonical)."""
    night = getattr(spec.scene, "night", None)
    rate = getattr(spec, "precipitation_rate_mmh", None)
    profile = getattr(spec, "wind_profile", None)
    kind = None if profile is None else str(profile.kind.value)
    return _stated(night) or _stated(rate) or (kind is not None and kind != "uniform")


def cloud_base_m(spec) -> float:
    """The layer base the drift is evaluated at: the randomisation block's
    drawn ``cloud_base_m`` when sampled, else the documented default."""
    from .weather_visuals import DEFAULT_CLOUD_BASE_M
    from ..scenario.fields import Source

    q = spec.randomization.cloud_base_m
    if q.source == Source.SAMPLED and q.value:
        return float(q.value)
    return DEFAULT_CLOUD_BASE_M


def spec_cloud_drift(spec) -> Dict[str, Any]:
    """The drift from the spec's own wind providers at the cloud base."""
    from .weather_visuals import cloud_drift_at_base
    from ..scenario.runner import environment_for

    stack = environment_for(spec)
    return cloud_drift_at_base(stack.wind, float(spec.latitude.value),
                               float(spec.longitude.value), float(spec.terrain_elevation.value),
                               cloud_base_m(spec))


def world_look(spec) -> Optional[Dict[str, Any]]:
    """The full world look (every number the record keeps), or None:
    ``{"night": NightSky | None, "rain": {...} | None, "precipitation":
    card block | None, "cloud_drift": {...}}``. Refuses by name through
    the modules (look.moon, look.stars, night.sun_units,
    look.precipitation_rate)."""
    if not world_stated(spec):
        return None
    from . import night as night_module
    from . import precipitation as rain_module

    sky = night_module.spec_night(spec)
    rate = getattr(spec, "precipitation_rate_mmh", None)
    rain = card = None
    if _stated(rate):
        rain = rain_module.rain(rate.value)
        card = rain_module.card_block(rate.value, rain_module.spec_rain_cameras(spec))
    return {"night": sky, "rain": rain, "precipitation": card,
            "cloud_drift": spec_cloud_drift(spec)}


def card_look(look: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The card's ``look`` block in LOOK_KEYS order, each sub-block in its
    module's fixed key order."""
    if look is None:
        return None
    from .weather_visuals import CLOUD_DRIFT_KEYS

    out: Dict[str, Any] = {}
    if look["night"] is not None:
        out["night"] = look["night"].card_block()
    if look["precipitation"] is not None:
        out["precipitation"] = dict(look["precipitation"])
    drift = look["cloud_drift"]
    out["cloud_drift"] = {key: drift[key] for key in CLOUD_DRIFT_KEYS}
    return out


def predictions(spec, look: Dict[str, Any]) -> List[NullTest]:
    """The null tests, both kinds: every number here, every measurement a
    Windows clause (named in each note)."""
    from . import night as night_module

    out: List[NullTest] = []
    sky = look["night"]
    if sky is not None and sky.moon_requested:
        band_az = float(spec.heading.value) % 360.0
        band = night_module.sky_luminance_cd_m2(
            sky.phase_angle_deg, sky.moon_azimuth_deg, sky.moon_elevation_deg, band_az,
            SKY_BAND_ELEVATION_DEG, moon=True)
        out.append(NullTest(
            quantity="sky-band luminance, moon on against off", unit="cd/m^2",
            with_value=band["total_cd_m2"], without_value=band["dark_cd_m2"],
            threshold=band["dark_cd_m2"], kind="reached",
            note=(f"K&S 1991 at {SKY_BAND_ELEVATION_DEG:g} deg above the horizon along "
                  f"{band_az:.1f} deg, moon at {sky.moon_elevation_deg:.2f} deg elevation, "
                  f"phase angle {sky.phase_angle_deg:.2f} deg; threshold the dark sky (the "
                  f"moon must at least double the band). Measured by: "
                  f"{WINDOWS_CLAUSES['moon']}")))
    if sky is not None and sky.stars_mode != "off":
        count = float(sky.star_count if sky.night else 0)
        out.append(NullTest(
            quantity="stars above the horizon to V 6.5, stars on against off", unit="stars",
            with_value=count, without_value=0.0, threshold=STAR_THRESHOLD, kind="reached",
            note=(f"{sky.stars_mode} field, sun at {sky.sun_elevation_deg:.2f} deg (night "
                  f"{'yes' if sky.night else 'no: no star is predicted visible'}). Measured "
                  f"by: {WINDOWS_CLAUSES['stars']}")))
    if look["precipitation"] is not None:
        streaks = look["precipitation"]["streak_px"]
        first = next(iter(streaks)) if streaks else None
        length = float(streaks[first]["relative_px"]) if first is not None else 0.0
        out.append(NullTest(
            quantity="relative rain streak length, streaks on against off", unit="px",
            with_value=length, without_value=0.0, threshold=STREAK_THRESHOLD_PX,
            kind="reached",
            note=(f"camera {first}, on the optical axis at "
                  f"{streaks[first]['range_m'] if first else 0:g} m, the fitted D0's fall "
                  f"speed relative to the camera over its shutter. Measured by: "
                  f"{WINDOWS_CLAUSES['streaks']}")))
    drift = look["cloud_drift"]
    out.append(NullTest(
        quantity=f"cloud offset after the {DRIFT_DOUBLET_S:g} s doublet, drift against none",
        unit="m", with_value=float(drift["mps"]) * DRIFT_DOUBLET_S, without_value=0.0,
        threshold=DRIFT_THRESHOLD_M, kind="reached",
        note=(f"{drift['mps']} m/s from {drift['from_deg']} deg, {drift['source']} "
              f"({drift['base_m']} m above the scene datum). Measured by: "
              f"{WINDOWS_CLAUSES['drift']}")))
    out.append(NullTest(
        quantity="label-pass bytes that differ, world look on against off", unit="bytes",
        with_value=0.0, without_value=0.0, threshold=0.0, kind="bounded",
        note=(f"the look is drawn on the beauty capture only (the rain blendable, the moon "
              f"light, the starfield, the cloud offset); the label captures do not see it. "
              f"Measured by: {WINDOWS_CLAUSES['labels']}")))
    return out


def world_record(spec, look: Optional[Dict[str, Any]] = None) -> Optional[AppliedVariable]:
    """The ``scene.world`` record, or None without a world look."""
    look = world_look(spec) if look is None else look
    if look is None:
        return None
    from . import night as night_module
    from . import precipitation as rain_module

    tests = predictions(spec, look)
    stated = [q for q in (getattr(spec.scene, "night", None),
                          getattr(spec, "precipitation_rate_mmh", None)) if _stated(q)]
    sources = [str(q.source) for q in stated] or [str(spec.wind_profile.kind.source)]
    source = "user" if "user" in sources else sources[0]
    written = []
    if look["night"] is not None:
        written += ["engine: moon directional light (AtmosphereSunLightIndex 1, lux)",
                    "engine: M_Starfield"]
    if look["precipitation"] is not None:
        written.append("engine: M_RainStreaks (beauty capture only)")
    written.append("engine: cloud material wind offset")
    parameters: Dict[str, Any] = {
        "night": None if look["night"] is None else look["night"].to_dict(),
        "rain": look["rain"],
        "cloud_drift": look["cloud_drift"],
        "null_tests": [t.to_dict() for t in tests],
        "windows_clauses": dict(WINDOWS_CLAUSES),
        "sky_band": {"elevation_deg": SKY_BAND_ELEVATION_DEG,
                     "azimuth_deg": float(spec.heading.value) % 360.0},
        "effects_on": ("the render only: no recorded column moves; the registry's pairs for "
                       "scene.night and environment.precipitation_rate_mmh are bounded "
                       "invariances on recorded columns, the render-side effects are the "
                       "reached predictions above, each measured by its Windows clause"),
    }
    frm = "; ".join(str(q.frm) for q in stated if q.frm) or None
    return AppliedVariable(
        name=RECORD_NAME, value=card_look(look), unit="look", source=source,
        model_name=("the world look: Meeus ch. 47/48 moon with K&S 1991 light, BSC5 or procedural "
               "stars, Marshall-Palmer rain with a fitted Lambda and Atlas 1973 fall speed, "
               "Atlas 1953 extinction reconciled with Koschmieder, the wind providers at "
               "cloud base"),
        parameters=parameters,
        references=tuple(night_module.REFERENCES) + tuple(rain_module.REFERENCES),
        properties_written=tuple(written),
        null_test=tests[0],
        not_claimed=(tuple(night_module.NOT_CLAIMED) + tuple(rain_module.NOT_CLAIMED)
                     + ("cloud drift only if the cloud material exposes an offset; the wind "
                        "aloft is frozen at 0 s",
                        "every prediction is a number computed here; every measurement is a "
                        "named Windows clause; nothing engine-side is verified here")),
        frm=frm,
        model=Model(name="world look (W3)", standard="Meeus 1998; K&S 1991; MP 1948; "
                                                          "Atlas 1953, 1973",
                          version="1",
                          parameters={"sky_band_elevation_deg": SKY_BAND_ELEVATION_DEG,
                                      "drift_doublet_s": DRIFT_DOUBLET_S},
                          references=tuple(night_module.REFERENCES[:2])
                          + tuple(rain_module.REFERENCES[:2])),
    )


def world_records(spec) -> List[AppliedVariable]:
    """The manifest's share: ``[scene.world]`` or nothing."""
    record = world_record(spec)
    return [] if record is None else [record]
