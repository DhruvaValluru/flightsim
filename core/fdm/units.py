"""Unit conversions, defined once.

JSBSim's property tree is mixed-unit: feet, knots, slugs, pounds, Rankine,
radians and degrees all appear, sometimes for the same quantity under different
property names. Every conversion in the codebase resolves to a constant here so
that a factor is never re-typed at a call site.

All constants are exact by definition unless noted.
"""

# Length -- the international foot is exactly 0.3048 m.
M_PER_FT = 0.3048
FT_PER_M = 1.0 / M_PER_FT

# Speed -- the international nautical mile is exactly 1852 m.
MPS_PER_KT = 1852.0 / 3600.0          # 0.5144444...
KT_PER_MPS = 1.0 / MPS_PER_KT
FPS_PER_KT = MPS_PER_KT / M_PER_FT    # 1.68780985...
KT_PER_FPS = 1.0 / FPS_PER_KT
FPM_PER_MPS = FT_PER_M * 60.0

# Mass / force
KG_PER_LB = 0.45359237                # exact, international avoirdupois pound
LB_PER_KG = 1.0 / KG_PER_LB

# Density -- slug/ft^3 to kg/m^3
SLUG_PER_LBF_S2_FT = 1.0
KGM3_PER_SLUGFT3 = 515.378818393      # 1 slug/ft^3
# Pressure -- lbf/ft^2 to pascals
PA_PER_PSF = 47.880258980336          # 1 lbf/ft^2

# Force -- pound-force to newtons
N_PER_LBF = 4.4482216152605           # 1 lbf (exact from lb x g0)

# Temperature -- Rankine to Kelvin
K_PER_R = 5.0 / 9.0

# Standard gravity, m/s^2 (CGPM definition). Used for energy terms in TECS.
G0 = 9.80665


def ft_to_m(ft: float) -> float:
    return ft * M_PER_FT


def m_to_ft(m: float) -> float:
    return m * FT_PER_M


def kt_to_mps(kt: float) -> float:
    return kt * MPS_PER_KT


def mps_to_kt(mps: float) -> float:
    return mps * KT_PER_MPS


def fps_to_mps(fps: float) -> float:
    return fps * M_PER_FT


def mps_to_fps(mps: float) -> float:
    return mps * FT_PER_M


def kt_to_fps(kt: float) -> float:
    return kt * FPS_PER_KT


def fps_to_kt(fps: float) -> float:
    return fps * KT_PER_FPS


def lb_to_kg(lb: float) -> float:
    return lb * KG_PER_LB


def kg_to_lb(kg: float) -> float:
    return kg * LB_PER_KG


def rankine_to_kelvin(r: float) -> float:
    return r * K_PER_R


def slugft3_to_kgm3(s: float) -> float:
    return s * KGM3_PER_SLUGFT3


def psf_to_pa(psf: float) -> float:
    return psf * PA_PER_PSF


def lbf_to_n(lbf: float) -> float:
    return lbf * N_PER_LBF
