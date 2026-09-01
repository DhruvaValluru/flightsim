# Camera Phase 1 — checkpoints in plain English

One sentence per checkpoint from the Phase 1 plan, written so anyone can
understand the change. Companion to `docs/BRIEF_CAMERA_PHASE1.md` (the
technical mapping) and `docs/PROMPT_CAMERA_PHASE1.md` (the implementation
prompt).

**The whole phase in one line:** cameras go from a hardcoded view inside the
renderer to a planned, checked, and recorded part of the experiment — so
every image comes with the exact geometry needed to use it as training data.

## A — Camera specification

- Cameras are now written into the scenario file itself, with every setting
  labeled by where it came from (typed by the user, guessed, or a default).
- A scenario can list multiple cameras, and changing any camera changes the
  run's unique fingerprint so no two setups get confused.
- The review screen shows each camera and all its settings before anything
  runs.
- Old scenario files are clearly rejected with a message instead of being
  misread by the new format.
- If you don't mention a camera at all, everything works exactly like it did
  before.

## B — Camera positioning

- The camera's position for every moment of the flight is calculated ahead
  of time in plain Python, not inside the game engine.
- The five existing camera views (chase, ground, wingman, tower, cockpit)
  were rebuilt in Python to behave exactly the same.
- You can place a camera at an exact spot, including real map coordinates.
- Cameras can follow planned moves (pan, zoom, reposition) that play out the
  same on any computer at any speed.
- All of this works with no 3-D engine installed, so it runs on any laptop.
- A test reruns the math and checks the answer is identical down to the last
  digit.

## C — When photos get taken

- You can ask for a photo every few seconds, or an exact total number of
  photos.
- You can ask for photos at specific spots along the flight path.
- You can ask for photos when something happens, like a sharp turn — with a
  cooldown so one event doesn't spam images.
- If your request can't produce exactly the number you asked for, it refuses
  upfront and tells you why.
- Photo timing is based purely on the recorded flight, so it's identical
  whether or not images are actually drawn.

## D — Safety checks

- A camera that would end up inside or too close to a mountain is rejected
  before running.
- A camera placed outside the map area is rejected.
- A camera placed inside a hazard like the tornado is rejected.
- Impossible lens or resolution settings are rejected.
- Impossible photo schedules are rejected.
- The system never quietly "fixes" a value you typed — it says no and
  explains.
- All these rejections show up in the web app just like the existing ones.

## E — The data file behind the images

- Every photo comes with a record of exactly where the camera was, where it
  was pointing, and its lens settings at that instant.
- Each record includes the math needed to map any 3-D point to a pixel in
  that photo.
- Each record also includes exactly where the plane was at that moment.
- Every run records which scenario, terrain, and software version produced
  it, so any image traces back to its source.
- The file format is documented and versioned so other tools can trust it.
- Nothing in the old output files changed — only new information was added.

## F — Asking in plain English

- Words like "chase view," "50 images," or "wide lens" in a prompt now
  actually set up cameras instead of being ignored.
- The AI that reads prompts fills in camera settings under the same strict
  rules as everything else.
- If a prompt clearly wants pictures but doesn't say from where, the system
  asks one follow-up question.
- Camera understanding is scored with tests, not assumed to work.

## G — The renderer (macOS only)

- The pre-computed camera path is handed to the engine, which just plays it
  back — it never invents its own.
- If the path doesn't cover the whole run, the engine refuses instead of
  guessing.
- One scenario can render separate image sets from several cameras at once.
- The engine double-checks every frame that it used the exact camera
  position it was given, and stops loudly if not.
- The plane is projected into each image to confirm the picture matches the
  data.

## H — Proof it works

- Running the same scenario with different cameras gives identical flights
  and identical photo timing — cameras can't affect the physics.
- A separately-written piece of math confirms the recorded camera data
  really maps 3-D points to the right pixels.
- A point seen by two cameras can be traced back to its true 3-D position,
  proving the images work as training data.
- Every safety check has a test that triggers it on purpose.
- Asking for N images is tested to produce exactly N images.
- Each safeguard is deliberately switched off to confirm its test catches
  it.
- On a Mac, rendered images are checked against the recorded data.

## I — The demo

- A lightweight previewer draws the terrain and plane from each camera's
  viewpoint on any computer, no game engine needed.
- Ready-made example scenarios are included, including one designed to be
  rejected.
- One command runs all the proof checks and prints pass or fail.
- A short write-up explains what was built, how to run it, and what's not
  included.
