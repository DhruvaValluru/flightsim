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
    # round 25: absent means the class masters (compile-checked, coat then flat fallback)
    assert look.parse_aircraft_probes("") == ()
    assert look.parse_aircraft_probes("-aircraft-materials=on") == ()
    assert look.parse_aircraft_probes("-aircraft-probe=flat") == ("flat",)
    assert look.parse_aircraft_probes("-aircraft-probe=coat") == ("coat",)
    assert look.parse_aircraft_probes("-aircraft-probe=none") == ()
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
    block = FX_CPP[FX_CPP.index("// Round 23: the bisect probes, on the paint"):
                   FX_CPP.index("// Round 25: a probe whose parameter the drawn master lacks")]
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
    assert re.search(r'^LOOK_GENERATION = "7"$', MASTERS, re.M)
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


# -- round 24 (LOOK_GENERATION 6) ---------------------------------------------------

import aircraft_wet_layer as wet_layer  # noqa: E402


def test_round24_words_parse_and_reach_the_host():
    assert look.parse_aircraft_probes("-aircraft-probe=nowet,rawbase,defaultlit,basecolor-debug,tangentnormal") == (
        "nowet", "rawbase", "defaultlit", "basecolor-debug", "tangentnormal")
    parse = FX_CPP[FX_CPP.index("// Round 23: the master bisect probes"):FX_CPP.index("double FFlightSimAircraftFX::HeatHaze")]
    for word in ("nowet", "rawbase", "defaultlit", "basecolor-debug", "tangentnormal"):
        assert f'TEXT("{word}")' in parse, word
    assert 'LookMid->SetScalarParameterValue(TEXT("WetLayerAmount"), 0.0f);' in FX_CPP
    assert 'LookMid->SetScalarParameterValue(TEXT("RawBaseAmount"), 1.0f);' in FX_CPP
    assert 'LookMid->SetScalarParameterValue(TEXT("BaseDebug"), 1.0f);' in FX_CPP
    assert "LookMid->CopyParameterOverrides(LookMic);" in FX_CPP
    for master in (look.PROBE_DEFAULT_LIT_MASTER, look.PROBE_TANGENT_NORMAL_MASTER):
        assert f"/Game/FlightSim/Aircraft/{master}.{master}" in FX_CPP


def test_round24_handles_default_to_the_gen5_graph():
    assert wet_layer.PROBE_SCALARS["WetLayerAmount"] == 1.0
    assert wet_layer.PROBE_SCALARS["RawBaseAmount"] == 0.0
    assert wet_layer.PROBE_SCALARS["BaseDebug"] == 0.0
    graft = (REPO / "scripts/aircraft_wet_layer.py").read_text(encoding="utf-8")
    graft = graft[graft.index("def add_wet_layer("):graft.index("def add_canopy_scratch(")]
    assert "if raw_base is None:" in graft                       # glass keeps its gen-5 graft exactly
    assert '_pin("EmissiveColor")' in graft
    surface = MASTERS[MASTERS.index("def _surface("):MASTERS.index("def create_aircraft_paint")]
    assert "add_wet_layer(material, sys.modules[__name__], cls, raw_base=raw_base)" in surface
    assert surface.index("raw_base = base") < surface.index('_min(material, base, s["AlbedoMax"]')
    dl = MASTERS[MASTERS.index("def create_aircraft_paint_default_lit"):MASTERS.index("def create_aircraft_paint_tangent_normal")]
    assert 'shading_model="MSM_DEFAULT_LIT"' in dl and "coat=True" in dl
    tn = MASTERS[MASTERS.index("def create_aircraft_paint_tangent_normal"):MASTERS.index("def create_aircraft_probe_flat")]
    assert "tangent_normal=True" in tn and "coat=True" in tn
    creators = MASTERS[MASTERS.index("CREATORS = ("):MASTERS.index("CREATED = (")]
    assert "create_aircraft_paint_default_lit" in creators and "create_aircraft_paint_tangent_normal" in creators
