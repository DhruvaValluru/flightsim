"""The engine's frames pass, from the Python side: what a per-camera
consume-poses invocation must leave behind, and the by-product clip.

Camera Phase 1's brief: "a run should emit a defined number of images
rather than a clip". The render commandlet's ``-camera-index=N`` pass
consumes ONE camera's solved track from the card and captures ONLY at
that camera's scheduled instants, writing ``NNNN.png`` named by the
manifest index and ``render.json`` with the applied pose per frame.
This module is the contract's Python half, shared by the webapp's
frames flow and ``python -m flightsim.capture --render frames``:

* :func:`check_render_pass` grades what one pass wrote against the
  schedule it was handed -- render.json present, the engine's own
  ``frames_captured``/``frames_scheduled`` equal to the schedule, and
  every PNG named by index on disk. Anything short is a NAMED problem
  (``render.frames``) the caller fails the run with; a pass that
  returned but rendered fewer frames than scheduled is never presented
  as frames.
* :func:`frames_host_parity_refusal` refuses BY NAME (``render.host_parity``)
  a frames pass whose labels could not match its pixels: the engine
  flies its own FDM, and same-seed Dryden turbulence was measured and
  REFUSED for host parity (docs/VALIDITY.md), so a turbulent spec is
  never rendered as frames and graded to a failure -- Clip only keeps
  its visual-only label with the seed recorded.
* :func:`concat_playlist` / :func:`encode_scheduled_clip` make the clip
  a BY-PRODUCT of camera 0: the rendered frames shown at their scheduled
  instants (ffmpeg's concat demuxer with per-frame durations, a black
  lead-in PNG listed first for the time to the first instant), so the
  clip's clock IS the simulation clock and the page's telemetry panel
  keeps its 1:1 mapping. No frame is deleted, resampled or duplicated to
  a render fps; the argv is pinned by test and the clip's expected
  length is :func:`scheduled_clip_seconds`, recorded in provenance.
* :func:`pass_stepping` reads how far a pass stepped (``steps_taken``,
  ``stepped_s``): the commandlet stops after its last scheduled instant
  and the status lines and provenance say how much editor time a pass
  cost, per camera.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence

#: The named constraint a short or absent engine pass fails with.
RENDER_FRAMES_CONSTRAINT = "render.frames"
#: The three render choices, in the page's own words (webapp.runs
#: re-exports them). The richest option the machine supports is the
#: default everywhere the choice is offered.
RENDER_CHOICES = ("frames", "clip", "none")
RENDER_WORDS = {"frames": "Render frames and clip", "clip": "Clip only",
                "none": "Headless"}


#: The named refusal for a frames pass whose labels could not match its
#: pixels (host parity measured and refused for the spec's air).
HOST_PARITY_CONSTRAINT = "render.host_parity"


def frames_host_parity_refusal(spec, rotor_attached: bool = False
                               ) -> Optional[str]:
    """None when the engine's flight can be labelled from the manifest;
    otherwise WHY a frames pass is refused by name (render.host_parity).

    Engine parity judges the aircraft the engine DREW against the
    manifest's aircraft, the headless flight. Same-seed Dryden
    turbulence was measured and REFUSED for host parity (docs/VALIDITY.md:
    with seed 424242 the two hosts diverge from the first flown sample),
    so a turbulent spec -- the spec's own turbulence word, or a lee rotor
    the webapp attaches on a terrain scene -- would render frames whose
    labels cannot match their pixels. Those are refused HERE, before any
    editor time, never rendered and then failed by the verifier; Clip
    only stays available with its visual-only label and the seed
    recorded.
    """
    word = str(spec.turbulence.value)
    if word != "none":
        return (f"turbulence '{word}': same-seed host parity is measured and "
                f"refused for turbulence realisations (docs/VALIDITY.md), so "
                f"the aircraft the engine draws cannot be labelled from the "
                f"manifest; choose '{RENDER_WORDS['clip']}' (visual-only, "
                f"seed recorded) or turbulence none")
    if rotor_attached:
        return ("lee-rotor turbulence is attached on this terrain scene: "
                "same-seed host parity is measured and refused for "
                "turbulence realisations (docs/VALIDITY.md), so the "
                "aircraft the engine draws cannot be labelled from the "
                f"manifest; choose '{RENDER_WORDS['clip']}' (visual-only, "
                f"seed recorded) or calm air")
    return None


def render_choice_default() -> str:
    """The richest render choice this machine supports: frames where the
    engine exists (core.util.platform.ue_available), else none."""
    from core.util.platform import ue_available

    return "frames" if ue_available() else "none"


def render_command(editor, project, card, frames, *, fps: int, width: int,
                   height: int, look: Dict, fog_density: float,
                   scene: Dict, mesh, telemetry=None,
                   camera_flags=None, camera_index: Optional[int] = None
                   ) -> List[str]:
    """The render commandlet's argument list -- ONE builder for the
    webapp's flows and the CLI, so the two cannot drift.

    Gotcha 1: absolute paths, -stdout -FullStdOutLogOutput,
    -RenderOffScreen -AllowCommandletRendering. The terrain, imagery,
    mesh and telemetry arguments appear only when given. ``camera_flags``
    is the preset pass's (inline, trailing) pair from
    camera_render_flags; ``camera_index`` selects the consume-poses pass
    instead: ``-camera-index=N`` and no preset words at all.
    """
    if camera_index is not None:
        inline, trailing = [f"-camera-index={int(camera_index)}"], []
    else:
        inline, trailing = camera_flags if camera_flags else ([], [])
    command = [
        str(editor), str(project), "-run=FlightSimBridge.FlightSimRender",
        f"-scenario={card}", f"-frames={frames}",
        "-Visual", "-shot=showcase",
        *inline,
        f"-fps={fps}", f"-width={width}", f"-height={height}",
        f"-sun-elev={look['sun_elev']}", f"-sun-azim={look['sun_azim']}",
        f"-exposure-bias={look['exposure_bias']}",
        f"-fog-density={fog_density}",
        "-unattended", "-nopause", "-nosplash",
        "-stdout", "-FullStdOutLogOutput",
        "-RenderOffScreen", "-AllowCommandletRendering",
    ]
    command += list(trailing)
    if scene.get("terrain"):
        command += ["-GeorefTerrain", f"-terrain={scene['terrain']}"]
    if scene.get("imagery"):
        command += [f"-imagery={scene['imagery']}"]
    if mesh is not None and Path(mesh).is_file():
        command += [f"-mesh={mesh}"]
    if telemetry is not None:
        command += [f"-telemetry={telemetry}"]
    return command


def run_render_pass(command: Sequence[str], frames: Path, log: Path) -> bool:
    """Run one commandlet pass with its output in ``log``; True when it
    left render.json under ``frames``. A stale render.json is removed
    first so a pass that died cannot inherit the previous one's."""
    frames = Path(frames)
    frames.mkdir(parents=True, exist_ok=True)
    (frames / "render.json").unlink(missing_ok=True)
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as sink:
        subprocess.run(list(command), stdout=sink, stderr=subprocess.STDOUT,
                       stdin=subprocess.DEVNULL)
    return (frames / "render.json").is_file()
#: How long the last frame of the by-product clip is held, seconds --
#: the concat demuxer needs a duration for it and the schedule has none.
LAST_FRAME_HOLD_S = 1.0


def frame_name(index: int) -> str:
    """The PNG the engine writes for manifest frame ``index`` -- the
    basename of core.capture.manifest.frame_filename, spelled once
    here for the checks that look at a directory rather than a
    manifest."""
    return f"{index:04d}.png"


def check_render_pass(frames_dir: Path, scheduled: int) -> Optional[str]:
    """None when the pass under ``frames_dir`` delivered exactly the
    ``scheduled`` frames; otherwise the problem, in words. Reads only
    what the engine wrote: render.json's counts and the files."""
    frames_dir = Path(frames_dir)
    report = frames_dir / "render.json"
    if not report.is_file():
        return (f"the engine pass wrote no render.json under {frames_dir}; "
                f"see {frames_dir / 'render.log'}")
    try:
        render = json.loads(report.read_text(encoding="utf-8"))
    except ValueError as exc:
        return f"render.json under {frames_dir} is not JSON ({exc})"
    if not isinstance(render, dict):
        return f"render.json under {frames_dir} is not a mapping"
    captured = render.get("frames_captured")
    declared = render.get("frames_scheduled")
    if captured != scheduled or declared != scheduled:
        return (f"the engine captured {captured} of {declared} scheduled "
                f"frames against the {scheduled} the card scheduled")
    missing = [frame_name(i) for i in range(scheduled)
               if not (frames_dir / frame_name(i)).is_file()]
    if missing:
        shown = ", ".join(missing[:5])
        return (f"{len(missing)} of {scheduled} scheduled PNGs are missing "
                f"under {frames_dir} ({shown}"
                + (", ..." if len(missing) > 5 else "") + ")")
    return None


def pass_stepping(frames_dir: Path) -> Optional[Dict[str, float]]:
    """``{"steps_taken": N, "stepped_s": S}`` from a pass's render.json --
    how far the commandlet stepped the FDM (it stops after the last
    scheduled instant) -- or None when the pass did not say."""
    report = Path(frames_dir) / "render.json"
    try:
        render = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(render, dict):
        return None
    steps, seconds = render.get("steps_taken"), render.get("stepped_s")
    if not isinstance(steps, (int, float)) or \
            not isinstance(seconds, (int, float)):
        return None
    return {"steps_taken": int(steps), "stepped_s": float(seconds)}


def stepping_words(stepping: Optional[Dict[str, float]]) -> str:
    """The status-line clause for a pass's stepping, or '' when the pass
    did not record it."""
    if not stepping:
        return ""
    return (f" (engine stepped {stepping['stepped_s']:.3f} s in "
            f"{stepping['steps_taken']} steps)")


def rendered_count(frames_dir: Path) -> int:
    """PNGs actually on disk under one camera's frames directory."""
    frames_dir = Path(frames_dir)
    if not frames_dir.is_dir():
        return 0
    return sum(1 for p in frames_dir.glob("*.png") if p.is_file())


#: The black lead-in of the by-product clip: a PNG at the frames' own
#: size, listed FIRST in the playlist for the time to the first instant,
#: so clip time equals simulation time from t=0. Written beside the
#: per-camera frame directories (never inside one: a directory's PNGs are
#: its rendered frames, counted as such).
CLIP_LEAD_NAME = "clip_lead.png"


def scheduled_clip_seconds(times: Sequence[float],
                           lead_in_s: Optional[float] = None,
                           last_hold_s: float = LAST_FRAME_HOLD_S) -> float:
    """The by-product clip's expected length: the lead-in (default: the
    first instant, so clip time is simulation time), the span to the
    last instant, and the last frame's hold."""
    if not times:
        raise ValueError("no capture instants; no clip to size")
    lead = float(times[0]) if lead_in_s is None else float(lead_in_s)
    return lead + (float(times[-1]) - float(times[0])) + float(last_hold_s)


def concat_playlist(times: Sequence[float], names: Sequence[str],
                    last_hold_s: float = LAST_FRAME_HOLD_S,
                    lead_in=None) -> str:
    """The ffconcat playlist showing frame i from times[i] until
    times[i+1]. The concat demuxer applies a file's duration only when
    another entry follows it, so the last frame is listed twice: once
    with its hold, once to terminate. ``lead_in`` is an optional
    ``(name, seconds)`` entry listed first (the black lead-in)."""
    if len(times) != len(names) or not times:
        raise ValueError(f"{len(times)} instants against {len(names)} "
                         f"frames; refusing an unpaired playlist")
    lines = ["ffconcat version 1.0"]
    if lead_in is not None:
        lead_name, lead_seconds = lead_in
        if float(lead_seconds) <= 0.0:
            raise ValueError(f"a lead-in must last longer than 0 s, not "
                             f"{lead_seconds}")
        lines.append(f"file '{lead_name}'")
        lines.append(f"duration {float(lead_seconds):.6f}")
    for index, (t, name) in enumerate(zip(times, names)):
        if index + 1 < len(times):
            duration = float(times[index + 1]) - float(t)
            if duration <= 0.0:
                raise ValueError(f"capture instants must increase: "
                                 f"{t} then {times[index + 1]}")
        else:
            duration = float(last_hold_s)
        lines.append(f"file '{name}'")
        lines.append(f"duration {duration:.6f}")
    lines.append(f"file '{names[-1]}'")
    return "\n".join(lines) + "\n"


def clip_command(ffmpeg: Path, playlist: Path, clip: Path) -> List[str]:
    """The by-product clip's ffmpeg argv, spelled once and pinned by
    test: the concat demuxer over the playlist (``-safe 0`` because the
    lead-in lives one directory up), variable frame rate so every frame
    keeps its scheduled instant, H.264 at the showcase's own quality."""
    return [str(ffmpeg), "-y", "-f", "concat", "-safe", "0",
            "-i", str(playlist), "-vsync", "vfr",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19",
            "-pix_fmt", "yuv420p", str(clip)]


def encode_scheduled_clip(ffmpeg: Path, frames_dir: Path,
                          times: Sequence[float], clip: Path,
                          lead_in_s: Optional[float] = None) -> bool:
    """Encode the by-product clip from frames named by index, each
    shown at its scheduled instant. ``lead_in_s`` (default: the first
    instant) is black -- a PNG at the frames' size, written beside the
    camera directories and listed first in the playlist -- so clip time
    equals simulation time from t=0 (:func:`scheduled_clip_seconds` is
    the expected length). The PNGs are left in place: they are the
    deliverable."""
    frames_dir = Path(frames_dir)
    names = [frame_name(i) for i in range(len(times))]
    playlist = frames_dir / "clip_playlist.ffconcat"
    lead = float(times[0]) if lead_in_s is None else float(lead_in_s)
    lead_in = None
    if lead > 0.0:
        from PIL import Image

        with Image.open(frames_dir / names[0]) as first:
            size = first.size
        Image.new("RGB", size, (0, 0, 0)).save(frames_dir.parent
                                               / CLIP_LEAD_NAME)
        lead_in = (f"../{CLIP_LEAD_NAME}", lead)
    playlist.write_text(concat_playlist(times, names, lead_in=lead_in),
                        encoding="utf-8")
    command = clip_command(ffmpeg, playlist, clip)
    clip.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(command, capture_output=True)
    return proc.returncode == 0 and Path(clip).is_file()


def pass_summary(frames_dir: Path, scheduled: int) -> Dict[str, object]:
    """The counts one pass leaves: scheduled (the card's), rendered
    (PNGs on disk), and whether the pass is complete by
    :func:`check_render_pass`."""
    problem = check_render_pass(frames_dir, scheduled)
    return {"scheduled": int(scheduled),
            "rendered": rendered_count(frames_dir),
            "complete": problem is None,
            **({"problem": problem} if problem else {}),
            **(pass_stepping(frames_dir) or {})}
