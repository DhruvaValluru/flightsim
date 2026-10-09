"use strict";
// The route map: the flight path drawn on the ground the physics flies,
// checked as it is drawn, nudged until it is flyable, flown for real by
// the server, and written into the spec as user-stated waypoints.
//
// Frames and conventions are the pose solver's, the same as the 3D camera
// placer's (webapp/static/camera3d.js, core/capture/poses.py):
//   * x = EAST metres, y = NORTH metres about the spec origin; altitude
//     metres MSL. The aircraft starts at (0, 0, spec altitude). "Use this
//     path" sets the spec's heading to the first leg's bearing, so the
//     engine here treats the start as already pointed along the line.
//   * The ground is the server's grid (POST /route/terrain): the scene
//     raster pick_scene chooses, sampled 129 x 129 over the reach window
//     (webapp/camera_placer.py _sample_grid), bilinear between nodes. A
//     flat scene is the datum everywhere and the map says so.
//   * Every limit is the payload's `route` block -- true airspeed, the
//     turn radius at the bank limit, the bank limit, the autopilot's
//     climb-rate demand clip, the clearance floor, the pure-pursuit
//     lookahead and the run's seconds -- served from core/control/route.py
//     and the TECS autopilot's own limits (core/control/systems/tecs.xml).
//     No limit is typed here: the numbers in this file are geometry and
//     the engine's own resolution, and tests/test_route_page.py pins them.
//
// The four checks and the thin flown track on the map are the mockup's
// engine: a bank-limited pure-pursuit stand-in for the autopilot, flown
// for the run's seconds over the map's grid. They are quick and local,
// and the page says the clearance is "measured on the map's grid".
// "Check with the physics" is the real thing: JSBSim, the TECS autopilot
// and the route guidance over the scene's full raster, on the server
// (webapp/route_map.py check_route). Its refusals come back by name and
// are shown with the server's own sentence; nothing is substituted.
//
// Public surface: RouteMap.open({container, getSpec, onPlaced}) and
// RouteMap.close(), the CameraPlacer shape. onPlaced receives
// {waypoints, bank_limit_deg, heading_deg, altitude_m, from, length_m}.

window.RouteMap = (function () {
  // -- the only numbers in the engine (tests/test_route_page.py pins them)
  //: Mirrors core/control/route.py G_MPS2. The served turn radius is at
  //: the served bank; when the bank is changed on the page the radius is
  //: V^2 / (g tan bank) again, the same formula.
  const G_MPS2 = 9.80665;
  //: Mirrors webapp/camera_placer.py KT_TO_MPS.
  const KT_TO_MPS = 0.514444;
  //: Mirrors core/control/route.py TURN_RADIUS_SLACK (route.turn): a bend
  //: is a problem when its radius is under this fraction of the limit.
  const TURN_RADIUS_SLACK = 0.9;
  //: Mirrors core/control/route.py CLIMB_MIN_LEG_S (route.climb): the
  //: shortest leg time a climb rate is judged over.
  const CLIMB_MIN_LEG_S = 1;
  const DEG = Math.PI / 180;
  //: The checked line's resolution: about this many points per turn
  //: radius, bounded in metres so a slow aircraft's line is not thousands
  //: of points and a fast one's still draws as a curve.
  const RESAMPLE_PER_RADIUS = 30;
  const RESAMPLE_STEP_MIN_M = 5;
  const RESAMPLE_STEP_MAX_M = 60;
  //: Chaikin smoothing passes over the pointer's polyline.
  const CHAIKIN_PASSES = 3;
  //: The stand-in's integration step (s); every second step is kept.
  const SIM_DT_S = 0.05;
  //: Self adjust aims this fraction of the clearance floor above it, so
  //: the fix holds on the raster; it uses a little less than the full
  //: climb-rate clip and bank, so the result passes the checks with margin.
  const ADJ_MARGIN_FRACTION = 0.25;
  const RATE_MARGIN = 0.97;
  const BANK_IN_HAND = 0.85;
  //: Self adjust's rounding of altitudes (m), its iteration caps and its
  //: wall-clock budget (ms); a result shorter than LOST_FRACTION of the
  //: drawing is "lost", not adjusted, and nothing is changed.
  const ALT_ROUND_M = 10;
  const ADJUST_ITERATIONS = 12;
  const ALTITUDE_PASSES = 6;
  const ADJUST_BUDGET_MS = 2000;
  const LOST_FRACTION = 0.4;
  //: A gap of this many seconds between low samples ends a low stretch.
  const LOW_STRETCH_GAP_S = 2;
  //: The altitude popup's step (m).
  const PIN_STEP_M = 50;

  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const wrap = a => Math.atan2(Math.sin(a), Math.cos(a));
  const fmtN = v => Math.round(v).toLocaleString("en-US");
  const m = v => fmtN(v) + " m";
  const km = v => Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + " km" : m(v);
  const fmtT = s => {
    const t = Math.max(0, Math.round(s));
    return t < 120 ? `${t} s` : `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
  };
  const bearingDeg = psi => ((psi / DEG) % 360 + 360) % 360;
  function esc(text) {
    return String(text).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;",
      ">": "&gt;", '"': "&quot;", "'": "&#39;"})[c]);
  }

  // -- the server's grid ----------------------------------------------------
  class Grid {
    // Row = north index from the south edge, column = east index from the
    // west edge (webapp/camera_placer.py _sample_grid). The bilinear
    // lookup is camera3d.js's Terrain.elevation, copied here because
    // window.Flight3D exposes the WebGL helpers and not that class. A
    // flat scene arrives as 2 x 2 nodes at the datum, which this reads
    // as the datum everywhere without resampling.
    constructor(data) {
      this.g = data.grid;
      this.P = this.g.points;
      this.kind = data.kind;
      this.datum = data.datum_m;
      this.lo = Math.min(...this.g.heights_m);
      this.hi = Math.max(...this.g.heights_m);
      this.step = this.g.step_m;
      this.span = this.g.step_m * (this.P - 1);
    }
    h(r, c) {
      r = Math.max(0, Math.min(this.P - 1, r));
      c = Math.max(0, Math.min(this.P - 1, c));
      return this.g.heights_m[r * this.P + c];
    }
    contains(north, east) {
      return north >= this.g.south_m && north <= this.g.south_m + this.span &&
             east >= this.g.west_m && east <= this.g.west_m + this.span;
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
  }

  /*ENGINE*/
  // -- the engine: the mockup's CORE with the grid for its terrain and the
  // -- payload's limits for its numbers --------------------------------------
  function turnRadius(V, bankDeg) {
    return V * V / (G_MPS2 * Math.tan(bankDeg * DEG));
  }
  // Ramer-Douglas-Peucker: the mask of points that keep the polyline
  // within eps of itself.
  function rdpKeep(pts, eps) {
    const keep = new Uint8Array(pts.length);
    if (pts.length < 3) { keep.fill(1); return keep; }
    keep[0] = keep[pts.length - 1] = 1;
    const st = [[0, pts.length - 1]];
    while (st.length) {
      const [a, b] = st.pop();
      let md = 0, mi = -1;
      const A = pts[a], B = pts[b], dx = B.x - A.x, dy = B.y - A.y, l2 = dx * dx + dy * dy;
      for (let i = a + 1; i < b; i++) {
        const P = pts[i];
        let d;
        if (!l2) d = Math.hypot(P.x - A.x, P.y - A.y);
        else {
          const t = clamp(((P.x - A.x) * dx + (P.y - A.y) * dy) / l2, 0, 1);
          d = Math.hypot(P.x - A.x - t * dx, P.y - A.y - t * dy);
        }
        if (d > md) { md = d; mi = i; }
      }
      if (md > eps) { keep[mi] = 1; st.push([a, mi], [mi, b]); }
    }
    return keep;
  }
  function rdp(pts, eps) {
    const keep = rdpKeep(pts, eps);
    return pts.filter((_, i) => keep[i]);
  }
  function chaikin(pts, it) {
    let p = pts;
    for (let k = 0; k < it; k++) {
      if (p.length < 3) return p;
      const q = [p[0]];
      for (let i = 0; i < p.length - 1; i++) {
        const a = p[i], b = p[i + 1];
        q.push({x: 0.75 * a.x + 0.25 * b.x, y: 0.75 * a.y + 0.25 * b.y},
               {x: 0.25 * a.x + 0.75 * b.x, y: 0.25 * a.y + 0.75 * b.y});
      }
      q.push(p[p.length - 1]);
      p = q;
    }
    return p;
  }
  function resample(pts, step) {
    const out = [{x: pts[0].x, y: pts[0].y}], cum = [0];
    let total = 0, next = step;
    for (let i = 0; i < pts.length - 1; i++) {
      const a = pts[i], b = pts[i + 1], L = Math.hypot(b.x - a.x, b.y - a.y);
      if (!L) continue;
      while (next <= total + L) {
        const t = (next - total) / L;
        out.push({x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t});
        cum.push(next);
        next += step;
      }
      total += L;
    }
    if (total - cum[cum.length - 1] > 1e-6) {
      const l = pts[pts.length - 1];
      out.push({x: l.x, y: l.y});
      cum.push(total);
    }
    return {pts: out, cum};
  }
  function cumLen(pts) {
    const c = [0];
    for (let i = 1; i < pts.length; i++)
      c.push(c[i - 1] + Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y));
    return c;
  }
  function pointAtCum(pts, cum, d) {
    if (pts.length < 2) return {x: pts[0].x, y: pts[0].y};
    let i = 0;
    while (i < cum.length - 2 && cum[i + 1] < d) i++;
    const t = clamp((d - cum[i]) / ((cum[i + 1] - cum[i]) || 1), 0, 1);
    return {x: pts[i].x + (pts[i + 1].x - pts[i].x) * t,
            y: pts[i].y + (pts[i + 1].y - pts[i].y) * t};
  }
  // Distance along the line of the point nearest (x, y), by projection.
  function projectD(pts, cum, x, y) {
    let best = 0, bd = Infinity;
    for (let i = 0; i < pts.length - 1; i++) {
      const ax = pts[i].x, ay = pts[i].y, vx = pts[i + 1].x - ax, vy = pts[i + 1].y - ay;
      const l2 = vx * vx + vy * vy || 1;
      const t = clamp(((x - ax) * vx + (y - ay) * vy) / l2, 0, 1);
      const px = ax + vx * t, py = ay + vy * t, d = (px - x) ** 2 + (py - y) ** 2;
      if (d < bd) { bd = d; best = cum[i] + Math.sqrt(l2) * t; }
    }
    return best;
  }
  function nearestIdx(pts, x, y) {
    let b = 0, bd = Infinity;
    for (let i = 0; i < pts.length; i++) {
      const d = (pts[i].x - x) ** 2 + (pts[i].y - y) ** 2;
      if (d < bd) { bd = d; b = i; }
    }
    return b;
  }
  // The first leg's bearing (radians from north toward east): the heading
  // the spec gets when the path is used, and so the heading the engine
  // starts with. A line that has not left the origin keeps the spec's.
  function firstLegHeading(rs, step, fallback) {
    for (let i = 1; i < rs.pts.length; i++) {
      const p = rs.pts[i];
      if (Math.hypot(p.x, p.y) >= step / 2) return Math.atan2(p.x, p.y);
    }
    return fallback;
  }
  // Turn radius along the line, judged over a window about one turn
  // radius long. The aircraft arrives already pointed along the first leg
  // and keeps its last heading, so both ends are padded with those.
  function turnAnalysis(rs, Rmin, step, psi0) {
    const n = rs.pts.length;
    if (n < 2) return {markers: [], minR: Infinity};
    const k0 = Math.ceil(Rmin / step), hd = [];
    for (let i = 0; i < k0; i++) hd.push(psi0);
    for (let i = 0; i < n - 1; i++) {
      const a = rs.pts[i], b = rs.pts[i + 1];
      hd.push(Math.atan2(b.x - a.x, b.y - a.y));
    }
    const last = hd[hd.length - 1];
    for (let i = 0; i < k0; i++) hd.push(last);
    const ps = [0];
    for (let i = 0; i < hd.length; i++) ps.push(ps[i] + (i ? wrap(hd[i] - hd[i - 1]) : 0));
    const half = Math.max(2, Math.round(Rmin / 2 / step)), W = 2 * half * step;
    let minR = Infinity;
    const markers = [];
    let run = null;
    for (let s = 0; s < n - 1; s++) {
      const i = s + k0;
      const turn = Math.abs(ps[i + half + 1] - ps[i - half + 1]);
      const R = turn > 1e-6 ? W / turn : Infinity;
      minR = Math.min(minR, R);
      if (R < TURN_RADIUS_SLACK * Rmin) {
        if (!run) run = {R, s};
        else if (R < run.R) { run.R = R; run.s = s; }
      } else if (run) { markers.push(run); run = null; }
    }
    if (run) markers.push(run);
    // Corners closer together than about one turn radius read as one problem.
    const merged = [];
    for (const r of markers) {
      const p = merged[merged.length - 1];
      if (p && rs.cum[r.s] - rs.cum[p.s] < 1.5 * Rmin) {
        if (r.R < p.R) { p.R = r.R; p.s = r.s; }
      } else merged.push({...r});
    }
    return {markers: merged.map(r => ({x: rs.pts[r.s].x, y: rs.pts[r.s].y, R: r.R, d: rs.cum[r.s]})),
            minR};
  }
  // The autopilot stand-in: bank toward the point one lookahead ahead on
  // the line (the server's pure pursuit, RouteGuidance), limited by the
  // bank limit. The roll is instant unless the payload states a roll rate
  // (roll_rate_dps); the physics check flies the real airframe.
  function simulate(rs, V, T, phiMax, L, psi0, rollRate) {
    const dt = SIM_DT_S;
    let x = 0, y = 0, psi = psi0, phi = 0, j = 0;
    const out = [];
    const n = rs ? rs.pts.length : 0, end = rs ? rs.cum[n - 1] : 0;
    const steps = Math.round(T / dt);
    for (let k = 0; k <= steps; k++) {
      const t = k * dt;
      let tx, ty, xt = 0, along = 0, onPath = false;
      if (rs) {
        const lim = rs.cum[j] + 2 * L;
        let best = j, bd = Infinity;
        for (let i = j; i < n && rs.cum[i] <= lim; i++) {
          const d = (rs.pts[i].x - x) ** 2 + (rs.pts[i].y - y) ** 2;
          if (d < bd) { bd = d; best = i; }
        }
        j = best; xt = Math.sqrt(bd); along = rs.cum[j]; onPath = j < n - 1;
        const la = along + L;
        if (la < end) {
          let i = j;
          while (i < n - 1 && rs.cum[i] < la) i++;
          tx = rs.pts[i].x; ty = rs.pts[i].y;
        } else {
          const a = rs.pts[Math.max(0, n - 2)], b = rs.pts[n - 1];
          const hd = n > 1 ? Math.atan2(b.x - a.x, b.y - a.y) : psi0;
          const ex = la - end;
          tx = b.x + Math.sin(hd) * ex; ty = b.y + Math.cos(hd) * ex;
        }
      } else { tx = x + Math.sin(psi) * L; ty = y + Math.cos(psi) * L; }
      const eta = wrap(Math.atan2(tx - x, ty - y) - psi);
      // A point behind the aircraft gets the full bank toward it: pure
      // pursuit alone commands nothing at 180 degrees.
      const cmd = Math.abs(eta) > Math.PI / 2 ? Math.sign(eta || 1) * phiMax
        : clamp(Math.atan(2 * V * V * Math.sin(eta) / (L * G_MPS2)), -phiMax, phiMax);
      phi += clamp(cmd - phi, -rollRate * dt, rollRate * dt);
      if (k % 2 === 0) out.push({t, x, y, psi, phi, along, xt, onPath});
      psi += G_MPS2 * Math.tan(phi) / V * dt;
      x += V * Math.sin(psi) * dt;
      y += V * Math.cos(psi) * dt;
    }
    return {samples: out, dt: 2 * dt};
  }

  // Everything the page shows for one state: the smoothed line, its turn
  // analysis, the stand-in flight, the altitude profile, the clearance
  // over the grid, the climbs between altitude points, and the checks.
  function compute(S, lim, grid) {
    const V = lim.tas_kt * KT_TO_MPS, T = lim.seconds, phiMax = S.bank * DEG;
    const Rmin = turnRadius(V, S.bank), reach = V * T;
    const poly = [{x: 0, y: 0}];
    for (const s of S.strokes) for (const p of s) poly.push(p);
    const step = clamp(Rmin / RESAMPLE_PER_RADIUS, RESAMPLE_STEP_MIN_M, RESAMPLE_STEP_MAX_M);
    const R = {V, T, Rmin, reach, phiMax, empty: poly.length < 2, step,
               psi0: lim.heading_deg * DEG};
    if (!R.empty) {
      R.path = resample(chaikin(poly, CHAIKIN_PASSES), step);
      R.len = R.path.cum[R.path.cum.length - 1];
      R.psi0 = firstLegHeading(R.path, step, R.psi0);
      R.turns = turnAnalysis(R.path, Rmin, step, R.psi0);
    } else { R.len = 0; R.turns = {markers: [], minR: Infinity}; }
    const rollRate = lim.roll_rate_dps ? lim.roll_rate_dps * DEG : Infinity;
    R.sim = simulate(R.empty ? null : R.path, V, T, phiMax, lim.lookahead_m, R.psi0, rollRate);
    const pins = S.pins.filter(p => p.d <= R.len + 1).sort((a, b) => a.d - b.d);
    R.pins = pins;
    const altAt = d => {
      let pd = 0, pa = S.alt0;
      for (const p of pins) {
        if (d <= p.d) return pa + (p.alt - pa) * (p.d > pd ? (d - pd) / (p.d - pd) : 1);
        pd = p.d; pa = p.alt;
      }
      return pa;
    };
    R.altAt = altAt;
    let minC = Infinity, minS = null, maxDev = 0, maxBank = 0;
    for (const s of R.sim.samples) {
      s.alt = altAt(s.along);
      s.terr = grid.elevation(s.y, s.x);
      s.clr = s.alt - s.terr;
      if (s.clr < minC) { minC = s.clr; minS = s; }
      if (s.onPath) maxDev = Math.max(maxDev, s.xt);
      maxBank = Math.max(maxBank, Math.abs(s.phi));
    }
    Object.assign(R, {minClr: minC, minS, maxDev, maxBank});
    R.climbs = [];
    {
      let pd = 0, pa = S.alt0;
      for (const p of pins) {
        const dt = Math.max(CLIMB_MIN_LEG_S, (p.d - pd) / V);
        R.climbs.push({from: pa, to: p.alt, rate: (p.alt - pa) / dt, d: p.d});
        pd = p.d; pa = p.alt;
      }
    }
    R.checks = buildChecks(R, S, lim);
    return R;
  }

  // The four checks, each a sentence first with its rule name beside it
  // (route.time, route.turn, route.terrain_clearance, route.climb are the
  // validator's and the server check's names; the page never invents
  // one). Every number in a sentence is the payload's or measured here.
  function buildChecks(R, S, lim) {
    const out = [], floor = lim.min_clearance_m, hdot = lim.hdot_max_mps;
    const tas = `${fmtN(lim.tas_kt)} kt true`;
    if (R.empty) out.push({id: "route.time", s: "idle", t: "Fits the time",
      m: `No line yet. The aircraft flies straight ahead for ${fmtT(R.T)}.`});
    else if (R.len > R.reach * 1.001) out.push({id: "route.time", s: "warn",
      t: "Longer than the time allows",
      m: `Your line is ${km(R.len)}. ${fmtT(R.T)} at ${tas} covers ${km(R.reach)}, ` +
         `so the run ends at the flag. Self adjust cuts the line there.`});
    else {
      const tl = R.len / R.V;
      out.push({id: "route.time", s: "ok", t: "Fits the time",
        m: `Your line takes about ${fmtT(tl)} of ${fmtT(R.T)}.` +
           (R.T - tl >= CLIMB_MIN_LEG_S ? ` Then the aircraft flies straight for ${fmtT(R.T - tl)}.` : "")});
    }

    if (R.empty) out.push({id: "route.turn", s: "idle", t: "Turns flyable", m: "Nothing drawn yet."});
    else if (R.turns.markers.length) {
      const n = R.turns.markers.length;
      const tight = Math.min(...R.turns.markers.map(k => k.R));
      // The bank that would make the tightest bend flyable, to the next
      // 5 degrees; offered when it is steeper than the current limit and
      // within the payload's maximum if the server states one.
      const needBank = Math.ceil(Math.atan(R.V * R.V / (G_MPS2 * tight)) / DEG / 5) * 5;
      const allowed = lim.bank_limit_max_deg == null || needBank <= lim.bank_limit_max_deg;
      out.push({id: "route.turn", s: "warn", t: n > 1 ? `${n} turns too tight` : "1 turn too tight",
        m: `At ${fmtN(S.bank)}° bank the aircraft cannot turn tighter than ${m(R.Rmin)} ` +
           `(${tas}). It rounds ${n > 1 ? "them" : "it"} off and strays up to ` +
           `${m(R.maxDev)} from your line.`,
        act: needBank > S.bank && allowed ? {label: `Allow ${needBank}° bank`, set: {bank: needBank}} : null});
    } else out.push({id: "route.turn", s: "ok", t: "Turns flyable",
      m: `Tightest turn ${R.turns.minR > 50 * R.Rmin ? "is a straight line" : km(R.turns.minR)}; ` +
         `${fmtN(S.bank)}° bank allows ${m(R.Rmin)}. The track stays within ${m(R.maxDev)} of your line.`});

    const s = R.minS;
    if (R.minClr < 0) out.push({id: "route.terrain_clearance", s: "error", t: "Hits the ground",
      m: `At ${fmtT(s.t)} the track meets ${m(s.terr)} of ground while flying at ${m(s.alt)}. ` +
         `Move the line away or set a higher altitude there.`});
    else if (R.minClr < floor) out.push({id: "route.terrain_clearance", s: "error", t: "Too close to the ground",
      m: `At ${fmtT(s.t)} the track clears the ground by ${m(R.minClr)}; it needs ${fmtN(floor)} m. ` +
         `Move the line away or set a higher altitude there.`});
    else out.push({id: "route.terrain_clearance", s: "ok", t: "Clear of the ground",
      m: `Lowest point is ${m(R.minClr)} above the ground, at ${fmtT(s.t)}. The minimum is ${fmtN(floor)} m.`});

    const bound = `the autopilot's climb-rate demand limit is ${hdot.toFixed(2)} m/s ` +
                  `(its own bound, not a measured airframe climb figure)`;
    if (!R.climbs.length) out.push({id: "route.climb", s: "ok", t: "Climbs feasible",
      m: `Holds ${m(S.alt0)} the whole way; ${bound}. Use the Altitude tool to change it at a point on the line.`});
    else {
      let worst = R.climbs[0], ratio = -1;
      for (const c of R.climbs) {
        const r = Math.abs(c.rate) / hdot;
        if (r > ratio) { ratio = r; worst = c; }
      }
      const up = worst.rate >= 0, rate = Math.abs(worst.rate).toFixed(1);
      if (ratio > 1) out.push({id: "route.climb", s: "warn", t: up ? "Climb too steep" : "Descent too steep",
        m: `Getting to ${m(worst.to)} in time needs ${rate} m/s ${up ? "up" : "down"}; ${bound}, so it arrives late.`});
      else out.push({id: "route.climb", s: "ok", t: "Climbs feasible",
        m: `Steepest change is ${rate} m/s ${up ? "up" : "down"}; ${bound}.`});
    }
    return out;
  }

  // Clearance rule: each stretch of the flown track that comes too close
  // to the ground is moved as one block, sideways to the line, toward the
  // lower side of the grid, by as much as the slope says it needs,
  // tapered over a turn radius each side so the bend stays flyable.
  function pushClear(pts, samples, Rmin, step, grid, floor, probe) {
    const n = pts.length, runs = [], aim = floor * (1 + ADJ_MARGIN_FRACTION);
    let cur = null;
    for (const s of samples) {
      if (s.clr < aim) {
        if (!cur) { cur = {first: s, last: s, worst: s}; runs.push(cur); }
        cur.last = s;
        if (s.clr < cur.worst.clr) cur.worst = s;
      } else if (cur && s.t - cur.last.t > LOW_STRETCH_GAP_S) cur = null;
    }
    if (!runs.length) return false;
    const dx = new Float64Array(n), dy = new Float64Array(n), w = new Float64Array(n);
    const half = Math.max(3, Math.round(Rmin / step));
    for (const r of runs) {
      const ia = nearestIdx(pts, r.first.x, r.first.y), ib = nearestIdx(pts, r.last.x, r.last.y);
      const i0 = Math.min(ia, ib), i1 = Math.max(ia, ib);
      const a = pts[Math.max(0, i0 - 2)], b = pts[Math.min(n - 1, i1 + 2)];
      let tx = b.x - a.x, ty = b.y - a.y;
      const tl = Math.hypot(tx, ty) || 1;
      tx /= tl; ty /= tl;
      let nx = -ty, ny = tx;
      const W = r.worst;
      const hP = grid.elevation(W.y + ny * probe, W.x + nx * probe);
      const hM = grid.elevation(W.y - ny * probe, W.x - nx * probe);
      // Toward the lower side; the slope across the probe is the lever.
      const side = hM - hP;
      if (side < 0) { nx = -nx; ny = -ny; }
      const hSide = side < 0 ? hM : hP;
      const slope = Math.max(0.05, (grid.elevation(W.y, W.x) - hSide) / probe);
      const deficit = aim - W.clr;
      const amt = clamp(deficit / slope, step, Math.max(4 * step, Rmin * 0.6));
      for (let j = Math.max(1, i0 - half); j <= Math.min(n - 1, i1 + half); j++) {
        const k = j < i0 ? i0 - j : j > i1 ? j - i1 : 0;
        const f = 0.5 + 0.5 * Math.cos(Math.PI * k / half), v = amt * f;
        if (v > w[j]) { w[j] = v; dx[j] = nx * v; dy[j] = ny * v; }
      }
    }
    for (let j = 1; j < n; j++) { pts[j].x += dx[j]; pts[j].y += dy[j]; }
    return true;
  }

  // Self adjust: moves the drawn line as little as needed so every check
  // passes. The line is replaced by the track the stand-in flies along it
  // (bank-limited, starting along the first leg), so every turn is
  // flyable by construction; where that track comes too close to the
  // ground, the line is pushed sideways toward lower ground and flown
  // again. Altitude changes only when no sideways move gets the ground
  // clear, and the start altitude only when no climb could get there in
  // time (it is reported, and "Use this path" writes it into the table).
  function selfAdjust(st, lim, grid, budgetMs) {
    const V = lim.tas_kt * KT_TO_MPS, reach = V * lim.seconds, phiMax = st.bank * DEG;
    const Rmin = turnRadius(V, st.bank);
    const step = clamp(Rmin / RESAMPLE_PER_RADIUS, RESAMPLE_STEP_MIN_M, RESAMPLE_STEP_MAX_M);
    const floor = lim.min_clearance_m, aim = floor * (1 + ADJ_MARGIN_FRACTION);
    const hdot = lim.hdot_max_mps * RATE_MARGIN, probe = Math.max(2 * grid.step, 4 * step);
    const roundUp = v => Math.ceil(v / ALT_ROUND_M) * ALT_ROUND_M;
    const roundDown = v => Math.floor(v / ALT_ROUND_M) * ALT_ROUND_M;
    const poly = [{x: 0, y: 0}];
    for (const s of st.strokes) for (const p of s) poly.push(p);
    if (poly.length < 2) return null;
    const t0 = Date.now(), changes = [];
    const rs0 = resample(chaikin(poly, CHAIKIN_PASSES), step), len0 = rs0.cum[rs0.cum.length - 1];
    const ghost = rs0.pts.map(p => ({x: p.x, y: p.y}));
    let pts = ghost.map(p => ({x: p.x, y: p.y})), alt0 = st.alt0, shift = 0, nextId = 0;
    // Pins ride along by position; their distance is re-read by projecting
    // onto the current line.
    let pins = st.pins.filter(p => p.d <= len0 + 1).sort((a, b) => a.d - b.d).map(p => {
      const q = pointAtCum(rs0.pts, rs0.cum, p.d);
      return {id: nextId++, x: q.x, y: q.y, alt: p.alt, alt0: p.alt, t0: p.d / V, why: null};
    });
    const pinList = () => {
      const cum = cumLen(pts), len = cum[cum.length - 1];
      const lo = Math.min(step, len / 2), hi = Math.max(len - step, len / 2);
      const list = pins.map(p => ({...p, d: clamp(projectD(pts, cum, p.x, p.y), lo, hi)}))
        .sort((a, b) => a.d - b.d);
      const out = [];
      for (const p of list) {
        const q = out[out.length - 1];
        if (q && p.d - q.d < step) { if (p.alt > q.alt) { q.alt = p.alt; q.why = q.why || p.why; } }
        else out.push(p);
      }
      return {cum, len, list: out};
    };
    const setPins = (cum, list) => {
      pins = list.map(p => { const q = pointAtCum(pts, cum, p.d); return {...p, x: q.x, y: q.y}; });
    };
    const state = () => ({bank: st.bank, alt0, strokes: [pts.map(p => ({x: p.x, y: p.y}))],
                          pins: pinList().list.map(p => ({d: p.d, alt: p.alt}))});
    // 1. A line longer than the run is cut where the run ends.
    const trim = () => {
      const cum = cumLen(pts), len = cum[cum.length - 1];
      if (len <= reach * 1.001) return 0;
      const cut = cum.findIndex(c => c > reach);
      pts = pts.slice(0, Math.max(2, cut));
      return len - reach;
    };
    const trimmed = trim();
    let R = compute(state(), lim, grid);
    const turns0 = R.turns.markers.length;
    // 2. Sideways: fly the line, push it clear of the ground, fly it again.
    const bad = R => R.checks.some(c => c.s === "error" || (c.s === "warn" && c.id === "route.turn"));
    // Fly with a little bank in hand, so the track's turns pass with margin.
    const phiFly = Math.atan(Math.tan(phiMax) * BANK_IN_HAND);
    const rollRate = lim.roll_rate_dps ? lim.roll_rate_dps * DEG : Infinity;
    const fly = keepAll => {
      if (!R.path) return;
      const sim = simulate(R.path, V, lim.seconds, phiFly, lim.lookahead_m, R.psi0, rollRate), trk = [];
      let ended = false;
      for (const s of sim.samples) {
        if (!s.onPath && !keepAll && trk.length > 1) { ended = true; break; }
        trk.push({x: s.x, y: s.y});
      }
      if (trk.length < 2) return;
      if (!ended && !keepAll) {
        // Out of time before the end: keep the rest as drawn.
        const P = R.path.pts, C = R.path.cum, e = trk[trk.length - 1], along = projectD(P, C, e.x, e.y);
        for (let i = 0; i < P.length; i++) if (C[i] > along + step) trk.push({x: P[i].x, y: P[i].y});
      }
      pts = resample(trk, step).pts.map(p => ({x: p.x, y: p.y}));
    };
    let pushed = false, extended = 0;
    for (let it = 0; it < ADJUST_ITERATIONS && bad(R); it++) {
      // The straight run after the line meets the ground: bend it too.
      const lowOff = R.sim.samples.some(s => !s.onPath && s.clr < aim);
      const before = cumLen(pts)[pts.length - 1];
      fly(lowOff);
      if (lowOff) extended = Math.max(extended, cumLen(pts)[pts.length - 1] - before);
      if (R.minClr < aim) pushed = pushClear(pts, R.sim.samples, Rmin, step, grid, floor, probe) || pushed;
      R = compute(state(), lim, grid);
      if (Date.now() - t0 > budgetMs) break;
    }
    // End on a flown line, never on a pushed one.
    if (R.checks.some(c => c.s === "warn" && c.id === "route.turn")) { fly(false); R = compute(state(), lim, grid); }
    const lost = trim();
    // How far the result is from the drawing, both ways, over the part
    // that could be flown.
    const cumF = cumLen(pts), lenF = cumF[cumF.length - 1];
    if (lenF < LOST_FRACTION * Math.min(len0, reach)) return null;
    let maxMove = 0;
    for (let i = 0; i < pts.length; i++) {
      if (cumF[i] > len0 + step) break;
      const p = pts[i], q = ghost[nearestIdx(ghost, p.x, p.y)];
      maxMove = Math.max(maxMove, Math.hypot(p.x - q.x, p.y - q.y));
    }
    for (let i = 0; i < ghost.length; i++) {
      if (rs0.cum[i] > Math.min(reach, len0)) break;
      const g = ghost[i], k = nearestIdx(pts, g.x, g.y);
      if (k >= pts.length - 2) continue;
      const q = pts[k];
      maxMove = Math.max(maxMove, Math.hypot(g.x - q.x, g.y - q.y));
    }
    if (trimmed > 1) changes.push({kind: "trim", m: trimmed});
    if (lost > 1) changes.push({kind: "lost", m: lost});
    if (extended > 1) changes.push({kind: "extend", m: extended});
    if (turns0 && maxMove > 1) changes.push({kind: "turns", n: turns0, R: Rmin});
    if (pushed && maxMove > step) changes.push({kind: "lateral", m: maxMove});
    // 3. Altitude. Points that ask for more climb or descent than the
    //    demand clip allows are moved later or limited; then, only where
    //    sideways moves did not get the ground clear, the line climbs, or
    //    starts higher when no climb could get there in time.
    const climbFix = () => {
      const {cum, len, list} = pinList();
      let pd = 0, pa = alt0;
      for (const p of list) {
        if (p.d < pd + step) p.d = pd + step;
        const dt = Math.max(CLIMB_MIN_LEG_S, (p.d - pd) / V);
        if (p.alt > pa + hdot * dt) {
          const need = pd + (p.alt - pa) / hdot * V;
          if (need <= len - step) { p.d = need; p.why = p.why || "climb"; }
          else { p.alt = roundDown(pa + hdot * ((len - step - pd) / V)); p.d = len - step; p.why = "climbEnd"; }
        } else if (p.alt < pa - hdot * dt) { p.alt = roundUp(pa - hdot * dt); p.why = p.why || "descent"; }
        pd = p.d; pa = p.alt;
      }
      setPins(cum, list);
    };
    for (let pass = 0; pass < ALTITUDE_PASSES; pass++) {
      climbFix();
      R = compute(state(), lim, grid);
      if (R.minClr >= floor) break;
      const {len, list} = pinList(), s = R.minS;
      const d = clamp(Math.min(s.along, len), Math.min(step, len / 2), Math.max(len - step, len / 2));
      const need = roundUp(R.altAt(d) + floor * (1 + ADJ_MARGIN_FRACTION / 2) - s.clr);
      let prev = {d: 0, alt: alt0};
      for (const p of list) if (p.d <= d - Rmin / 2) prev = p;
      const canReach = prev.alt + hdot * ((d - prev.d) / V);
      if (need > canReach) {
        const sh = roundUp(need - canReach);
        alt0 += sh; shift += sh;
        for (const p of list) p.alt += sh;
      }
      let pin = list.find(p => Math.abs(p.d - d) <= Rmin / 2);
      if (pin) { if (pin.alt < need) { pin.alt = need; pin.why = "ground"; } }
      else {
        pin = {id: nextId++, d, alt: need, alt0: null, t0: null, why: "ground"};
        list.push(pin);
        list.sort((a, b) => a.d - b.d);
      }
      let pa = pin.alt, pd = pin.d;
      for (const p of list) {
        if (p.d <= pin.d) continue;
        const fl = pa - hdot * ((p.d - pd) / V);
        if (p.alt < fl) { p.alt = roundUp(fl); p.why = p.why || "descent"; }
        pa = p.alt; pd = p.d;
      }
      setPins(cumLen(pts), list);
    }
    R = compute(state(), lim, grid);
    if (R.minClr < floor) {
      // A parallel shift keeps every climb as it was.
      const sh = roundUp(floor * (1 + ADJ_MARGIN_FRACTION / 2) - R.minClr);
      alt0 += sh; shift += sh;
      for (const p of pins) p.alt += sh;
      climbFix();
      R = compute(state(), lim, grid);
    }
    if (pts.some(p => !Number.isFinite(p.x) || !Number.isFinite(p.y))) return null;
    // The altitude story, told from the final state so it can never go stale.
    if (shift) changes.push({kind: "alt0", from: st.alt0, to: alt0});
    const fin = pinList().list;
    for (const p of pins) if (!fin.some(q => q.id === p.id) && p.alt0 != null)
      changes.push({kind: "pinMerged", alt: p.alt0, t: p.t0});
    for (const p of fin) {
      const t = p.d / V;
      if (p.alt0 == null) { changes.push({kind: "pinNew", to: p.alt, t}); continue; }
      const base = p.alt0 + shift, moved = Math.abs(t - p.t0) > CLIMB_MIN_LEG_S;
      const changed = Math.abs(p.alt - base) >= ALT_ROUND_M / 2;
      if (!moved && !changed) continue;
      if (p.why === "ground") changes.push({kind: "pinGround", from: base, to: p.alt, t});
      else if (p.why === "climbEnd") changes.push({kind: "pinLower", from: base, to: p.alt, t});
      else if (p.why === "descent") changes.push({kind: "pinHigher", from: base, to: p.alt, t});
      else if (moved) changes.push({kind: "pinLater", alt: p.alt, tOld: p.t0, tNew: t});
      else changes.push({kind: "pinGround", from: base, to: p.alt, t});
    }
    const finState = state(), RF = compute(finState, lim, grid);
    return {strokes: finState.strokes, pins: finState.pins, alt0, changes, ghost, maxMove,
            ok: RF.checks.every(c => c.s === "ok" || c.s === "idle"), checks: RF.checks,
            ms: Date.now() - t0};
  }

  // The waypoints the spec gets: the checked line itself (smoothed and
  // resampled, what the checks and the stand-in saw), thinned so a smooth
  // bend is a handful of points, never the raw pointer samples. Every
  // altitude point is kept as a waypoint, so the piecewise-linear profile
  // between waypoints is the profile the checks used. The origin is not
  // repeated: the server starts there (core/control/route.py Route).
  function exportWaypoints(R, maxPoints) {
    const P = R.path.pts, C = R.path.cum;
    let eps = R.step / 4, keep;
    for (;;) {
      keep = rdpKeep(P, eps);
      for (const p of R.pins) {
        let i = 0;
        while (i < C.length - 1 && C[i] < p.d) i++;
        keep[i] = 1;
      }
      let count = 0;
      for (let i = 1; i < keep.length; i++) if (keep[i]) count++;
      if (!maxPoints || count <= maxPoints) break;
      eps *= 2;
    }
    const out = [];
    for (let i = 1; i < P.length; i++) if (keep[i] && Math.hypot(P[i].x, P[i].y) > 1e-6)
      out.push({east_m: Math.round(P[i].x * 10) / 10, north_m: Math.round(P[i].y * 10) / 10,
                alt_m: Math.round(R.altAt(C[i]) * 10) / 10});
    return out;
  }
  /*ENDENGINE*/

  // -- the page's dark theme, as the index page spells it ------------------
  const TK = {
    bg: "#101418", surface: "#151b22", surface2: "#1d2733", line: "#232d38",
    fg: "#d8dde2", muted: "#7d8a93", route: "#ff5cb0", halo: "#1a0b14",
    flown: "#e2eeff", flownHalo: "rgba(8,14,22,.85)", physics: "#ffc861",
    ok: "#7fd08f", warn: "#e0b452", danger: "#e07a6f", mono: '"SF Mono", Menlo, monospace',
  };
  // The 3D placer's height ramp (camera3d.js rampColour), 0..1 of the
  // grid's relief, dimmed for the dark page.
  const RAMP = [[0, [0.29, 0.41, 0.23]], [0.4, [0.43, 0.46, 0.30]], [0.7, [0.50, 0.45, 0.39]],
                [0.88, [0.62, 0.60, 0.58]], [1, [0.93, 0.94, 0.96]]];
  function rampColour(t) {
    for (let i = 1; i < RAMP.length; i++) {
      if (t <= RAMP[i][0]) {
        const [t0, c0] = RAMP[i - 1], [t1, c1] = RAMP[i], f = (t - t0) / ((t1 - t0) || 1);
        return [0, 1, 2].map(k => 255 * (c0[k] + (c1[k] - c0[k]) * f));
      }
    }
    return RAMP[RAMP.length - 1][1].map(v => 255 * v);
  }

  const HINTS = {
    pen: "Drag from the aircraft to draw. Click to add a straight leg.",
    alt: "Click your line to set the altitude at that point.",
    pan: "Drag to move the map. Scroll or use + and − to zoom.",
  };

  class RouteMapView {
    constructor(opts, data) {
      this.opts = opts;
      this.data = data;
      this.grid = new Grid(data);
      this.lim = {...data.route, heading_deg: data.aircraft.heading_deg};
      const spec = (typeof opts.getSpec === "function" && opts.getSpec()) || {};
      const duration = spec.run && spec.run.duration ? +spec.run.duration.value : null;
      // The clock is the run's seconds; when the render's clip cap is the
      // shorter one the payload's seconds are the cap, and the page says so.
      this.clipCapped = duration != null && duration > this.lim.seconds + 1e-9;
      this.duration = duration;
      this.S = {strokes: [], pins: [], alt0: data.aircraft.alt_m, bank: data.route.bank_limit_deg,
                tool: "pen", adjusted: false};
      this.loadStated(data.route);
      this.view = {zoom: 1, ox: 0, oy: 0, lastMove: 0};
      this.hist = [];
      this.ghost = null;
      this.flown = null;
      this.anim = null;
      this.drawing = null;
      this.panning = null;
      this.pinEdit = null;
      this.raf = 0;
      this.terr = {key: ""};
      this.W = 1; this.H = 1; this.PW = 1; this.PH = 1; this.dpr = 1;
      this.mpp = 10; this.cx = 0; this.cy = 0; this.topPad = 56;
      this.build();
    }

    loadStated(route) {
      // A route the spec already states (drawn earlier and used) opens
      // as the line, with its altitude changes as altitude points.
      const wps = Array.isArray(route.waypoints) ? route.waypoints : [];
      if (!wps.length) return;
      const stroke = wps.map(w => ({x: +w.east_m, y: +w.north_m}));
      this.S.strokes = [stroke];
      const cum = cumLen([{x: 0, y: 0}, ...stroke]);
      let prev = this.S.alt0;
      wps.forEach((w, i) => {
        if (Math.abs(+w.alt_m - prev) > 1e-6) { this.S.pins.push({d: cum[i + 1], alt: +w.alt_m}); prev = +w.alt_m; }
      });
    }

    // -- DOM --------------------------------------------------------------
    build() {
      const root = this.opts.container;
      root.className = "card";
      const scene = this.data.scene || {};
      const lim = this.lim;
      root.innerHTML = `
<style>
  .rm-row { display: flex; gap: .8rem; flex-wrap: wrap; align-items: flex-start; }
  .rm-mapcol { flex: 1 1 480px; min-width: 300px; }
  .rm-rail { flex: 0 0 300px; max-width: 100%; display: flex; flex-direction: column; gap: .6rem; }
  @media (max-width: 760px) { .rm-rail { flex-basis: 100%; } }
  .rm-mapwrap { position: relative; height: 440px; border: 1px solid #232d38; border-radius: 6px;
                overflow: hidden; background: #0d1217; }
  .rm-map { display: block; width: 100%; height: 100%; touch-action: none; cursor: crosshair; }
  .rm-mapwrap[data-tool="alt"] .rm-map { cursor: copy; }
  .rm-mapwrap[data-tool="pan"] .rm-map { cursor: grab; }
  .rm-toolbar { position: absolute; top: 8px; left: 8px; right: 8px; display: flex; flex-wrap: wrap;
                gap: 4px; pointer-events: none; }
  .rm-group { display: flex; gap: 2px; padding: 2px; border-radius: 6px; background: rgba(21,27,34,.92);
              border: 1px solid #232d38; pointer-events: auto; }
  .rm-group button { padding: .2rem .5rem; margin: 0; background: transparent; color: #d8dde2;
                     border-radius: 4px; font-size: 12px; }
  .rm-group button:hover { background: #1d2733; }
  .rm-group button[aria-pressed="true"] { background: #ff5cb0; color: #22071a; }
  .rm-hud { position: absolute; right: 8px; top: 48px; padding: .3rem .5rem; border-radius: 6px;
            background: rgba(21,27,34,.92); border: 1px solid #232d38; font-size: 12px; }
  .rm-legend { position: absolute; left: 8px; bottom: 8px; max-width: calc(100% - 150px);
               padding: .35rem .5rem; border-radius: 6px; background: rgba(21,27,34,.9);
               border: 1px solid #232d38; font-size: 12px; display: flex; flex-direction: column; gap: 2px; }
  .rm-keys { display: flex; flex-wrap: wrap; gap: 2px 10px; color: #7d8a93; }
  .rm-keys span { display: flex; align-items: center; gap: 5px; }
  .rm-keys i { display: inline-block; width: 16px; height: 0; border-top: 3px solid #ff5cb0; }
  .rm-keys i.fl { border-top: 2px solid #e2eeff; }
  .rm-keys i.ph { border-top: 2px solid #ffc861; }
  .rm-keys i.rc { border-top: 1.5px dashed #e2eeff; }
  .rm-keys i.gh { border-top: 2px dotted #d8dde2; opacity: .7; }
  .rm-readout { color: #7d8a93; font-size: 11px; }
  .rm-pinpop { position: absolute; z-index: 3; display: flex; flex-wrap: wrap; align-items: center; gap: 5px;
               padding: .5rem; border-radius: 6px; background: #151b22; border: 1px solid #2c3947;
               font-size: 12px; width: 230px; }
  .rm-pinpop label { flex-basis: 100%; }
  .rm-pinpop input { width: 5.5rem; background: #171d24; color: inherit; border: 1px solid #2c3947;
                     border-radius: 4px; font: inherit; padding: .1rem .3rem; }
  .rm-pinpop button { padding: .2rem .6rem; }
  .rm-profile { margin-top: .5rem; border: 1px solid #232d38; border-radius: 6px; padding: .3rem .5rem;
                background: #0d1217; }
  .rm-profhead { display: flex; justify-content: space-between; gap: .8rem; flex-wrap: wrap; font-size: 11px;
                 color: #7d8a93; }
  .rm-prof { display: block; width: 100%; height: 110px; }
  .rm-box { border: 1px solid #232d38; border-radius: 6px; padding: .6rem .7rem; background: #121921; }
  .rm-box h4 { margin: 0 0 .4rem; font-size: 12px; letter-spacing: .08em; text-transform: uppercase;
               color: #9fb4c7; font-weight: normal; }
  .rm-meter .num { font-size: 22px; }
  .rm-bar { position: relative; height: 7px; margin: .4rem 0; border-radius: 4px; background: #1d2733;
            overflow: hidden; }
  .rm-bar span { position: absolute; top: 0; bottom: 0; left: 0; background: #ff5cb0; }
  .rm-bar span.over { background: repeating-linear-gradient(135deg, #e07a6f 0 4px, transparent 4px 7px);
                      left: auto; right: 0; }
  .rm-checks { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .5rem; }
  .rm-checks li { display: grid; grid-template-columns: 18px minmax(0, 1fr); gap: 1px 8px; }
  .rm-ic { grid-row: span 4; width: 18px; height: 18px; border-radius: 50%; display: grid; place-items: center;
           font-size: 11px; font-weight: bold; color: #101418; background: #7d8a93; }
  .rm-checks li[data-s="ok"] .rm-ic { background: #7fd08f; }
  .rm-checks li[data-s="warn"] .rm-ic { background: #e0b452; border-radius: 4px; }
  .rm-checks li[data-s="error"] .rm-ic { background: #e07a6f; border-radius: 3px; }
  .rm-checks .t { font-weight: bold; }
  .rm-checks .m { color: #a8b3bc; font-size: 12px; }
  .rm-rule { color: #7d8a93; font-size: 10px; }
  .rm-checks .act { justify-self: start; margin-top: 3px; padding: .15rem .5rem; font-size: 11px; }
  .rm-caveat { margin-top: .5rem; font-size: 11px; }
  .rm-adjrow { display: flex; flex-wrap: wrap; gap: .4rem .6rem; align-items: center; margin-top: .5rem;
               padding-top: .5rem; border-top: 1px solid #232d38; }
  .rm-adjrow:empty { display: none; }
  .rm-adjrow .note { color: #7d8a93; font-size: 11px; flex: 1 1 140px; }
  .rm-adjusted[data-s="ok"] { border-color: #7fd08f; }
  .rm-adjusted[data-s="error"], .rm-result[data-s="error"] { border-color: #e07a6f; }
  .rm-result[data-s="ok"] { border-color: #ffc861; }
  .rm-changes { margin: 0 0 .5rem; padding-left: 1.1rem; font-size: 12px; display: flex; flex-direction: column;
                gap: 3px; }
  .rm-kv { display: grid; grid-template-columns: auto 1fr; gap: 2px 10px; margin: .3rem 0; font-size: 12px; }
  .rm-kv dt { color: #7d8a93; }
  .rm-kv dd { margin: 0; text-align: right; }
  .rm-field { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; font-size: 12px; }
  .rm-field input { width: 4.5rem; background: #171d24; color: inherit; border: 1px solid #2c3947;
                    border-radius: 4px; font: inherit; padding: .1rem .3rem; }
  .rm-actions { display: flex; flex-wrap: wrap; gap: .4rem; }
  .rm-actions button { flex: 1 1 45%; padding: .4rem .5rem; }
  .rm-use { background: #2f7d4f; }
  .rm-warn { color: #e07a6f; }
  .rm-foot { color: #7d8a93; font-size: 11px; margin: .4rem 0 0; }
</style>
<div><b>Route map</b>
  <span class="dim">— ${esc(scene.label || this.data.kind)}</span></div>
<div class="dim" style="margin:.3rem 0">Draw the flight path from the aircraft with the pen,
  or click straight legs; the Altitude tool sets the altitude at a point on the line. North is
  up; X is east, Y is north, metres from the start, where the aircraft begins at its spec
  altitude and heads along the first leg. The ground is the scene the physics flies${
  this.grid.kind === "flat" ? `: this scene is flat, the datum at ${fmtN(this.grid.datum)} m everywhere`
  : `, hill-shaded with contour bands`}. The checks update as you draw; they are the
  browser's quick look, and <b>Check with the physics</b> flies the line for real.</div>
<div class="rm-row">
  <div class="rm-mapcol">
    <div class="rm-mapwrap" data-tool="pen">
      <canvas class="rm-map" tabindex="0" aria-label="Route map. Draw the flight path here."></canvas>
      <div class="rm-toolbar" role="toolbar" aria-label="Map tools">
        <div class="rm-group">
          <button class="rm-tool" data-tool="pen" aria-pressed="true" title="Draw the path (P)">Pen</button>
          <button class="rm-tool" data-tool="alt" aria-pressed="false" title="Set an altitude on the line (A)">Altitude</button>
          <button class="rm-tool" data-tool="pan" aria-pressed="false" title="Move the map (M)">Move</button>
        </div>
        <div class="rm-group">
          <button class="rm-out" title="Zoom out (−)">−</button>
          <button class="rm-in" title="Zoom in (+)">+</button>
          <button class="rm-fit" title="Zoom to your line">Fit line</button>
          <button class="rm-reach" title="Zoom out to everywhere the aircraft can reach">Show reach</button>
        </div>
        <div class="rm-group">
          <button class="rm-undo" title="Undo (Ctrl+Z)">Undo</button>
          <button class="rm-clear">Clear</button>
        </div>
      </div>
      <div class="rm-hud" hidden></div>
      <div class="rm-legend">
        <div class="rm-hint">${HINTS.pen}</div>
        <div class="rm-keys"><span><i></i>Your line</span><span><i class="fl"></i>Quick look (browser)</span>
          <span class="rm-legphys" hidden><i class="ph"></i>Flown by the physics</span>
          <span><i class="rc"></i>Farthest it can get</span>
          <span class="rm-legghost" hidden><i class="gh"></i>As drawn, before self adjust</span></div>
        <div class="rm-readout"></div>
      </div>
      <div class="rm-pinpop" hidden>
        <label>Altitude at this point</label>
        <input class="rm-pinalt" type="number" step="${PIN_STEP_M}"> <span>m MSL</span>
        <button class="rm-pinsave">Set</button>
        <button class="rm-pindel opt">Remove</button>
      </div>
    </div>
    <div class="rm-profile">
      <div class="rm-profhead"><span>altitude along the quick-look track</span><span class="rm-profnote"></span></div>
      <canvas class="rm-prof" aria-label="Altitude profile: flight altitude over the ground below the track"></canvas>
    </div>
  </div>
  <div class="rm-rail">
    <div class="rm-box rm-meter"></div>
    <div class="rm-box">
      <h4>Checks</h4>
      <ul class="rm-checks"></ul>
      <div class="rm-caveat dim"></div>
      <div class="rm-adjrow"></div>
    </div>
    <div class="rm-box rm-adjusted" hidden aria-live="polite"></div>
    <div class="rm-box">
      <h4>Flight</h4>
      <div class="rm-field"><label>bank limit <input class="rm-bank" type="number" step="5" value="${esc(lim.bank_limit_deg)}"> °</label>
        <span class="dim">served ${esc(lim.bank_limit_deg)}° (the autopilot's)</span></div>
      <div class="rm-field dim" style="margin-top:.3rem">${esc(fmtN(lim.tas_kt))} kt true · ${esc(fmtN(lim.seconds))} s
        ${this.clipCapped ? `(the render's ${esc(fmtN(lim.seconds))} s clip; the duration is ${esc(fmtN(this.duration))} s)` : ""}
        · start ${esc(fmtN(this.S.alt0))} m MSL</div>
    </div>
    <div class="rm-actions">
      <button class="rm-preview opt">Preview</button>
      <button class="rm-physics">Check with the physics</button>
      <button class="rm-use">Use this path</button>
      <button class="rm-close opt">Close</button>
    </div>
    <div class="rm-box rm-result" hidden aria-live="polite"></div>
    <div class="rm-state dim"></div>
  </div>
</div>`;
      const $ = sel => root.querySelector(sel);
      this.$ = $;
      this.mapEl = $(".rm-map");
      this.wrapEl = $(".rm-mapwrap");
      this.profEl = $(".rm-prof");
      this.mctx = this.mapEl.getContext("2d");
      this.pctx = this.profEl.getContext("2d");
      root.querySelectorAll(".rm-tool").forEach(b => b.onclick = () => this.setTool(b.dataset.tool));
      $(".rm-in").onclick = () => this.setZoom(this.view.zoom * 1.5);
      $(".rm-out").onclick = () => this.setZoom(this.view.zoom / 1.5);
      $(".rm-fit").onclick = () => this.fitLine();
      $(".rm-reach").onclick = () => this.showReach();
      $(".rm-undo").onclick = () => this.undo();
      $(".rm-clear").onclick = () => this.clear();
      $(".rm-pinsave").onclick = () => this.savePin();
      $(".rm-pindel").onclick = () => this.deletePin();
      $(".rm-pinalt").addEventListener("keydown", e => {
        if (e.key === "Enter") this.savePin();
        if (e.key === "Escape") this.closePin();
      });
      $(".rm-bank").addEventListener("change", () => {
        const v = +$(".rm-bank").value;
        if (!Number.isFinite(v) || v <= 0) return;
        this.S.bank = v;
        this.onSetting();
      });
      $(".rm-preview").onclick = () => { if (this.anim && !this.anim.done) this.stopPreview(); else { this.stopPreview(); this.startPreview(); } };
      $(".rm-physics").onclick = () => this.physicsCheck();
      $(".rm-use").onclick = () => this.usePath();
      $(".rm-close").onclick = () => this.close();
      $(".rm-adjrow").addEventListener("click", e => { if (e.target.closest(".rm-adjust")) this.runAdjust(); });
      $(".rm-checks").addEventListener("click", e => {
        const b = e.target.closest("button[data-i]");
        if (!b) return;
        const c = this.R.checks[+b.dataset.i];
        if (c && c.act) { Object.assign(this.S, c.act.set); $(".rm-bank").value = this.S.bank; this.onSetting(); }
      });
      this.bindPointer();
      this.onKey = e => {
        if (!root.isConnected) return;
        if (e.target.closest("input,select,textarea")) return;
        if (!root.contains(e.target) && e.target !== document.body) return;
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); this.undo(); }
        else if (e.key === "p" || e.key === "P") this.setTool("pen");
        else if (e.key === "a" || e.key === "A") this.setTool("alt");
        else if (e.key === "m" || e.key === "M") this.setTool("pan");
        else if (e.key === "+" || e.key === "=") this.setZoom(this.view.zoom * 1.5);
        else if (e.key === "-" || e.key === "_") this.setZoom(this.view.zoom / 1.5);
        else if (e.key === "Escape") this.closePin();
      };
      document.addEventListener("keydown", this.onKey);
      this.resizer = new ResizeObserver(() => this.layout());
      this.resizer.observe(this.wrapEl);
      this.resizer.observe(this.profEl);
      this.update();
      this.layout();
      if (this.S.strokes.length) this.fitLine();
    }

    // -- state ----------------------------------------------------------
    snap() { return JSON.stringify({strokes: this.S.strokes, pins: this.S.pins, alt0: this.S.alt0, adjusted: this.S.adjusted}); }
    pushHist() { this.hist.push(this.snap()); if (this.hist.length > 60) this.hist.shift(); }
    dropGhost() { this.ghost = null; this.$(".rm-legghost").hidden = true; this.$(".rm-adjusted").hidden = true; }
    update() {
      this.R = compute(this.S, this.lim, this.grid);
      this.fitMap();
      this.renderRail();
      this.drawProf();
      this.render();
    }
    // A changed bank re-checks the same line: its provenance (self-adjusted
    // or not) is the line's, so it stays.
    onSetting() { this.closePin(); this.stopPreview(); this.clearResult(); this.dropGhost(); this.update(); }
    undo() {
      if (!this.hist.length) return;
      const s = JSON.parse(this.hist.pop());
      this.S.strokes = s.strokes; this.S.pins = s.pins; this.S.alt0 = s.alt0; this.S.adjusted = s.adjusted;
      this.dropGhost(); this.closePin(); this.stopPreview(); this.clearResult(); this.update();
    }
    clear() {
      if (!this.S.strokes.length && !this.S.pins.length) return;
      this.pushHist();
      this.S.strokes = []; this.S.pins = []; this.S.adjusted = false;
      this.dropGhost(); this.closePin(); this.stopPreview(); this.clearResult(); this.update();
    }
    setTool(t) {
      this.S.tool = t;
      this.wrapEl.dataset.tool = t;
      this.opts.container.querySelectorAll(".rm-tool").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.tool === t)));
      this.$(".rm-hint").textContent = HINTS[t];
      this.closePin();
    }

    // -- the rail ---------------------------------------------------------
    renderRail() {
      const R = this.R, S = this.S, lim = this.lim, $ = this.$;
      const over = R.len > R.reach, pct = R.reach ? Math.min(R.len / R.reach, 1) * 100 : 0;
      const overPct = over ? Math.min((R.len - R.reach) / R.len * 100, 100) : 0;
      $(".rm-meter").innerHTML = `<h4>Path length</h4>
        <div><span class="num">${km(R.len)}</span> <span class="dim">drawn, of ${km(R.reach)} in ${fmtT(R.T)}</span></div>
        <div class="rm-bar" role="img" aria-label="${Math.round(R.len / (R.reach || 1) * 100)}% of the distance available">${
          over ? `<span style="width:${100 - overPct}%"></span><span class="over" style="width:${overPct}%"></span>`
               : `<span style="width:${pct}%"></span>`}</div>
        <div class="dim" style="font-size:11px">${fmtN(lim.tas_kt)} kt true × ${fmtN(R.T)} s = ${km(R.reach)}${
          this.clipCapped ? ` (the render's ${fmtN(R.T)} s clip)` : ""}<br>
          Tightest turn at ${fmtN(S.bank)}° bank: ${m(R.Rmin)}</div>`;
      const icon = {ok: "✓", warn: "!", error: "×", idle: "·"};
      $(".rm-checks").innerHTML = R.checks.map((c, i) =>
        `<li data-s="${c.s}" data-rule="${c.id}"><span class="rm-ic" aria-hidden="true">${icon[c.s]}</span>` +
        `<span class="t">${esc(c.t)}</span><span class="m">${esc(c.m)}</span>` +
        `<span class="rm-rule">${esc(c.id)}</span>` +
        (c.act ? `<button class="act opt" data-i="${i}">${esc(c.act.label)}</button>` : "")).join("");
      // Said once, here, not under every check.
      $(".rm-caveat").textContent = `Ground clearance is measured on the map's grid` + (this.grid.kind === "flat"
        ? `: this scene is flat, the datum at ${fmtN(this.grid.datum)} m everywhere. The physics check measures it on the raster.`
        : ` (${fmtN(this.grid.step)} m cells); the physics check measures it on the raster, and the two can disagree near a ridge.`);
      const probs = R.checks.filter(c => c.s === "warn" || c.s === "error").length;
      $(".rm-adjrow").innerHTML = R.empty ? "" : probs
        ? `<button class="rm-adjust">Self adjust</button><span class="note">Moves your line as little as ` +
          `needed so every check passes. Undo brings the drawn line back.</span>`
        : `<span class="note">Every check passes.</span>`;
    }

    // -- pointer ----------------------------------------------------------
    local(e) { const r = this.mapEl.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
    bindPointer() {
      const el = this.mapEl;
      el.addEventListener("contextmenu", e => e.preventDefault());
      el.addEventListener("pointerdown", e => {
        const [px, py] = this.local(e);
        if (e.button !== 0 || this.S.tool === "pan") {
          this.panning = {px, py, ox: this.view.ox, oy: this.view.oy};
          el.setPointerCapture(e.pointerId);
          this.closePin();
          e.preventDefault();
          return;
        }
        this.stopPreview();
        if (this.S.tool === "pen") {
          this.closePin();
          this.drawing = {pts: [this.toW(px, py)], px: [[px, py]]};
          el.setPointerCapture(e.pointerId);
        } else this.pickPin(px, py);
      });
      el.addEventListener("pointermove", e => {
        const [px, py] = this.local(e);
        this.readout(px, py);
        if (this.panning) {
          this.view.ox = this.panning.ox - (px - this.panning.px) * this.mpp;
          this.view.oy = this.panning.oy + (py - this.panning.py) * this.mpp;
          this.view.lastMove = performance.now();
          this.fitMap(); this.render();
          return;
        }
        if (!this.drawing) return;
        const l = this.drawing.px[this.drawing.px.length - 1];
        if (Math.hypot(px - l[0], py - l[1]) < 2.5) return;
        this.drawing.px.push([px, py]);
        this.drawing.pts.push(this.toW(px, py));
        this.render();
      });
      const end = () => this.endStroke();
      el.addEventListener("pointerup", end);
      el.addEventListener("pointercancel", end);
      el.addEventListener("pointerleave", () => { if (!this.drawing) this.$(".rm-readout").textContent = ""; });
      el.addEventListener("wheel", e => {
        e.preventDefault();
        const [px, py] = this.local(e);
        this.setZoom(this.view.zoom * Math.exp(-e.deltaY * 0.0015), px, py);
      }, {passive: false});
    }
    endStroke() {
      if (this.panning) { this.panning = null; this.render(); return; }
      if (!this.drawing) return;
      const d = this.drawing;
      this.drawing = null;
      let len = 0;
      for (let i = 1; i < d.px.length; i++) len += Math.hypot(d.px[i][0] - d.px[i - 1][0], d.px[i][1] - d.px[i - 1][1]);
      // A short press is a click: one straight leg to that point.
      const stroke = len < 6 ? [d.pts[d.pts.length - 1]] : rdp(d.pts, 1.6 * this.mpp);
      this.pushHist();
      this.dropGhost();
      this.S.strokes.push(stroke);
      this.S.adjusted = false;
      this.clearResult();
      this.update();
    }
    readout(px, py) {
      const w = this.toW(px, py);
      const inside = this.grid.contains(w.y, w.x);
      this.$(".rm-readout").textContent = `X ${fmtN(w.x)} m east · Y ${fmtN(w.y)} m north · ` +
        (inside ? `ground ${fmtN(this.grid.elevation(w.y, w.x))} m MSL` : "outside the map's grid");
    }

    // -- altitude pins ----------------------------------------------------
    pointAt(d) {
      const c = this.R.path.cum, p = this.R.path.pts;
      let i = 0;
      while (i < c.length - 1 && c[i + 1] < d) i++;
      if (i >= c.length - 1) return p[p.length - 1];
      const t = (d - c[i]) / ((c[i + 1] - c[i]) || 1);
      return {x: p[i].x + (p[i + 1].x - p[i].x) * t, y: p[i].y + (p[i + 1].y - p[i].y) * t};
    }
    pickPin(px, py) {
      const R = this.R;
      if (!R.path) return;
      for (let k = 0; k < this.S.pins.length; k++) {
        const q = this.pointAt(this.S.pins[k].d), [qx, qy] = this.toPx(q.x, q.y);
        if (Math.hypot(qx - px, qy - py) < 14) { this.openPin(k, this.S.pins[k].d, qx, qy); return; }
      }
      let best = -1, bd = 16;
      R.path.pts.forEach((p, i) => {
        const [x, y] = this.toPx(p.x, p.y), d = Math.hypot(x - px, y - py);
        if (d < bd) { bd = d; best = i; }
      });
      if (best < 0) { this.$(".rm-hint").textContent = "Click closer to your line to set an altitude there."; return; }
      const [qx, qy] = this.toPx(R.path.pts[best].x, R.path.pts[best].y);
      this.openPin(-1, R.path.cum[best], qx, qy);
    }
    openPin(k, d, qx, qy) {
      this.pinEdit = {k, d};
      const pop = this.$(".rm-pinpop"), input = this.$(".rm-pinalt");
      input.value = Math.round(this.R.altAt(d) / PIN_STEP_M) * PIN_STEP_M;
      pop.querySelector("label").textContent = `Altitude ${km(d)} along the line`;
      this.$(".rm-pindel").hidden = k < 0;
      pop.hidden = false;
      const pw = pop.offsetWidth, ph = pop.offsetHeight;
      pop.style.left = clamp(qx - pw / 2, 8, this.W - pw - 8) + "px";
      pop.style.top = (qy - ph - 14 > this.topPad ? qy - ph - 14 : Math.min(qy + 14, this.H - ph - 8)) + "px";
      input.focus(); input.select();
    }
    closePin() { this.$(".rm-pinpop").hidden = true; this.pinEdit = null; }
    savePin() {
      if (!this.pinEdit) return;
      const v = Math.round((+this.$(".rm-pinalt").value || 0) / PIN_STEP_M) * PIN_STEP_M;
      this.pushHist(); this.dropGhost();
      if (this.pinEdit.k >= 0) this.S.pins[this.pinEdit.k].alt = v;
      else this.S.pins.push({d: this.pinEdit.d, alt: v});
      this.S.adjusted = false;
      this.closePin(); this.clearResult(); this.update();
    }
    deletePin() {
      if (!this.pinEdit || this.pinEdit.k < 0) return;
      this.pushHist(); this.dropGhost();
      this.S.pins.splice(this.pinEdit.k, 1);
      this.closePin(); this.clearResult(); this.update();
    }

    // -- layout -------------------------------------------------------------
    toPx(x, y) { return [this.cx + x / this.mpp, this.cy - y / this.mpp]; }
    toW(px, py) { return {x: (px - this.cx) * this.mpp, y: (this.cy - py) * this.mpp}; }
    layout() {
      this.dpr = window.devicePixelRatio || 1;
      const r = this.wrapEl.getBoundingClientRect();
      this.W = Math.max(1, Math.round(r.width)); this.H = Math.max(1, Math.round(r.height));
      this.mapEl.width = Math.round(this.W * this.dpr); this.mapEl.height = Math.round(this.H * this.dpr);
      const pr = this.profEl.getBoundingClientRect();
      this.PW = Math.max(1, Math.round(pr.width)); this.PH = Math.max(1, Math.round(pr.height));
      this.profEl.width = Math.round(this.PW * this.dpr); this.profEl.height = Math.round(this.PH * this.dpr);
      this.topPad = this.$(".rm-toolbar").offsetHeight + 16;
      this.fitMap(); this.drawProf(); this.render();
    }
    // Zoom 1 fits the reach circle; the view centre (ox, oy) is in metres
    // from the start.
    baseMpp() {
      return 2 * this.R.reach * 1.06 / Math.max(120, Math.min(this.W - 24, this.H - this.topPad - 28));
    }
    scx() { return this.W / 2; }
    scy() { return this.topPad + (this.H - this.topPad) / 2; }
    fitMap() {
      if (!this.R) return;
      this.mpp = this.baseMpp() / this.view.zoom;
      this.cx = this.scx() - this.view.ox / this.mpp;
      this.cy = this.scy() + this.view.oy / this.mpp;
    }
    setZoom(z, px, py) {
      const ax = px ?? this.scx(), ay = py ?? this.scy(), w = this.toW(ax, ay);
      this.view.zoom = clamp(z, 0.5, 40);
      this.mpp = this.baseMpp() / this.view.zoom;
      this.view.ox = w.x - (ax - this.scx()) * this.mpp;
      this.view.oy = w.y + (ay - this.scy()) * this.mpp;
      this.view.lastMove = performance.now();
      this.fitMap(); this.render();
      setTimeout(() => this.render(), 200);
    }
    fitLine() {
      const R = this.R;
      if (!R || this.W < 2) return;
      let x0 = 0, x1 = 0, y0 = 0, y1 = 0;
      const add = p => { x0 = Math.min(x0, p.x); x1 = Math.max(x1, p.x); y0 = Math.min(y0, p.y); y1 = Math.max(y1, p.y); };
      if (R.path) R.path.pts.forEach(add);
      const sm = R.sim.samples;
      const cut = R.path ? Math.min(sm.length, Math.ceil(R.len / R.V / R.sim.dt) + 1) : sm.length;
      for (let i = 0; i < cut; i++) add(sm[i]);
      const pad = 4 * R.step;
      const need = Math.max((x1 - x0 + pad) / Math.max(60, this.W - 40), (y1 - y0 + pad) / Math.max(60, this.H - this.topPad - 90));
      this.view.zoom = clamp(this.baseMpp() / need, 0.5, 40);
      this.view.ox = (x0 + x1) / 2; this.view.oy = (y0 + y1) / 2 - 30 * need;
      this.fitMap(); this.render();
    }
    showReach() { this.view.zoom = 1; this.view.ox = 0; this.view.oy = 0; this.fitMap(); this.render(); }

    // -- the ground: hill-shaded relief with contour bands, from the grid
    ensureTerrain() {
      const moving = this.panning || performance.now() - this.view.lastMove < 150;
      const c = moving ? 4 : 2;
      const key = `${this.W}x${this.H}@${this.mpp.toFixed(4)}|${this.cx.toFixed(1)}|${this.cy.toFixed(1)}|${c}`;
      if (this.terr.key === key) return;
      if (moving) setTimeout(() => this.render(), 170);
      const gw = Math.ceil(this.W / c) + 1, gh = Math.ceil(this.H / c) + 1, cm = c * this.mpp;
      const hs = new Float32Array(gw * gh), inside = new Uint8Array(gw * gh), grid = this.grid;
      for (let j = 0; j < gh; j++) for (let i = 0; i < gw; i++) {
        const w = this.toW(i * c, j * c);
        hs[j * gw + i] = grid.elevation(w.y, w.x);
        inside[j * gw + i] = grid.contains(w.y, w.x) ? 1 : 0;
      }
      const relief = grid.hi - grid.lo;
      // Contour interval: a band every ~1/12 of the relief, on a chart
      // tick; a flat scene has none.
      const I = relief > 0 ? ([10, 20, 50, 100, 200, 500, 1000].find(v => v >= relief / 12) || 1000) : 0;
      const MJ = I * 5;
      const img = new ImageData(gw, gh), D = img.data;
      // Light from the north-west, the cartographic convention.
      const Lx = -0.5, Ly = 0.5, Lz = Math.SQRT1_2;
      for (let j = 0; j < gh; j++) for (let i = 0; i < gw; i++) {
        const k = j * gw + i, h = hs[k];
        const hl = hs[j * gw + Math.max(0, i - 1)], hr = hs[j * gw + Math.min(gw - 1, i + 1)];
        const hu = hs[Math.max(0, j - 1) * gw + i], hd = hs[Math.min(gh - 1, j + 1) * gw + i];
        const dzdx = (hr - hl) / (2 * cm), dzdy = (hu - hd) / (2 * cm);
        const nl = Math.hypot(dzdx, dzdy, 1), shade = Math.max(0, (-dzdx * Lx - dzdy * Ly + Lz) / nl);
        let t = relief > 0 ? (h - grid.lo) / relief : 0;
        if (relief <= 600) t *= 0.6;
        const col = rampColour(t);
        let b = (0.42 + 0.78 * shade) * 0.72;
        if (I) {
          const f = Math.floor(h / I);
          if (f !== Math.floor(hr / I) || f !== Math.floor(hd / I))
            b *= Math.floor(h / MJ) !== Math.floor(hr / MJ) || Math.floor(h / MJ) !== Math.floor(hd / MJ) ? 0.6 : 0.8;
        }
        if (!inside[k]) b *= 0.35;
        D[4 * k] = clamp(col[0] * b * 0.92, 0, 255); D[4 * k + 1] = clamp(col[1] * b, 0, 255);
        D[4 * k + 2] = clamp(col[2] * b * 1.1, 0, 255); D[4 * k + 3] = 255;
      }
      const off = this.terr.canvas || document.createElement("canvas");
      off.width = gw; off.height = gh;
      off.getContext("2d").putImageData(img, 0, 0);
      this.terr = {key, canvas: off, gw, gh, I, c};
    }

    // -- drawing -------------------------------------------------------------
    render() { if (!this.raf) this.raf = requestAnimationFrame(() => { this.raf = 0; this.draw(); }); }
    txt(c, s, x, y, o = {}) {
      c.font = o.font || `11px ${TK.mono}`; c.textAlign = o.align || "left"; c.textBaseline = o.base || "middle";
      c.lineJoin = "round"; c.lineWidth = o.hw || 3.5; c.strokeStyle = o.halo || TK.bg; c.strokeText(s, x, y);
      c.fillStyle = o.color || TK.fg; c.fillText(s, x, y);
    }
    pill(c, s, x, y, color) {
      c.font = `bold 11px ${TK.mono}`;
      const w = c.measureText(s).width + 14, h = 20;
      const bx = clamp(x - w / 2, 4, this.W - w - 4), by = clamp(y - h / 2, this.topPad, this.H - h - 4);
      c.beginPath(); c.roundRect(bx, by, w, h, 5); c.fillStyle = TK.surface; c.fill();
      c.lineWidth = 1.5; c.strokeStyle = color; c.stroke();
      c.fillStyle = color; c.textAlign = "left"; c.textBaseline = "middle"; c.fillText(s, bx + 7, by + h / 2 + 0.5);
    }
    poly(c, pts, a, b) {
      c.beginPath();
      for (let i = a; i <= b; i++) { const [x, y] = this.toPx(pts[i].x, pts[i].y); i === a ? c.moveTo(x, y) : c.lineTo(x, y); }
    }
    planeIcon(c, x, y, psi, phi, size) {
      c.save(); c.translate(x, y); c.rotate(psi);
      const s = size / 22;
      c.scale(s * Math.max(0.55, Math.cos(phi || 0)), s);
      c.beginPath(); c.moveTo(0, -11); c.bezierCurveTo(1.6, -11, 1.8, -7, 1.8, -5); c.lineTo(1.8, -2.5); c.lineTo(11, 2);
      c.lineTo(11, 4.2); c.lineTo(1.8, 2.6); c.lineTo(1.3, 7.5); c.lineTo(4.4, 9.6); c.lineTo(4.4, 11); c.lineTo(0, 10.2);
      c.lineTo(-4.4, 11); c.lineTo(-4.4, 9.6); c.lineTo(-1.3, 7.5); c.lineTo(-1.8, 2.6); c.lineTo(-11, 4.2); c.lineTo(-11, 2);
      c.lineTo(-1.8, -2.5); c.lineTo(-1.8, -5); c.bezierCurveTo(-1.8, -7, -1.6, -11, 0, -11); c.closePath();
      c.lineWidth = 3 / s; c.strokeStyle = TK.flownHalo; c.stroke(); c.fillStyle = TK.flown; c.fill(); c.restore();
    }
    niceLen(px) {
      const target = px * this.mpp, cands = [50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000];
      let best = cands[0];
      for (const v of cands) if (v <= target) best = v;
      return best;
    }
    draw() {
      const R = this.R;
      if (!R) return;
      const c = this.mctx, W = this.W, H = this.H;
      c.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      c.clearRect(0, 0, W, H);
      this.ensureTerrain();
      c.imageSmoothingEnabled = true;
      c.drawImage(this.terr.canvas, 0, 0, this.terr.gw * this.terr.c, this.terr.gh * this.terr.c);
      const [px0, py0] = this.toPx(0, 0), rr = R.reach / this.mpp;
      // The reach circle.
      c.save(); c.globalAlpha = 0.75; c.setLineDash([7, 6]); c.lineWidth = 1.6; c.strokeStyle = TK.flown;
      c.beginPath(); c.arc(px0, py0, rr, 0, Math.PI * 2); c.stroke(); c.restore();
      // Labelled at the circle's foot: the flag of a northbound run sits at its top.
      this.txt(c, `farthest in ${fmtT(R.T)} · ${km(R.reach)}`, px0, py0 + rr + 12, {align: "center"});
      // The line as drawn, before self adjust.
      const ghost = this.ghost;
      if (ghost && ghost.length > 1) {
        c.save(); c.setLineDash([2, 5]); c.lineCap = "round"; c.lineWidth = 2.5; c.strokeStyle = TK.fg; c.globalAlpha = 0.6;
        this.poly(c, ghost, 0, ghost.length - 1); c.stroke(); c.restore();
      }
      // The drawn line, dimmed past the reach.
      if (R.path) {
        const P = R.path.pts, C = R.path.cum;
        let ri = C.findIndex(v => v > R.reach);
        if (ri < 0) ri = P.length;
        c.lineCap = "round"; c.lineJoin = "round";
        if (ri < P.length) {
          this.poly(c, P, Math.max(0, ri - 1), P.length - 1);
          c.setLineDash([6, 6]); c.lineWidth = 3; c.strokeStyle = TK.muted; c.stroke(); c.setLineDash([]);
        }
        if (ri > 1) {
          this.poly(c, P, 0, ri - 1);
          c.lineWidth = 8; c.strokeStyle = TK.halo; c.globalAlpha = 0.85; c.stroke(); c.globalAlpha = 1;
          c.lineWidth = 5; c.strokeStyle = TK.route; c.stroke();
        }
      }
      // The quick-look track.
      const sm = R.sim.samples, last = sm.length - 1, anim = this.anim;
      const prog = anim ? clamp(Math.round(anim.t / R.sim.dt), 0, last) : last;
      c.lineCap = "round"; c.lineJoin = "round";
      this.poly(c, sm, 0, last);
      c.lineWidth = 3.6; c.strokeStyle = TK.flownHalo; c.stroke();
      c.lineWidth = 1.6; c.strokeStyle = TK.flown; c.globalAlpha = anim ? 0.35 : 1; c.stroke(); c.globalAlpha = 1;
      if (anim && prog > 0) { this.poly(c, sm, 0, prog); c.lineWidth = 2.6; c.strokeStyle = TK.flown; c.stroke(); }
      // The physics' track, when the server flew the line.
      if (this.flown && this.flown.length > 1) {
        this.poly(c, this.flown, 0, this.flown.length - 1);
        c.lineWidth = 4; c.strokeStyle = TK.flownHalo; c.stroke();
        c.lineWidth = 2.2; c.strokeStyle = TK.physics; c.stroke();
      }
      // Time ticks.
      const every = R.T <= 30 ? 5 : R.T <= 90 ? 10 : R.T <= 240 ? 30 : 60;
      for (let t = every; t < R.T - every * 0.4; t += every) {
        const s = sm[Math.round(t / R.sim.dt)];
        if (!s) continue;
        const [x, y] = this.toPx(s.x, s.y);
        c.beginPath(); c.arc(x, y, 3.2, 0, Math.PI * 2); c.fillStyle = TK.flown; c.fill();
        c.lineWidth = 1.5; c.strokeStyle = TK.flownHalo; c.stroke();
        const nx = Math.cos(s.psi), ny = Math.sin(s.psi);
        this.txt(c, fmtT(t), x + nx * 10, y + ny * 10, {font: `10px ${TK.mono}`, align: nx >= 0 ? "left" : "right"});
      }
      // The end flag.
      {
        const s = sm[last], [x, y] = this.toPx(s.x, s.y);
        c.lineWidth = 2; c.strokeStyle = TK.flown; c.beginPath(); c.moveTo(x, y); c.lineTo(x, y - 20); c.stroke();
        c.beginPath(); c.moveTo(x, y - 20); c.lineTo(x + 12, y - 16); c.lineTo(x, y - 12); c.closePath();
        c.fillStyle = TK.route; c.fill();
        this.txt(c, `${fmtT(R.T)} ends`, x + 15, y - 15, {font: `bold 10px ${TK.mono}`});
      }
      // Turn markers.
      for (const k of R.turns.markers) {
        const [x, y] = this.toPx(k.x, k.y);
        c.beginPath(); c.arc(x, y, 13, 0, Math.PI * 2); c.lineWidth = 3; c.strokeStyle = TK.warn;
        c.setLineDash([4, 3]); c.stroke(); c.setLineDash([]);
        this.pill(c, `turn ${m(k.R)} · needs ${m(R.Rmin)}`, x, y - 28, TK.warn);
      }
      // The clearance marker.
      if (R.minClr < this.lim.min_clearance_m && R.minS) {
        const s = R.minS, [x, y] = this.toPx(s.x, s.y);
        c.beginPath(); c.moveTo(x, y - 10); c.lineTo(x + 9, y + 6); c.lineTo(x - 9, y + 6); c.closePath();
        c.fillStyle = TK.danger; c.lineWidth = 3; c.strokeStyle = TK.surface; c.stroke(); c.fill();
        this.txt(c, "!", x, y + 1.5, {font: `bold 11px ${TK.mono}`, color: TK.surface, halo: TK.danger, hw: 0.1, align: "center"});
        this.pill(c, R.minClr < 0 ? `hits ${fmtN(s.terr)} m ground at ${fmtT(s.t)}` : `${m(R.minClr)} above ground at ${fmtT(s.t)}`,
                  x, y + 22, TK.danger);
      }
      // Altitude points.
      for (const p of R.pins) {
        const q = this.pointAt(p.d), [x, y] = this.toPx(q.x, q.y);
        c.beginPath(); c.moveTo(x, y - 7); c.lineTo(x + 7, y); c.lineTo(x, y + 7); c.lineTo(x - 7, y); c.closePath();
        c.fillStyle = TK.surface; c.fill(); c.lineWidth = 2.5; c.strokeStyle = TK.route; c.stroke();
        this.pill(c, `${fmtN(p.alt)} m`, x, y - 20, TK.route);
      }
      // The live stroke.
      if (this.drawing && this.drawing.px.length > 1) {
        c.beginPath(); this.drawing.px.forEach(([x, y], i) => i ? c.lineTo(x, y) : c.moveTo(x, y));
        c.lineWidth = 4; c.strokeStyle = TK.route; c.globalAlpha = 0.8; c.stroke(); c.globalAlpha = 1;
      }
      // The aircraft.
      if (anim) { const s = sm[prog], [x, y] = this.toPx(s.x, s.y); this.planeIcon(c, x, y, s.psi, s.phi, 28); }
      else this.planeIcon(c, px0, py0, R.psi0, 0, 28);
      // North arrow.
      {
        const x = W - 26, y = this.topPad + 16;
        c.beginPath(); c.moveTo(x, y - 12); c.lineTo(x + 6, y + 6); c.lineTo(x, y + 2); c.lineTo(x - 6, y + 6); c.closePath();
        c.fillStyle = TK.fg; c.lineWidth = 3; c.strokeStyle = TK.bg; c.stroke(); c.fill();
        this.txt(c, "N", x, y + 16, {align: "center", font: `bold 11px ${TK.mono}`});
      }
      // Scale bar.
      {
        const len = this.niceLen(110), px = len / this.mpp, x1 = W - 14, x0 = x1 - px, y = H - 22;
        c.fillStyle = TK.surface; c.globalAlpha = 0.85; c.fillRect(x0 - 6, y - 18, px + 12, 30); c.globalAlpha = 1;
        c.fillStyle = TK.fg; c.fillRect(x0, y, px, 4); c.fillStyle = TK.surface;
        c.fillRect(x0 + px / 4, y + 1, px / 4, 2); c.fillRect(x0 + 3 * px / 4, y + 1, px / 4 - 1, 2);
        this.txt(c, len >= 1000 ? `${len / 1000} km` : `${len} m`, x1, y - 8, {align: "right", font: `10px ${TK.mono}`});
      }
    }

    drawProf() {
      const R = this.R;
      if (!R) return;
      const c = this.pctx, PW = this.PW, PH = this.PH, floor = this.lim.min_clearance_m;
      c.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      c.clearRect(0, 0, PW, PH);
      const s = R.sim.samples, l = 48, r = 10, t = 8, b = 18, iw = PW - l - r, ih = PH - t - b;
      let lo = Infinity, hi = -Infinity;
      for (const q of s) { lo = Math.min(lo, q.terr); hi = Math.max(hi, q.alt, q.terr + floor); }
      const span = Math.max(hi - lo, 1), gs = [50, 100, 200, 500, 1000, 2000].find(v => v >= span / 5) || 2000;
      lo = Math.floor((lo - span * 0.1) / gs) * gs; hi = Math.ceil((hi + span * 0.1) / gs) * gs;
      const X = v => l + v / R.T * iw, Y = h => t + (hi - h) / (hi - lo) * ih;
      c.font = `10px ${TK.mono}`; c.textBaseline = "middle";
      for (let h = lo; h <= hi; h += gs) {
        c.strokeStyle = TK.line; c.lineWidth = 1; c.beginPath(); c.moveTo(l, Y(h) + 0.5); c.lineTo(PW - r, Y(h) + 0.5); c.stroke();
        c.fillStyle = TK.muted; c.textAlign = "right"; c.fillText(fmtN(h), l - 6, Y(h));
      }
      // The ground.
      c.beginPath(); c.moveTo(X(0), Y(lo));
      for (const q of s) c.lineTo(X(q.t), Y(q.terr));
      c.lineTo(X(R.T), Y(lo)); c.closePath(); c.fillStyle = "#3a3a36"; c.fill();
      // Where the track is under the floor.
      c.fillStyle = TK.danger; c.globalAlpha = 0.4;
      for (const q of s) if (q.clr < floor) c.fillRect(X(q.t) - 1, Y(q.terr + floor), 2.5, Math.max(1, Y(Math.min(q.alt, q.terr + floor)) - Y(q.terr + floor)));
      c.globalAlpha = 1;
      // The floor.
      c.setLineDash([3, 3]); c.beginPath();
      s.forEach((q, i) => i ? c.lineTo(X(q.t), Y(q.terr + floor)) : c.moveTo(X(q.t), Y(q.terr + floor)));
      c.strokeStyle = TK.danger; c.globalAlpha = 0.6; c.stroke(); c.globalAlpha = 1; c.setLineDash([]);
      // The altitude.
      c.beginPath(); s.forEach((q, i) => i ? c.lineTo(X(q.t), Y(q.alt)) : c.moveTo(X(q.t), Y(q.alt)));
      c.strokeStyle = TK.route; c.lineWidth = 2.2; c.stroke();
      const every = R.T <= 30 ? 5 : R.T <= 90 ? 10 : R.T <= 240 ? 30 : 60;
      c.fillStyle = TK.muted; c.textAlign = "center";
      for (let tt = 0; tt <= R.T + 0.01; tt += every) c.fillText(fmtT(tt), clamp(X(tt), l + 12, PW - r - 12), PH - 7);
      if (this.anim) { const x = X(this.anim.t); c.strokeStyle = TK.fg; c.lineWidth = 1.5; c.beginPath(); c.moveTo(x, t); c.lineTo(x, t + ih); c.stroke(); }
      this.$(".rm-profnote").textContent = `flight altitude · ground · ${fmtN(floor)} m minimum (dashed)`;
    }

    // -- preview ----------------------------------------------------------
    startPreview() {
      this.closePin(); this.clearResult();
      const R = this.R, speed = Math.max(2, R.T / 12);
      this.anim = {t: 0, speed, t0: performance.now()};
      this.$(".rm-preview").textContent = "Stop preview";
      this.$(".rm-hud").hidden = false;
      const step = () => {
        const anim = this.anim;
        if (!anim || !this.opts.container.isConnected) return;
        anim.t = Math.min(R.T, (performance.now() - anim.t0) / 1000 * anim.speed);
        this.showHud(); this.render(); this.drawProf();
        if (anim.t < R.T) anim.raf = requestAnimationFrame(step);
        else { anim.done = true; this.$(".rm-preview").textContent = "Preview again"; }
      };
      this.anim.raf = requestAnimationFrame(step);
    }
    stopPreview() {
      if (!this.anim) return;
      cancelAnimationFrame(this.anim.raf);
      this.anim = null;
      this.$(".rm-hud").hidden = true;
      this.$(".rm-preview").textContent = "Preview";
      this.render(); this.drawProf();
    }
    showHud() {
      const R = this.R, s = R.sim.samples[clamp(Math.round(this.anim.t / R.sim.dt), 0, R.sim.samples.length - 1)];
      const bk = Math.round(s.phi / DEG), low = s.clr < this.lim.min_clearance_m;
      this.$(".rm-hud").innerHTML = `<b>${fmtT(this.anim.t)}</b> / ${fmtT(R.T)} &nbsp;×${Math.round(this.anim.speed)}<br>` +
        `${fmtN(this.lim.tas_kt)} kt true · bank ${Math.abs(bk)}°${bk > 1 ? " R" : bk < -1 ? " L" : ""}<br>` +
        `${fmtN(s.alt)} m · <span${low ? ' class="rm-warn"' : ""}>${fmtN(s.clr)} m above ground</span>`;
    }

    // -- self adjust ------------------------------------------------------
    runAdjust() {
      if (!this.R || this.R.empty) return;
      this.closePin(); this.stopPreview(); this.clearResult();
      const el = this.$(".rm-adjusted");
      el.hidden = false; el.dataset.s = "run";
      el.innerHTML = `<h4>Adjusting</h4><div class="dim">Nudging the line until every check passes…</div>`;
      setTimeout(() => {
        let res = null;
        try { res = selfAdjust(this.S, this.lim, this.grid, ADJUST_BUDGET_MS); } catch (e) { res = null; }
        if (!res) {
          el.dataset.s = "error";
          el.innerHTML = `<h4>Could not adjust</h4><div>Nothing was changed. Draw the line further from the ` +
            `high ground, or allow more bank.</div>`;
          return;
        }
        this.pushHist();
        this.S.strokes = res.strokes; this.S.pins = res.pins; this.S.alt0 = res.alt0; this.S.adjusted = true;
        this.ghost = this.ghost || res.ghost;
        this.$(".rm-legghost").hidden = res.maxMove < 1;
        this.update();
        this.renderAdjusted(res);
        this.fitLine();
      }, 40);
    }
    renderAdjusted(res) {
      const el = this.$(".rm-adjusted"), lim = this.lim, S = this.S, floor = lim.min_clearance_m;
      const hdot = `${lim.hdot_max_mps.toFixed(2)} m/s`;
      el.hidden = false; el.dataset.s = res.ok ? "ok" : "error";
      const lines = res.changes.map(ch => {
        switch (ch.kind) {
          case "trim": return `Cut ${km(ch.m)} off the end so the line fits in ${fmtT(lim.seconds)}.`;
          case "lost": return `The detour uses up ${km(ch.m)} of the run, so the last ${km(ch.m)} of your line is not reached in ${fmtT(lim.seconds)}.`;
          case "extend": return `Extended the line ${km(ch.m)} along its last heading so the straight run after it could be bent clear of the ground.`;
          case "turns": return `Rounded off ${ch.n} turn${ch.n > 1 ? "s" : ""} to ${m(ch.R)} or wider, the tightest turn at ${fmtN(S.bank)}° bank.`;
          case "lateral": return `Moved the line sideways by up to ${m(ch.m)} toward lower ground, to stay ${fmtN(floor)} m above it.`;
          case "pinNew": return `Climbs to ${m(ch.to)} by ${fmtT(ch.t)} to clear the ground.`;
          case "pinGround": return `Raised the ${m(ch.from)} point at ${fmtT(ch.t)} to ${m(ch.to)} to clear the ground.`;
          case "pinMerged": return `Dropped the ${m(ch.alt)} point at ${fmtT(ch.t)}: it fell beyond the end of the run or onto another point.`;
          case "alt0": return `Starts at ${m(ch.to)} instead of ${m(ch.from)}, and every altitude point moves up by the same ${m(ch.to - ch.from)}: at the autopilot's ${hdot} climb-rate limit it could not get high enough in time. "Use this path" writes the new start altitude into the table.`;
          case "pinLater": return `Reaches ${m(ch.alt)} at ${fmtT(ch.tNew)} instead of ${fmtT(ch.tOld)}: the autopilot's climb-rate limit is ${hdot}.`;
          case "pinLower": return `Ends at ${m(ch.to)} instead of ${m(ch.from)}: that is as high as the autopilot's ${hdot} climb gets by the end of the line.`;
          case "pinHigher": return `Descends to ${m(ch.to)} instead of ${m(ch.from)} at ${fmtT(ch.t)}: the autopilot's descent-rate limit is ${hdot}.`;
          default: return null;
        }
      }).filter(Boolean);
      const fail = res.ok ? null : (this.R.checks.find(c => c.s === "error") || this.R.checks.find(c => c.s === "warn"));
      const advice = fail ? ({
        "route.turn": "Allow more bank, or draw the turns wider.",
        "route.time": "Draw a shorter line, or give the run more time in the table.",
        "route.climb": "Move the altitude point later along the line, or ask for less altitude.",
        "route.terrain_clearance": "Undo and draw the line further from the high ground, or allow more bank.",
      }[fail.id] || "") : "";
      const cut = res.changes.some(ch => ch.kind === "trim" || ch.kind === "lost");
      const moved = res.maxMove >= 1
        ? `The dotted line is what you drew; the new line stays within ${m(res.maxMove)} of it.`
        : cut ? "The part of the line that is kept did not move." : "The line itself did not move.";
      el.innerHTML = `<h4>${res.ok ? "Adjusted" : "Adjusted, but not all the way"}</h4>` +
        (lines.length ? `<ol class="rm-changes">${lines.map(l => `<li>${esc(l)}</li>`).join("")}</ol>`
                      : `<div style="margin-bottom:.5rem">Nothing needed to move.</div>`) +
        `<div class="rm-foot">${res.ok ? `Every check passes. ${esc(moved)}` : `${esc(fail.t)}: ${esc(fail.m)} ${esc(advice)}`}</div>` +
        `<div class="rm-actions" style="margin-top:.5rem"><button class="rm-undoadj opt">Undo adjustment</button>` +
        `<button class="rm-prevadj opt">Preview</button></div>`;
      this.$(".rm-undoadj").onclick = () => this.undo();
      this.$(".rm-prevadj").onclick = () => { this.stopPreview(); this.startPreview(); };
    }

    // -- the server: check with the physics, use this path ------------
    waypoints() {
      return this.R.path ? exportWaypoints(this.R, this.lim.max_waypoints || 0) : [];
    }
    provenance() {
      return this.S.adjusted ? "drawn on the route map, then self-adjusted" : "drawn on the route map";
    }
    clearResult() {
      this.flown = null;
      this.$(".rm-result").hidden = true;
      this.$(".rm-result").innerHTML = "";
      this.$(".rm-legphys").hidden = true;
    }
    refusal(r) {
      // The page's helper (index.html refusalHtml) when it is there, so a
      // refusal reads exactly as the review table's; else its two-line
      // form: the sentence, the rule name underneath.
      if (typeof window.refusalHtml === "function") return window.refusalHtml(r);
      const rule = (r.details && r.details.rule) || r.refused || r.constraint || "";
      const sentence = r.sentence || r.message || r.error || "The request was refused.";
      return `<div>${esc(sentence)}</div>` + (rule ? `<div class="rm-rule">rule: ${esc(rule)}</div>` : "");
    }
    async physicsCheck() {
      const R = this.R, box = this.$(".rm-result");
      this.stopPreview(); this.closePin();
      if (R.empty) {
        box.hidden = false; box.dataset.s = "error";
        box.innerHTML = `<h4>Nothing to fly</h4><div class="dim">Draw a line first.</div>`;
        return;
      }
      const waypoints = this.waypoints();
      box.hidden = false; box.dataset.s = "run"; this.flown = null; this.$(".rm-legphys").hidden = true;
      box.innerHTML = `<h4>Flying the line in the physics</h4><div class="dim">JSBSim, the TECS autopilot ` +
        `and the route guidance over the scene's full raster, on the server (${waypoints.length} waypoints)…</div>`;
      this.render();
      let payload, status;
      try {
        const response = await fetch("/route/check", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({spec: this.opts.getSpec(), waypoints, bank_limit_deg: this.S.bank}),
        });
        status = response.status;
        payload = await response.json();
      } catch (error) {
        box.dataset.s = "error";
        box.innerHTML = `<h4>Not flown</h4><div class="rm-warn">could not reach the server: ${esc(error)}</div>`;
        return;
      }
      const violations = Array.isArray(payload.violations) ? payload.violations : [];
      const refused = payload.error || payload.refused || (status >= 400) || (violations.length && !payload.ok);
      if (refused) {
        // A named refusal is a result: the physics will not fly this line
        // as it stands, and the server says which rule and why.
        const items = violations.length ? violations : [payload];
        box.dataset.s = "error";
        box.innerHTML = `<h4>Refused by the physics</h4>` + items.map(v => this.refusal(v)).join("") +
          `<div class="rm-foot">Nothing was flown. The run would be refused the same way.</div>`;
        return;
      }
      this.flown = flownPoints(payload.flown);
      this.$(".rm-legphys").hidden = this.flown.length < 2;
      const closure = Array.isArray(payload.closure) ? payload.closure : [];
      const row = (k, v) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`;
      box.dataset.s = "ok";
      box.innerHTML = `<h4>Flown by the physics</h4><dl class="rm-kv">` +
        row("lowest above the ground", payload.min_clearance_m != null ? `${m(payload.min_clearance_m)} (on the raster)` : "not reported") +
        row("furthest from your line", payload.max_cross_track_m != null ? m(payload.max_cross_track_m) : "not reported") +
        row("flown for", payload.seconds != null ? fmtT(payload.seconds) : "not reported") +
        closure.map(c => row(`closure · ${c.name || "?"}`,
          `${c.ok === false ? "FAIL" : "ok"} ${c.achieved != null ? (+c.achieved).toFixed(1) : ""}` +
          `${c.tolerance != null ? ` (tol ${(+c.tolerance).toFixed(1)}${c.unit ? " " + c.unit : ""})` : ""}`)).join("") +
        `</dl><div class="rm-foot">The amber track is what JSBSim flew with the TECS autopilot along your line, ` +
        `over the scene's full raster. ${this.flown.length} samples.</div>`;
      this.render();
    }
    usePath() {
      const R = this.R, state = this.$(".rm-state");
      if (R.empty) { state.textContent = "draw a line first"; return; }
      const waypoints = this.waypoints();
      if (!waypoints.length) { state.textContent = "the line has no point away from the start"; return; }
      const route = {
        waypoints, bank_limit_deg: this.S.bank, heading_deg: Math.round(bearingDeg(R.psi0) * 10) / 10,
        altitude_m: Math.abs(this.S.alt0 - this.data.aircraft.alt_m) > 1e-6 ? this.S.alt0 : null,
        from: this.provenance(), length_m: R.len,
      };
      state.textContent = `${waypoints.length} waypoints, ${km(R.len)}, heading ${route.heading_deg}°: in the spec ` +
        `(${route.from}); the review table's route row shows the server's summary after the next round trip`;
      if (typeof this.opts.onPlaced === "function") this.opts.onPlaced(route);
    }

    close() {
      this.stopPreview();
      document.removeEventListener("keydown", this.onKey);
      if (this.resizer) this.resizer.disconnect();
      this.opts.container.innerHTML = "";
      this.opts.container.className = "";
      if (current === this) current = null;
    }
  }

  // The server's flown track as map points: either a list of samples
  // ({t_s, north_m, east_m, ...}) or columns of them.
  function flownPoints(flown) {
    if (!flown) return [];
    const at = (p, i) => ({x: +p.east_m, y: +p.north_m, t: +p.t_s, alt: +p.alt_m});
    if (Array.isArray(flown)) return flown.map(at).filter(p => Number.isFinite(p.x) && Number.isFinite(p.y));
    const n = Array.isArray(flown.north_m) ? flown.north_m.length : 0, out = [];
    for (let i = 0; i < n; i++) out.push({x: +flown.east_m[i], y: +flown.north_m[i],
                                          t: flown.t_s ? +flown.t_s[i] : i, alt: flown.alt_m ? +flown.alt_m[i] : NaN});
    return out.filter(p => Number.isFinite(p.x) && Number.isFinite(p.y));
  }

  let current = null;

  async function open(opts) {
    if (current) current.close();
    const box = opts.container;
    box.className = "card";
    box.textContent = "loading the route map's terrain...";
    let data;
    try {
      const response = await fetch("/route/terrain", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({spec: opts.getSpec()}),
      });
      data = await response.json();
      if (data.error) {
        box.innerHTML = typeof window.refusalHtml === "function" ? window.refusalHtml(data) : esc(data.error);
        return null;
      }
    } catch (error) {
      box.textContent = `could not reach the server: ${error}`;
      return null;
    }
    const need = ["tas_kt", "turn_radius_m", "bank_limit_deg", "hdot_max_mps", "min_clearance_m", "lookahead_m", "seconds"];
    const missing = need.filter(k => !data.route || !Number.isFinite(+data.route[k]));
    if (!data.grid || !data.aircraft || missing.length) {
      box.textContent = `the server's route payload is missing ${missing.length ? missing.join(", ") : "its grid or aircraft"}: ` +
        `the map draws nothing rather than guess a limit`;
      return null;
    }
    try {
      current = new RouteMapView(opts, data);
    } catch (error) {
      box.textContent = `the route map could not start: ${error.message || error}`;
      return null;
    }
    box.scrollIntoView({behavior: "smooth", block: "start"});
    return current;
  }

  return {open, close: () => current && current.close(),
          // The engine, for the page test's own checks (pure functions).
          _engine: {compute, selfAdjust, exportWaypoints, turnRadius, Grid}};
})();
