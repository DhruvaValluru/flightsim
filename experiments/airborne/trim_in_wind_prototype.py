"""Package A prototype: a fixed point on the OBSERVED air-relative state.

JSBSim's wind initial conditions hold ground velocity and re-derive
airspeed (measured: 250 kt CAS commanded came out 303/197 kt in a 30 kt
head/tailwind), and their sign conventions are easy to get wrong
(ic/vw-dir-deg is the direction the wind blows TOWARD). Rather than
reason about the setters, iterate on what the FDM reports after run_ic:
adjust the NED ground-velocity ICs until vc == commanded and beta == 0
with the wind present, then trim. Print convergence and the 30 s
open-loop excursion for six cases.
"""
import json, math, sys
sys.path.insert(0, "/home/user/flightsim")
import jsbsim
from core.fdm import FlightDynamics, mode_for
from core.fdm import units as u
from core.scenario.runner import wind_components_fps

def build(aircraft, alt_m, cas_kt, heading_deg, wind_kt, wind_from_deg, max_iter=8):
    f = FlightDynamics(aircraft, rate_hz=120.0); ex = f._exec
    f.set_initial_conditions({"h-sl-ft": u.m_to_ft(alt_m), "vc-kts": cas_kt, "gamma-deg": 0.0, "phi-deg": 0.0,
        "psi-true-deg": heading_deg, "beta-deg": 0.0, "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0})
    # TAS the calm IC implies for this CAS at this altitude: the target air speed.
    vt_target = ex.get_property_value("ic/vt-fps")
    n_fps, e_fps = wind_components_fps(wind_kt, wind_from_deg)     # NED "TO" vector, the runner's convention
    # Initial guess: v_ground = v_air(along heading) + v_wind
    psi = math.radians(heading_deg)
    vn, ve = vt_target*math.cos(psi) + n_fps, vt_target*math.sin(psi) + e_fps
    log = []
    for it in range(max_iter):
        # wind IC in JSBSim's own terms, then NED ground velocity, then run_ic
        mag = math.hypot(n_fps, e_fps); to_deg = math.degrees(math.atan2(e_fps, n_fps)) % 360.0
        ex.set_property_value("ic/vw-mag-fps", mag); ex.set_property_value("ic/vw-dir-deg", to_deg)
        ex.set_property_value("ic/vn-fps", vn); ex.set_property_value("ic/ve-fps", ve); ex.set_property_value("ic/vd-fps", 0.0)
        ex.set_property_value("ic/psi-true-deg", heading_deg)
        ex.run_ic()
        vc = ex.get_property_value("velocities/vc-kts"); beta = ex.get_property_value("aero/beta-deg")
        wn, we = ex.get_property_value("atmosphere/wind-north-fps"), ex.get_property_value("atmosphere/wind-east-fps")
        vt = ex.get_property_value("velocities/vt-fps")
        log.append(dict(it=it, vc=round(vc,3), beta=round(beta,4), vt=round(vt,2), wind=(round(wn,2), round(we,2))))
        if abs(vc - cas_kt) < 0.05 and abs(beta) < 0.02:
            break
        # Correct the AIR velocity we implied: rotate by -beta and scale by the vc ratio, re-add the wind.
        # Observed air vector = ground - wind(as the FDM sees it); use the FDM's own wind sign.
        an, ae = vn - wn, ve - we
        a_mag = math.hypot(an, ae); a_dir = math.atan2(ae, an)
        a_mag *= cas_kt / max(vc, 1.0)           # airspeed scale
        a_dir -= math.radians(beta)             # remove sideslip: point the air vector along the nose
        an, ae = a_mag*math.cos(a_dir), a_mag*math.sin(a_dir)
        vn, ve = an + wn, ae + we
    f.start_engines()
    f.trim(mode_for(crosswind=wind_kt > 0.0)); f.hold_mass(True)
    p = f.props
    trim = dict(vc=round(p.get("velocities/vc-kts"),2), beta=round(p.get("aero/beta-deg"),3), phi=round(p.get("attitude/phi-deg"),3),
                psi=round(p.get("attitude/psi-deg"),3), rud=round(p.get("fcs/rudder-cmd-norm"),3), ail=round(p.get("fcs/aileron-cmd-norm"),3),
                wind=(round(p.get("atmosphere/total-wind-north-fps"),2), round(p.get("atmosphere/total-wind-east-fps"),2)),
                gs=round(u.fps_to_mps(p.get("velocities/vg-fps")),2), tas=round(u.fps_to_mps(p.get("velocities/vtrue-fps")),2))
    # 30 s open loop with the wind re-written every step, exactly as the run loop does
    h0 = u.ft_to_m(p.get("position/h-sl-ft")); hs=[]; phis=[]
    for i in range(30*120):
        p.set_many({"atmosphere/wind-north-fps": n_fps, "atmosphere/wind-east-fps": e_fps, "atmosphere/wind-down-fps": 0.0}); f.step()
        if i % 12 == 0: hs.append(u.ft_to_m(p.get("position/h-sl-ft"))); phis.append(p.get("attitude/phi-deg"))
    return dict(iterations=len(log), log=log, trim=trim, h_excursion_30s=round(max(hs)-min(hs),2), phi_peak_30s=round(max(abs(x) for x in phis),2))

cases = {"B747_head": ("B747",3000,250,0,30,0), "B747_tail": ("B747",3000,250,0,30,180), "B747_cross": ("B747",3000,250,0,30,90),
         "c172p_head": ("c172p",600,85,0,20,0), "c172p_cross": ("c172p",600,85,0,20,90), "B747_quartering": ("B747",3000,250,45,30,300)}
out = {}
for k,(ac,alt,cas,hdg,w,frm) in cases.items():
    try: out[k] = build(ac,alt,cas,hdg,w,frm)
    except Exception as exc: out[k] = f"{type(exc).__name__}: {str(exc)[:160]}"
print(json.dumps(out, indent=1))
