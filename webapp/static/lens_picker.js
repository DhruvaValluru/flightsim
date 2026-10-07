// The lens picker: drag a slider (or the sample frame itself) until the
// aircraft is framed the way you want, read off the focal length, and put
// "with a <n> mm lens" into the prompt -- the phrase both compilers already
// take as a user-stated focal length (core/nl/compiler.py, "<n> mm lens").
//
// The sample frame is a pinhole projection, not a picture scaled by eye:
// the documented default chase camera (core/scenario/camera.py
// CHASE_OFFSETS, aimed at the aircraft) on the default 36 x 20.25 mm
// sensor at 16:9, over flat ground 500 m below. The aircraft is a
// simplified silhouette at its published overall dimensions, so the share
// of the frame its wingspan fills is the share the render will give it at
// that focal length from the chase view. Other views sit at other
// distances; the number still means the same lens there.
//
// The constants below mirror core/scenario/camera.py and are pinned to it
// by tests/test_lens_picker.py.
(function () {
"use strict";

const DEFAULT_FOCAL_MM = 35.0;
const SENSOR_W_MM = 36.0;
const SENSOR_H_MM = 20.25;
const MIN_MM = 12;
const MAX_MM = 400;
const STOPS = [[18, "wide"], [24, ""], [35, "default"], [50, ""],
               [85, "tele"], [135, ""], [200, ""], [400, "long"]];
const CHASE_OFFSETS = {
  "B747": [-110.0, 0.0, 12.0],
  "A320": [-95.0, 0.0, 10.0],
  "c172p": [-28.0, 0.0, 4.0],
  "A4": [-42.0, 0.0, 6.0],
};
const GROUND_BELOW_M = 500;

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
.lensPicker summary { cursor: pointer; }
.lensPicker .lpBody { margin-top: .6rem; }
.lensPicker canvas { width: 100%; max-width: 640px; aspect-ratio: 16 / 9;
  display: block; border-radius: 6px; border: 1px solid #2c3947;
  cursor: ew-resize; touch-action: none; }
.lensPicker .lpRow { display: flex; flex-wrap: wrap; align-items: center;
  gap: .6rem; margin: .5rem 0; max-width: 640px; }
.lensPicker input[type=range] { flex: 1 1 260px; }
.lensPicker .lpMm { font-size: 1.6rem; font-weight: 600; min-width: 6.5rem; }
.lensPicker .lpStops button { padding: .15rem .5rem; margin: 0 .2rem .2rem 0;
  font-size: .85em; }
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

// A pinhole camera at the chase offset, aimed at the aircraft origin.
function makeCamera(offset, mm, w) {
  const [ox, , oz] = offset;
  const pitch = Math.atan2(oz, -ox);           // looking down by this much
  const fwd = [Math.cos(pitch), 0, -Math.sin(pitch)];
  const up = [Math.sin(pitch), 0, Math.cos(pitch)];
  const k = mm / SENSOR_W_MM * w;              // pixels per unit tangent
  return {pitch, k, project(p, h) {
    const r = [p[0] - ox, p[1], p[2] - oz];
    const depth = r[0] * fwd[0] + r[2] * fwd[2];
    if (depth <= 0.5) return null;
    return [w / 2 + k * r[1] / depth,
            h / 2 - k * (r[0] * up[0] + r[2] * up[2]) / depth, depth];
  }};
}

function fillPoly(ctx, cam, h, pts) {
  const q = pts.map(p => cam.project(p, h));
  if (q.some(p => p === null)) return;
  ctx.beginPath();
  q.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]));
  ctx.closePath(); ctx.fill(); ctx.stroke();
}

function fillDisc(ctx, cam, h, centre, r) {
  const c = cam.project(centre, h);
  if (!c) return;
  ctx.beginPath();
  ctx.arc(c[0], c[1], Math.max(0.4, cam.k * r / c[2]), 0, 2 * Math.PI);
  ctx.fill();
}

// A tapered, swept, dihedralled surface (wing or stabiliser), both sides,
// with a little thickness so it does not vanish edge-on.
function surface(ctx, cam, h, s, half, z0) {
  const t = Math.max(0.12, 0.11 * s.chord);
  const sweep = Math.tan((s.sweep || 0) * Math.PI / 180);
  const dih = Math.tan((s.dihedral || 0) * Math.PI / 180);
  for (const side of [-1, 1]) {
    const ztip = z0 + half * dih;
    const rootLE = [s.x, 0, z0], rootTE = [s.x - s.chord, 0, z0];
    const tipLE = [s.x - half * sweep, side * half, ztip];
    const tipTE = [tipLE[0] - s.tip, side * half, ztip];
    for (const dz of [0, t]) {
      const lift = p => [p[0], p[1], p[2] + dz];
      fillPoly(ctx, cam, h, [rootLE, tipLE, tipTE, rootTE].map(lift));
    }
    fillPoly(ctx, cam, h, [rootTE, tipTE, [tipTE[0], tipTE[1], ztip + t],
                           [rootTE[0], 0, z0 + t]]);
  }
}

function drawAircraft(ctx, cam, h, a) {
  ctx.fillStyle = "#dfe5ea";
  ctx.strokeStyle = "#dfe5ea";
  ctx.lineWidth = 0.6;
  // Fuselage: cross-sections along the length, tapered at nose and tail.
  const L = a.length, n = 40;
  for (let i = 0; i <= n; i++) {
    const x = -L / 2 + L * i / n;
    const fromTail = (x + L / 2) / (0.3 * L), fromNose = (L / 2 - x) / (0.12 * L);
    const r = a.r * Math.max(0.15, Math.min(1, fromTail, Math.sqrt(Math.max(0, fromNose))));
    fillDisc(ctx, cam, h, [x, 0, 0], r);
  }
  surface(ctx, cam, h, a.wing, a.span / 2, a.wing.z);
  surface(ctx, cam, h, a.stab, a.stab.span / 2, a.stab.z);
  // Fin: a thin swept slab on the centreline.
  const f = a.fin, sw = Math.tan(f.sweep * Math.PI / 180), ht = f.top - a.r * 0.6;
  const tw = Math.max(0.12, 0.06 * f.chord);
  for (const y of [-tw, tw]) {
    fillPoly(ctx, cam, h, [[f.x, y, a.r * 0.6], [f.x - ht * sw, y, f.top],
                           [f.x - ht * sw - f.tip, y, f.top], [f.x - f.chord, y, a.r * 0.6]]);
  }
  fillPoly(ctx, cam, h, [[f.x - f.chord, -tw, a.r * 0.6], [f.x - ht * sw - f.tip, -tw, f.top],
                         [f.x - ht * sw - f.tip, tw, f.top], [f.x - f.chord, tw, a.r * 0.6]]);
  for (const e of a.engines) {
    for (const side of [-1, 1]) {
      for (let i = 0; i <= 8; i++) {
        fillDisc(ctx, cam, h, [e.x - e.len * i / 8, side * e.y, e.z], e.r);
      }
    }
  }
}

function drawScene(canvas, aircraft, mm) {
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 640;
  const w = Math.round(cssW * dpr), h = Math.round(w * SENSOR_H_MM / SENSOR_W_MM);
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  const ctx = canvas.getContext("2d");
  const a = AIRFRAMES[aircraft];
  const cam = makeCamera(CHASE_OFFSETS[aircraft], mm, w);
  const horizon = h / 2 - cam.k * Math.tan(cam.pitch);

  const sky = ctx.createLinearGradient(0, 0, 0, Math.max(1, horizon));
  sky.addColorStop(0, "#3d6f9e"); sky.addColorStop(1, "#a9c4dc");
  ctx.fillStyle = sky; ctx.fillRect(0, 0, w, Math.max(0, horizon));
  const ground = ctx.createLinearGradient(0, Math.max(0, horizon), 0, h);
  ground.addColorStop(0, "#8c9a86"); ground.addColorStop(1, "#4f6340");
  ctx.fillStyle = ground; ctx.fillRect(0, Math.max(0, horizon), w, h);

  // Field lines on the ground, 200 m apart, for a sense of scale and depth.
  ctx.strokeStyle = "rgba(255,255,255,0.13)"; ctx.lineWidth = dpr;
  const z = -GROUND_BELOW_M;
  for (let y = -6000; y <= 6000; y += 200) {
    ctx.beginPath(); let on = false;
    for (let x = 0; x <= 40; x++) {
      const p = cam.project([-200 + 30 * Math.pow(1.22, x), y, z], h);
      if (!p) { on = false; continue; }
      on ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]); on = true;
    }
    ctx.stroke();
  }
  for (let x = 0; x <= 8000; x += 200) {
    const p = cam.project([x, -8000, z], h), q = cam.project([x, 8000, z], h);
    if (!p || !q) continue;
    ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke();
  }

  drawAircraft(ctx, cam, h, a);

  // Rule-of-thirds guides, faint.
  ctx.strokeStyle = "rgba(255,255,255,0.12)"; ctx.lineWidth = dpr;
  for (const fx of [1 / 3, 2 / 3]) {
    ctx.beginPath(); ctx.moveTo(w * fx, 0); ctx.lineTo(w * fx, h); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, h * fx); ctx.lineTo(w, h * fx); ctx.stroke();
  }
  const l = cam.project([0, -a.span / 2, a.wing.z], h);
  const r = cam.project([0, a.span / 2, a.wing.z], h);
  return l && r ? Math.abs(r[0] - l[0]) / w : null;
}

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
    `<summary>Pick a zoom from a sample frame</summary>` +
    `<div class="lpBody">` +
    `<div class="lpDim">Drag the slider, or drag across the frame, until the ` +
    `aircraft looks right. The number is the lens's focal length: bigger is ` +
    `more zoomed in. The frame is the default chase view (the camera behind ` +
    `and above the aircraft), drawn to scale; other views are further away, ` +
    `so the aircraft will look smaller there at the same number.</div>` +
    `<div class="lpRow"><label>sample aircraft <select class="lpAircraft">${options}</select></label></div>` +
    `<canvas class="lpCanvas" role="img" aria-label="sample frame"></canvas>` +
    `<div class="lpRow"><span class="lpMm"></span>` +
    `<input type="range" class="lpSlider" min="0" max="1000" step="1" ` +
    `aria-label="focal length"></div>` +
    `<div class="lpRow lpStops"></div>` +
    `<div class="lpDim lpStats"></div>` +
    `<div class="lpRow">Say it in the prompt: <span class="lpPhrase"></span>` +
    `<button type="button" class="opt lpInsert">Add to prompt</button>` +
    `<button type="button" class="opt lpCopy">Copy</button>` +
    `<span class="lpDim lpNote"></span></div>` +
    `</div>`;
  holder.appendChild(box);

  const $ = sel => box.querySelector(sel);
  const canvas = $(".lpCanvas"), slider = $(".lpSlider"), pick = $(".lpAircraft");
  let mm = DEFAULT_FOCAL_MM;

  for (const [stop, word] of STOPS) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "opt";
    b.textContent = word ? `${stop} ${word}` : String(stop);
    b.addEventListener("click", () => set(stop));
    $(".lpStops").appendChild(b);
  }

  function render() {
    const shown = Math.round(mm);
    $(".lpMm").textContent = `${shown} mm`;
    $(".lpPhrase").textContent = phraseFor(shown);
    slider.value = String(Math.round(sliderFromFocal(mm)));
    if (!box.open) return;
    const fill = drawScene(canvas, pick.value, mm);
    const zoom = shown / DEFAULT_FOCAL_MM;
    let span = "";
    if (fill !== null) {
      span = fill > 1 ? "; the wingtips are cut off at the frame edges"
                      : `; the wingspan fills ${Math.round(fill * 100)}% of the frame width`;
    }
    $(".lpStats").textContent =
      `horizontal field of view ${hfovDeg(shown).toFixed(1)}°; ` +
      (shown === DEFAULT_FOCAL_MM ? `the default lens`
        : zoom > 1 ? `${zoom.toFixed(1)}x the default ${DEFAULT_FOCAL_MM} mm (zoomed in)`
        : `${(1 / zoom).toFixed(1)}x wider than the default ${DEFAULT_FOCAL_MM} mm`) +
      `${span}.`;
  }
  function set(value) {
    mm = Math.min(MAX_MM, Math.max(MIN_MM, value));
    $(".lpNote").textContent = "";
    render();
  }

  slider.addEventListener("input", () => set(focalFromSlider(Number(slider.value))));
  pick.addEventListener("change", render);
  box.addEventListener("toggle", render);
  window.addEventListener("resize", () => box.open && render());

  // Drag across the frame: right zooms in, left zooms out.
  let dragX = null, dragFrom = 0;
  canvas.addEventListener("pointerdown", e => {
    dragX = e.clientX; dragFrom = sliderFromFocal(mm);
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", e => {
    if (dragX === null) return;
    const per = 1000 / Math.max(200, canvas.clientWidth);
    set(focalFromSlider(Math.min(1000, Math.max(0, dragFrom + (e.clientX - dragX) * per))));
  });
  const endDrag = () => { dragX = null; };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);

  $(".lpInsert").addEventListener("click", () => {
    if (!textarea) return;
    textarea.value = applyToPrompt(textarea.value, mm);
    textarea.dispatchEvent(new Event("input", {bubbles: true}));
    $(".lpNote").textContent = "added to the prompt";
  });
  $(".lpCopy").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(phraseFor(mm));
      $(".lpNote").textContent = "copied";
    } catch (error) {
      $(".lpNote").textContent = "select the phrase and copy it by hand";
    }
  });
  render();
  return {set, get: () => mm};
}

window.LensPicker = {mount, applyToPrompt, phraseFor, hfovDeg,
                     DEFAULT_FOCAL_MM, SENSOR_W_MM, SENSOR_H_MM, MIN_MM, MAX_MM,
                     CHASE_OFFSETS};
})();
