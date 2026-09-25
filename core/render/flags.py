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


def render_flags(card, frames, *, scene: Optional[Mapping[str, Any]],
                 mesh, look: Optional[Mapping[str, Any]],
                 camera_flags: Optional[Tuple[Sequence[str], Sequence[str]]],
                 labels: bool = True, linear: bool = False,
                 deterministic: bool = True, void: bool = False,
                 width: int, height: int, fps: float,
                 telemetry=None, extra: Iterable[str] = ()) -> List[str]:
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
    if not void:
        flags += [f"-sun-elev={tod['sun_elev']}",
                  f"-sun-azim={tod['sun_azim']}",
                  f"-exposure-bias={tod['exposure_bias']}",
                  f"-fog-density={tod['fog_density']}"]
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
    if not void and scene.get("terrain"):
        flags += ["-GeorefTerrain", f"-terrain={scene['terrain']}"]
    if not void and scene.get("imagery"):
        flags += [f"-imagery={scene['imagery']}"]
    if mesh is not None:
        # The one line the placeholder rule hangs on: a render without
        # it draws boxes under a manifest that names the real mesh.
        flags.append(f"-mesh={mesh}")
    if telemetry is not None:
        flags.append(f"-telemetry={telemetry}")
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
