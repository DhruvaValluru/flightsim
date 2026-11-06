# FlightSim: the short guide

## 1. What this is

FlightSim is a flight simulator that films an aircraft over real terrain and
labels every picture with boxes around the aircraft and its payload. You pick a
place, press one button, and get a short clip, the frames, and a dataset you
can train on.

## 2. What to open

Double-click `Launch FlightSim.cmd`. A window opens and works through seven
steps in order: install, preflight, build, materials, aircraft, bake, server.
When the last step is done the window prints `READY` and your browser opens on
the app by itself.

The first launch takes a while, because it builds the engine and prepares the
two places. A second launch is quick: the steps already done say `up to date`.

If the launch stops, the last line in the window names the step and the
reason, for example which tool is missing. The same lines are kept in
`logs/launch.log`, so you can read them later or send them to someone.

## 3. Once, the first time

Open Settings (the gear). It has six items, in this order:

1. **Google tiles key or Cesium ion token.** The ground in every picture is
   drawn from Google's 3D tiles; there is nothing to switch off. A new install
   can usually draw them with the token the engine came with, so try a run
   first, even if Settings says there is one thing to fix. If the tiles cannot
   be drawn, the run stops and names the key: paste either one here, once, and
   it is kept in `settings.json`.
2. **Cesium status.** Read-only, taken from the installed tools.
3. **Engine.** Read-only, the engine the launcher built.
4. **Render quality.** Measure for plain, accurate pictures; beauty for the
   cinematic look.
5. **LLM key.** Optional. Without it, a built-in reader turns your prompt into
   a run.
6. **Extra passes.** Three checkboxes: Normals, Flow, Amodal. Leave them off
   unless you want those extra images in the dataset.

Nothing else is needed. Everything else sits under Advanced, and the defaults
are the ones the project ships with.

## 4. What to choose

Pick an **Environment**: Desert is the Grand Canyon, Forest is Yosemite. Both
were prepared by the launcher, so the first run over either is ready to go.
Beside it, the **Aircraft** picker lists every aircraft you can film, with the
Cessna 172P already chosen.

Press **Capture**. With nothing typed, the run is:

- the Cessna 172P at 3,500 m and 100 kt;
- over the Desert;
- a chase camera;
- a six-second clip;
- labels on;
- Google tiles as the ground, with the storm weather effects ready: rain and
  storms appear when a prompt asks for them, and calm air is recorded as none.

To change any of that, type a prompt first (an aircraft, a place, a camera, a
time of day) and press **Interpret**; then press Capture. If the prompt leaves
something out, the app asks one question and waits for your answer.

## 5. What to expect

The status line on the run page moves from queued to flying to rendering to
done. A first run over a place that has not been prepared yet takes a few
minutes longer, once, while the terrain is baked; after that it is quick.

When it finishes, the clip and the frames appear on the page with their boxes
drawn on. Below them, the checks are listed by name, each marked PASS or FAIL.
A FAIL does not throw the run away; it tells you which check to read. NOT RUN
means the check had nothing to measure in this run, such as an extra pass you
did not ask for; it is not a failure.

## 6. What the output contains

Press **Download the dataset** to get `dataset.zip`. Choose the format first
if you want one other than COCO: KITTI, WebDataset, YOLO and VOC are also
offered. Inside the zip:

- the images, one set per camera;
- the labels: on every frame where it is visible, one box for the aircraft,
  one for its landing gear and one for each payload store it carries, plus
  the terrain;
- the per-camera manifest with the flight data (position, attitude, speed) for
  every frame;
- the verification report, the same checks you saw on the page, including the
  ones that confirm every aircraft and payload box was found;
- the dataset card, which says in plain words what was flown, where, in what
  weather, with which camera, and what was checked.

The card is the thing to read first when you come back to a dataset later.

## 7. When something is refused

FlightSim refuses clearly rather than make something up. Every refusal is one
sentence that names what to change:

- a missing key: open Settings and paste it;
- a place that has no terrain yet: wait for the bake to finish, then press
  Capture again;
- a check that failed: its name is on the run page, next to what it measured;
- a scenario that cannot be flown (an aircraft too heavy, a speed it cannot
  reach): the sentence names the rule, and you change the prompt.

No terminal is needed for any of it. If the sentence is not enough,
`logs/launch.log` and the run page hold the whole story. Developers who want
the command-line path will find it in the [README](../README.md).
