"""One builder for the FlightSimRender commandlet's argument list.

Measured before this module existed (Phase 2 subsystem maps, webapp
known_defects[3]): thirteen separate places assembled a render command
by hand, and the two that matter for labelled data -- the CLI's
``--render`` and the web app's ``RunManager._render`` -- disagreed. The
web app passed ``-shot=showcase -fps= -width= -height=``, the harness's
noon look and ``-mesh=``; the CLI passed ``-labels`` and (since the
placeholder rule) ``-mesh=`` but no look unless the randomisation block
was on; NEITHER passed ``-deterministic``, the one flag Gate 10-R
proves the frame digests need. A commandlet flag the CLI forgot was
invisible: nothing compared the two lists.

This module is the one place the list is written. Both callers build
from :func:`render_flags`; ``tests/test_render_flags.py`` drives both
code paths over one compiled spec and asserts the flag SETS agree,
apart from the tokens the launcher itself owns.

What this module does NOT do, on purpose:

* it touches no filesystem and runs no subprocess -- ``mesh`` is a
  path the caller has already vouched for (the CLI refuses
  ``aircraft.mesh`` before any flight; the web app provisions the
  model, then checks the file), and the builder forwards it verbatim;
* it does not validate the card, the scene or the look -- the
  commandlet refuses those by name itself (a mesh/FDM mismatch, a
  cameras block without ``width_px``);
* it does not claim the size or rate flags describe the pixels of a
  CARD THAT CARRIES CAMERAS: under consume-poses the commandlet takes
  the output size from the card's own camera (``width_px``,
  ``height_px``) and the capture instants from its schedule, records
  ``applied_width_px`` per frame, and the ``-width= -height= -fps=``
  it was given are inert. They are passed for the legacy single-pass
  preset path, where they are the size, and so both callers state the
  same numbers for the same spec.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

#: The harness's default look: noon sun, clear air. The same four
#: numbers ``experiments/showcase_matrix.py`` keeps as ``TIME_OF_DAY
#: ["noon"]`` + ``VISIBILITY["clear"]`` (pinned equal by test, so the
#: two cannot drift). The web app has passed exactly these since the
#: showcase matrix; the CLI, until this builder, passed no look at all
#: when the randomisation block was off and so took the COMMANDLET's
#: own defaults (no sun override, fog 0.0025, AutoExposureBias 11.0).
#: One builder means one default; the web app's is the one pinned
#: byte-identical by test, so it stands for both.
DEFAULT_LOOK: Dict[str, float] = {
    "sun_elev": 50.0,
    "sun_azim": 180.0,
    "exposure_bias": 9.5,
    "fog_density": 0.0012,
}

#: The legacy single-pass output size and rate (``showcase_matrix.py``
#: ``WIDTH, HEIGHT, FPS``; pinned equal by test). See the module
#: docstring for what they do and do not mean on a camera-carrying card.
DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_FPS = 1280, 720, 30

#: The tokens every commandlet launch needs (NEXT.md gotcha 1: without
#: ``-stdout -FullStdOutLogOutput`` the editor stalls; without
#: ``-RenderOffScreen -AllowCommandletRendering`` every frame is blank
#: and the run reports success). They sit in the list at the position
#: the web app has always put them, because the camera-less argument
#: list is pinned byte-identical by test and the commandlet's parser
#: is order-blind. The wrapper scripts add their own copy, so
#: :func:`for_wrapper` strips them.
LAUNCHER_FLAGS: Tuple[str, ...] = (
    "-unattended", "-nopause", "-nosplash",
    "-stdout", "-FullStdOutLogOutput",
    "-RenderOffScreen", "-AllowCommandletRendering",
)

#: Prefixes of the flags ``scripts/render_ue_scenario.ps1`` writes
#: ITSELF, from its two positional arguments and its per-camera loop:
#: ``-scenario=`` / ``-frames=`` from ``<card> <frames-dir>``, and
#: ``-camera-index=N`` / ``-telemetry=<frames>/<cam>/host_telemetry.json``
#: per camera pass. A caller that goes through the wrapper must not
#: pass them a second time; :func:`for_wrapper` removes them.
WRAPPER_OWNED_PREFIXES: Tuple[str, ...] = (
    "-scenario=", "-frames=", "-camera-index=", "-telemetry=",
)

#: Bare switches the builder emits at most once, wherever they come
#: from: the web app's per-camera loop (``webapp/capture.py``) hands
#: ``-labels`` in through ``extra``, and a switch stated twice is the
#: same switch to the commandlet but a lie about who asked for it.
_SWITCHES: Tuple[str, ...] = (
    "-Visual", "-GeorefTerrain", "-labels", "-linear", "-deterministic",
)

#: The ground-truth passes the commandlet knows (I6, gap S3), in the
#: order ``-passes=`` states them: ``normal`` (frame_NNNN_normal.png),
#: ``velocity`` (frame_NNNN_flow.f32), ``albedo`` (frame_NNNN_albedo.png).
#: Each is optional; the commandlet refuses an unknown word by name
#: (labels.pass_unknown) and a missing material by name
#: (labels.pass_material). The builder emits the flag ONLY when asked,
#: so every argument list pinned before the passes existed is
#: byte-identical (tests/test_annotation_passes.py measures that).
PASS_NAMES: Tuple[str, ...] = ("normal", "velocity", "albedo")

#: S1 (gap S1/S2): three opt-in sensing flags for the commandlet (S4
#: implements them; uncompiled here). ``-calibration`` adds the
#: calibration frame (emissive grey card, Lambertian white quad under
#: the sun alone, a 5 degree slanted-edge quad; calibration.json);
#: ``-sun-lux=<lux>`` sets the directional light in physical units
#: (light_units 'physical' in look_applied); ``-accumulate=<K>`` asks for
#: K sub-exposure captures on a dedicated AA-off capture (k = 1 recorded
#: when the predicted blur is under 0.25 px). Each is emitted ONLY when
#: asked, after the passes flag, so every list pinned before them is
#: byte-identical (tests/test_render_flags.py measures that).
CALIBRATION_FLAG = "-calibration"
SUN_LUX_PREFIX = "-sun-lux="
ACCUMULATE_PREFIX = "-accumulate="

#: W5 (the world engine side): ``-scene=<scene document>`` -- the Landscape
#: scene level scripts/ue_build_scene.py built for the bake, loaded by the
#: commandlet in place of the procedural terrain and matched against the
#: card's world block (refused world.scene_stale / world.scene_missing
#: there). Emitted ONLY when asked, right after ``-imagery=`` (the ordering
#: pin in tests/test_ue_world_source.py), never on the void tier, so every
#: list pinned before it is byte-identical.
SCENE_PREFIX = "-scene="
#: The procedural terrain's triangle budget (FlightSimVisualScene.h
#: ``TerrainTriangleBudget``, 4 M by default): the host picks the
#: smallest raster stride whose triangle count fits it, so a bake finer
#: than 30 m (core/terrain/dem3dep.py, ~10 m) is decimated back to ~30 m
#: posting under the default. ``-triangle-budget=<n>`` raises it for that
#: render; emitted ONLY when asked, as the last token, so every pinned
#: list is byte-identical. What the engine does with 20 M triangles
#: (memory, the shadow cascades) is measured on Windows, not here; the
#: host records the posting it achieved (``terrain_posting_m``).
TRIANGLE_BUDGET_PREFIX = "-triangle-budget="

#: The lighting block's engine knobs (core/scene/lighting.py): look key ->
#: commandlet flag. Emitted right after ``-fog-density=``, in this order,
#: ONLY for the keys the look carries, so a look without them (every look
#: before the block existed) builds a byte-identical list. The commandlet
#: multiplies the calibrated sun and sky light by the two scales, sets the
#: sun's colour temperature and its disc's angular size (shadow softness),
#: and records each in render.json look_applied.lighting.
LIGHTING_FLAGS: Tuple[Tuple[str, str], ...] = (
    ("sun_intensity_scale", "-sun-intensity-scale="),
    ("sky_light_scale", "-sky-light-scale="),
    ("sun_temperature_k", "-sun-temperature="),
    ("sun_source_angle_deg", "-sun-source-angle="),
)


def passes_flag(passes: Iterable[str]) -> Optional[str]:
    """``-passes=a,b`` for the requested passes in :data:`PASS_NAMES`
    order, or None for none. Repeats collapse. A word the commandlet
    does not know is refused HERE (ValueError) rather than sent: the
    commandlet would refuse it too, but after building the scene."""
    wanted = {str(name).strip().lower() for name in passes if str(name).strip()}
    unknown = sorted(wanted - set(PASS_NAMES))
    if unknown:
        raise ValueError(f"unknown render pass(es) {unknown}; the passes are "
                         f"{list(PASS_NAMES)}")
    ordered = [name for name in PASS_NAMES if name in wanted]
    return f"-passes={','.join(ordered)}" if ordered else None


def sensing_flags(calibration: bool = False, sun_lux=None, accumulate=None) -> List[str]:
    """The S1 opt-in tokens in their fixed order: ``-calibration``,
    ``-sun-lux=<lux>``, ``-accumulate=<K>``; an empty list when nothing is
    asked. A sun that is not a positive finite number of lux, or an
    accumulation that is not an integer of at least 1, is refused HERE
    (ValueError) rather than sent: the commandlet would refuse it too,
    but after building the scene."""
    import math

    out: List[str] = []
    if calibration:
        out.append(CALIBRATION_FLAG)
    if sun_lux is not None:
        try:
            lux = float(sun_lux)
        except (TypeError, ValueError):
            raise ValueError(f"-sun-lux takes a number of lux, not {sun_lux!r}")
        if isinstance(sun_lux, bool) or not math.isfinite(lux) or lux <= 0.0:
            raise ValueError(f"-sun-lux takes a positive number of lux, not {sun_lux!r}")
        # repr: the shortest text that round-trips the double, so the
        # host's lux is the one the grey-card check predicts (":g" kept six
        # digits and could miss the 1e-6 comparison); a whole number keeps
        # its old spelling (95788, not 95788.0).
        text = repr(lux)
        out.append(f"{SUN_LUX_PREFIX}{text[:-2] if text.endswith('.0') else text}")
    if accumulate is not None:
        if isinstance(accumulate, bool) or int(accumulate) != accumulate or int(accumulate) < 1:
            raise ValueError(f"-accumulate takes a whole number of sub-exposures >= 1, not {accumulate!r}")
        out.append(f"{ACCUMULATE_PREFIX}{int(accumulate)}")
    return out


def lighting_flags(look: Optional[Mapping[str, Any]]) -> List[str]:
    """The :data:`LIGHTING_FLAGS` tokens for the engine keys a look
    carries, in table order; [] for None or a look without them. A value
    that is not a finite non-negative number is refused HERE (ValueError)
    rather than sent."""
    import math

    out: List[str] = []
    for key, prefix in LIGHTING_FLAGS:
        if not look or look.get(key) is None:
            continue
        value = look[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(float(value)) or float(value) < 0.0:
            raise ValueError(f"{prefix} takes a non-negative number, not {value!r}")
        out.append(f"{prefix}{float(value):g}")
    return out


def render_flags(card, frames, *, scene: Optional[Mapping[str, Any]],
                 mesh, look: Optional[Mapping[str, Any]],
                 camera_flags: Optional[Tuple[Sequence[str], Sequence[str]]],
                 labels: bool = True, linear: bool = False,
                 deterministic: bool = True, void: bool = False,
                 width: int, height: int, fps: float,
                 telemetry=None, extra: Iterable[str] = (),
                 passes: Iterable[str] = (), calibration: bool = False,
                 sun_lux=None, accumulate=None, scene_document=None,
                 quality: Optional[str] = None, sky=None,
                 triangle_budget=None) -> List[str]:
    """The ORDERED argument list for the FlightSimRender commandlet,
    after the ``<editor> <project> -run=FlightSimBridge.FlightSimRender``
    tokens.

    ``card`` / ``frames``: the run card and the frames directory
    (``-scenario=`` / ``-frames=``; stringified verbatim, so callers
    pass absolute paths -- gotcha 1).

    ``scene``: the web app's scene dict (``terrain`` = bake stem or
    path, ``imagery`` = drape sidecar) or None; the CLI passes
    ``{"terrain": <stem>}``. Terrain and imagery flags appear only when
    the scene names them, so a flat scene renders the labelled slab
    rather than failing on an empty path.

    ``mesh``: the imported model's ``mesh_manifest.json`` path, or None
    for the placeholder boxes. Forwarded verbatim; NOT checked here
    (see the module docstring). The mutation guard in
    ``scripts/mutation_check.sh`` covers this forwarding.

    ``look``: the four look numbers (``sun_elev``, ``sun_azim``,
    ``exposure_bias``, ``fog_density``) -- the sampled look, the storm
    look, or None for :data:`DEFAULT_LOOK`. A partial dict is completed
    from the default key by key (the storm look states a fog; the
    time-of-day looks do not), exactly as the web app always did.

    ``camera_flags``: ``(inline, trailing)`` from
    ``webapp.runs.camera_render_flags`` for the LEGACY preset path, or
    None. Under consume-poses (any card with a cameras block) the
    commandlet takes pose, lens and size from the card and these are
    inert; the CLI passes None.

    ``labels`` / ``linear`` / ``deterministic``: the Phase 10 opt-in
    passes. ``void``: Gate 5's black-void tier -- no ``-Visual``, no
    ``-shot``, no terrain, no imagery, no look (the void has no sun).

    ``telemetry``: the host recorder's output path (``-telemetry=``).
    ``extra``: tokens appended verbatim after the camera trailing
    flags (the web app's per-camera ``-camera-index=N -labels``); a
    switch already present there is not emitted twice.

    ``passes``: the ground-truth passes (:data:`PASS_NAMES`) to add
    beside the label bundle -- ``-passes=normal,velocity,albedo`` after
    the opt-in switches. Empty (the default) emits NOTHING, so every
    list pinned before the passes existed is unchanged; the commandlet
    refuses ``-passes`` without ``-labels`` by name
    (labels.pass_needs_labels), and this builder does not second-guess
    it. Not claimed here: that the engine writes the files -- the
    commandlet is uncompiled off Windows (source pins in
    ``tests/test_gate6_visual.py``).

    ``calibration`` / ``sun_lux`` / ``accumulate`` (S1): the sensing
    opt-ins, :func:`sensing_flags`, after the passes flag and only when
    asked -- the default list is byte-identical to the one before they
    existed. Not claimed here: that the engine honours them (S4,
    uncompiled off Windows).

    ``scene_document`` (W5): the scene document of the bake's Landscape
    scene level (``<stem>_scene.json``, scripts/ue_build_scene.py), as
    :data:`SCENE_PREFIX` right after ``-imagery=``; None (the default)
    emits nothing, and the void tier never gets it. Forwarded verbatim;
    the commandlet checks it (and refuses without ``-GeorefTerrain``).

    ``triangle_budget``: a whole number >= 1 adds
    :data:`TRIANGLE_BUDGET_PREFIX` as the LAST token (never on the void
    tier); None (the default) emits nothing, so every pinned list stands.
    webapp.runs asks for one only when the bake is finer than 30 m.

    ``quality`` (visual plan V0): ``"beauty"`` adds ``-quality=beauty``
    (Lumen GI/reflections, TSR, virtual shadow maps and 16 warm-up
    captures in the commandlet) after the sensing opt-ins; None or
    ``"measure"`` emits nothing, so every pinned list stands.

    ``sky``: a physical-sky sidecar (``sky.json``, core/sky/plan.py). It
    replaces ``-sun-elev= -sun-azim= -exposure-bias=`` with ``-sky=`` in
    the same place (the commandlet's FlightSimSky reads sun, moon, stars
    and EV100 from it); None leaves the list unchanged.

    Returns a new list every call. Behaviour byte-identical to the web
    app's pre-builder command for every flag it passed (pinned by
    ``tests/test_camera_spec.py`` and ``tests/test_render_flags.py``).
    """
    extra = [str(token) for token in extra]
    inline, trailing = camera_flags if camera_flags is not None else ((), ())
    scene = scene or {}
    tod = dict(DEFAULT_LOOK)
    if look:
        tod.update({key: look[key] for key in DEFAULT_LOOK if key in look})

    flags: List[str] = [f"-scenario={card}", f"-frames={frames}"]
    if not void:
        flags += ["-Visual", "-shot=showcase"]
    flags += [str(token) for token in inline]
    flags += [f"-fps={fps}", f"-width={width}", f"-height={height}"]
    if not void and sky is not None:
        flags += [f"-sky={sky}", f"-fog-density={tod['fog_density']}"]
    elif not void:
        flags += [f"-sun-elev={tod['sun_elev']}",
                  f"-sun-azim={tod['sun_azim']}",
                  f"-exposure-bias={tod['exposure_bias']}",
                  f"-fog-density={tod['fog_density']}"]
        flags += lighting_flags(look)
    flags += list(LAUNCHER_FLAGS)
    flags += [str(token) for token in trailing]
    flags += extra
    # The opt-in passes go right after ``extra`` so a caller that
    # states one there (the web app's loop states -labels) and a caller
    # that asks for it here (the CLI) end up with the SAME order, not
    # just the same set. A switch already in the list is not repeated.
    wanted = [("-labels", labels), ("-linear", linear),
              ("-deterministic", deterministic)]
    for switch, on in wanted:
        if on and switch not in flags:
            flags.append(switch)
    # I6: the ground-truth passes, only when asked (an empty list adds
    # no token, so the pinned lists stand byte for byte).
    pass_token = passes_flag(passes)
    if pass_token is not None and pass_token not in flags:
        flags.append(pass_token)
    # S1: the sensing opt-ins, only when asked, after the passes flag.
    for token in sensing_flags(calibration, sun_lux, accumulate):
        if token not in flags:
            flags.append(token)
    if quality not in (None, "measure"):
        token = f"-quality={quality}"
        if token not in flags:
            flags.append(token)
    if not void and scene.get("terrain"):
        flags += ["-GeorefTerrain", f"-terrain={scene['terrain']}"]
    if not void and scene.get("imagery"):
        flags += [f"-imagery={scene['imagery']}"]
    if not void and scene_document is not None:
        # W5: only when asked, after -imagery= (the default list stands).
        flags.append(f"{SCENE_PREFIX}{scene_document}")
    if mesh is not None:
        # The one line the placeholder rule hangs on: a render without
        # it draws boxes under a manifest that names the real mesh.
        flags.append(f"-mesh={mesh}")
    if telemetry is not None:
        flags.append(f"-telemetry={telemetry}")
    if triangle_budget is not None:
        if (isinstance(triangle_budget, bool) or int(triangle_budget) != triangle_budget
                or int(triangle_budget) < 1):
            raise ValueError(f"{TRIANGLE_BUDGET_PREFIX} takes a whole number of "
                             f"triangles >= 1, not {triangle_budget!r}")
        if not void:
            flags.append(f"{TRIANGLE_BUDGET_PREFIX}{int(triangle_budget)}")
    return flags


def for_wrapper(flags: Iterable[str]) -> List[str]:
    """The same flags, minus everything ``scripts/render_ue_scenario.ps1``
    adds itself: the launcher tokens and the wrapper-owned ``-scenario=
    -frames= -camera-index= -telemetry=`` (:data:`WRAPPER_OWNED_PREFIXES`).
    What is left is what the wrapper forwards to EVERY camera pass, in
    the builder's order. Not verified here: the ``.sh`` twin forwards
    nothing (it takes exactly two arguments and refuses off macOS), so
    off Windows these flags reach no engine -- the wrapper refuses
    ``ue.platform`` first."""
    kept = []
    for token in flags:
        token = str(token)
        if token in LAUNCHER_FLAGS:
            continue
        if token.startswith(WRAPPER_OWNED_PREFIXES):
            continue
        kept.append(token)
    return kept


def switches_present(flags: Iterable[str]) -> Tuple[str, ...]:
    """Which of the bare switches this module knows are in ``flags``
    (for reports and tests; the commandlet does its own parsing)."""
    present = set(str(token) for token in flags)
    return tuple(switch for switch in _SWITCHES if switch in present)
