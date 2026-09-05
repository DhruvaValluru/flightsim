# The bar: what the best version of each Camera Phase 1 checkpoint looks like

This is the standard the improvement loop judges against. Not
"reasonable", not "meets the brief": the best version a demanding
instructor could imagine, the one that makes the capability obvious in
thirty seconds and checkable in five minutes. Each section states the
best version, then the tell-tale signs that a build is short of it.

The rules that never bend, whatever the bar: `prompt → spec → validate →
run`; the only writer of physical state is `fdm.step()`; nothing a host
cannot honour exactly is approximated silently, it refuses by name; every
number is measured, never assumed; no existing test or guard is weakened;
every new safeguard gets a mutation guard verified to fail when disabled;
C++ is additive and cannot be compiled in the cloud session, so every
engine change ships with the exact verification the user runs on the
Windows machine, and is never described as verified until it was.

## 1. The run emits frames, not a clip (brief headline; packages G + H)

**Best version.** A run with cameras produces, on a machine with the
engine, exactly the scheduled number of rendered PNGs per camera in
`capture/frames/<camera_id>/NNNN.png`, each named by its manifest index,
each taken at the scheduled simulation instant to within one fixed step,
each placed from the solved pose track with the applied pose written
back per frame. The verifier proves it: applied pose equals solved pose
within 10 cm and 0.1 deg, the applied time equals the scheduled time,
and the aircraft reprojects into every rendered frame within a pixel
tolerance the test states. Two runs of the same spec with different
camera sets give identical spec and telemetry digests, identical counts
and identical frame times, on rendered frames. The clip is a by-product
of camera 0, never the deliverable. When the engine is absent, the run
says so by name and produces the previews and manifest, and nothing on
the page pretends otherwise.

**Short of it:** a clip plus schematic previews; frame counts that come
from the render fps; "captured N frames" when nothing was rendered; an
engine pass that exists in C++ but is never invoked; parity that warns
instead of failing.

## 2. The Windows render choice (user request)

**Best version.** The run form carries an explicit choice, visible before
the run starts: **Render frames and clip** (engine), **Clip only**
(today's behaviour), **Headless** (manifest, previews, verification; no
engine). The default is the richest option the machine supports, and
the control says why an option is unavailable ("no engine on this
machine: set UE_ROOT"). The choice is recorded in the run's provenance
and the status lines name what was produced. The CLI has the same
switch (`--render frames|clip|none`) with the same words.

**Short of it:** a hidden default; a choice the page offers that the
backend ignores; a run that silently degrades from frames to a clip.

## 3. The geometry preview (package I)

**Best version.** A picture a person can read at a glance and an
engineer can check against the manifest. The terrain is a projected
wireframe of the raster with depth shading and a horizon; flat scenes
get a ground grid with distance rings and a north arrow. The aircraft is
a scaled three-axis body (span and length from the FDM's own metrics)
with a heading tick and its flown track; the camera's look direction and
field of view are marked; a header states camera id, frame index,
simulation time, position, look direction and focal length. Full output
resolution by default. When a rendered frame exists, a second image
overlays the reprojected aircraft box and the projected terrain
wireframe on the rendered PNG, so the verification is visible to the
eye. A per-camera contact sheet ties the set together.

**Short of it:** dots on black; a circle for the aircraft; half scale;
no horizon; nothing that says what the viewer is looking at.

## 4. The run page (package I, the web interface)

**Best version.** After a run the page shows, per camera, the rendered
frames as a gallery (previews only as a clearly labelled fallback),
the count contract ("8 scheduled, 8 rendered, 8 verified"), the
verifier's checks with their numbers, the closure report, and one
download per artefact class: frames zip, manifest, telemetry, clip. The
review table shows every camera field with its source. Refusals name
their constraint and the offending value. The page never shows a
number it cannot back with a file the user can open.

**Short of it:** eight thumbnails of previews labelled "frames"; a
status line that counts previews as captures; a file list without
notes; a refusal without its constraint name.

## 5. The commands and their output (package I)

**Best version.** `python -m flightsim.capture` and `flightsim.verify`
print a report a person wants to read: a header with the spec digest,
scene and cameras; a per-camera table of scheduled instants; a
verification table with each check, its measured value, its tolerance
and PASS/FAIL; a final line that states the verdict and where the
artefacts are. Exit codes mean something. `--json` gives the same as
data. The examples in `examples/` run in under a minute each and their
expected output is in the document, verbatim.

**Short of it:** a wall of JSBSim banners; a summary that says "ok"
with no numbers; examples whose expected output is a promise.

## 6. Verification that cannot be fooled (package H)

**Best version.** Alignment, geometry recovery and cross-view
consistency are each a test the instructor can run and watch fail on
purpose (`--corrupt manifest` or a mutation guard). Cross-view
consistency is exercised by a committed two-camera example, not
reported "not exercised". Engine parity is a real check on rendered
frames on the Windows machine, with its expected numbers written down.

## 7. Documentation (package I)

**Best version.** `docs/CAMERA_PHASE1_REPORT.md` says what runs on
which platform today, with the Windows engine verification written up
from an actual run log, the expected output of every command, and a
Known Limitations list that is true. NEXT.md and README point at it.

## Scoring

Each section is scored 0 to 10 against its best version. 10 means a
demanding instructor finds nothing to ask for. Below 8 is not done.
Anything that cannot be verified in the cloud session (engine builds,
rendered frames) is scored on the code and the written verification
steps, and is flagged "awaiting Windows verification", never counted as
verified.
