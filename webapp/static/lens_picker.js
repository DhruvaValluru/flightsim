// The sample frame: a 3D scene of the aircraft you move the camera around.
// Drag in the frame to go round the aircraft and higher or lower, scroll
// to come closer or pull back, or type the exact position; the zoom
// slider is the lens. "Add to prompt" writes both into the prompt:
//   "camera 110 m behind, 0 m right, 12 m above the aircraft, with a 35 mm lens"
// -- the position phrase both compilers read as a user-stated chase offset
// (core/nl/compiler.py CAMERA_OFFSET_PHRASE), the lens phrase as a
// user-stated focal length ("<n> mm lens").
//
// The frame is a pinhole projection, not a picture scaled by eye: the
// camera sits at an offset in the aircraft's heading frame (forward,
// right, up metres -- the chase convention of core/scenario/camera.py,
// aimed at the aircraft) on the default 36 x 20.25 mm sensor at 16:9,
// over flat ground 500 m below. The aircraft is a simplified model at its
// published overall dimensions, so the share of the frame it fills is the
// share the render will give it from that position at that focal length.
// The small view beside the frame shows where the camera is.
//
// The constants below mirror core/scenario/camera.py and are pinned to it
// by tests/test_lens_picker.py. Drawing uses window.Flight3D
// (webapp/static/camera3d.js), which the pages load first.
(function () {
"use strict";

const DEFAULT_FOCAL_MM = 35.0;
const SENSOR_W_MM = 36.0;
const SENSOR_H_MM = 20.25;
const MIN_MM = 4;
const MAX_MM = 400;
const STOPS = [[4, "widest"], [6, ""], [10, ""], [18, "wide"], [24, ""], [35, "default"], [50, ""],
               [85, "tele"], [135, ""], [200, ""], [400, "long"]];
const CHASE_OFFSETS = {
  "B747": [-110.0, 0.0, 12.0],
  "A320": [-95.0, 0.0, 10.0],
  "c172p": [-28.0, 0.0, 4.0],
  "A4": [-42.0, 0.0, 6.0],
};
const GROUND_BELOW_M = 500;
const MIN_DIST_M = 3;
const MAX_DIST_M = 5000;

// Simplified airframes, metres (x forward, y right, z up from the
// fuselage axis at mid-length). span/length are published overall figures.
const AIRFRAMES = {
  "A320": {label: "Airbus A320", span: 35.8, length: 37.6, r: 1.98,
           wing: {x: 3.5, z: -1.2, chord: 6.1, tip: 1.6, sweep: 25, dihedral: 5},
           stab: {x: -14.5, z: 0.6, span: 12.45, chord: 3.6, tip: 1.3, sweep: 30},
           fin: {x: -12.5, top: 9.6, chord: 6.0, tip: 2.0, sweep: 35},
           engines: [{y: 5.75, z: -2.4, r: 1.1, x: 5.5, len: 4.4}]},
  "B747": {label: "Boeing 747", span: 64.4, length: 70.6, r: 3.25,
           wing: {x: 7.0, z: -2.0, chord: 14.0, tip: 4.0, sweep: 37.5, dihedral: 7},
           stab: {x: -28.0, z: 1.0, span: 22.2, chord: 7.5, tip: 2.6, sweep: 37},
           fin: {x: -24.5, top: 14.0, chord: 11.0, tip: 4.0, sweep: 45},
           engines: [{y: 12.0, z: -3.6, r: 1.4, x: 9.0, len: 6.0},
                     {y: 21.0, z: -2.6, r: 1.4, x: 4.0, len: 6.0}]},
  "c172p": {label: "Cessna 172", span: 11.0, length: 8.28, r: 0.55,
            wing: {x: 1.0, z: 0.75, chord: 1.6, tip: 1.2, sweep: 0, dihedral: 1.7},
            stab: {x: -3.4, z: 0.0, span: 3.45, chord: 1.1, tip: 0.8, sweep: 5},
            fin: {x: -3.2, top: 1.9, chord: 1.4, tip: 0.7, sweep: 35},
            engines: []},
  "A4": {label: "A-4 Skyhawk", span: 8.38, length: 12.22, r: 0.75,
         wing: {x: 0.6, z: -0.4, chord: 4.6, tip: 1.0, sweep: 33, dihedral: -2},
         stab: {x: -5.2, z: 0.4, span: 3.4, chord: 1.4, tip: 0.6, sweep: 25},
         fin: {x: -4.4, top: 2.9, chord: 2.9, tip: 0.9, sweep: 40},
         engines: []},
};

const STYLE = `
.lensPicker { margin: .6rem 0; }
.lensPicker summary { cursor: default; list-style: none; }
.lensPicker summary::-webkit-details-marker { display: none; }
.lensPicker .lpBody { margin-top: .6rem; }
.lensPicker .lpViews { display: flex; flex-wrap: wrap; gap: .6rem;
  align-items: flex-start; }
.lensPicker canvas { display: block; border-radius: 6px;
  border: 1px solid #2c3947; touch-action: none; cursor: grab; }
.lensPicker .lpCanvas { width: 100%; max-width: 640px; aspect-ratio: 16 / 9;
  flex: 1 1 420px; }
.lensPicker .lpSide { flex: 0 1 260px; min-width: 200px; }
.lensPicker .lpOutside { width: 100%; aspect-ratio: 4 / 3; }
.lensPicker .lpRow { display: flex; flex-wrap: wrap; align-items: center;
  gap: .6rem; margin: .5rem 0; max-width: 920px; }
.lensPicker input[type=range] { flex: 1 1 260px; }
.lensPicker .lpMm { font-size: 1.6rem; font-weight: 600; min-width: 6.5rem; }
.lensPicker .lpStops button, .lensPicker .lpViewsChips button {
  padding: .15rem .5rem; margin: 0 .2rem .2rem 0; font-size: .85em; }
.lensPicker .lpGrid { display: grid; grid-template-columns: 11rem 1fr 6.5rem 1.5rem;
  gap: .25rem .6rem; align-items: center; max-width: 920px; margin: .4rem 0; }
.lensPicker .lpGrid input[type=number] { width: 6rem; background: #171d24;
  color: inherit; border: 1px solid #2c3947; border-radius: 4px; font: inherit;
  padding: .1rem .3rem; }
.lensPicker .lpPhrase { font-family: "SF Mono", Menlo, monospace;
  background: #1b232d; border: 1px solid #2c3947; border-radius: 4px;
  padding: .15rem .45rem; }
.lensPicker .lpDim { color: #8b98a5; font-size: .9em; }
`;

function focalFromSlider(v) {
  return MIN_MM * Math.pow(MAX_MM / MIN_MM, v / 1000);
}
function sliderFromFocal(mm) {
  return 1000 * Math.log(mm / MIN_MM) / Math.log(MAX_MM / MIN_MM);
}
function hfovDeg(mm) {
  return 2 * Math.atan(SENSOR_W_MM / 2 / mm) * 180 / Math.PI;
}
function phraseFor(mm) {
  const n = Math.round(mm);
  // "an 8", "an 18", "an 85": the article the number is spoken with.
  const an = /^(8|11|18)$|^8\d$/.test(String(n));
  return `with ${an ? "an" : "a"} ${n} mm lens`;
}

// Put the phrase into the prompt: replace a stated "<n> mm lens", else
// append it. Exported for the pages and the test.
function applyToPrompt(text, mm) {
  const n = Math.round(mm);
  const stated = /(-?\d+(?:\.\d+)?)\s*mm\s+lens/i;
  if (stated.test(text)) return text.replace(stated, `${n} mm lens`);
  const base = text.replace(/[\s,.;]+$/, "");
  return base ? `${base}, ${phraseFor(n)}` : phraseFor(n);
}

// The exact camera position, in the words the compilers read
// (core/nl/compiler.py CAMERA_OFFSET_PHRASE). Metres to 0.1.
function metres(v) {
  const r = Math.round(Math.abs(v) * 10) / 10;
  return String(r);
}
function positionPhrase(offset) {
  const [f, r, u] = offset;
  return `camera ${metres(f)} m ${f < 0 ? "behind" : "ahead"}, ` +
         `${metres(r)} m ${r < 0 ? "left" : "right"}, ` +
         `${metres(u)} m ${u < 0 ? "below" : "above"} the aircraft`;
}
const POSITION_RE = new RegExp(
  "camera\\s+(?:at\\s+)?\\d+(?:\\.\\d+)?\\s*m\\s+(?:behind|ahead|in front)" +
  "\\s*,?\\s*\\d+(?:\\.\\d+)?\\s*m\\s+(?:to the\\s+)?(?:left|right)" +
  "\\s*,?\\s*(?:and\\s+)?\\d+(?:\\.\\d+)?\\s*m\\s+(?:above|below)" +
  "(?:\\s+the\\s+aircraft)?", "i");
// Put the position and the lens into the prompt, replacing either one
// already stated. Exported for the pages and the test.
function applyCameraToPrompt(text, offset, mm) {
  const phrase = positionPhrase(offset);
  let out;
  if (POSITION_RE.test(text)) out = text.replace(POSITION_RE, phrase);
  else {
    const base = text.replace(/[\s,.;]+$/, "");
    out = base ? `${base}, ${phrase}` : phrase;
  }
  return applyToPrompt(out, mm);
}

// -- the aircraft as triangles ----------------------------------------
// Body frame (x forward, y right, z up) -> GL (right, up, -forward), the
// frame camera3d.js draws in.
const G = p => [p[1], p[2], -p[0]];
const AIRCRAFT_COLOUR = [0.87, 0.89, 0.92];

function prism(out, bottom, top, colour) {
  // A closed solid from two matching outlines; every face normal points
  // away from the solid's centre, so the lighting is right either way
  // round the outline was given.
  const F3 = window.Flight3D;
  const all = bottom.concat(top).map(G);
  const centre = all.reduce((a, p) => F3.add(a, p), [0, 0, 0]).map(v => v / all.length);
  const quad = (a, b, c, d) => {
    let n = F3.norm(F3.cross(F3.sub(b, a), F3.sub(c, a)));
    const mid = F3.scale(F3.add(F3.add(a, b), F3.add(c, d)), 0.25);
    if (F3.dot(n, F3.sub(mid, centre)) < 0) n = F3.scale(n, -1);
    F3.pushTri(out, a, b, c, n, colour);
    F3.pushTri(out, a, c, d, n, colour);
  };
  const B = bottom.map(G), T = top.map(G), k = B.length;
  quad(B[0], B[1], B[2], B[3]);
  quad(T[0], T[1], T[2], T[3]);
  for (let i = 0; i < k; i++) quad(B[i], B[(i + 1) % k], T[(i + 1) % k], T[i]);
}

function tube(out, x0, x1, radiusAt, cy, cz, colour) {
  // A body of revolution along x, 14 sides, 24 rings.
  const F3 = window.Flight3D, sides = 14, rings = 24;
  const ring = i => {
    const x = x0 + (x1 - x0) * i / rings, r = radiusAt(x);
    return Array.from({length: sides}, (_, j) => {
      const a = 2 * Math.PI * j / sides;
      return {p: G([x, cy + r * Math.cos(a), cz + r * Math.sin(a)]),
              n: G([0, Math.cos(a), Math.sin(a)])};
    });
  };
  let prev = ring(0);
  for (let i = 1; i <= rings; i++) {
    const cur = ring(i);
    for (let j = 0; j < sides; j++) {
      const a = prev[j], b = prev[(j + 1) % sides], c = cur[(j + 1) % sides], d = cur[j];
      for (const v of [a, b, c, a, c, d]) out.push(...v.p, ...v.n, ...colour);
    }
    prev = cur;
  }
  // Close the ends so the tube reads as solid end-on.
  for (const [x, ringPts, sign] of [[x0, ring(0), -1], [x1, ring(rings), 1]]) {
    const c = G([x, cy, cz]), n = G([sign, 0, 0]);
    for (let j = 0; j < sides; j++)
      F3.pushTri(out, c, ringPts[j].p, ringPts[(j + 1) % sides].p, n, colour);
  }
}

function surfaceMesh(out, s, half, z0) {
  // A tapered, swept, dihedralled surface, both sides, with thickness.
  const t = Math.max(0.12, 0.11 * s.chord);
  const sweep = Math.tan((s.sweep || 0) * Math.PI / 180);
  const dih = Math.tan((s.dihedral || 0) * Math.PI / 180);
  for (const side of [-1, 1]) {
    const ztip = z0 + half * dih;
    const tipLE = [s.x - half * sweep, side * half, ztip];
    const outline = [[s.x, 0, z0], tipLE, [tipLE[0] - s.tip, side * half, ztip],
                     [s.x - s.chord, 0, z0]];
    prism(out, outline, outline.map(p => [p[0], p[1], p[2] + t]), AIRCRAFT_COLOUR);
  }
}

function aircraftMesh(a) {
  const out = [], L = a.length;
  tube(out, -L / 2, L / 2, x => {
    const fromTail = (x + L / 2) / (0.3 * L), fromNose = (L / 2 - x) / (0.12 * L);
    return a.r * Math.max(0.15, Math.min(1, fromTail, Math.sqrt(Math.max(0, fromNose))));
  }, 0, 0, AIRCRAFT_COLOUR);
  surfaceMesh(out, a.wing, a.span / 2, a.wing.z);
  surfaceMesh(out, a.stab, a.stab.span / 2, a.stab.z);
  const f = a.fin, sw = Math.tan(f.sweep * Math.PI / 180), ht = f.top - a.r * 0.6;
  const tw = Math.max(0.12, 0.06 * f.chord);
  const fin = y => [[f.x, y, a.r * 0.6], [f.x - ht * sw, y, f.top],
                    [f.x - ht * sw - f.tip, y, f.top], [f.x - f.chord, y, a.r * 0.6]];
  prism(out, fin(-tw), fin(tw), AIRCRAFT_COLOUR);
  for (const e of a.engines)
    for (const side of [-1, 1])
      tube(out, e.x - e.len, e.x, () => e.r, side * e.y, e.z, [0.72, 0.75, 0.79]);
  return new Float32Array(out);
}

function groundMesh() {
  // One big square 500 m below, out past the fog.
  const F3 = window.Flight3D, out = [], R = 60000, z = -GROUND_BELOW_M;
  const c = [0.40, 0.49, 0.34], n = [0, 1, 0];
  const p = (x, y) => G([x, y, z]);
  F3.pushTri(out, p(-R, -R), p(R, -R), p(R, R), n, c);
  F3.pushTri(out, p(-R, -R), p(R, R), p(-R, R), n, c);
  return new Float32Array(out);
}

function fieldLines() {
  // Field boundaries every 200 m, for a sense of scale and depth. Drawn
  // over the ground with the depth test off (View.lines overlay), so a
  // grazing view does not lose them to depth-buffer precision.
  const lines = [], z = -GROUND_BELOW_M, colour = [0.52, 0.60, 0.46];
  for (let v = -6000; v <= 6000; v += 200) {
    lines.push([G([v, -6000, z]), G([v, 6000, z]), colour]);
    lines.push([G([-6000, v, z]), G([6000, v, z]), colour]);
  }
  return lines;
}

// -- camera position: exact offsets <-> round the aircraft --------------
// around: degrees clockwise from dead astern seen from above (0 behind,
// 90 off the right wing, 180 in front, -90 off the left wing);
// height: degrees above the aircraft's level; dist: metres.
function toOffset({around, height, dist}) {
  const a = around * Math.PI / 180, h = height * Math.PI / 180;
  return [-dist * Math.cos(h) * Math.cos(a), dist * Math.cos(h) * Math.sin(a),
          dist * Math.sin(h)];
}
function fromOffset([f, r, u]) {
  const dist = Math.max(MIN_DIST_M, Math.hypot(f, r, u));
  return {dist, around: Math.atan2(r, -f) * 180 / Math.PI,
          height: Math.asin(Math.max(-1, Math.min(1, u / dist))) * 180 / Math.PI};
}
// The ground is 500 m down; a camera is kept 5 m above it.
function clampHeight(pose) {
  const lowest = Math.asin(Math.max(-1, (-(GROUND_BELOW_M - 5)) / pose.dist)) * 180 / Math.PI;
  return {...pose, height: Math.max(lowest, Math.min(89, pose.height))};
}

const VIEWS = [
  ["chase (default)", null],
  ["left side", {around: -90, height: 5}],
  ["right side", {around: 90, height: 5}],
  ["front", {around: 180, height: 3}],
  ["from above", {around: 0, height: 85}],
  ["from below", {around: 20, height: -35}],
];

function mount(holder, textarea) {
  if (!document.getElementById("lensPickerStyle")) {
    const style = document.createElement("style");
    style.id = "lensPickerStyle"; style.textContent = STYLE;
    document.head.appendChild(style);
  }
  const box = document.createElement("details");
  box.className = "lensPicker";
  const options = Object.entries(AIRFRAMES)
    .map(([id, a]) => `<option value="${id}"${id === "A320" ? " selected" : ""}>${a.label}</option>`)
    .join("");
  box.innerHTML =
    `<summary>Pick the camera from a 3D sample frame</summary>` +
    `<div class="lpBody">` +
    `<div class="lpDim">Drag in the frame to move the camera round the ` +
    `aircraft (left and right go round it, up and down go higher or lower); ` +
    `scroll to come closer or pull back; or type the exact position. The ` +
    `zoom slider is the lens's focal length: bigger is more zoomed in. The ` +
    `small view shows where the camera is. "Add to prompt" writes the ` +
    `position and the lens into the prompt, and the camera follows the ` +
    `aircraft from there.</div>` +
    `<div class="lpRow"><label>sample aircraft <select class="lpAircraft">${options}</select></label></div>` +
    `<div class="lpViews">` +
    `<canvas class="lpCanvas" role="img" aria-label="sample frame: what the camera sees"></canvas>` +
    `<div class="lpSide"><canvas class="lpOutside" role="img" ` +
    `aria-label="where the camera is"></canvas>` +
    `<div class="lpDim">where the camera is: drag to look round, scroll to zoom</div></div>` +
    `</div>` +
    `<div class="lpRow lpViewsChips"></div>` +
    `<div class="lpRow"><span class="lpMm"></span>` +
    `<input type="range" class="lpSlider" min="0" max="1000" step="1" ` +
    `aria-label="focal length"></div>` +
    `<div class="lpRow lpStops"></div>` +
    `<div class="lpGrid lpPose"></div>` +
    `<div class="lpGrid lpXyz"></div>` +
    `<div class="lpDim lpStats"></div>` +
    `<div class="lpRow">Say it in the prompt: <span class="lpPhrase"></span>` +
    `<button type="button" class="opt lpInsert">Add to prompt</button>` +
    `<button type="button" class="opt lpCopy">Copy</button>` +
    `<span class="lpDim lpNote"></span></div>` +
    `</div>`;
  // Always open: the picker is the page's way to choose a zoom, so it is
  // shown expanded and its header no longer folds it away.
  box.open = true;
  box.querySelector("summary").addEventListener("click", e => e.preventDefault());
  holder.appendChild(box);

  const $ = sel => box.querySelector(sel);
  const canvas = $(".lpCanvas"), outside = $(".lpOutside");
  const slider = $(".lpSlider"), pick = $(".lpAircraft");
  const F3 = window.Flight3D;
  let mm = DEFAULT_FOCAL_MM;
  let pose = fromOffset(CHASE_OFFSETS[pick.value]);
  let atDefault = true;
  const orbit = {yaw: 0.9, pitch: 0.45, zoom: 1};

  let frame = null, side = null;
  try {
    frame = new F3.View(canvas);
    side = new F3.View(outside);
  } catch (error) {
    $(".lpViews").textContent = "This browser cannot draw 3D (no WebGL); " +
      "the numbers and the zoom below still work.";
  }
  const meshes = {};
  function loadAircraft() {
    if (!frame) return;
    if (!meshes[pick.value]) meshes[pick.value] = aircraftMesh(AIRFRAMES[pick.value]);
    for (const v of [frame, side]) {
      v.upload("aircraft", meshes[pick.value]);
      if (!v.static.ground) v.upload("ground", groundMesh());
    }
    if (!side.static.camera) side.upload("camera", F3.cameraBodyMesh());
  }
  const lines = fieldLines();

  // -- controls ------------------------------------------------------
  for (const [stop, word] of STOPS) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "opt";
    b.textContent = word ? `${stop} ${word}` : String(stop);
    b.addEventListener("click", () => set(stop));
    $(".lpStops").appendChild(b);
  }
  for (const [label, view] of VIEWS) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "opt";
    b.textContent = label;
    b.addEventListener("click", () => {
      if (view === null) { pose = fromOffset(CHASE_OFFSETS[pick.value]); atDefault = true; }
      else {
        // Keep the distance; a standoff of at least ~1.6 spans.
        const span = AIRFRAMES[pick.value].span;
        pose = clampHeight({...view, dist: Math.max(pose.dist, span * 1.6)});
        atDefault = false;
      }
      render();
    });
    $(".lpViewsChips").appendChild(b);
  }
  const rows = {};
  function row(grid, key, label, unit, min, max, step) {
    const span = document.createElement("span");
    span.textContent = label;
    const range = document.createElement("input");
    range.type = "range"; range.min = min; range.max = max; range.step = step;
    const num = document.createElement("input");
    num.type = "number"; num.step = step;
    const u = document.createElement("span");
    u.className = "lpDim"; u.textContent = unit;
    $(grid).append(span, range, num, u);
    rows[key] = {range, num};
    range.addEventListener("input", () => setKey(key, Number(range.value), true));
    num.addEventListener("input", () => {
      if (num.value !== "" && !Number.isNaN(Number(num.value)))
        setKey(key, Number(num.value), false);
    });
  }
  // Distance is a log slider (3 m to 5 km); the number is metres.
  const distToSlider = d => 1000 * Math.log(d / MIN_DIST_M) / Math.log(MAX_DIST_M / MIN_DIST_M);
  const sliderToDist = v => MIN_DIST_M * Math.pow(MAX_DIST_M / MIN_DIST_M, v / 1000);
  row(".lpPose", "dist", "distance", "m", 0, 1000, 1);
  row(".lpPose", "around", "round the aircraft", "°", -180, 180, 1);
  row(".lpPose", "height", "height angle", "°", -89, 89, 1);
  row(".lpXyz", "x", "X  right of it", "m", -2000, 2000, 0.1);
  row(".lpXyz", "y", "Y  ahead of it (− behind)", "m", -2000, 2000, 0.1);
  row(".lpXyz", "z", "Z  above it", "m", -495, 2000, 0.1);
  rows.dist.num.min = MIN_DIST_M; rows.dist.num.max = MAX_DIST_M;

  function setKey(key, value, fromSlider) {
    atDefault = false;
    if (key === "dist") {
      // The slider is logarithmic (3 m to 5 km); the number is metres.
      pose.dist = Math.min(MAX_DIST_M, Math.max(MIN_DIST_M, fromSlider ? sliderToDist(value) : value));
      pose = clampHeight(pose);
    } else if (key === "around" || key === "height") {
      pose = clampHeight({...pose, [key]: value});
    } else {
      const off = toOffset(pose);
      const index = {y: 0, x: 1, z: 2}[key];
      off[index] = value;
      off[2] = Math.max(-(GROUND_BELOW_M - 5), off[2]);
      pose = fromOffset(off);
    }
    render(key);
  }

  function syncRows(editing) {
    const off = toOffset(pose);
    const values = {dist: pose.dist, around: pose.around, height: pose.height,
                    x: off[1], y: off[0], z: off[2]};
    for (const [key, {range, num}] of Object.entries(rows)) {
      const v = values[key];
      range.value = String(key === "dist" ? distToSlider(v) : v);
      if (key !== editing || document.activeElement !== num)
        num.value = String(Math.round(v * 10) / 10);
    }
  }

  // -- drawing ---------------------------------------------------------
  function cameraGl() { return G(toOffset(pose)); }

  function drawFrame() {
    const a = AIRFRAMES[pick.value];
    const eye = cameraGl();
    const [w, h] = frame.resize();
    const fovy = 2 * Math.atan(SENSOR_H_MM / 2 / mm);
    const upHint = Math.abs(pose.height) > 88.5 ? [0, 0, -1] : [0, 1, 0];
    // The near plane scales with the standoff: nothing is closer than a
    // few percent of it, and a far-off near plane keeps depth precise.
    const vp = F3.mul(F3.perspective(fovy, w / h, Math.max(0.3, pose.dist * 0.02), 120000),
                      F3.lookAt(eye, [0, 0, 0], upHint));
    frame.begin(vp, eye, 40000);
    frame.draw("ground", null, 1);
    frame.lines(lines, true);
    frame.draw("aircraft", null, 1);
    // Rule-of-thirds guides, faint, on a 2D layer would need a second
    // canvas; the stats line says what the guides would.
    const l = F3.project(vp, G([0, -a.span / 2, a.wing.z]), w, h);
    const r = F3.project(vp, G([0, a.span / 2, a.wing.z]), w, h);
    return l && r ? Math.abs(r[0] - l[0]) / w : null;
  }

  function drawOutside() {
    const a = AIRFRAMES[pick.value];
    const cam = cameraGl();
    const reach = Math.max(pose.dist, a.span);
    const target = F3.scale(cam, 0.5);
    const dist = Math.max(a.span * 2.2, reach * 1.8) * orbit.zoom;
    const eye = F3.add(target, F3.scale([Math.cos(orbit.pitch) * Math.sin(orbit.yaw),
      Math.sin(orbit.pitch), Math.cos(orbit.pitch) * Math.cos(orbit.yaw)], dist));
    const [w, h] = side.resize();
    const vp = F3.mul(F3.perspective(45 * Math.PI / 180, w / h, Math.max(0.3, dist / 50), 150000),
                      F3.lookAt(eye, target, [0, 1, 0]));
    side.begin(vp, eye, 60000);
    side.draw("ground", null, 1);
    side.lines(lines, true);
    // The aircraft grows when the camera is far, so it can be found.
    const grow = Math.max(1, dist / (a.span * 6));
    side.draw("aircraft", F3.modelMatrix([0, 0, 0], 0, grow), 1);
    // The camera: a body pointed at the aircraft, its frustum, a sight line.
    const look = F3.norm(F3.scale(cam, -1));
    let right = F3.cross(look, [0, 1, 0]);
    if (Math.hypot(...right) < 1e-6) right = [1, 0, 0];
    right = F3.norm(right);
    const up = F3.cross(right, look), back = F3.scale(look, -1);
    const s = Math.max(1.5, dist / 45);
    side.draw("camera", new Float32Array([right[0] * s, right[1] * s, right[2] * s, 0,
      up[0] * s, up[1] * s, up[2] * s, 0, back[0] * s, back[1] * s, back[2] * s, 0,
      cam[0], cam[1], cam[2], 1]), 1);
    const th = Math.tan(Math.atan(SENSOR_W_MM / 2 / mm)), tv = Math.tan(Math.atan(SENSOR_H_MM / 2 / mm));
    const d = pose.dist, cyan = [0.25, 0.85, 0.95];
    const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([x, y]) =>
      F3.add(cam, F3.scale(F3.add(look, F3.add(F3.scale(right, x * th), F3.scale(up, y * tv))), d)));
    const segs = [];
    for (let i = 0; i < 4; i++) {
      segs.push([cam, corners[i], cyan]);
      segs.push([corners[i], corners[(i + 1) % 4], cyan]);
    }
    segs.push([cam, [cam[0], -GROUND_BELOW_M, cam[2]], [0.6, 0.85, 0.95]]);
    side.lines(segs);
  }

  let pending = false;
  function render(editing) {
    const shown = Math.round(mm);
    const off = toOffset(pose);
    $(".lpMm").textContent = `${shown} mm`;
    $(".lpPhrase").textContent = `${positionPhrase(off)}, ${phraseFor(shown)}`;
    slider.value = String(Math.round(sliderFromFocal(mm)));
    syncRows(editing);
    const zoom = shown / DEFAULT_FOCAL_MM;
    const where = `the camera is ${Math.round(pose.dist)} m from the aircraft`;
    const lens = `horizontal field of view ${hfovDeg(shown).toFixed(1)}°; ` +
      (shown === DEFAULT_FOCAL_MM ? `the default lens`
        : zoom > 1 ? `${zoom.toFixed(1)}x the default ${DEFAULT_FOCAL_MM} mm (zoomed in)`
        : `${(1 / zoom).toFixed(1)}x wider than the default ${DEFAULT_FOCAL_MM} mm`);
    if (!frame) { $(".lpStats").textContent = `${lens}; ${where}.`; return; }
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      loadAircraft();
      const fill = drawFrame();
      drawOutside();
      let span = "";
      if (fill !== null) {
        span = fill > 1 ? "; the wingtips are cut off at the frame edges"
                        : `; the wingspan fills ${Math.round(fill * 100)}% of the frame width`;
      }
      $(".lpStats").textContent = `${lens}; ${where}${span}.`;
    });
  }
  function set(value) {
    mm = Math.min(MAX_MM, Math.max(MIN_MM, value));
    $(".lpNote").textContent = "";
    render();
  }

  slider.addEventListener("input", () => set(focalFromSlider(Number(slider.value))));
  pick.addEventListener("change", () => {
    if (atDefault) pose = fromOffset(CHASE_OFFSETS[pick.value]);
    render();
  });
  window.addEventListener("resize", () => render());

  // Drag in the frame: go round the aircraft and up or down; scroll:
  // closer or further.
  function dragOn(el, onMove) {
    let last = null;
    el.addEventListener("pointerdown", e => {
      last = [e.clientX, e.clientY];
      el.setPointerCapture(e.pointerId);
      el.style.cursor = "grabbing";
    });
    el.addEventListener("pointermove", e => {
      if (!last) return;
      const dx = e.clientX - last[0], dy = e.clientY - last[1];
      last = [e.clientX, e.clientY];
      onMove(dx, dy);
    });
    const end = () => { last = null; el.style.cursor = "grab"; };
    el.addEventListener("pointerup", end);
    el.addEventListener("pointercancel", end);
  }
  dragOn(canvas, (dx, dy) => {
    atDefault = false;
    let around = pose.around - dx * 0.4;
    around = ((around + 540) % 360) - 180;
    pose = clampHeight({...pose, around, height: pose.height + dy * 0.3});
    render();
  });
  canvas.addEventListener("wheel", e => {
    e.preventDefault();
    atDefault = false;
    pose = clampHeight({...pose, dist: Math.min(MAX_DIST_M, Math.max(MIN_DIST_M,
      pose.dist * Math.exp(e.deltaY * 0.0012)))});
    render();
  }, {passive: false});
  dragOn(outside, (dx, dy) => {
    orbit.yaw -= dx * 0.008;
    orbit.pitch = Math.max(0.05, Math.min(1.5, orbit.pitch + dy * 0.008));
    render();
  });
  outside.addEventListener("wheel", e => {
    e.preventDefault();
    orbit.zoom = Math.min(6, Math.max(0.25, orbit.zoom * Math.exp(e.deltaY * 0.0012)));
    render();
  }, {passive: false});

  $(".lpInsert").addEventListener("click", () => {
    if (!textarea) return;
    textarea.value = applyCameraToPrompt(textarea.value, toOffset(pose), mm);
    textarea.dispatchEvent(new Event("input", {bubbles: true}));
    $(".lpNote").textContent = "added to the prompt";
  });
  $(".lpCopy").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(`${positionPhrase(toOffset(pose))}, ${phraseFor(mm)}`);
      $(".lpNote").textContent = "copied";
    } catch (error) {
      $(".lpNote").textContent = "select the phrase and copy it by hand";
    }
  });
  render();
  return {set, get: () => mm, offset: () => toOffset(pose)};
}

window.LensPicker = {mount, applyToPrompt, applyCameraToPrompt, positionPhrase,
                     phraseFor, hfovDeg,
                     DEFAULT_FOCAL_MM, SENSOR_W_MM, SENSOR_H_MM, MIN_MM, MAX_MM,
                     CHASE_OFFSETS};
})();
