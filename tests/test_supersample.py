"""Supersampled beauty (visual overhaul, supersample lane, 2026-11-09).

What must hold without an engine:

* the C++ pure block (FlightSimSupersample.cpp) and the Python mirror
  (core/capture/supersample.py) are the same numbers: the block is COMPILED
  here with the machine's C++ compiler and its output compared byte for
  byte and to the last printed digit;
* an exact integer box keeps pixel centres aligned: on a synthetic edge the
  reduced frame differs from the label mask only on the pixels the edge
  crosses, its 50 % crossing sits on the geometric edge, both within the
  verifier's tolerance; a Lanczos-3 rings beyond that tolerance (why the
  box was chosen) and a box shifted by one internal pixel is caught;
* the VRAM estimate at 4K internal and the refusals by name;
* the commandlet's hooks are small, beauty-only, after the read-back and
  before the PNG, and the label targets stay at the output size;
* the record passes the verifier's look checks and is not pixel-moving.
"""

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from core.capture import supersample as ss
from core.capture.verify import LOOK_ALIGNMENT_TOL_PX, MASK_TOL_PX

REPO = Path(__file__).resolve().parents[1]
PRIVATE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge" / "Private"
SS_CPP = (PRIVATE / "FlightSimSupersample.cpp").read_text(encoding="utf-8")
SS_H = (PRIVATE / "FlightSimSupersample.h").read_text(encoding="utf-8")
COMMANDLET = (PRIVATE / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
CHECK = (REPO / "scripts" / "check_bridge_api.sh").read_text(encoding="utf-8")
CATALOG = (REPO / "core" / "messages" / "catalog.yaml").read_text(encoding="utf-8")
SHEET = (REPO / "experiments" / "visual_contact_sheet.py").read_text(encoding="utf-8")
CXX = shutil.which("g++") or shutil.which("clang++") or shutil.which("c++")
NEEDS_CXX = pytest.mark.skipif(CXX is None, reason="no C++ compiler on this machine")


def _block():
    begin, end = "// FLIGHTSIM-SUPERSAMPLE-PURE-BEGIN", "// FLIGHTSIM-SUPERSAMPLE-PURE-END"
    return SS_CPP[SS_CPP.index(begin) + len(begin):SS_CPP.index(end)]


def _compile_and_run(tmp_path, main):
    source = tmp_path / "pure.cpp"
    source.write_text("#include <cmath>\n#include <cstdio>\n" + _block() + "\n" + main,
                      encoding="utf-8")
    binary = tmp_path / "pure"
    subprocess.run([CXX, "-std=c++17", "-O1", "-Wall", "-Werror", "-o", str(binary), str(source)],
                   check=True, capture_output=True, text=True)
    return subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout.splitlines()


def _cpp_array(name, values):
    return f"static const unsigned char {name}[] = {{{', '.join(str(int(v)) for v in values)}}};"


# -- the C++ block, compiled, against the Python mirror -----------------------------

def test_the_pure_block_has_no_engine_type():
    block = _block()
    assert "#include" not in block and "FString" not in block and "TEXT(" not in block


@NEEDS_CXX
def test_the_cpp_tables_encoder_and_box_are_the_python_ones(tmp_path):
    rng = np.random.default_rng(20261109)
    cases = []
    for factor in (1, 2, 3, 4):
        for out_w, out_h in ((1, 1), (3, 2), (5, 4)):
            data = rng.integers(0, 256, size=out_w * factor * out_h * factor * 4, dtype=np.uint8)
            cases.append((factor, out_w, out_h, data))
    # a hard case: every byte value inside one block, and a black/white edge
    cases.append((4, 4, 4, np.arange(4 * 4 * 16 * 4, dtype=np.int64) % 256))
    probes = [0.0, 1e-9, 0.0005, 0.003, 0.2, 0.5, 0.73, 0.999, 1.0, 1.5, -0.1]
    probes += [t for t in ss._THRESHOLD[::37]]  # exact ties round up in both
    main = ["using namespace FlightSimSupersamplePure;", "int main() {",
            "double D[256]; double T[255]; BuildTables(D, T);",
            "for (int b = 0; b < 256; ++b) printf(\"dec %.17g\\n\", D[b]);",
            "for (int b = 0; b < 255; ++b) printf(\"thr %.17g\\n\", T[b]);"]
    for p in probes:
        main.append(f"printf(\"enc %d\\n\", (int)EncodeLinear({p!r}, T));")
    for k, (factor, out_w, out_h, data) in enumerate(cases):
        n = out_w * out_h * 4
        main.insert(0, _cpp_array(f"In{k}", data))
        main.append(f"{{ unsigned char O[{n}]; if (!BoxDownsample(In{k}, {out_w}, {out_h}, {factor}, 4, O)) "
                    f"return 1; printf(\"box\"); for (int i = 0; i < {n}; ++i) printf(\" %d\", O[i]); "
                    "printf(\"\\n\"); }")
    main.append("{ unsigned char O[4]; printf(\"bad %d %d\\n\", BoxDownsample(In0, 1, 1, 5, 4, O) ? 1 : 0, "
                "BoxDownsample(In0, 0, 1, 2, 4, O) ? 1 : 0); }")
    sizes = [(3840, 2160, 200.0), (7680, 4320, 200.0), (1920, 1080, 100.0), (5760, 3240, 0.0)]
    for w, h, hsp in sizes:
        main.append(f"printf(\"vram %.17g\\n\", EstimateVramMiB({w}, {h}, {hsp!r}));")
    checks = [(f, w, h, hsp, side, budget) for f in (0, 1, 2, 3, 4, 5)
              for w, h in ((1920, 1080), (3840, 2160), (4097, 100))
              for hsp in (100.0, 200.0) for side, budget in ((16384, 7168.0), (8192, 4096.0))]
    for f, w, h, hsp, side, budget in checks:
        main.append(f"printf(\"chk %d\\n\", Check({f}, {w}, {h}, {hsp!r}, {side}, {budget!r}));")
    main.append("printf(\"const %d %d %d %.17g %.17g %.17g\\n\", MinFactor, MaxFactor, FallbackMaxTextureSide,"
                " RenderBytesPerPixel, TsrHistoryBytesPerPixel, VramBudgetMiBDefault);")
    main.append("return 0; }")
    out = _compile_and_run(tmp_path, "\n".join(main))
    lines = iter(out)

    for b in range(256):
        assert next(lines) == f"dec {ss._DECODE[b]:.17g}"
    for b in range(255):
        assert next(lines) == f"thr {ss._THRESHOLD[b]:.17g}"
    for p in probes:
        assert next(lines) == f"enc {ss.encode_linear(p)}"
    for factor, out_w, out_h, data in cases:
        cpp = [int(v) for v in next(lines).split()[1:]]
        reference = ss.box_downsample_reference([int(v) for v in data], out_w, out_h, factor, 4)
        image = np.asarray(data, dtype=np.uint8).reshape(out_h * factor, out_w * factor, 4)
        fast = ss.box_downsample(image, factor).reshape(-1).tolist()
        assert cpp == reference == fast
    assert next(lines) == "bad 0 0"
    for w, h, hsp in sizes:
        assert next(lines) == f"vram {ss.estimate_vram_mib(w, h, hsp):.17g}"
    for f, w, h, hsp, side, budget in checks:
        assert next(lines) == f"chk {ss.check(f, w, h, hsp, side, budget)}"
    assert next(lines) == (f"const {ss.MIN_FACTOR} {ss.MAX_FACTOR} {ss.FALLBACK_MAX_TEXTURE_SIDE} "
                           f"{ss.RENDER_BYTES_PER_PIXEL:.17g} {ss.TSR_HISTORY_BYTES_PER_PIXEL:.17g} "
                           f"{ss.VRAM_BUDGET_MIB_DEFAULT:.17g}")


def test_the_python_tsr_percentage_is_the_commandlets():
    match = re.search(r"RenderBeautyTsrHistoryScreenPercentage = ([0-9.]+)f;", COMMANDLET)
    assert match and float(match.group(1)) == ss.TSR_HISTORY_SCREEN_PERCENTAGE


# -- the box itself -----------------------------------------------------------------

def test_every_byte_survives_a_round_trip_and_a_flat_block():
    assert all(ss.encode_linear(ss._DECODE[b]) == b for b in range(256))
    for factor in (1, 2, 3, 4):
        flat = np.repeat(np.repeat(np.arange(256, dtype=np.uint8).reshape(16, 16), factor, 0), factor, 1)
        assert np.array_equal(ss.box_downsample(flat, factor), np.arange(256, dtype=np.uint8).reshape(16, 16))


def test_factor_one_is_the_identity():
    rng = np.random.default_rng(7)
    image = rng.integers(0, 256, size=(9, 13, 4), dtype=np.uint8)
    assert np.array_equal(ss.box_downsample(image, 1), image)


def test_the_box_averages_in_linear_light():
    # half black, half white: linear 0.5, which is sRGB byte 188, not 128
    block = np.array([[0, 255], [255, 0]], dtype=np.uint8)
    assert int(ss.box_downsample(block, 2)[0, 0]) == ss.encode_linear(0.5) == 188


@pytest.mark.parametrize("factor", [0, 5])
def test_a_factor_out_of_range_is_refused_by_name(factor):
    with pytest.raises(ValueError, match=r"^render\.supersample:"):
        ss.box_downsample(np.zeros((8, 8), dtype=np.uint8), factor)
    assert ss.refuse_reason(factor, 1920, 1080).startswith("render.supersample:")


# -- labels match pixels: the synthetic edge ------------------------------------------

#
# The label mask is the edge point-sampled at the OUTPUT pixel centres; the
# beauty is the same edge point-sampled at the INTERNAL centres, then
# reduced. Measured (2026-11-09; PROBE_LOG "## supersample"), worst over the
# angles and offsets below:
#   box      N=2: reach 0.35 px, edge 0.21 px; N=3: 0.44 / 0.13; N=4: 0.52 / 0.12; no overshoot
#   Lanczos3 N=2: reach 2.33 px, edge 0.21 px; N=3: 2.63 / 0.14; N=4: 2.50 / 0.12; overshoot ~0.1

ANGLES = (0.0, 17.0, 45.0, 73.0, 90.0, 131.0, 200.0, 287.0)
OFFSETS = (0.0, 0.13, 0.37, -0.29)
W, H = 24, 16
MARGIN = 3   # border lines left out (the Lanczos' truncated taps)


def _worst(reduce, factor):
    worst = {"reach_px": 0.0, "edge_px": 0.0, "overshoot": 0.0}
    for angle in ANGLES:
        for offset in OFFSETS:
            beauty = reduce(ss.half_plane(W * factor, H * factor, angle, offset, scale=factor), factor)
            mask = ss.half_plane(W, H, angle, offset)
            row = ss.edge_report(beauty, mask, angle, offset, margin=MARGIN)
            worst = {k: max(worst[k], float(row[k])) for k in worst}
    return worst


@pytest.mark.parametrize("factor", [2, 3, 4])
def test_the_box_keeps_pixel_centres_aligned(factor):
    box = _worst(ss.box_downsample_linear, factor)
    # only the pixels the edge crosses change: a pixel it does not cross is
    # wholly on one side, its centre at most sqrt(2)/2 px from the edge
    assert box["reach_px"] <= math.sqrt(2.0) / 2.0 + 1e-9
    assert box["overshoot"] == 0.0
    # the edge read back from the image is the geometric edge to within the
    # internal samples' own quantisation, 1/(2N) px
    assert box["edge_px"] <= 0.5 / factor + 1e-9
    # both inside the verifier's tolerances
    assert box["reach_px"] < MASK_TOL_PX <= LOOK_ALIGNMENT_TOL_PX
    assert box["edge_px"] < MASK_TOL_PX


@pytest.mark.parametrize("factor", [2, 3, 4])
def test_the_lanczos_rings_past_the_verifiers_tolerance(factor):
    """Why the box: a Lanczos-3 centred on the same output centres places
    the edge as well, but changes pixels past the tolerance
    look_label_alignment grants an unrecorded effect (and overshoots), so
    it would be pixel-moving at the sub-pixel level."""
    lanczos = _worst(ss.lanczos3_downsample, factor)
    assert lanczos["edge_px"] <= 0.5 / factor + 0.02
    assert lanczos["reach_px"] > LOOK_ALIGNMENT_TOL_PX
    assert lanczos["overshoot"] > 0.05


@pytest.mark.parametrize("factor", [2, 3, 4])
def test_a_box_one_internal_pixel_off_is_caught(factor):
    """The control: blocks starting one internal pixel late move the edge
    by exactly 1/N px, and the measure sees it."""
    hi = ss.half_plane(W * factor, H * factor, 0.0, 0.0, factor)
    late = np.concatenate([hi[:, 1:], hi[:, -1:]], axis=1)
    mask = ss.half_plane(W, H, 0.0, 0.0)
    assert ss.edge_report(ss.box_downsample_linear(hi, factor), mask, 0.0, 0.0)["edge_px"] <= 1e-12
    assert ss.edge_report(ss.box_downsample_linear(late, factor), mask, 0.0, 0.0)["edge_px"] == \
        pytest.approx(1.0 / factor)


@pytest.mark.parametrize("factor", [2, 3, 4])
def test_the_8bit_path_keeps_the_label_side_exact(factor):
    """Through the shipped path (sRGB bytes in, bytes out): a pixel the edge
    does not cross decodes to exactly 0 or 1, the mask's own value."""
    for angle in ANGLES:
        for offset in OFFSETS:
            hi = (ss.half_plane(W * factor, H * factor, angle, offset, factor) * 255).astype(np.uint8)
            out = ss._DECODE_NP[ss.box_downsample(hi, factor)]
            row = ss.edge_report(out, ss.half_plane(W, H, angle, offset), angle, offset)
            assert row["reach_px"] <= math.sqrt(2.0) / 2.0 + 1e-9 and row["overshoot"] == 0.0


# -- memory ---------------------------------------------------------------------------

def test_the_vram_estimate_at_4k_internal():
    # 3840 x 2160 internal (the sheet's 1920 x 1080 at -supersample=2), TSR
    # history at 200 %: 8 294 400 px x (112 + 24 x 4) B
    assert ss.estimate_vram_mib(3840, 2160) == pytest.approx(8294400 * 208 / 2 ** 20)
    assert ss.estimate_vram_mib(3840, 2160) == pytest.approx(1645.3125)
    assert ss.check(2, 1920, 1080) == ss.CHECK_OK
    assert ss.check(4, 1920, 1080) == ss.CHECK_OK          # 7680 x 4320: 6581 MiB
    assert ss.check(2, 3840, 2160) == ss.CHECK_OK          # 4K output at 2: the same 6581 MiB
    assert ss.estimate_vram_mib(7680, 4320) == pytest.approx(6581.25)


def test_over_the_budget_is_refused_by_name():
    assert ss.check(3, 3840, 2160) == ss.CHECK_VRAM        # 11520 x 6480: 14 808 MiB
    words = ss.refuse_reason(3, 3840, 2160)
    assert words.startswith("render.supersample:") and "MiB" in words
    assert ss.check(4, 4097, 100) == ss.CHECK_SIZE         # 16388 px wide
    assert ss.check(2, 1920, 1080, budget_mib=1000.0) == ss.CHECK_VRAM


# -- the commandlet hooks -------------------------------------------------------------

def test_the_hooks_are_few_and_marked():
    lines = COMMANDLET.splitlines()
    marks = [i for i, line in enumerate(lines) if "supersample lane hook" in line]
    assert len(marks) == 4
    for i in marks:
        assert "FFlightSimSupersample" in lines[i + 1] or "Supersample" in lines[i + 1]
    assert '#include "FlightSimSupersample.h"' in COMMANDLET


def test_configure_runs_before_the_beauty_target_and_after_the_lens_size():
    configure = COMMANDLET.index("FFlightSimSupersample::Configure(")
    target = COMMANDLET.index("RenderTarget->InitAutoFormat(Width * Supersample, Height * Supersample);")
    lens = COMMANDLET.index("Width = FMath::RoundToInt(CameraWidthPx);")
    assert lens < configure < target
    assert "RenderBeautyTsrHistoryScreenPercentage" in COMMANDLET[configure:configure + 200]


def test_the_downsample_is_after_the_read_back_and_before_the_png():
    read = COMMANDLET.index("if (Resource == nullptr || !Resource->ReadPixels(Pixels) || Pixels.Num() == 0)")
    down = COMMANDLET.index("FFlightSimSupersample::Downsample(Pixels, Width, Height, Supersample")
    lit = COMMANDLET.index("int32 Lit = 0;", read)
    png = COMMANDLET.index("FImageUtils::PNGCompressImageArray(Width, Height, Pixels, Png);")
    assert read < down < lit < png


def test_the_label_targets_stay_at_the_output_size():
    for name in ("LabelDepthTarget", "LabelIdTarget"):
        assert f"{name}->InitAutoFormat(Width, Height);" in COMMANDLET
    assert COMMANDLET.count("* Supersample") == 2      # the beauty target's two axes only


def test_every_other_target_and_the_tile_selection_stay_at_the_output_size():
    # Skeptic pass: not only the two label targets. Every render target the
    # commandlet makes, except the beauty's, is Width x Height, and the
    # Google tiles are selected for the OUTPUT viewport, so the beauty and
    # every label capture of a step draw one and the same tile set.
    sizes = re.findall(r"(\w+)->InitAutoFormat\(([^;]*)\);", COMMANDLET)
    assert len(sizes) >= 9
    for name, args in sizes:
        if name == "RenderTarget":
            assert args == "Width * Supersample, Height * Supersample"
        elif name == "CoverTarget":
            # The measured subject cover (3680856c): its own half-size
            # capture, never the output's, so the tile selection is unaffected.
            assert args == "CoverMeasure.CaptureWidth, CoverMeasure.CaptureHeight"
        else:
            assert args == "Width, Height", (name, args)
    assert re.search(r"GoogleTiles\.WaitForView\(Capture->GetComponentLocation\(\), "
                     r"Capture->GetComponentRotation\(\),\s*Capture->FOVAngle, Width, Height, Error\)",
                     COMMANDLET)


def test_the_record_follows_the_beauty_look():
    look = COMMANDLET.index('Root->SetObjectField(TEXT("beauty_look"), BeautyLook);')
    record = COMMANDLET.index("FFlightSimSupersample::Record(Root);")
    assert look < record


def test_configure_refuses_off_beauty_and_records_only_when_stated():
    body = SS_CPP.split("bool FFlightSimSupersample::Configure", 1)[1].split(
        "bool FFlightSimSupersample::Downsample", 1)[0]
    assert 'if (!FParse::Value(Params, TEXT("supersample="), Factor))\n\t{\n\t\treturn true;' in body
    assert 'if (Quality != TEXT("beauty"))' in body
    assert body.count('TEXT("render.supersample: ') == 5
    assert "State.bStated = true;" in body
    record = SS_CPP.split("void FFlightSimSupersample::Record", 1)[1]
    assert "if (!State.bStated || !Root.IsValid())" in record
    assert 'TryGetObjectField(TEXT("beauty_samples"), Existing)' in record   # merged, not replaced


def test_the_cpp_record_has_the_python_records_keys():
    record = SS_CPP.split("void FFlightSimSupersample::Record", 1)[1]
    cpp_keys = set(re.findall(r'Samples->Set\w+Field\(TEXT\("([a-z_]+)"\)', record))
    assert cpp_keys == set(ss.beauty_samples_record(2, 1920, 1080))


def test_the_refusal_is_catalogued_and_the_symbols_are_checked():
    assert re.search(r"^render\.supersample:\n  sentence: ", CATALOG, re.M)
    block = CHECK[CHECK.index("# -- supersample lane"):CHECK.index("# -- supersample lane end")]
    for symbol in ("GMaxTextureDimensions", "void InitAutoFormat(uint32 InSizeX, uint32 InSizeY);",
                   "bool ReadPixels(TArray<FColor>& OutImageData", "TryGetObjectField(FStringView FieldName",
                   "static CORE_API bool Value( const TCHAR* Stream, const TCHAR* Match, int32& Value );",
                   "RTF_RGBA8_SRGB", "SCS_FinalColorLDR"):
        assert symbol in block, symbol


# -- the verifier reads the record as label-aligned ----------------------------------

def test_the_record_passes_the_look_checks(tmp_path):
    from core.capture.manifest import read_capture_manifest
    from core.capture.verify import PASS, verify_look_label_alignment, verify_look_record
    run = tmp_path / "run"
    shutil.copytree(REPO / "tests" / "fixtures" / "engine_bundle_min", run)
    path = run / "frames" / "chase" / "render.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["scene"]["render_quality"] = "beauty"
    payload["beauty_samples"] = ss.beauty_samples_record(2, 1920, 1080)
    path.write_text(json.dumps(payload), encoding="utf-8")
    manifest = read_capture_manifest(run / "capture_manifest.json")
    assert verify_look_record(manifest, run).status == PASS
    assert verify_look_label_alignment(manifest, run).status == PASS


def test_no_record_key_reads_as_a_pixel_moving_look_key():
    from core.capture import beauty_look as bl
    for key in ss.beauty_samples_record(4, 960, 540):
        assert key not in bl.PIXEL_MOVING_KEYS


# -- the contact sheet asks for 2 by default ----------------------------------------

def test_the_beauty_sheet_supersamples_by_default():
    import experiments.visual_contact_sheet as sheet
    assert sheet.render_extra_tokens("beauty", None, False, None,
                                     supersample=ss.SHEET_DEFAULT_FACTOR) == ["-supersample=2"]
    assert sheet.render_extra_tokens("beauty", None, False, None) == []
    assert sheet.sheet_supersample("beauty", False, None) == 2
    assert sheet.sheet_supersample("measure", False, None) is None
    assert sheet.sheet_supersample("beauty", True, None) is None
    with pytest.raises(ValueError, match=r"^render\.supersample:"):
        sheet.render_extra_tokens("measure", None, False, None, supersample=2)
    with pytest.raises(ValueError, match=r"^render\.supersample:"):
        sheet.render_extra_tokens("beauty", None, True, None, supersample=2)
    with pytest.raises(ValueError, match=r"^render\.supersample:"):
        sheet.render_extra_tokens("beauty", None, False, None, supersample=5)
    assert 'TEXT("supersample=")' in SS_CPP
