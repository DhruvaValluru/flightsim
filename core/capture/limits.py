"""What is NOT claimed, written down per frame in plain words.

Every label this pipeline writes has limits: a mask is not exact on a
plane a few pixels big, occlusion behind cloud is not measured, the fog
number is a model, and so on. They were scattered -- a ``not_claimed``
list of keywords on each object record, constants in labels.py and
verify.py, sentences in check details. This module puts them in ONE
section of every frame's data file (``limits``), each as a sentence a
person can read, with whether it APPLIES TO THIS FRAME and to which
plane, so a reader of one frame knows which of its numbers to trust.

Each entry: ``key`` (stable), ``limit`` (the sentence), ``applies``
(true / false for this frame, or "always"), ``objects`` (the planes it
applies to here) and ``why``.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional


def _span_px(box) -> Optional[float]:
    if isinstance(box, (list, tuple)) and len(box) == 4:
        return max(float(box[2]) - float(box[0]), float(box[3]) - float(box[1]))
    return None


def _range_m(entry: Dict) -> Optional[float]:
    cg = (entry.get("bbox_3d_camera") or {}).get("cg_m")
    if isinstance(cg, (list, tuple)) and len(cg) == 3:
        return math.sqrt(sum(float(c) ** 2 for c in cg))
    return None


def limits_section(manifest: Dict, record: Dict) -> Dict:
    """The frame sidecar's ``limits`` section."""
    from .labels import NOT_CLAIMED_OBJECT_PX, NOT_CLAIMED_SUBPIXEL_RANGE_M
    from .verify import DEPTH_TOL_FRACTION, DEPTH_TOL_M

    class_of = {str(o.get("id")): str(o.get("class"))
                for o in manifest.get("objects") or [] if isinstance(o, dict)}
    labels = record.get("labels") or {}
    entries = labels.get("objects")
    if not isinstance(entries, list):
        entries = [{"id": f"aircraft:{manifest.get('aircraft')}:0", **labels}]
    planes = [e for e in entries if isinstance(e, dict)
              and class_of.get(str(e.get("id")), "aircraft") == "aircraft"]

    far = [str(e["id"]) for e in planes
           if (_range_m(e) or 0.0) > NOT_CLAIMED_SUBPIXEL_RANGE_M]
    tiny = [str(e["id"]) for e in planes
            if _span_px(e.get("bbox_2d")) is not None
            and _span_px(e.get("bbox_2d")) < NOT_CLAIMED_OBJECT_PX]
    no_occlusion = [str(e["id"]) for e in planes if e.get("visible_fraction") is None]
    shape_stated = [str(e["id"]) for e in planes
                    if not isinstance(e.get("bbox_3d_camera_shape"), dict)]
    near_depth = [str(e["id"]) for e in planes if (_range_m(e) or 1e9) < 200.0]
    rendered = any(e.get("bbox_2d_tight") is not None for e in planes)
    fog_basis = None
    for e in planes:
        fog_basis = ((e.get("basis") or {}).get("atmospheric_transmittance")) or fog_basis
    fog_unmodelled = bool(fog_basis and "NOT a measurement" in fog_basis)
    headless = str(manifest.get("solve_source") or "") == "headless pre-run"

    out: List[Dict] = []

    def add(key, limit, applies, objects, why):
        out.append({"key": key, "limit": limit, "applies": applies,
                    "objects": objects, "why": why})

    add("mask_far_away",
        f"Masks and mask boxes are not pixel-exact for a plane more than "
        f"{NOT_CLAIMED_SUBPIXEL_RANGE_M:g} m from the camera.",
        bool(far), far,
        "beyond that range one pixel covers more of the airframe than the "
        "imported mesh's accuracy")
    add("tiny_object",
        f"Boxes and masks of a plane smaller than {NOT_CLAIMED_OBJECT_PX} px "
        f"across are not claimed and not checked.",
        bool(tiny), tiny,
        "a few pixels cannot pin down an edge; box_vs_mask counts these and "
        "does not grade them")
    add("not_rendered",
        "No mask, mask box, measured depth or measured occlusion exists for "
        "this frame: it was not rendered by the engine.",
        not rendered, [str(e["id"]) for e in planes] if not rendered else [],
        "only a run on the Windows Unreal host writes the ID and depth images; "
        "the boxes here are predicted from the geometry")
    add("occlusion_not_measured",
        "How much of the plane is hidden is not measured for these planes "
        "(visible_fraction is null, not 1).",
        bool(no_occlusion), no_occlusion,
        "measuring it needs the engine's ID image and the plane drawn alone")
    add("cloud_occlusion",
        "A plane behind cloud is not counted as hidden.",
        "always", [], "volumetric clouds write no id into the ID image")
    add("fog_is_a_model",
        "The fog / haze dimming (fog_transmittance) is computed from the "
        "stated visibility, never measured from pixels"
        + ("; nothing was stated for this run, so its 1.0 is a placeholder"
           if fog_unmodelled else "") + ".",
        "always", [], "Koschmieder's law along the line to the plane's CG")
    add("box_3d_is_stated_size",
        "The 3-D box is the airframe's stated length, span and height, not "
        "its exact shape.",
        bool(shape_stated), shape_stated,
        "no measured mesh box (bbox_3d_camera_shape) on the machine that ran "
        "this; with the imported model it is measured instead")
    add("truncation_by_box",
        "How much of a plane is inside the picture is the share of its "
        "projected 3-D box, not of its pixels.",
        "always", [], "fraction_inside = cut-box area / full-box area")
    add("depth_tolerance",
        f"Depth is checked to {DEPTH_TOL_FRACTION * 100:g} % + {DEPTH_TOL_M:g} m; a "
        f"depth image scaled wrong by under 2 % is not caught within 200 m.",
        bool(near_depth), near_depth,
        "inside 200 m the tolerance is wider than a 2 % scale error")
    add("aircraft_state_from_pre_run",
        "The aircraft positions in the labels come from a headless flight; a "
        "rendered run flies its own, and the difference is checked, not "
        "removed.",
        "always" if headless else False, [],
        "verify_flight_agreement measures the gap against the host's flight")
    applying = [o["key"] for o in out if o["applies"] is True]
    return {
        "about": ("What is NOT claimed. Each limit says whether it applies to "
                  "this frame (true / false / 'always') and to which planes. "
                  "A number under a limit that applies should not be trusted "
                  "beyond what the limit says."),
        "applies_here": applying,
        "limits": out,
    }
