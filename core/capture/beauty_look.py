"""The beauty look as the verifier reads it: label honesty for a new look.

The visual overhaul (docs/VISUAL_FIDELITY_PLAN.md V0, V8) puts a look on
the beauty frames -- light, post, weather, camera feel -- that the label
captures never see. Most of it changes only what a pixel's colour is.
Some of it changes WHERE a pixel lands: lens distortion, chromatic
aberration, heat-haze refraction, heavy motion blur, overscan and
upscaling. A mask taken from the undistorted label capture then no
longer lies on the subject it labels, and the bundle stops being a
labelled dataset unless the record says how to map one onto the other.

This module is the pure part: which render.json keys exist, which look
keys move pixels, and how one recorded effect is classified. The checks
that grade a run (``look_record`` and ``look_label_alignment``) live in
:mod:`core.capture.verify` beside the others, and
``experiments/look_label_check.py`` measures the same question from the
pixels on the render machine.

The render.json keys (all optional; a bundle written before them stays
valid -- the checks report NOT RUN, never FAIL, on their absence). The
schema is written out in docs/schemas/render_json_beauty_look.md:

* ``scene.render_quality`` -- ``measure`` | ``beauty`` | ``pathtrace``
  (root ``quality`` is read as an alias when ``scene`` lacks it);
* ``beauty_look`` -- the look-dev record of the look applied;
* ``pixel_moving_effects`` -- one entry per effect that moves pixels;
* ``beauty_samples`` -- spatial / temporal sample counts, shutter, and
  the path tracer's samples per pixel;
* ``beauty_only_actors`` -- the actors hidden from every label capture;
* ``cloud_occlusion`` -- what was decided about a beauty-only actor in
  front of the subject;
* per frame, ``beauty_window_s`` -- the beauty's time window, which must
  contain the labels' instant.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Tuple

#: The renderer configurations a render.json may name. ``pathtrace`` is
#: new with the overhaul (render-path lane; hero stills on Windows).
QUALITIES = ("measure", "beauty", "pathtrace")

#: Look keys that move pixels when on. A key ON in ``beauty_look`` and
#: absent from ``pixel_moving_effects`` is ``look.pixel_moving_unrecorded``.
#: Depth of field, bloom, grain, vignette and tonemapping change values,
#: not positions, and are not listed: an in-focus subject keeps its edge
#: (docs/schemas/render_json_beauty_look.md says why each one is out).
PIXEL_MOVING_KEYS: Dict[str, str] = {
    "motion_blur": "motion_blur",
    "motion_blur_amount": "motion_blur",
    "lens_distortion": "lens_distortion",
    "chromatic_aberration": "chromatic_aberration",
    "scene_fringe_intensity": "chromatic_aberration",
    "heat_haze": "heat_haze",
    "refraction": "heat_haze",
    "panini": "panini",
    "panini_d": "panini",
    "overscan": "overscan",
    "overscan_fraction": "overscan",
    "upscale": "upscale",
    "upscaling": "upscale",
    "screen_percentage": "upscale",
    "temporal_accumulation": "temporal_accumulation",
    # The C++ spellings the look-dev record actually carries
    # (render.json beauty_look.plan.camera / .applied.lens_post echo UE's
    # FPostProcessSettings member names; integration 2026-11-09).
    "MotionBlurAmount": "motion_blur",
    "SceneFringeIntensity": "chromatic_aberration",
}

#: Every effect name the render commandlet writes into
#: ``pixel_moving_effects`` (FlightSimRenderCommandlet.cpp
#: RenderWriteLookContract), on or off. Depth of field and the path
#: tracer's pixel filter spread edges rather than shift them, but the class
#: and depth labels of a defocused or filtered edge still disagree with the
#: beauty, so they are listed and graded like the rest.
COMMANDLET_EFFECTS = ("motion_blur", "depth_of_field", "heat_haze", "path_tracer_filter",
                      "chromatic_aberration", "lens_distortion")

#: Every effect name the verifier knows (look keys and the commandlet's).
EFFECT_NAMES = tuple(sorted(set(PIXEL_MOVING_KEYS.values()) | set(COMMANDLET_EFFECTS)))

#: Effect names that are the same thing under another spelling, so a
#: ``motion_blur`` entry answers a ``temporal_accumulation`` key and back.
EQUIVALENT_EFFECTS: Dict[str, Tuple[str, ...]] = {
    "motion_blur": ("motion_blur", "temporal_accumulation"),
    "temporal_accumulation": ("temporal_accumulation", "motion_blur"),
}

#: How a beauty-only actor in front of the subject was handled.
#: ``labels_unoccluded``: the mask shows the subject where a beauty-only
#: cloud or contrail covers it (honest only below the visibility gate's
#: tolerance, measured); ``kept_clear``: the visual scene keeps
#: beauty-only volumes out of the camera-to-subject cone by construction;
#: ``none_in_frame``: no beauty-only actor projects into the frame.
OCCLUSION_POLICIES = ("labels_unoccluded", "kept_clear", "none_in_frame")

#: The record keys this module introduces; a render.json carrying none
#: of them predates the beauty-look record. The render commandlet writes
#: all five on beauty and pathtrace renders (none on measure):
#: ``beauty_look`` from FFlightSimBeautyLook::Record, the other four from
#: RenderWriteLookContract (FlightSimRenderCommandlet.cpp), and
#: ``cloud_occlusion`` from FFlightSimWorldBeauty::CloudOcclusionRecord.
LOOK_KEYS = ("beauty_look", "pixel_moving_effects", "beauty_samples",
             "beauty_only_actors", "cloud_occlusion")

_ON_WORDS = ("on", "true", "yes", "enabled")
_OFF_WORDS = ("", "off", "false", "no", "none", "disabled", "0")
_AMOUNT_KEYS = ("amount", "intensity", "strength", "scale", "k1", "fraction",
                "max_displacement_px")


def quality_of(payload: Dict) -> Optional[str]:
    """``scene.render_quality``, else root ``quality``; None when neither."""
    scene = payload.get("scene")
    if isinstance(scene, dict) and isinstance(scene.get("render_quality"), str):
        return scene["render_quality"]
    for key in ("quality", "render_quality"):
        if isinstance(payload.get(key), str):
            return payload[key]
    return None


def has_look_record(payload: Dict) -> bool:
    return any(key in payload for key in LOOK_KEYS)


def _number(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def is_on(key: str, value) -> bool:
    """Whether one ``beauty_look`` value turns its effect on.

    True / a positive number / an ON word / an object whose ``on`` or
    ``enabled`` is true or whose amount is non-zero. ``screen_percentage``
    is on away from 0 (the engine's "default") and 100 (no resampling).
    """
    if key == "screen_percentage":
        number = _number(value)
        if number is None and isinstance(value, str):
            try:
                number = float(value)
            except ValueError:
                return value.strip().lower() not in _OFF_WORDS + ("absent",)
        return number is not None and number not in (0.0, 100.0)
    if isinstance(value, bool):
        return value
    number = _number(value)
    if number is not None:
        return number != 0.0
    if isinstance(value, str):
        word = value.strip().lower()
        if word in _OFF_WORDS:
            return False
        return True if word in _ON_WORDS else bool(word)
    if isinstance(value, dict):
        for flag in ("on", "enabled", "applied"):
            if flag in value:
                word = value[flag]
                if isinstance(word, str):
                    return word.strip().lower() not in _OFF_WORDS
                return bool(word)
        return any((_number(value.get(k)) or 0.0) != 0.0 for k in _AMOUNT_KEYS)
    if isinstance(value, (list, tuple)):
        return len(value) > 0
    return False


def look_effects_on(look: Dict) -> List[Tuple[str, str]]:
    """(key, effect name) for every pixel-moving key ON in ``beauty_look``,
    searched through every nested object (``post.motion_blur``,
    ``camera.lens.lens_distortion``): an effect recorded one level deeper
    than expected still moves pixels."""
    found: List[Tuple[str, str]] = []

    def visit(where: str, mapping: Dict) -> None:
        for key, value in mapping.items():
            path = f"{where}.{key}" if where else str(key)
            if key in PIXEL_MOVING_KEYS:
                if is_on(key, value):
                    found.append((path, PIXEL_MOVING_KEYS[key]))
            elif isinstance(value, dict):
                visit(path, value)

    if isinstance(look, dict):
        visit("", look)
    return found


#: Pixel-moving show flags the commandlet MEASURES on the beauty capture
#: and writes today (FlightSimRenderCommandlet.cpp,
#: render_settings.beauty_show_flags). UE 5.7 turns motion blur off on
#: every scene capture (SceneCaptureComponent.cpp), so ``true`` here
#: means someone turned it on, whatever beauty_look says.
MEASURED_SHOW_FLAGS: Dict[str, str] = {"motion_blur": "motion_blur"}


def measured_effects_on(payload: Dict) -> List[Tuple[str, str]]:
    """(key, effect name) for every pixel-moving show flag the commandlet
    measured ON on the beauty capture (``render_settings.beauty_show_flags``).
    Read on every bundle, old or new: it is a measurement, not the
    look-dev record."""
    settings = payload.get("render_settings")
    flags = settings.get("beauty_show_flags") if isinstance(settings, dict) else None
    if not isinstance(flags, dict):
        return []
    return [(f"render_settings.beauty_show_flags.{key}", name)
            for key, name in MEASURED_SHOW_FLAGS.items() if flags.get(key) is True]


def look_anything_on(look) -> bool:
    """A ``beauty_look`` record that applies anything at all (for the
    measure rule): absent, empty, ``applied: false`` or every value off
    is nothing."""
    if not isinstance(look, dict) or not look:
        return False
    if "applied" in look:
        return is_on("applied", look["applied"])
    return any(is_on(str(k), v) for k, v in look.items()
               if k not in ("not_claimed", "source", "note", "notes", "uncalibrated"))


def normalise_effects(raw) -> Tuple[List[Dict], List[str]]:
    """The ``pixel_moving_effects`` list as dicts, and the problems with it.

    A bare string is ``{"name": s, "on": true}`` with nothing else
    recorded. An entry with no ``on`` key is on (it was listed)."""
    problems: List[str] = []
    if raw is None:
        return [], problems
    if not isinstance(raw, list):
        return [], [f"pixel_moving_effects is {type(raw).__name__}, not a list"]
    out: List[Dict] = []
    for i, entry in enumerate(raw):
        if isinstance(entry, str) and entry.strip():
            out.append({"name": entry.strip(), "on": True})
        elif isinstance(entry, dict) and isinstance(entry.get("name"), str) and entry["name"].strip():
            item = dict(entry)
            item["name"] = entry["name"].strip()
            item["on"] = bool(entry.get("on", True))
            out.append(item)
        else:
            problems.append(f"pixel_moving_effects[{i}] = {entry!r} has no name")
    return out, problems


def transform_problem(transform) -> Optional[str]:
    """Why a recorded transform does not map labels onto the beauty, or
    None when it is a usable record: an object with a non-empty ``kind``
    whose numeric parameters are all finite."""
    if not isinstance(transform, dict):
        return f"transform {transform!r} is not an object"
    kind = transform.get("kind")
    if not isinstance(kind, str) or not kind.strip() or kind.strip().lower() in _OFF_WORDS:
        return f"transform has no kind ({kind!r})"
    for key, value in transform.items():
        if isinstance(value, float) and not math.isfinite(value):
            return f"transform {kind}: {key} is not finite"
    return None


def classify_effect(effect: Dict, tolerance_px: float) -> Tuple[bool, str]:
    """(label-aligned, sentence) for one ON effect.

    Aligned when a usable transform is recorded (the labels map onto the
    beauty through it), or when a MEASURED ``max_displacement_px`` is
    within ``tolerance_px``. An uncalibrated displacement is not evidence
    of alignment, however small it says it is."""
    name = effect["name"]
    if effect.get("transform") is not None:
        problem = transform_problem(effect["transform"])
        if problem is None:
            return True, f"{name}: transform {effect['transform']['kind']} recorded"
        return False, f"{name}: {problem}"
    shift = _number(effect.get("max_displacement_px"))
    basis = str(effect.get("displacement_basis") or "").strip().lower()
    if shift is None:
        return False, (f"{name}: on, with no transform and no measured displacement, so the "
                       f"labels cannot be shown to lie on the beauty")
    if basis != "measured":
        return False, (f"{name}: {shift:g} px of displacement is "
                       f"{basis or 'not stated as measured'}, not measured; an uncalibrated "
                       f"figure is not evidence that the labels lie on the beauty")
    if shift > tolerance_px:
        return False, f"{name}: {shift:g} px measured displacement over the {tolerance_px:g} px tolerance"
    return True, f"{name}: {shift:g} px measured displacement within {tolerance_px:g} px"


def listed(effects: Iterable[Dict], name: str) -> bool:
    """Whether ``name`` (or an equivalent spelling) is among the entries."""
    names = {e["name"] for e in effects}
    return any(n in names for n in EQUIVALENT_EFFECTS.get(name, (name,)))
