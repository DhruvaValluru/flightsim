"use strict";
// The 3D camera placer: the scene the spec will fly over, as terrain you
// can orbit, with the camera's x / y / z and aim as numbers you move.
//
// Frames and conventions are the pose solver's (core/capture/poses.py),
// so what this view shows is what the capture stage will solve:
//   * x = EAST metres, y = NORTH metres about the spec origin, z =
//     altitude metres MSL. The aircraft starts at (0, 0, spec altitude).
//   * "Fixed in the world" is an `explicit` camera in scene metres, aimed
//     at the aircraft (exactly, every frame) or along a fixed bearing /
//     elevation.
//   * "Rides with the aircraft" is a `chase` camera at a stated forward /
//     right / up offset in the HEADING-ONLY frame (pitch and roll
//     discarded). The render lags it by the director's 0.45 s spring;
//     this view shows where it settles.
//   * Yaw is degrees true from north toward east; pitch positive up.
// The aircraft's path here is its start pose carried straight along its
// heading -- a framing guide, not the flown track (JSBSim flies that).
//
// WebGL draws in x = east, y = up, z = -north, with y relative to the
// lowest terrain sample to keep float32 positions small.
//
// Public surface: CameraPlacer.open({container, getSpec, onPlaced,
// edit}) where edit = {index, camera} reopens an existing camera.

window.CameraPlacer = (function () {
  const VS = `
attribute vec3 aPos; attribute vec3 aNormal; attribute vec3 aColor;
uniform mat4 uViewProj; uniform mat4 uModel; uniform vec3 uEye;
uniform float uLit;
varying vec3 vColor; varying float vDist;
void main() {
  vec4 world = uModel * vec4(aPos, 1.0);
  gl_Position = uViewProj * world;
  vec3 n = normalize((uModel * vec4(aNormal, 0.0)).xyz);
  float lambert = max(dot(n, normalize(vec3(-0.45, 0.8, 0.35))), 0.0);
  vColor = aColor * mix(1.0, 0.38 + 0.72 * lambert, uLit);
  vDist = length(world.xyz - uEye);
}`;
  const FS = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
varying vec3 vColor; varying float vDist;
uniform vec3 uFog; uniform float uFogDist;
void main() {
  float f = clamp(vDist / uFogDist, 0.0, 1.0);
  gl_FragColor = vec4(mix(vColor, uFog, f * f * 0.8), 1.0);
}`;

  //: Overall lengths, metres, so the aircraft is drawn at its true size
  //: in the camera's view (the framing question is "how big will it
  //: be"). Unknown airframes draw at 15 m.
  const AIRFRAME_LENGTH_M = {B747: 70.7, A320: 37.6, c172p: 8.28, A4: 12.2};
  const SKY = [0.55, 0.68, 0.80];
  const DEG = Math.PI / 180;

  // -- small linear algebra (column-major mat4, like GL) ---------------
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  const scale = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1],
                           a[2] * b[0] - a[0] * b[2],
                           a[0] * b[1] - a[1] * b[0]];
  const norm = a => { const l = Math.hypot(a[0], a[1], a[2]) || 1;
                      return [a[0] / l, a[1] / l, a[2] / l]; };

  function perspective(fovy, aspect, near, far) {
    const f = 1 / Math.tan(fovy / 2);
    return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0,
      0, 0, (far + near) / (near - far), -1,
      0, 0, 2 * far * near / (near - far), 0]);
  }
  function lookAt(eye, target, upHint) {
    const z = norm(sub(eye, target));
    let x = cross(upHint, z);
    if (Math.hypot(x[0], x[1], x[2]) < 1e-6) x = [1, 0, 0];
    x = norm(x);
    const y = cross(z, x);
    return new Float32Array([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0,
      x[2], y[2], z[2], 0, -dot(x, eye), -dot(y, eye), -dot(z, eye), 1]);
  }
  function mul(a, b) {
    const o = new Float32Array(16);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
      let s = 0;
      for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
      o[c * 4 + r] = s;
    }
    return o;
  }
  const IDENTITY = new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
  function modelMatrix(t, headingDeg, s) {
    // Translate * rotate about up by -heading * uniform scale; the mesh
    // is built nose to -z (north) and right wing to +x (east).
    const th = -headingDeg * DEG, c = Math.cos(th), si = Math.sin(th);
    return new Float32Array([c * s, 0, -si * s, 0, 0, s, 0, 0,
      si * s, 0, c * s, 0, t[0], t[1], t[2], 1]);
  }
  function project(m, p, w, h) {
    const x = m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12];
    const y = m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13];
    const ww = m[3] * p[0] + m[7] * p[1] + m[11] * p[2] + m[15];
    if (ww <= 1e-6) return null;
    return [(x / ww + 1) / 2 * w, (1 - y / ww) / 2 * h];
  }

  // -- geometry --------------------------------------------------------
  function pushTri(out, a, b, c, n, col) {
    for (const p of [a, b, c]) out.push(p[0], p[1], p[2], n[0], n[1], n[2],
                                        col[0], col[1], col[2]);
  }
  function box(out, f0, f1, r0, r1, u0, u1, col) {
    // Body frame (forward, right, up) -> mesh (right, up, -forward).
    const P = (f, r, u) => [r, u, -f];
    const v = [P(f0, r0, u0), P(f1, r0, u0), P(f1, r1, u0), P(f0, r1, u0),
               P(f0, r0, u1), P(f1, r0, u1), P(f1, r1, u1), P(f0, r1, u1)];
    const faces = [[0, 1, 2, 3], [4, 7, 6, 5], [0, 4, 5, 1],
                   [1, 5, 6, 2], [2, 6, 7, 3], [3, 7, 4, 0]];
    for (const [a, b, c, d] of faces) {
      const n = norm(cross(sub(v[b], v[a]), sub(v[c], v[a])));
      pushTri(out, v[a], v[b], v[c], n, col);
      pushTri(out, v[a], v[c], v[d], n, col);
    }
  }
  function airframeMesh(colour) {
    // A unit-length aircraft: fuselage, wing, tailplane, fin.
    const out = [];
    box(out, -0.5, 0.5, -0.05, 0.05, -0.05, 0.05, colour);
    box(out, -0.08, 0.10, -0.46, 0.46, -0.01, 0.01, colour);
    box(out, -0.50, -0.38, -0.17, 0.17, 0.0, 0.015, colour);
    box(out, -0.50, -0.36, -0.008, 0.008, 0.04, 0.22, colour);
    return new Float32Array(out);
  }
  function cameraBodyMesh() {
    const out = [];
    box(out, -0.6, 0.3, -0.3, 0.3, -0.35, 0.35, [0.25, 0.85, 0.95]);
    box(out, 0.3, 0.7, -0.18, 0.18, -0.18, 0.18, [0.15, 0.5, 0.6]);
    return new Float32Array(out);
  }

  function rampColour(t) {
    const stops = [[0, [0.29, 0.41, 0.23]], [0.4, [0.43, 0.46, 0.30]],
                   [0.7, [0.50, 0.45, 0.39]], [0.88, [0.62, 0.60, 0.58]],
                   [1, [0.93, 0.94, 0.96]]];
    for (let i = 1; i < stops.length; i++) {
      if (t <= stops[i][0]) {
        const [t0, c0] = stops[i - 1], [t1, c1] = stops[i];
        const f = (t - t0) / ((t1 - t0) || 1);
        return [0, 1, 2].map(k => c0[k] + (c1[k] - c0[k]) * f);
      }
    }
    return stops[stops.length - 1][1];
  }

  class Terrain {
    // The server's grid: row = north index from the south edge, col =
    // east index from the west edge.
    constructor(data) {
      let g = data.grid;
      if (g.points < 3) {
        // Flat scene: resample the datum so the 1 km cells show scale.
        const pts = 65, step = g.step_m * (g.points - 1) / (pts - 1);
        g = {points: pts, step_m: step, south_m: g.south_m,
             west_m: g.west_m, heights_m: new Array(pts * pts).fill(data.datum_m)};
      }
      this.g = g;
      this.P = g.points;
      this.lo = Math.min(...g.heights_m);
      this.hi = Math.max(...g.heights_m);
      this.base = this.lo;
    }
    h(r, c) {
      r = Math.max(0, Math.min(this.P - 1, r));
      c = Math.max(0, Math.min(this.P - 1, c));
      return this.g.heights_m[r * this.P + c];
    }
    contains(north, east) {
      const span = this.g.step_m * (this.P - 1);
      return north >= this.g.south_m && north <= this.g.south_m + span &&
             east >= this.g.west_m && east <= this.g.west_m + span;
    }
    elevation(north, east) {
      const r = (north - this.g.south_m) / this.g.step_m;
      const c = (east - this.g.west_m) / this.g.step_m;
      const rc = Math.max(0, Math.min(this.P - 1, r));
      const cc = Math.max(0, Math.min(this.P - 1, c));
      const r0 = Math.floor(rc), c0 = Math.floor(cc);
      const fr = rc - r0, fc = cc - c0;
      const top = this.h(r0, c0) * (1 - fc) + this.h(r0, c0 + 1) * fc;
      const bot = this.h(r0 + 1, c0) * (1 - fc) + this.h(r0 + 1, c0 + 1) * fc;
      return top * (1 - fr) + bot * fr;
    }
    gl(north, east, alt) { return [east, alt - this.base, -north]; }
    fromGl(p) { return {north: -p[2], east: p[0], alt: p[1] + this.base}; }
    mesh() {
      const {P, g} = this, out = [];
      const span = (this.hi - this.lo) || 1;
      const snowy = this.hi - this.lo > 600;
      const vtx = (r, c) => this.gl(g.south_m + r * g.step_m,
                                    g.west_m + c * g.step_m, this.h(r, c));
      const normal = (r, c) => {
        const de = (this.h(r, c + 1) - this.h(r, c - 1)) / (2 * g.step_m);
        const dn = (this.h(r + 1, c) - this.h(r - 1, c)) / (2 * g.step_m);
        return norm([-de, 1, dn]);
      };
      for (let r = 0; r < P - 1; r++) {
        for (let c = 0; c < P - 1; c++) {
          const n = g.south_m + (r + 0.5) * g.step_m;
          const e = g.west_m + (c + 0.5) * g.step_m;
          const mean = (this.h(r, c) + this.h(r + 1, c) + this.h(r, c + 1) +
                        this.h(r + 1, c + 1)) / 4;
          let t = (mean - this.lo) / span;
          if (!snowy) t *= 0.6;
          const tint = (Math.floor(n / 1000) + Math.floor(e / 1000)) & 1 ? 0.92 : 1.0;
          const col = rampColour(t).map(v => v * tint);
          const quad = [[r, c], [r, c + 1], [r + 1, c + 1], [r + 1, c]];
          for (const k of [0, 1, 2, 0, 2, 3]) {
            const [rr, cc] = quad[k], p = vtx(rr, cc), nn = normal(rr, cc);
            out.push(p[0], p[1], p[2], nn[0], nn[1], nn[2], col[0], col[1], col[2]);
          }
        }
      }
      return new Float32Array(out);
    }
  }

  // -- one WebGL view ----------------------------------------------------
  class View {
    constructor(canvas) {
      this.canvas = canvas;
      const gl = canvas.getContext("webgl", {antialias: true});
      if (!gl) throw new Error("this browser has no WebGL");
      this.gl = gl;
      const shader = (type, src) => {
        const s = gl.createShader(type);
        gl.shaderSource(s, src);
        gl.compileShader(s);
        if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
          throw new Error(gl.getShaderInfoLog(s));
        return s;
      };
      const prog = gl.createProgram();
      gl.attachShader(prog, shader(gl.VERTEX_SHADER, VS));
      gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, FS));
      gl.linkProgram(prog);
      gl.useProgram(prog);
      this.prog = prog;
      this.loc = {};
      for (const a of ["aPos", "aNormal", "aColor"])
        this.loc[a] = gl.getAttribLocation(prog, a);
      for (const u of ["uViewProj", "uModel", "uEye", "uLit", "uFog", "uFogDist"])
        this.loc[u] = gl.getUniformLocation(prog, u);
      gl.enable(gl.DEPTH_TEST);
      this.static = {};
      this.dynamic = gl.createBuffer();
    }
    upload(name, data) {
      const gl = this.gl, buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      this.static[name] = {buf, count: data.length / 9};
    }
    resize() {
      const dpr = window.devicePixelRatio || 1;
      const w = Math.round(this.canvas.clientWidth * dpr);
      const h = Math.round(this.canvas.clientHeight * dpr);
      if (this.canvas.width !== w || this.canvas.height !== h) {
        this.canvas.width = w;
        this.canvas.height = h;
      }
      return [w, h];
    }
    begin(viewProj, eye, fogDist) {
      const gl = this.gl;
      const [w, h] = this.resize();
      gl.viewport(0, 0, w, h);
      gl.clearColor(SKY[0], SKY[1], SKY[2], 1);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.uniformMatrix4fv(this.loc.uViewProj, false, viewProj);
      gl.uniform3fv(this.loc.uEye, eye);
      gl.uniform3fv(this.loc.uFog, SKY);
      gl.uniform1f(this.loc.uFogDist, fogDist);
    }
    bind(buf) {
      const gl = this.gl;
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      const stride = 36;
      gl.enableVertexAttribArray(this.loc.aPos);
      gl.vertexAttribPointer(this.loc.aPos, 3, gl.FLOAT, false, stride, 0);
      if (this.loc.aNormal >= 0) {
        gl.enableVertexAttribArray(this.loc.aNormal);
        gl.vertexAttribPointer(this.loc.aNormal, 3, gl.FLOAT, false, stride, 12);
      }
      gl.enableVertexAttribArray(this.loc.aColor);
      gl.vertexAttribPointer(this.loc.aColor, 3, gl.FLOAT, false, stride, 24);
    }
    draw(name, model, lit) {
      const item = this.static[name], gl = this.gl;
      this.bind(item.buf);
      gl.uniformMatrix4fv(this.loc.uModel, false, model || IDENTITY);
      gl.uniform1f(this.loc.uLit, lit === undefined ? 1 : lit);
      gl.drawArrays(gl.TRIANGLES, 0, item.count);
    }
    lines(segments) {
      // segments: [[p0, p1, colour], ...] in GL coordinates.
      if (!segments.length) return;
      const gl = this.gl, data = [];
      for (const [a, b, col] of segments)
        for (const p of [a, b]) data.push(p[0], p[1], p[2], 0, 1, 0, col[0], col[1], col[2]);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.dynamic);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.DYNAMIC_DRAW);
      this.bind(this.dynamic);
      gl.uniformMatrix4fv(this.loc.uModel, false, IDENTITY);
      gl.uniform1f(this.loc.uLit, 0);
      gl.drawArrays(gl.LINES, 0, segments.length * 2);
    }
  }

  // -- the placer --------------------------------------------------------
  const FIELDS = {
    world: [
      ["east", "X  east", "m", 1],
      ["north", "Y  north", "m", 1],
      ["alt", "Z  altitude MSL", "m", 1],
    ],
    follow: [
      ["forward", "forward of the aircraft", "m", 1],
      ["right", "right of the aircraft", "m", 1],
      ["up", "above the aircraft", "m", 1],
    ],
    aim: [
      ["bearing", "yaw (bearing, true)", "deg", 0.1],
      ["elevation", "pitch (up +)", "deg", 0.1],
    ],
    lens: [["focal", "focal length", "mm", 0.5]],
  };

  const fmt = (v, d = 1) => Number(v).toLocaleString(undefined,
    {minimumFractionDigits: d, maximumFractionDigits: d});

  class Placer {
    constructor(opts, data) {
      this.opts = opts;
      this.data = data;
      this.terrain = new Terrain(data);
      this.ac = data.aircraft;
      this.lengthM = AIRFRAME_LENGTH_M[this.ac.aircraft] || 15;
      this.lens = data.lens;
      this.edit = opts.edit || null;
      this.st = this.initialState();
      // The scene view starts behind the aircraft and a little to its
      // right, looking down on it (eye offset = (sin yaw, ., cos yaw)).
      this.orbit = {target: this.aircraftGl(0), yaw: (25 - this.ac.heading_deg) * DEG,
                    pitch: 0.42, dist: Math.max(1200, this.lengthM * 40)};
      this.build();
    }

    // -- state --------------------------------------------------------
    initialState() {
      const st = {mode: "world", aim: "aircraft", east: 0, north: 0, alt: 0,
                  forward: 0, right: 0, up: 0, bearing: 0, elevation: 0,
                  focal: this.lens.focal_length_mm, t: 0};
      const cam = this.edit && this.edit.camera;
      if (cam) {
        const v = {};
        for (const f of cam.fields) v[f.name] = f.value;
        st.focal = +v.focal_length_mm || st.focal;
        if (v.position_mode === "offset") {
          st.mode = "follow";
          st.forward = +v.offset_forward_m;
          st.right = +v.offset_right_m;
          st.up = +v.offset_up_m;
        } else {
          st.mode = "world";
          st.east = +v.position_east_m;
          st.north = +v.position_north_m;
          st.alt = +v.position_alt_m;
          st.aim = v.aim_mode === "bearing" ? "bearing" : "aircraft";
          st.bearing = +v.aim_bearing_deg;
          st.elevation = +v.aim_elevation_deg;
        }
        return st;
      }
      // A new camera starts 250 m behind and 60 m above the start, to the
      // left, looking at the aircraft: a framed shot to move from.
      const back = Math.max(250, this.lengthM * 6);
      const p = this.offsetToWorld(-back, -back * 0.35, back * 0.25, 0);
      st.east = Math.round(p.east);
      st.north = Math.round(p.north);
      st.alt = Math.round(p.alt);
      return st;
    }
    aircraftAt(t) {
      // {north, east, alt}, linear along the server's straight-line
      // estimate and held at its ends.
      const tr = this.data.track;
      const at = p => ({north: p.north_m, east: p.east_m, alt: p.alt_m});
      if (!tr.length) return {north: 0, east: 0, alt: this.ac.alt_m};
      if (t <= tr[0].t_s) return at(tr[0]);
      for (let i = 1; i < tr.length; i++) {
        if (t <= tr[i].t_s) {
          const a = tr[i - 1], b = tr[i];
          const f = (t - a.t_s) / ((b.t_s - a.t_s) || 1);
          return {north: a.north_m + (b.north_m - a.north_m) * f,
                  east: a.east_m + (b.east_m - a.east_m) * f,
                  alt: a.alt_m + (b.alt_m - a.alt_m) * f};
        }
      }
      return at(tr[tr.length - 1]);
    }
    aircraftGl(t) {
      const a = this.aircraftAt(t);
      return this.terrain.gl(a.north, a.east, a.alt);
    }
    offsetToWorld(forward, right, up, t) {
      // The pose solver's _heading_only rotation.
      const h = this.ac.heading_deg * DEG, a = this.aircraftAt(t);
      return {north: a.north + forward * Math.cos(h) - right * Math.sin(h),
              east: a.east + forward * Math.sin(h) + right * Math.cos(h),
              alt: a.alt + up};
    }
    worldToOffset(p, t) {
      const h = this.ac.heading_deg * DEG, a = this.aircraftAt(t);
      const dn = p.north - a.north, de = p.east - a.east;
      return {forward: dn * Math.cos(h) + de * Math.sin(h),
              right: -dn * Math.sin(h) + de * Math.cos(h),
              up: p.alt - a.alt};
    }
    cameraWorld(t) {
      const s = this.st;
      return s.mode === "world" ? {north: s.north, east: s.east, alt: s.alt}
                                : this.offsetToWorld(s.forward, s.right, s.up, t);
    }
    setCameraWorld(p) {
      const s = this.st;
      if (s.mode === "world") {
        s.north = p.north; s.east = p.east; s.alt = p.alt;
      } else {
        const o = this.worldToOffset(p, s.t);
        s.forward = o.forward; s.right = o.right; s.up = o.up;
      }
    }
    lookDir(t) {
      // Unit look vector in GL space, and yaw / pitch in degrees.
      const s = this.st, w = this.cameraWorld(t);
      const cam = this.terrain.gl(w.north, w.east, w.alt);
      let dir;
      if (s.mode === "world" && s.aim === "bearing") {
        const y = s.bearing * DEG, p = s.elevation * DEG;
        dir = [Math.cos(p) * Math.sin(y), Math.sin(p), -Math.cos(p) * Math.cos(y)];
      } else {
        dir = sub(this.aircraftGl(t), cam);
        if (Math.hypot(...dir) < 1e-6) {
          const h = this.ac.heading_deg * DEG;
          dir = [Math.sin(h), 0, -Math.cos(h)];
        }
      }
      dir = norm(dir);
      const yaw = ((Math.atan2(dir[0], -dir[2]) / DEG) + 360) % 360;
      const pitch = Math.asin(Math.max(-1, Math.min(1, dir[1]))) / DEG;
      return {cam, dir, yaw, pitch};
    }
    fovDeg() {
      const f = this.st.focal;
      return {h: 2 * Math.atan(this.lens.sensor_width_mm / (2 * f)) / DEG,
              v: 2 * Math.atan(this.lens.sensor_height_mm / (2 * f)) / DEG};
    }

    // -- DOM ----------------------------------------------------------
    build() {
      const root = this.opts.container;
      root.innerHTML = "";
      root.className = "card";
      const scene = this.data.scene || {};
      root.innerHTML = `
<style>
  .c3d-views { display: flex; gap: .8rem; flex-wrap: wrap; }
  .c3d-pane { flex: 1 1 420px; min-width: 300px; }
  .c3d-stack { position: relative; }
  .c3d-pane canvas { width: 100%; display: block; border-radius: 6px;
                     border: 1px solid #2c3947; }
  .c3d-pane canvas.gl { aspect-ratio: 16 / 9; }
  .c3d-pane canvas.ov { position: absolute; left: 0; top: 0;
                        pointer-events: none; border-color: transparent; }
  .c3d-pane .cap { font-size: 12px; color: #7d8a93; margin: .2rem 0 .3rem; }
  #c3dOverview { cursor: grab; touch-action: none; }
  .c3d-grid { display: grid; grid-template-columns: 13rem 1fr 7.5rem 2.5rem;
              gap: .25rem .6rem; align-items: center; margin: .5rem 0; }
  .c3d-grid input[type=range] { width: 100%; }
  .c3d-grid input[type=number] { width: 7rem; background: #171d24;
              color: inherit; border: 1px solid #2c3947; border-radius: 4px;
              font: inherit; padding: .1rem .3rem; }
  .c3d-read { background: #101820; border: 1px solid #2b6c9a;
              border-radius: 6px; padding: .45rem .7rem; margin: .5rem 0;
              white-space: pre-wrap; }
  .c3d-warn { color: #e07a6f; }
</style>
<div><b>3D camera placer</b>
  <span class="dim">— ${esc(scene.label || this.data.kind)}</span></div>
<div class="dim" style="margin:.3rem 0">Drag the scene to orbit,
  right-drag (or ctrl-drag) to pan, scroll to zoom. Drag the cyan camera
  to move it across; shift-drag it to raise or lower it. Double-click the
  ground to put the camera there. X is east, Y is north, Z is altitude
  above sea level; the aircraft starts at X 0, Y 0.</div>
<div class="c3d-views">
  <div class="c3d-pane"><div class="cap">scene</div>
    <div class="c3d-stack"><canvas class="gl" id="c3dOverview" tabindex="0"></canvas>
    <canvas class="ov" id="c3dOverviewLabels"></canvas></div></div>
  <div class="c3d-pane"><div class="cap">what the camera sees</div>
    <div class="c3d-stack"><canvas class="gl" id="c3dCamera"></canvas>
    <canvas class="ov" id="c3dCameraLabels"></canvas></div></div>
</div>
<div style="margin:.5rem 0">
  <button class="opt" id="c3dModeWorld">Fixed in the world</button>
  <button class="opt" id="c3dModeFollow">Rides with the aircraft</button>
  <span id="c3dAimRow">&nbsp; aim:
    <button class="opt" id="c3dAimAircraft">track the aircraft</button>
    <button class="opt" id="c3dAimBearing">fixed direction</button></span>
</div>
<div class="c3d-grid" id="c3dFields"></div>
<div class="c3d-grid">
  <span>time along the clip</span>
  <input type="range" id="c3dTime" min="0" max="${this.data.clip_seconds}" step="0.1" value="0">
  <span id="c3dTimeText">0.0 s</span>
  <button class="opt" id="c3dPlay" title="play the clip">&#9654;</button>
</div>
<div class="c3d-read" id="c3dRead"></div>
<div>
  <button id="c3dPlace">${this.edit ? `Update camera[${this.edit.index}]` : "Add this camera"}</button>
  <button class="opt" id="c3dFromView" title="Put the camera where the scene view's eye is, looking the same way">Camera = scene view</button>
  <button class="opt" id="c3dClose">Close</button>
  <span id="c3dState" class="dim"></span>
</div>`;
      const $ = id => root.querySelector("#" + id);
      this.$ = $;
      this.overview = new View($("c3dOverview"));
      this.camView = new View($("c3dCamera"));
      const terrainMesh = this.terrain.mesh();
      const plane = airframeMesh([0.95, 0.62, 0.20]);
      const traffic = airframeMesh([0.85, 0.30, 0.85]);
      const body = cameraBodyMesh();
      for (const v of [this.overview, this.camView]) {
        v.upload("terrain", terrainMesh);
        v.upload("aircraft", plane);
        v.upload("traffic", traffic);
      }
      this.overview.upload("camera", body);

      $("c3dModeWorld").onclick = () => this.setMode("world");
      $("c3dModeFollow").onclick = () => this.setMode("follow");
      $("c3dAimAircraft").onclick = () => { this.st.aim = "aircraft"; this.refresh(); };
      $("c3dAimBearing").onclick = () => {
        const look = this.lookDir(this.st.t);
        this.st.bearing = +look.yaw.toFixed(1);
        this.st.elevation = +look.pitch.toFixed(1);
        this.st.aim = "bearing";
        this.refresh();
      };
      $("c3dTime").oninput = e => { this.st.t = +e.target.value; this.refresh(false); };
      $("c3dPlay").onclick = () => this.play();
      $("c3dPlace").onclick = () => this.place();
      $("c3dClose").onclick = () => this.close();
      $("c3dFromView").onclick = () => this.fromView();
      this.bindMouse($("c3dOverview"));
      this.onResize = () => this.frame();
      window.addEventListener("resize", this.onResize);
      this.refresh();
    }

    ranges() {
      const g = this.terrain.g, span = g.step_m * (this.terrain.P - 1);
      const reach = Math.max(2000, this.lengthM * 60);
      return {
        east: [g.west_m, g.west_m + span],
        north: [g.south_m, g.south_m + span],
        alt: [Math.floor(this.terrain.lo - 50),
              Math.ceil(Math.max(this.terrain.hi, this.ac.alt_m) + 3000)],
        forward: [-reach, reach], right: [-reach, reach], up: [-reach / 2, reach],
        bearing: [0, 360], elevation: [-90, 90], focal: [8, 400],
      };
    }

    renderFields() {
      const s = this.st, holder = this.$("c3dFields"), r = this.ranges();
      const rows = [...FIELDS[s.mode]];
      if (s.mode === "world" && s.aim === "bearing") rows.push(...FIELDS.aim);
      rows.push(...FIELDS.lens);
      holder.innerHTML = "";
      for (const [key, label, unit, step] of rows) {
        const [lo, hi] = r[key];
        const span = document.createElement("span");
        span.textContent = label;
        const slider = document.createElement("input");
        slider.type = "range";
        slider.min = lo; slider.max = hi; slider.step = step;
        slider.value = s[key];
        const num = document.createElement("input");
        num.type = "number";
        num.step = step;
        num.value = +(+s[key]).toFixed(step < 1 ? 1 : 0);
        const u = document.createElement("span");
        u.className = "dim";
        u.textContent = unit;
        slider.oninput = () => { s[key] = +slider.value; num.value = slider.value; this.refresh(false); };
        num.oninput = () => {
          if (num.value === "" || Number.isNaN(+num.value)) return;
          s[key] = +num.value; slider.value = num.value; this.refresh(false);
        };
        holder.append(span, slider, num, u);
        this.inputs[key] = [slider, num];
      }
    }

    syncInputs() {
      for (const [key, [slider, num]] of Object.entries(this.inputs)) {
        if (document.activeElement === num) continue;
        const step = +num.step;
        slider.value = this.st[key];
        num.value = +(+this.st[key]).toFixed(step < 1 ? 1 : 0);
      }
    }

    refresh(rebuild = true) {
      const s = this.st, $ = this.$;
      if (rebuild) { this.inputs = {}; this.renderFields(); } else this.syncInputs();
      $("c3dModeWorld").classList.toggle("selected", s.mode === "world");
      $("c3dModeFollow").classList.toggle("selected", s.mode === "follow");
      $("c3dAimRow").style.display = s.mode === "world" ? "" : "none";
      $("c3dAimAircraft").classList.toggle("selected", s.aim === "aircraft");
      $("c3dAimBearing").classList.toggle("selected", s.aim === "bearing");
      $("c3dTime").value = s.t;
      $("c3dTimeText").textContent = `${fmt(s.t)} s`;
      this.readout();
      this.frame();
    }

    setMode(mode) {
      if (mode === this.st.mode) return;
      // Keep the camera where it is; only how it is anchored changes.
      const p = this.cameraWorld(this.st.t);
      this.st.mode = mode;
      if (mode === "world") this.st.aim = "aircraft";
      this.setCameraWorld(p);
      this.round();
      this.refresh();
    }

    round() {
      for (const k of ["east", "north", "alt", "forward", "right", "up"])
        this.st[k] = Math.round(this.st[k] * 10) / 10;
    }

    readout() {
      const s = this.st, p = this.cameraWorld(s.t), look = this.lookDir(s.t);
      const ground = this.terrain.elevation(p.north, p.east);
      const agl = p.alt - ground;
      const inside = this.terrain.contains(p.north, p.east);
      const a = this.aircraftAt(s.t);
      const range = Math.hypot(p.north - a.north, p.east - a.east, p.alt - a.alt);
      const fov = this.fovDeg();
      const lines = [
        `camera  X ${fmt(p.east)} m east   Y ${fmt(p.north)} m north   Z ${fmt(p.alt)} m MSL`,
        `        ${fmt(agl)} m above the ground (${fmt(ground)} m MSL under it)` +
          (s.mode === "follow"
            ? `\n        ${fmt(s.forward)} m forward, ${fmt(s.right)} m right, ${fmt(s.up)} m up of the aircraft`
            : ""),
        `looking yaw ${fmt(look.yaw)}°  pitch ${fmt(look.pitch)}°   ` +
          `lens ${fmt(s.focal)} mm (${fmt(fov.h)}° × ${fmt(fov.v)}°)`,
        `aircraft ${fmt(range, 0)} m from the camera at t = ${fmt(s.t)} s`,
      ];
      const el = this.$("c3dRead");
      el.textContent = lines.join("\n");
      const warn = [];
      if (s.mode === "world" && agl < this.data.min_clearance_m)
        warn.push(`the camera is less than ${this.data.min_clearance_m} m above the ground: ` +
                  "it will be refused (camera.terrain_clearance)");
      else if (agl < 0) warn.push("the camera is under the ground here");
      if (!inside && this.data.kind === "raster" && s.mode === "world")
        warn.push("the camera is outside the scene's terrain raster");
      if (warn.length) {
        const w = document.createElement("div");
        w.className = "c3d-warn";
        w.textContent = warn.join("; ");
        el.appendChild(w);
      }
    }

    // -- drawing -------------------------------------------------------
    frame() {
      if (this.pending) return;
      this.pending = requestAnimationFrame(() => { this.pending = null; this.draw(); });
    }

    drawWorld(view, viewProj, eye, fog, isOverview) {
      const s = this.st;
      view.begin(viewProj, eye, fog);
      view.draw("terrain", null, 1);
      const a = this.aircraftGl(s.t);
      // In the scene view the aircraft is enlarged so it is findable; the
      // camera's view draws it at its true size.
      const grow = isOverview ? Math.max(1, this.orbit.dist / (this.lengthM * 12)) : 1;
      view.draw("aircraft", modelMatrix(a, this.ac.heading_deg, this.lengthM * grow));
      for (const tr of this.data.traffic) {
        const pos = this.offsetFromStart(tr, s.t);
        view.draw("traffic", modelMatrix(pos, tr.heading_deg, this.lengthM * grow));
      }
      const segs = [];
      const track = this.data.track.map(p => this.terrain.gl(p.north_m, p.east_m, p.alt_m));
      for (let i = 1; i < track.length; i++) segs.push([track[i - 1], track[i], [1.0, 0.85, 0.25]]);
      if (isOverview) {
        const cw = this.cameraWorld(s.t);
        const cam = this.terrain.gl(cw.north, cw.east, cw.alt);
        const groundY = this.terrain.elevation(cw.north, cw.east) - this.terrain.base;
        segs.push([cam, [cam[0], groundY, cam[2]], [0.25, 0.85, 0.95]]);
        segs.push([a, [a[0], this.terrain.elevation(-a[2], a[0]) - this.terrain.base, a[2]],
                   [1.0, 0.85, 0.25]]);
        // The frustum, drawn out to the aircraft's range (or 300 m).
        const look = this.lookDir(s.t);
        const fov = this.fovDeg();
        const reach = Math.max(80, Math.min(4000, Math.hypot(...sub(a, cam)) || 300));
        let right = cross(look.dir, [0, 1, 0]);
        if (Math.hypot(...right) < 1e-6) right = [1, 0, 0];
        right = norm(right);
        const up = cross(right, look.dir);
        const th = Math.tan(fov.h * DEG / 2), tv = Math.tan(fov.v * DEG / 2);
        const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([x, y]) =>
          add(cam, scale(add(look.dir, add(scale(right, x * th), scale(up, y * tv))), reach)));
        const cyan = [0.25, 0.85, 0.95];
        for (let i = 0; i < 4; i++) {
          segs.push([cam, corners[i], cyan]);
          segs.push([corners[i], corners[(i + 1) % 4], cyan]);
        }
        const bodyScale = Math.max(4, this.orbit.dist / 90);
        view.lines(segs);
        // Camera body, nose along the look direction.
        view.draw("camera", this.cameraBodyMatrix(cam, look, bodyScale));
        return;
      }
      view.lines(segs);
    }

    cameraBodyMatrix(cam, look, s) {
      // Columns: right, up, -forward (the mesh's +x, +y, +z), scaled.
      let right = cross(look.dir, [0, 1, 0]);
      if (Math.hypot(...right) < 1e-6) right = [1, 0, 0];
      right = norm(right);
      const up = cross(right, look.dir);
      const back = scale(look.dir, -1);
      return new Float32Array([right[0] * s, right[1] * s, right[2] * s, 0,
        up[0] * s, up[1] * s, up[2] * s, 0, back[0] * s, back[1] * s, back[2] * s, 0,
        cam[0], cam[1], cam[2], 1]);
    }

    offsetFromStart(tr, t) {
      // Traffic flies alongside: its t = 0 offset carried with the
      // aircraft along the same straight line.
      const a = this.aircraftAt(t);
      return this.terrain.gl(tr.north_m + a.north, tr.east_m + a.east,
                             tr.alt_m + a.alt - this.ac.alt_m);
    }

    orbitEye() {
      const o = this.orbit;
      return add(o.target, scale([Math.cos(o.pitch) * Math.sin(o.yaw), Math.sin(o.pitch),
                                  Math.cos(o.pitch) * Math.cos(o.yaw)], o.dist));
    }

    draw() {
      const s = this.st;
      // Scene view.
      const ov = this.overview, [ow, oh] = ov.resize();
      const eye = this.orbitEye();
      const oProj = perspective(50 * DEG, ow / oh, Math.max(1, this.orbit.dist / 2000), 120000);
      this.ovViewProj = mul(oProj, lookAt(eye, this.orbit.target, [0, 1, 0]));
      this.drawWorld(ov, this.ovViewProj, eye, 60000, true);
      // Camera view.
      const look = this.lookDir(s.t);
      const cv = this.camView, [cw, ch] = cv.resize();
      const fov = this.fovDeg();
      let upHint = [0, 1, 0];
      if (Math.abs(look.dir[1]) > 0.999) {
        const h = this.ac.heading_deg * DEG;
        upHint = [Math.sin(h), 0, -Math.cos(h)];
      }
      const cProj = perspective(fov.v * DEG, cw / ch, 0.5, 120000);
      const cViewProj = mul(cProj, lookAt(look.cam, add(look.cam, look.dir), upHint));
      this.drawWorld(cv, cViewProj, look.cam, 45000, false);
      this.labels(cViewProj);
    }

    labels(cViewProj) {
      const dpr = window.devicePixelRatio || 1;
      const put = (canvas, glCanvas) => {
        canvas.width = glCanvas.width;
        canvas.height = glCanvas.height;
        canvas.style.width = glCanvas.clientWidth + "px";
        canvas.style.height = glCanvas.clientHeight + "px";
        const ctx = canvas.getContext("2d");
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.font = `${12 * dpr}px Menlo, monospace`;
        ctx.textAlign = "center";
        return ctx;
      };
      // Scene view: compass letters on the window edge, the two actors.
      const ovCanvas = this.$("c3dOverviewLabels"), ovGl = this.$("c3dOverview");
      const ctx = put(ovCanvas, ovGl);
      const w = ovCanvas.width, h = ovCanvas.height, g = this.terrain.g;
      const half = g.step_m * (this.terrain.P - 1) / 2;
      const cn = g.south_m + half, ce = g.west_m + half;
      const label = (text, p, colour) => {
        const q = project(this.ovViewProj, p, w, h);
        if (!q) return null;
        ctx.fillStyle = "rgba(0,0,0,.55)";
        const tw = ctx.measureText(text).width;
        ctx.fillRect(q[0] - tw / 2 - 3 * dpr, q[1] - 13 * dpr, tw + 6 * dpr, 17 * dpr);
        ctx.fillStyle = colour;
        ctx.fillText(text, q[0], q[1]);
        return q;
      };
      for (const [text, n, e] of [["N", cn + half, ce], ["S", cn - half, ce],
                                  ["E", cn, ce + half], ["W", cn, ce - half]])
        label(text, this.terrain.gl(n, e, this.terrain.elevation(n, e) + 40), "#e6ecf1");
      const a = this.aircraftGl(this.st.t);
      label(this.ac.aircraft, add(a, [0, Math.max(30, this.orbit.dist / 25), 0]), "#f3b04a");
      const cw = this.cameraWorld(this.st.t);
      const camGl = this.terrain.gl(cw.north, cw.east, cw.alt);
      this.cameraScreen = project(this.ovViewProj, camGl, w, h);
      label("camera", add(camGl, [0, Math.max(30, this.orbit.dist / 25), 0]), "#5fd8f2");

      // Camera view: thirds, a centre mark, the frame size.
      const cc = this.$("c3dCameraLabels"), cgl = this.$("c3dCamera");
      const c2 = put(cc, cgl), W = cc.width, H = cc.height;
      c2.strokeStyle = "rgba(255,255,255,.28)";
      c2.lineWidth = dpr;
      c2.beginPath();
      for (const f of [1 / 3, 2 / 3]) {
        c2.moveTo(W * f, 0); c2.lineTo(W * f, H);
        c2.moveTo(0, H * f); c2.lineTo(W, H * f);
      }
      c2.moveTo(W / 2 - 8 * dpr, H / 2); c2.lineTo(W / 2 + 8 * dpr, H / 2);
      c2.moveTo(W / 2, H / 2 - 8 * dpr); c2.lineTo(W / 2, H / 2 + 8 * dpr);
      c2.stroke();
      const q = project(cViewProj, a, W, H);
      c2.textAlign = "left";
      c2.fillStyle = "rgba(0,0,0,.55)";
      c2.fillRect(4 * dpr, H - 20 * dpr, 250 * dpr, 17 * dpr);
      c2.fillStyle = "#e6ecf1";
      const inFrame = q && q[0] >= 0 && q[0] <= W && q[1] >= 0 && q[1] <= H;
      c2.fillText(inFrame ? "aircraft in frame" : "aircraft OUT of frame",
                  8 * dpr, H - 7 * dpr);
    }

    // -- interaction -----------------------------------------------------
    ray(ev) {
      // The scene view's pick ray through the pointer, GL space.
      const canvas = this.$("c3dOverview"), rect = canvas.getBoundingClientRect();
      const nx = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
      const ny = 1 - ((ev.clientY - rect.top) / rect.height) * 2;
      const eye = this.orbitEye();
      const fwd = norm(sub(this.orbit.target, eye));
      const right = norm(cross(fwd, [0, 1, 0]));
      const up = cross(right, fwd);
      const t = Math.tan(25 * DEG), aspect = rect.width / rect.height;
      return {eye, dir: norm(add(fwd, add(scale(right, nx * t * aspect), scale(up, ny * t))))};
    }
    pickGround(ev) {
      const {eye, dir} = this.ray(ev);
      const step = this.terrain.g.step_m / 3;
      let prev = eye;
      for (let d = 0; d < 120000; d += step) {
        const p = add(eye, scale(dir, d)), w = this.terrain.fromGl(p);
        if (w.alt <= this.terrain.elevation(w.north, w.east)) {
          // One bisection pass is plenty at a third of a cell.
          const m = scale(add(prev, p), 0.5), wm = this.terrain.fromGl(m);
          return {north: wm.north, east: wm.east};
        }
        prev = p;
      }
      return null;
    }
    bindMouse(canvas) {
      let drag = null;
      canvas.addEventListener("contextmenu", e => e.preventDefault());
      canvas.addEventListener("pointerdown", e => {
        canvas.setPointerCapture(e.pointerId);
        const rect = canvas.getBoundingClientRect(), dpr = canvas.width / rect.width;
        const x = (e.clientX - rect.left) * dpr, y = (e.clientY - rect.top) * dpr;
        const c = this.cameraScreen;
        const onCamera = c && Math.hypot(c[0] - x, c[1] - y) < 22 * dpr;
        let mode = "orbit";
        if (onCamera && e.button === 0) mode = e.shiftKey ? "lift" : "move";
        else if (e.button === 2 || e.ctrlKey || e.metaKey || e.shiftKey) mode = "pan";
        drag = {mode, x: e.clientX, y: e.clientY};
        canvas.style.cursor = mode === "orbit" ? "grabbing" : "move";
      });
      canvas.addEventListener("pointermove", e => {
        if (!drag) return;
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        drag.x = e.clientX; drag.y = e.clientY;
        const o = this.orbit;
        if (drag.mode === "orbit") {
          o.yaw -= dx * 0.006;
          o.pitch = Math.max(0.03, Math.min(1.55, o.pitch + dy * 0.006));
        } else if (drag.mode === "pan") {
          const k = o.dist * 0.0016;
          const fx = Math.sin(o.yaw), fz = Math.cos(o.yaw);
          // The ground follows the pointer.
          o.target = add(o.target, [(-dx * fz - dy * fx) * k, 0, (dx * fx - dy * fz) * k]);
        } else if (drag.mode === "move") {
          // Slide the camera over the horizontal plane at its altitude.
          const {eye, dir} = this.ray(e);
          const p = this.cameraWorld(this.st.t);
          const y = p.alt - this.terrain.base;
          if (Math.abs(dir[1]) > 1e-4) {
            const d = (y - eye[1]) / dir[1];
            if (d > 0 && d < 150000) {
              const hit = add(eye, scale(dir, d)), w = this.terrain.fromGl(hit);
              this.setCameraWorld({north: w.north, east: w.east, alt: p.alt});
            }
          }
          this.round();
        } else if (drag.mode === "lift") {
          const p = this.cameraWorld(this.st.t);
          this.setCameraWorld({...p, alt: p.alt - dy * o.dist * 0.002});
          this.round();
        }
        if (drag.mode === "move" || drag.mode === "lift") {
          this.syncInputs();
          this.readout();
        }
        this.frame();
      });
      const end = () => { drag = null; canvas.style.cursor = "grab"; };
      canvas.addEventListener("pointerup", end);
      canvas.addEventListener("pointercancel", end);
      canvas.addEventListener("wheel", e => {
        e.preventDefault();
        this.orbit.dist = Math.max(15, Math.min(80000, this.orbit.dist * Math.exp(e.deltaY * 0.0012)));
        this.frame();
      }, {passive: false});
      canvas.addEventListener("dblclick", e => {
        const hit = this.pickGround(e);
        if (!hit) return;
        // Keep the camera's height above the ground; move it over the spot.
        const p = this.cameraWorld(this.st.t);
        const agl = Math.max(2, p.alt - this.terrain.elevation(p.north, p.east));
        this.setCameraWorld({north: hit.north, east: hit.east,
                             alt: this.terrain.elevation(hit.north, hit.east) + agl});
        this.round();
        this.syncInputs();
        this.readout();
        this.frame();
      });
    }

    fromView() {
      const eye = this.orbitEye(), w = this.terrain.fromGl(eye);
      const dir = norm(sub(this.orbit.target, eye));
      this.st.mode = "world";
      this.st.aim = "bearing";
      this.st.east = w.east; this.st.north = w.north; this.st.alt = w.alt;
      this.st.bearing = +(((Math.atan2(dir[0], -dir[2]) / DEG) + 360) % 360).toFixed(1);
      this.st.elevation = +(Math.asin(dir[1]) / DEG).toFixed(1);
      this.round();
      this.refresh();
    }

    play() {
      if (this.playing) { this.playing = false; return; }
      this.playing = true;
      const start = performance.now(), t0 = this.st.t >= this.data.clip_seconds ? 0 : this.st.t;
      const tick = now => {
        if (!this.playing || !this.opts.container.isConnected) return;
        this.st.t = Math.min(this.data.clip_seconds, t0 + (now - start) / 1000);
        this.refresh(false);
        if (this.st.t >= this.data.clip_seconds) { this.playing = false; return; }
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }

    async place() {
      const s = this.st, state = this.$("c3dState");
      const placement = s.mode === "world"
        ? {mode: "world", east_m: s.east, north_m: s.north, alt_m: s.alt,
           aim: s.aim, bearing_deg: s.bearing, elevation_deg: s.elevation,
           focal_length_mm: s.focal}
        : {mode: "follow", forward_m: s.forward, right_m: s.right, up_m: s.up,
           focal_length_mm: s.focal};
      if (this.edit) placement.replace = this.edit.index;
      state.textContent = "placing...";
      try {
        const response = await fetch("/cameras/place", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({spec: this.opts.getSpec(), placement}),
        });
        const payload = await response.json();
        if (payload.error) {
          state.className = "c3d-warn";
          state.textContent = (payload.refused ? payload.refused + ": " : "") + payload.error;
          return;
        }
        const cam = payload.cameras[payload.placed_index];
        state.className = "dim";
        state.textContent = `camera[${cam.index}] ${cam.camera_id} is in the spec ` +
          `(see the review table)`;
        // Further changes in this session edit the camera just placed.
        this.edit = {index: cam.index, camera: cam};
        this.$("c3dPlace").textContent = `Update camera[${cam.index}]`;
        this.opts.onPlaced(payload);
      } catch (error) {
        state.className = "c3d-warn";
        state.textContent = `could not reach the server: ${error}`;
      }
    }

    close() {
      this.playing = false;
      window.removeEventListener("resize", this.onResize);
      for (const v of [this.overview, this.camView]) {
        const lose = v.gl.getExtension("WEBGL_lose_context");
        if (lose) lose.loseContext();
      }
      this.opts.container.innerHTML = "";
      this.opts.container.className = "";
      if (current === this) current = null;
    }
  }

  function esc(text) {
    return String(text).replace(/[&<>"]/g, c =>
      ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  }

  let current = null;

  async function open(opts) {
    if (current) current.close();
    const box = opts.container;
    box.className = "card";
    box.textContent = "loading the scene's terrain...";
    let data;
    try {
      const response = await fetch("/cameras/terrain", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({spec: opts.getSpec()}),
      });
      data = await response.json();
      if (data.error) { box.textContent = data.error; return null; }
    } catch (error) {
      box.textContent = `could not reach the server: ${error}`;
      return null;
    }
    try {
      current = new Placer(opts, data);
    } catch (error) {
      box.textContent = `the 3D placer could not start: ${error.message || error}`;
      return null;
    }
    box.scrollIntoView({behavior: "smooth", block: "start"});
    return current;
  }

  return {open, close: () => current && current.close()};
})();
