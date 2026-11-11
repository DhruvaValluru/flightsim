"""Round 23 (2026-11-11): the bisect probes inside the gen-5 aircraft look
masters (-aircraft-probe=, with -aircraft-materials=on)."""

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import aircraft_look as look  # noqa: E402

PRIVATE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
FX_CPP = (PRIVATE / "FlightSimAircraftFX.cpp").read_text(encoding="utf-8")
MASTERS = (REPO / "scripts/ue_aircraft_master_materials.py").read_text(encoding="utf-8")


def test_parse_matches_the_host_words():
    assert look.parse_aircraft_probes("") == ()
    assert look.parse_aircraft_probes("-aircraft-materials=on") == ()
    assert look.parse_aircraft_probes("-aircraft-materials=on -aircraft-probe=nocoat,noao") == ("nocoat", "noao")
    assert look.parse_aircraft_probes("-aircraft-probe=flat,flat,none") == ("flat",)
    assert look.parse_aircraft_probes("-aircraft-probe=measured-mesh") == ("measured-mesh",)
    with pytest.raises(look.LookError, match="aircraft_look.switch"):
        look.parse_aircraft_probes("-aircraft-probe=nocoat,shiny")
    parse = FX_CPP[FX_CPP.index("// Round 23: the master bisect probes"):FX_CPP.index("double FFlightSimAircraftFX::HeatHaze")]
    assert 'FParse::Value(*Params, TEXT("aircraft-probe="), ProbeList, false)' in parse   # a comma list
    for word in look.AIRCRAFT_PROBES:
        assert f'TEXT("{word}")' in parse, word
    assert "aircraft_look.switch: -aircraft-probe=" in parse


def test_each_probe_sets_what_the_twin_says():
    block = FX_CPP[FX_CPP.index("// Round 23: the bisect probes, on the paint"):FX_CPP.index("++ProbedSlots;\n\t\t\t}")]
    assert 'LookMid->SetScalarParameterValue(TEXT("ClearCoat"), 0.0f);' in block
    assert 'LookMid->SetScalarParameterValue(TEXT("PanelAoAmount"), 0.0f);' in block
    assert 'LookMid->SetScalarParameterValue(TEXT("PanelNormalAmount"), 0.0f);' in block
    for name in ("WearAmount", "GrimeAmount", "SootAmount"):
        assert f'LookMid->SetScalarParameterValue(TEXT("{name}"), 0.0f);' in block
    for name in ("BaseColor", "BaseColorMap", "BaseColorMapWeight"):
        assert f'TEXT("{name}")' in block
    for master in look.PROBE_MASTERS:
        assert f'TEXT("{master}")' in block
    assert f"/Game/FlightSim/Aircraft/{look.PROBE_FLAT_MASTER}.{look.PROBE_FLAT_MASTER}" in FX_CPP
    assert 'Options.Probes.Contains(TEXT("measured-mesh"))' in FX_CPP
    assert 'Row->SetArrayField(TEXT("probes"), ProbeWords);' in FX_CPP


def test_the_gen5_masters_carry_the_probe_handles_at_the_gen4_values():
    assert re.search(r'^LOOK_GENERATION = "5"$', MASTERS, re.M)
    for cls in ("paint", "bare_metal"):
        assert look.CLASS_SCALARS[cls]["PanelNormalAmount"] == 1.0
        assert look.CLASS_SCALARS[cls]["PanelAoAmount"] == 1.0
    surface = MASTERS[MASTERS.index("def _surface("):MASTERS.index("def create_aircraft_paint")]
    assert '_lerp(material, normal, _mask(material, panels, "rgb", -600, -600), s["PanelNormalAmount"]' in surface
    assert '_mul(material, groove, s["PanelAoAmount"]' in surface
    flat = MASTERS[MASTERS.index("def create_aircraft_probe_flat"):MASTERS.index("def create_aircraft_bare_metal")]
    assert "MSM_DEFAULT_LIT" in flat and "_base_colour(material" in flat
    assert "add_wet_layer" not in flat and "tangent_space_normal" not in flat and "_custom(" not in flat
    assert "create_aircraft_probe_flat" in MASTERS[MASTERS.index("CREATORS = ("):MASTERS.index("CREATED = (")]
