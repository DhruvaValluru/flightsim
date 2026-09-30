"""Generate the A4 flight model from the A-4E visual model's own aircraft.cfg.

The visual model (assets/aircraft_models/A4) ships an MSFS/P3D aircraft.cfg
whose positions its author marked "checked against 3D model": gear, scrape
points (nose, tail, belly, wingtips), tail hook, eyepoint, fuel tanks and
engine position, in feet from the model datum (+x forward, +y right, +z up).
This module turns those numbers into the JSBSim structural frame (inches,
+x aft, +y right, +z up) so the physics and the mesh share one geometry.

What is taken from the cfg: span, area, empty weight, moments of inertia,
CG, gear/scrape/eyepoint/engine/tank positions, static thrust, TSFC, fuel
capacity. What is NOT: the aerodynamic coefficients, which stay the stock
Aeromatic set (the cfg has none). The .mdl vertex data was not used: its
PV44 vertex layout is not decoded here, so the cfg is the link to the mesh.

    python -m assets_pipeline.a4_sync          # regenerate fdm_root + UE copy
    python -m assets_pipeline.a4_sync --check  # fail if committed files drift
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CFG = REPO / "assets/aircraft_models/A4/SimObjects/Airplanes/A-4E/aircraft.cfg"
# Pristine stock inputs (the Aeromatic A4, its J52 and the direct thruster).
TEMPLATES = REPO / "assets_pipeline" / "a4_templates"
TEMPLATE = TEMPLATES / "A4_aeromatic.xml"
ENGINE_TEMPLATE = TEMPLATES / "J52_aeromatic.xml"
THRUSTER_TEMPLATE = TEMPLATES / "direct.xml"
# The headless host reads OUT; the Unreal plugin carries its own JSBSim data
# tree, so the same files are written there and the two hosts fly one airframe.
OUT = REPO / "assets/fdm_root"
UE_ROOT = REPO / "ue/Plugins/JSBSimFlightDynamicsModel/Resources/JSBSim"

FT_IN = 12.0
JET_A_LB_PER_GAL = 6.7
LOADED_WEIGHT_LB = 18300.0  # the cfg's own performance text
GEAR_DAMPING_RATIO = 0.8    # the cfg's value for both gear classes
G = 32.174
# External-store drag: drag area (ft2) per lb carried on STA1-5. One fitted
# constant, set so the model climbs at the cfg's published 8,440 ft/min at
# its published 18,300 lb loaded weight (assets_pipeline/a4_performance.py).
# The clean airframe (no stores) is untouched and keeps the published 585 kn.
STORES_DRAG_FT2_PER_LB = 0.001756
# Induced drag K = 1 / (pi * AR * e). The stock Aeromatic K of 0.09 is
# optimistic for an aspect-ratio-2.7 wing; e is the one fitted parameter,
# chosen so the service ceiling at the loaded weight is the cfg's 42,250 ft.
OSWALD_E = 0.918


def _cfg_lines() -> list:
    text = CFG.read_bytes().decode("latin-1").replace("\r", "")
    return [ln.split("//")[0].strip() for ln in text.split("\n")]


def _floats(s: str) -> list:
    return [float(x) for x in re.findall(r"-?\d+\.?\d*(?:[eE]-?\d+)?", s)]


def read_cfg() -> dict:
    lines = _cfg_lines()

    def value(key: str) -> str:
        for ln in lines:
            if re.match(rf"^{re.escape(key)}\s*=", ln, re.I):
                return ln.split("=", 1)[1]
        raise KeyError(key)

    pts = {}
    for ln in lines:
        m = re.match(r"^point\.(\d+)\s*=\s*(.*)$", ln)
        if m:
            pts[int(m.group(1))] = _floats(m.group(2))
    tanks = {}
    for ln in lines:
        m = re.match(r"^(Center\d|External\d)\s*=\s*(.*)$", ln, re.I)
        if m:
            tanks[m.group(1)] = _floats(m.group(2))
    stations = {}
    for ln in lines:
        m = re.match(r"^station_load\.(\d+)\s*=\s*(.*)$", ln)
        if m:
            stations[int(m.group(1))] = _floats(m.group(2))
    return {
        "stations": stations,
        "span_ft": float(value("wing_span").split()[0]),
        "area_ft2": float(value("wing_area").split()[0]),
        "empty_lb": float(value("empty_weight").split()[0]),
        "ixx": float(value("empty_weight_roll_MOI").split()[0]),
        "iyy": float(value("empty_weight_pitch_MOI").split()[0]),
        "izz": float(value("empty_weight_yaw_MOI").split()[0]),
        "thrust_lbf": float(value("static_thrust").split()[0]),
        "tsfc": float(value("ThrustSpecificFuelConsumption").split()[0]),
        "engine_pos": _floats(value("Engine.0"))[:3],
        "eye": _floats(value("eyepoint")),
        "hook": _floats(value("tailhook_position")),
        "points": pts,
        "tanks": tanks,
    }


def to_struct_in(long_ft: float, lat_ft: float, vert_ft: float):
    """Model datum frame (feet, +fwd/+right/+up) -> JSBSim structural (in)."""
    return (-long_ft * FT_IN + 0.0, lat_ft * FT_IN, vert_ft * FT_IN)


def _loc(name_attr: str, v, indent: str) -> str:
    x, y, z = (round(c, 2) + 0.0 for c in to_struct_in(*v))
    return (f'{indent}<location{name_attr} unit="IN">\n'
            f"{indent}  <x> {x:.2f} </x>\n{indent}  <y> {y:.2f} </y>\n"
            f"{indent}  <z> {z:.2f} </z>\n{indent}</location>\n")


def _contact(kind, name, pos, spring, damp, extra) -> str:
    return (f'  <contact type="{kind}" name="{name}">\n'
            + _loc("", pos, "   ")
            + "   <static_friction>  0.80 </static_friction>\n"
              "   <dynamic_friction> 0.50 </dynamic_friction>\n"
            + extra
            + f'   <spring_coeff unit="LBS/FT">  {spring:.2f} </spring_coeff>\n'
              f'   <damping_coeff unit="LBS/FT/SEC">  {damp:.2f} </damping_coeff>\n'
            + "  </contact>\n")


def _gear(cfg: dict) -> str:
    p = cfg["points"]
    # Static load split from the cfg's own loaded weight and the gear
    # geometry: nose carries (b/wheelbase) of the weight.
    nose, left = p[0], p[1]
    wheelbase = nose[1] - left[1]
    nose_frac = (0.0 - left[1]) / wheelbase  # CG at datum x = 0
    loads = {"nose": LOADED_WEIGHT_LB * nose_frac,
             "main": LOADED_WEIGHT_LB * (1 - nose_frac) / 2}

    def kc(load, compression):
        k = load / compression
        c = 2 * GEAR_DAMPING_RATIO * math.sqrt(k * load / G)
        return k, c

    out = "\n <ground_reactions>\n\n"
    for idx, name, key, comp, steer, brake in (
            (0, "NOSE", "nose", p[0][8], p[0][7], "NONE"),
            (1, "LEFT_MAIN", "main", p[1][8], 0, "LEFT"),
            (2, "RIGHT_MAIN", "main", p[2][8], 0, "RIGHT")):
        k, c = kc(loads[key], comp)
        extra = ("   <rolling_friction> 0.02 </rolling_friction>\n"
                 f'   <max_steer unit="DEG"> {steer:.2f} </max_steer>\n'
                 f"   <brake_group>{brake}</brake_group>\n"
                 "   <retractable>1</retractable>\n")
        # BOGEY children must precede spring/damping in the stock layout;
        # JSBSim accepts any order of these elements.
        out += _contact("BOGEY", name, p[idx][1:4], k, c, extra) + "\n"
    scrape = {3: "LEFT_WINGTIP", 4: "RIGHT_WINGTIP", 5: "TAIL_TOP",
              6: "TAIL_BOTTOM", 7: "NOSE_TIP", 8: "BELLY"}
    for idx, name in scrape.items():
        out += _contact("STRUCTURE", name, p[idx][1:4], 22500.0, 4500.0, "") + "\n"
    return out + " </ground_reactions>\n"


STATION_NAMES = {0: "PILOT", 2: "STA1", 3: "STA2", 4: "STA3", 5: "STA4",
                 6: "STA5"}


def _pointmasses(cfg: dict) -> str:
    """Pilot (loaded) and the five pylon stations (empty until stores are set).

    Positions and the pilot weight are the cfg's ``station_load`` entries.
    Set a store with ``inertia/pointmass-weight-lbs[n]``; n follows this
    order (0 = pilot, 1..5 = STA1..STA5).
    """
    out = ""
    for idx, name in STATION_NAMES.items():
        weight, lon, lat, vert = cfg["stations"][idx][:4]
        weight = weight if idx == 0 else 0.0
        out += (f'\n   <pointmass name="{name}">\n'
                f'    <weight unit="LBS"> {weight:.2f} </weight>\n'
                + _loc("", (lon, lat, vert), "    ")
                + "   </pointmass>\n")
    return out


def _propulsion(cfg: dict, engine_name: str) -> str:
    tanks = [cfg["tanks"][k] for k in
             ("Center1", "Center2", "External1", "External2", "Center3")]
    out = ("\n <propulsion>\n\n"
           f'   <engine file="{engine_name}">\n'
           + "".join(f"    <feed>{i}</feed>\n" for i in range(5))
           + "    <thruster file=\"direct\">\n"
           + _loc("", cfg["engine_pos"], "     ")
           + '     <orient unit="DEG">\n       <pitch> 0.00 </pitch>\n'
             "       <roll>   0.00 </roll>\n       <yaw>   0.00 </yaw>\n"
             "     </orient>\n    </thruster>\n  </engine>\n\n")
    for n, t in enumerate(tanks):
        lb = t[3] * JET_A_LB_PER_GAL
        # tanks 0-1 are internal and full; 2-4 are drop tanks, empty until
        # loaded (fuel/tank[n]/contents-lbs)
        fill = lb if n < 2 else 0.0
        out += (f'  <tank type="FUEL" number="{n}">\n'
                + _loc("", (t[0], t[1], t[2]), "   ")
                + f'   <capacity unit="LBS"> {lb:.2f} </capacity>\n'
                  f'   <contents unit="LBS"> {fill:.2f} </contents>\n'
                  "  </tank>\n\n")
    return out + " </propulsion>\n"


def _sub(text: str, tag: str, new: str) -> str:
    out, n = re.subn(rf"\n?[ \t]*<{tag}>.*?</{tag}>\n", new, text, count=1,
                     flags=re.S)
    if n != 1:
        raise RuntimeError(f"template has no <{tag}> block")
    return out


def _add_stores_drag(xml: str) -> str:
    """Drag area from pylon weight: a stores channel plus a CDstores term."""
    stations = "".join(f"<property>inertia/pointmass-weight-lbs[{i}]</property>"
                       for i in range(1, 6))
    channel = (
        '\n  <channel name="Stores">\n'
        '   <fcs_function name="Stores Drag Area">\n'
        f"    <function><product><value> {STORES_DRAG_FT2_PER_LB} </value>"
        f"<sum>{stations}</sum></product></function>\n"
        "    <output>stores/drag-area-ft2</output>\n"
        "   </fcs_function>\n  </channel>\n")
    term = (
        '    <function name="aero/coefficient/CDstores">\n'
        "       <description>Drag_due_to_external_stores</description>\n"
        "       <product>\n"
        "          <property>aero/qbar-psf</property>\n"
        "          <property>stores/drag-area-ft2</property>\n"
        "       </product>\n    </function>\n\n")
    if xml.count(" </flight_control>") != 1 or \
            xml.count('    <function name="aero/coefficient/CDi">') != 1:
        raise RuntimeError("template layout changed; cannot place stores drag")
    xml = xml.replace(" </flight_control>", channel + "\n </flight_control>", 1)
    return xml.replace('    <function name="aero/coefficient/CDi">',
                       term + '    <function name="aero/coefficient/CDi">', 1)


def _set_induced_drag(xml: str, cfg: dict) -> str:
    aspect = cfg["span_ft"] ** 2 / cfg["area_ft2"]
    k = 1.0 / (math.pi * aspect * OSWALD_E)
    out, n = re.subn(
        r'(<function name="aero/coefficient/CDi">.*?<value>)0\.09(</value>)',
        rf"\g<1>{k:.4f}\g<2>", xml, count=1, flags=re.S)
    if n != 1:
        raise RuntimeError("template has no CDi coefficient to replace")
    return out


# The stock Aeromatic file assumes this horizontal tail; its pitch-moment
# terms were sized for it. The mesh-measured tail scales them (see
# _scale_pitch_terms).
STOCK_HTAIL_AREA_FT2 = 52.0
STOCK_HTAIL_ARM_FT = 16.68


def _scale_function(xml: str, name: str, factor: float) -> str:
    """Multiply one aero function's constants by ``factor``: its <value>
    and the second column of its table rows."""
    m = re.search(rf'<function name="{re.escape(name)}">.*?</function>', xml,
                  flags=re.S)
    if m is None:
        raise RuntimeError(f"template has no {name}")
    block = m.group(0)
    scaled = re.sub(
        r"(<value>\s*)(-?\d+\.?\d*)(\s*</value>)",
        lambda g: f"{g.group(1)}{float(g.group(2)) * factor:.4f}{g.group(3)}",
        block)
    scaled = re.sub(
        r"^(\s*\d+\.?\d*\s+)(-?\d+\.?\d*)(\s*)$",
        lambda g: f"{g.group(1)}{float(g.group(2)) * factor:.4f}{g.group(3)}",
        scaled, flags=re.M)
    if scaled == block:
        raise RuntimeError(f"nothing to scale in {name}")
    return xml.replace(block, scaled, 1)


def _scale_pitch_terms(xml: str, tail: dict) -> str:
    """Elevator power scales with tail area x arm; pitch damping with
    area x arm^2. Static stability (Cmalpha) is wing-body plus tail and is
    left alone."""
    volume = (tail["area_ft2"] * tail["arm_ft"]) / (
        STOCK_HTAIL_AREA_FT2 * STOCK_HTAIL_ARM_FT)
    damping = (tail["area_ft2"] * tail["arm_ft"] ** 2) / (
        STOCK_HTAIL_AREA_FT2 * STOCK_HTAIL_ARM_FT ** 2)
    xml = _scale_function(xml, "aero/coefficient/Cmde", volume)
    xml = _scale_function(xml, "aero/coefficient/Cmq", damping)
    return _scale_function(xml, "aero/coefficient/Cmadot", damping)


FLAP_MAX_DEG = 50.0      # cfg [Flaps.0] flaps-position.4
FLAP_TIME_S = 3.0        # cfg extending-time
HOOK_DECEL_G = 2.2       # the stock JSBSim hook system's arrestment decel


def _extend_flaps(xml: str) -> str:
    """Flap travel 0 -> 50 deg in the cfg's 3 s.

    The lift and drag coefficients are linear in flap angle, so past the
    stock 30 deg they are an extrapolation of that line, not data.
    """
    old = re.search(r'(<kinematic name="Flaps Control">.*?</kinematic>)', xml,
                    flags=re.S)
    if old is None:
        raise RuntimeError("template has no flap kinematic")
    half = FLAP_MAX_DEG / 2
    new = (
        '<kinematic name="Flaps Control">\n'
        "     <input>fcs/flap-cmd-norm</input>\n     <traverse>\n"
        "       <setting>\n          <position>  0 </position>\n"
        "          <time>      0 </time>\n       </setting>\n"
        f"       <setting>\n          <position> {half:g} </position>\n"
        f"          <time>      {FLAP_TIME_S / 2:g} </time>\n       </setting>\n"
        f"       <setting>\n          <position> {FLAP_MAX_DEG:g} </position>\n"
        f"          <time>      {FLAP_TIME_S / 2:g} </time>\n       </setting>\n"
        "     </traverse>\n     <output>fcs/flap-pos-deg</output>\n"
        "   </kinematic>")
    return xml.replace(old.group(1), new, 1)


def _add_tailhook(xml: str, cfg: dict) -> str:
    """Tail hook at the cfg position: a stow/deploy state and, when the hook
    is down, the wire is engaged and the wheels are on the deck, the stock
    2.2 g arrestment force along the airplane's axis.

    The cable itself is not modelled: something outside the FDM sets
    ``systems/hook/wire-engaged`` when the hook catches a wire. The cfg's
    ``cable_force_adjust`` is an MSFS tuning scalar and is not applied.
    """
    declare = ("\n  <property>systems/hook/tailhook-cmd-norm</property>\n"
               "  <property>systems/hook/wire-engaged</property>\n")
    channel = (
        '\n  <channel name="Tailhook">\n'
        '   <kinematic name="Tailhook Control">\n'
        "    <input>systems/hook/tailhook-cmd-norm</input>\n    <traverse>\n"
        "     <setting><position> 0 </position><time> 0 </time></setting>\n"
        "     <setting><position> 1 </position><time> 1.5 </time></setting>\n"
        "    </traverse>\n    <output>systems/hook/tailhook-pos-norm</output>\n"
        "   </kinematic>\n"
        '   <switch name="Hook Arrestment">\n'
        '    <default value="0"/>\n'
        f'    <test logic="AND" value="{HOOK_DECEL_G}">\n'
        "     systems/hook/tailhook-pos-norm gt 0.99\n"
        "     systems/hook/wire-engaged eq 1\n"
        "     gear/unit[1]/WOW eq 1\n    </test>\n"
        "    <output>systems/hook/arrest-decel-g</output>\n   </switch>\n"
        '   <pure_gain name="Hook Force">\n'
        "    <input>systems/hook/arrest-decel-g</input>\n"
        "    <gain>inertia/weight-lbs</gain>\n"
        "    <output>external_reactions/hook/magnitude</output>\n"
        "   </pure_gain>\n  </channel>\n")
    x, y, z = to_struct_in(*cfg["hook"])
    reactions = (
        "\n <external_reactions>\n"
        '  <force name="hook" frame="BODY">\n'
        + _loc("", cfg["hook"], "   ")
        + "   <direction><x> -1 </x><y> 0 </y><z> 0 </z></direction>\n"
          "  </force>\n </external_reactions>\n")
    if xml.count(" </flight_control>") != 1 or xml.count(" <propulsion>") != 1 \
            or xml.count('<flight_control name="FCS: A-4">') != 1:
        raise RuntimeError("template layout changed; cannot place the tail hook")
    xml = xml.replace('<flight_control name="FCS: A-4">',
                      '<flight_control name="FCS: A-4">' + declare, 1)
    xml = xml.replace(" </flight_control>", channel + "\n </flight_control>", 1)
    return xml.replace(" <propulsion>", reactions.lstrip("\n") + "\n <propulsion>", 1)


def build() -> dict:
    cfg = read_cfg()
    xml = TEMPLATE.read_text(encoding="utf-8")

    xml = xml.replace('name="A-4" version="2.0" release="ALPHA"',
                      'name="A-4" version="2.0" release="ALPHA"')
    xml = re.sub(r"<description>.*?</description>",
                 "<description> A-4E Skyhawk: Aeromatic aerodynamics with mass, "
                 "geometry, gear, engine and fuel taken from the A-4E visual "
                 "model's aircraft.cfg. </description>", xml, count=1,
                 flags=re.S)

    from .a4_mesh_check import horizontal_tail

    tail = horizontal_tail()
    chord = cfg["area_ft2"] / cfg["span_ft"]
    metrics = (
        "\n <metrics>\n"
        f'   <wingarea  unit="FT2">  {cfg["area_ft2"]:.2f} </wingarea>\n'
        f'   <wingspan  unit="FT" >  {cfg["span_ft"]:.2f} </wingspan>\n'
        "   <wing_incidence>          0.00 </wing_incidence>\n"
        f'   <chord     unit="FT" >    {chord:.2f} </chord>\n'
        f'   <htailarea unit="FT2">   {tail["area_ft2"]:.2f} </htailarea>\n'
        f'   <htailarm  unit="FT" >   {tail["arm_ft"]:.2f} </htailarm>\n'
        '   <vtailarea unit="FT2">   31.20 </vtailarea>\n'
        '   <vtailarm  unit="FT" >   16.68 </vtailarm>\n'
        + _loc(' name="AERORP"', (0.0, 0.0, 0.0), "   ")
        + _loc(' name="EYEPOINT"', tuple(cfg["eye"]), "   ")
        + _loc(' name="VRP"', (0.0, 0.0, 0.0), "   ")
        + " </metrics>\n")
    xml = _sub(xml, "metrics", metrics)

    mass = (
        "\n <mass_balance>\n"
        f'   <ixx unit="SLUG*FT2">  {cfg["ixx"]:.2f} </ixx>\n'
        f'   <iyy unit="SLUG*FT2">  {cfg["iyy"]:.2f} </iyy>\n'
        f'   <izz unit="SLUG*FT2">  {cfg["izz"]:.2f} </izz>\n'
        '   <ixy unit="SLUG*FT2">         0 </ixy>\n'
        '   <ixz unit="SLUG*FT2">         0 </ixz>\n'
        '   <iyz unit="SLUG*FT2">         0 </iyz>\n'
        f'   <emptywt unit="LBS" >  {cfg["empty_lb"]:.2f} </emptywt>\n'
        + _loc(' name="CG"', (0.0, 0.0, 0.0), "   ")
        + _pointmasses(cfg)
        + " </mass_balance>\n")
    xml = _sub(xml, "mass_balance", mass)
    xml = _add_stores_drag(xml)
    xml = _set_induced_drag(xml, cfg)
    xml = _scale_pitch_terms(xml, tail)
    xml = _extend_flaps(xml)
    xml = _sub(xml, "ground_reactions", _gear(cfg))
    xml = _sub(xml, "propulsion", _propulsion(cfg, "J52P8A"))
    xml = _add_tailhook(xml, cfg)

    eng = ENGINE_TEMPLATE.read_text(encoding="utf-8")
    eng = re.sub(r"<milthrust>.*?</milthrust>",
                 f'<milthrust> {cfg["thrust_lbf"]:.1f} </milthrust>', eng)
    eng = re.sub(r"<tsfc>.*?</tsfc>", f'<tsfc>            {cfg["tsfc"]} </tsfc>', eng)
    eng = eng.replace('<turbine_engine name="J52">',
                      '<turbine_engine name="J52P8A">')
    eng = eng.replace("Author:   Aero-Matic v 0.8",
                      "Author:   Aero-Matic v 0.8; thrust and TSFC from the "
                      "A-4E model's aircraft.cfg (J52-P-8A)")
    thruster = THRUSTER_TEMPLATE.read_text(encoding="utf-8")
    files = {OUT / "aircraft/A4/A4.xml": xml,
             OUT / "engine/J52P8A.xml": eng,
             OUT / "engine/direct.xml": thruster,
             OUT / "systems/.gitkeep": "",
             UE_ROOT / "aircraft/A4/A4.xml": xml,
             UE_ROOT / "engine/J52P8A.xml": eng}
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    bad = 0
    for path, text in build().items():
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                print(f"DRIFT {path.relative_to(REPO)}")
                bad = 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {path.relative_to(REPO)}")
    return bad


if __name__ == "__main__":
    sys.exit(main())
