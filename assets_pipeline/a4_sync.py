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

    python -m assets_pipeline.a4_sync          # regenerate assets/fdm_root
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
TEMPLATE = (REPO / "ue/Plugins/JSBSimFlightDynamicsModel/Resources/JSBSim/"
            "aircraft/A4/A4.xml")
ENGINE_TEMPLATE = (REPO / "ue/Plugins/JSBSimFlightDynamicsModel/Resources/"
                   "JSBSim/engine/J52.xml")
THRUSTER_TEMPLATE = ENGINE_TEMPLATE.with_name("direct.xml")
OUT = REPO / "assets/fdm_root"

FT_IN = 12.0
JET_A_LB_PER_GAL = 6.7
LOADED_WEIGHT_LB = 18300.0  # the cfg's own performance text
GEAR_DAMPING_RATIO = 0.8    # the cfg's value for both gear classes
G = 32.174


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
    return {
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


def _propulsion(cfg: dict, engine_name: str) -> str:
    fuselage, wing = cfg["tanks"]["Center1"], cfg["tanks"]["Center2"]
    out = ("\n <propulsion>\n\n"
           f'   <engine file="{engine_name}">\n    <feed>0</feed>\n    <feed>1</feed>\n'
           "    <thruster file=\"direct\">\n"
           + _loc("", cfg["engine_pos"], "     ")
           + '     <orient unit="DEG">\n       <pitch> 0.00 </pitch>\n'
             "       <roll>   0.00 </roll>\n       <yaw>   0.00 </yaw>\n"
             "     </orient>\n    </thruster>\n  </engine>\n\n")
    for n, t in enumerate((fuselage, wing)):
        lb = t[3] * JET_A_LB_PER_GAL
        out += (f'  <tank type="FUEL" number="{n}">\n'
                + _loc("", (t[0], t[1], t[2]), "   ")
                + f'   <capacity unit="LBS"> {lb:.2f} </capacity>\n'
                  f'   <contents unit="LBS"> {lb:.2f} </contents>\n'
                  "  </tank>\n\n")
    return out + " </propulsion>\n"


def _sub(text: str, tag: str, new: str) -> str:
    out, n = re.subn(rf"\n?[ \t]*<{tag}>.*?</{tag}>\n", new, text, count=1,
                     flags=re.S)
    if n != 1:
        raise RuntimeError(f"template has no <{tag}> block")
    return out


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

    chord = cfg["area_ft2"] / cfg["span_ft"]
    metrics = (
        "\n <metrics>\n"
        f'   <wingarea  unit="FT2">  {cfg["area_ft2"]:.2f} </wingarea>\n'
        f'   <wingspan  unit="FT" >  {cfg["span_ft"]:.2f} </wingspan>\n'
        "   <wing_incidence>          0.00 </wing_incidence>\n"
        f'   <chord     unit="FT" >    {chord:.2f} </chord>\n'
        '   <htailarea unit="FT2">   52.00 </htailarea>\n'
        '   <htailarm  unit="FT" >   16.68 </htailarm>\n'
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
        + " </mass_balance>\n")
    xml = _sub(xml, "mass_balance", mass)
    xml = _sub(xml, "ground_reactions", _gear(cfg))
    xml = _sub(xml, "propulsion", _propulsion(cfg, "J52P8A"))

    eng = ENGINE_TEMPLATE.read_text(encoding="utf-8")
    eng = re.sub(r"<milthrust>.*?</milthrust>",
                 f'<milthrust> {cfg["thrust_lbf"]:.1f} </milthrust>', eng)
    eng = re.sub(r"<tsfc>.*?</tsfc>", f'<tsfc>            {cfg["tsfc"]} </tsfc>', eng)
    eng = eng.replace('<turbine_engine name="J52">',
                      '<turbine_engine name="J52P8A">')
    eng = eng.replace("Author:   Aero-Matic v 0.8",
                      "Author:   Aero-Matic v 0.8; thrust and TSFC from the "
                      "A-4E model's aircraft.cfg (J52-P-8A)")
    return {OUT / "aircraft/A4/A4.xml": xml,
            OUT / "engine/J52P8A.xml": eng,
            OUT / "engine/direct.xml":
                THRUSTER_TEMPLATE.read_text(encoding="utf-8"),
            OUT / "systems/.gitkeep": ""}


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
