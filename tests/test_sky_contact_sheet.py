"""Sky step 8: scripts/sky_contact_sheet.py, scripts/sky_compare_round.ps1 and their docs.

Synthetic frames and render.json stubs only: a check of the layout, the
bookkeeping and the pins on this machine, never a visual result. The PowerShell
is read, not run (no PowerShell here); every frame it would render is
UNMEASURED until the Windows laptop runs
``.\\scripts\\sky_compare_round.ps1 -Round 110 -Scene 3 -CompareWith 95``
from a checkout whose branch origin carries with sky steps 2-8 on it.

Repair round 1 (review): the sheet now says "applied unknown" and "-cloud-type=
not parsed" for a record that names no shape or does not carry the word asked
(an old host renders four frames of one look and used to pass as "no
mismatch"); round folders are looked up in docs/visual then the vis-windows
worktree, as visual_fix_round.ps1 does; the flat frames/render.json is read;
the ps1 passes -Branch and refuses a branch origin does not carry the sky steps
on, a reused round number and a duplicated -cloud-type=; the round numbers
moved to 110/115 because steps 2, 3 and 5 reserved 98-105.
"""

import json
import re
import sys
from pathlib import Path

import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import sky_contact_sheet as sheet  # noqa: E402
from core.scene import world_beauty as wb  # noqa: E402

PS1 = (REPO / "scripts" / "sky_compare_round.ps1").read_text(encoding="utf-8")
FIX_PS1 = (REPO / "scripts" / "visual_fix_round.ps1").read_text(encoding="utf-8")
CPP = (REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimClouds.cpp"
       ).read_text(encoding="utf-8")
DESIGN = (REPO / "docs" / "visual" / "XPLANE_SKY_DESIGN.md").read_text(encoding="utf-8")
PLAN = (REPO / "docs" / "VISUAL_FIDELITY_PLAN.md").read_text(encoding="utf-8")
README = (REPO / "docs" / "visual" / "sky_compare" / "README.md").read_text(encoding="utf-8")

SCENE = 3
OLD = 95
ROUNDS = [110, 111, 112, 113]
COMMAND_3 = ".\\scripts\\sky_compare_round.ps1 -Round 110 -Scene 3 -CompareWith 95"
COMMAND_13 = ".\\scripts\\sky_compare_round.ps1 -Round 115 -Scene 13 -CompareWith 95"


def _record(layers=(), hidden=(), tier="constrained", msf=1.0, switch="x"):
    """A sky-step-2 host's record: clouds.plan.cloud_type_switch is the word the
    host parsed from -cloud-type= (FlightSimClouds.cpp writes the switch string)."""
    return {"look_applied": {"world_beauty": {
        "clouds": {"layers": list(layers), "hidden_layers": list(hidden),
                   "march": {"tier": tier}, "plan": {"cloud_type_switch": switch}},
        "atmosphere": {"multi_scattering_factor": msf}}}}


def _layer(applied, source="switch"):
    return {"cloud_type_applied": applied, "cloud_type_source": source}


#: fbcbaa5d's shape: layers without cloud_type_applied, no plan block (the host
#: before sky step 2; -cloud-type= is not parsed there).
OLD_HOST_RECORD = {"look_applied": {"world_beauty": {
    "clouds": {"layers": [{"shape": "cumulus"}]},
    "atmosphere": {"multi_scattering_factor": 1.0}}}}
#: FlightSimClouds.cpp's -beauty-clouds=engine early return: clouds.drawn only.
ENGINE_RECORD = {"look_applied": {"world_beauty": {
    "clouds": {"drawn": "as the scene built them (-beauty-clouds=engine)"}}}}


def _frame(folder: Path, shade: int, name=f"{SCENE:02d}_a320_over_new_york.jpg", size=(640, 360)):
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (shade, shade + 20, shade + 40)).save(folder / name, quality=90)


def _round(root: Path, runs: Path, rnd: int, shade: int, record, switches=None, flat=False, run_id=None):
    """A round folder (frame, summary.json, ROUND.json) and its run's render.json
    under frames/cam/ (or the flat frames/render.json when ``flat``)."""
    _frame(root / f"round_{rnd}", shade)
    run = run_id or f"run{rnd}"
    (root / f"round_{rnd}" / "summary.json").write_text(json.dumps(
        [{"number": 1, "run_id": "other"}, {"number": SCENE, "run_id": run, "outcome": "done"}]),
        encoding="utf-8")
    (root / f"round_{rnd}" / "ROUND.json").write_text(json.dumps(
        {"round": rnd, "commit": f"c{rnd}", "switches": switches or f"-cloud-type=w{rnd}"}),
        encoding="utf-8")
    where = runs / run / "frames" if flat else runs / run / "frames" / "cam"
    where.mkdir(parents=True)
    (where / "render.json").write_text(json.dumps(record), encoding="utf-8")


@pytest.fixture
def fixture(tmp_path):
    """Rounds 110 (clear, hidden layer), 111 (cumulus, matching), 112 (NO frame),
    113 (overcast asked, stratocumulus drawn: MISMATCH); round 95 is the old look.
    Round 111 also carries a post twin that must not be picked. Every record
    carries the word asked in plan.cloud_type_switch (a step-2 host)."""
    root, runs = tmp_path / "visual", tmp_path / "runs"
    _frame(root / f"round_{OLD}", 100)
    (root / f"round_{OLD}" / "ROUND.json").write_text(json.dumps(
        {"round": OLD, "commit": "c95", "switches": ""}), encoding="utf-8")
    _round(root, runs, 110, 140, _record(hidden=[{"cloud_type_source": "switch", "reason": "clear"}],
                                         switch="clear"))
    _round(root, runs, 111, 60, _record(layers=[_layer("cumulus")], msf=1.25, switch="cumulus"))
    _round(root, runs, 113, 200, _record(layers=[_layer("stratocumulus")], switch="overcast"))
    _frame(root / "round_111", 60, f"{SCENE:02d}_a320_over_new_york_post.jpg")
    (root / "round_112").mkdir()
    return root, runs


def _compare(root, runs, rounds=ROUNDS, old=OLD, **kw):
    return sheet.compare(rounds, SCENE, old, roots=[root], run_root=runs, **kw)


def _report(out):
    return json.loads((out / "compare.json").read_text(encoding="utf-8"))


def test_the_sheet_and_the_report_cover_every_round_including_the_missing_one(fixture):
    root, runs = fixture
    out = _compare(root, runs, flightsim_sky="physical", switches="-cloud-march=probe")
    assert out == root / "sky_compare" / "round_110"
    with Image.open(out / "sheet.jpg") as im:
        assert im.width == 4 * sheet.TILE + 3 * sheet.GAP
        assert im.height == 2 * (270 + sheet.CAPTION_PX) + sheet.GAP   # 640x360 -> 480x270
    report = _report(out)
    assert report["scene"] == SCENE and report["old_round"] == OLD and report["old_found"]
    assert report["old_frame"] == f"round_{OLD}/{SCENE:02d}_a320_over_new_york.jpg"
    assert report["old_root"] == str(root) and report["roots"] == [str(root)]
    assert report["old_commit"] == "c95" and report["old_switches"] == ""
    assert report["rounds"] == ROUNDS and report["words"] == list(sheet.WORDS)
    assert report["flightsim_sky"] == "physical" and report["extra_switches"] == "-cloud-march=probe"
    assert report["missing"] == [112] and report["mismatches"] == [113]
    assert report["unknown"] == [] and report["switch_not_seen"] == [] and report["no_record"] == []
    assert report["reading_rule"] == sheet.READING_RULE
    tiles = {t["round"]: t for t in report["tiles"]}
    assert [t["word"] for t in report["tiles"]] == list(sheet.WORDS)
    # clear: no volumetric layer, read off hidden_layers, and that IS what clear asks for
    assert tiles[110]["applied"] == sheet.NO_LAYER and tiles[110]["mismatch"] is False
    assert tiles[110]["source"] == "switch" and tiles[110]["hidden_layers"] == 1
    assert tiles[110]["switch_seen"] is True and tiles[110]["cloud_type_switch"] == "clear"
    # cumulus: the layer, its march tier and the multi-scattering factor
    assert tiles[111]["applied"] == "cumulus" and tiles[111]["mismatch"] is False
    assert tiles[111]["march_tier"] == "constrained" and tiles[111]["multi_scattering_factor"] == 1.25
    assert tiles[111]["frame"].endswith("03_a320_over_new_york.jpg")   # not the _post twin
    assert tiles[111]["root"] == str(root)
    assert tiles[111]["commit"] == "c111" and tiles[111]["switches"] == "-cloud-type=w111"
    # the missing round is a row, not a gap; nothing about it is judged
    assert tiles[112]["found"] is False and tiles[112]["record"] is False
    assert tiles[112]["applied"] is None and tiles[112]["mismatch"] is None
    assert tiles[112]["switch_seen"] is None
    assert "against_old" not in tiles[112] and "health" not in tiles[112]
    # overcast asked, stratocumulus drawn: the host saw the word and drew another shape
    assert tiles[113]["expected"] == "overcast" and tiles[113]["mismatch"] is True
    assert tiles[113]["switch_seen"] is True
    # the pixel numbers against the old frame, and the health report, per present tile
    for rnd in (110, 111, 113):
        against = tiles[rnd]["against_old"]
        assert set(against) == {"mean_luma", "mean_abs_change", "moved_share", "mean_luma_old"}
        assert against["moved_share"] == 1.0            # every flat frame differs by > 8 levels
        assert tiles[rnd]["health"]["flags"] == ["blank"]   # a flat synthetic frame IS blank
        assert "UNCALIBRATED".lower() in tiles[rnd]["health"]["calibration"]
    assert tiles[111]["against_old"]["mean_luma"] < against["mean_luma_old"] < tiles[113]["against_old"]["mean_luma"]
    assert report["old_health"]["flags"] == ["blank"]
    assert "UNMEASURED" in report["basis"]


def test_the_same_inputs_write_the_same_bytes(fixture):
    root, runs = fixture
    a = _compare(root, runs, out=root / "a")
    b = _compare(root, runs, out=root / "b")
    assert (a / "compare.json").read_bytes() == (b / "compare.json").read_bytes()
    assert (a / "sheet.jpg").read_bytes() == (b / "sheet.jpg").read_bytes()


def test_a_missing_old_frame_is_said_not_invented(fixture):
    root, runs = fixture
    out = _compare(root, runs, old=7, out=root / "x")
    report = _report(out)
    assert report["old_found"] is False and report["old_frame"] is None and report["old_health"] is None
    assert report["old_root"] is None and report["old_commit"] is None
    assert "mean_abs_change" not in report["tiles"][1]["against_old"]
    assert (out / "sheet.jpg").is_file()


def test_an_old_host_record_is_unknown_and_not_parsed_never_a_match(tmp_path):
    """Review round 1: fbcbaa5d writes clouds.layers without cloud_type_applied and
    no plan block, because it does not parse -cloud-type=. Four such frames are
    one look; the sheet must say so instead of "applied None" in plain ink."""
    root, runs = tmp_path / "visual", tmp_path / "runs"
    _frame(root / f"round_{OLD}", 100)
    for rnd, shade in zip(ROUNDS, (120, 130, 140, 150)):
        _round(root, runs, rnd, shade, OLD_HOST_RECORD)
    got = sheet.applied_from(OLD_HOST_RECORD, "cumulus")
    assert got["record"] is True and got["applied"] == sheet.UNKNOWN
    assert got["source"] == "layers without cloud_type_applied"
    assert got["switch_seen"] is False and got["cloud_type_switch"] is None
    assert sheet.mismatch("cumulus", sheet.UNKNOWN) is True
    assert sheet.mismatch("clear", sheet.UNKNOWN) is True     # clear is no exception
    out = _compare(root, runs)
    report = _report(out)
    assert report["unknown"] == ROUNDS and report["switch_not_seen"] == ROUNDS
    assert report["mismatches"] == ROUNDS                     # never counted as a match
    assert report["missing"] == [] and report["no_record"] == []
    for tile in report["tiles"]:
        assert tile["applied"] == sheet.UNKNOWN and tile["mismatch"] is True
        lines = sheet.caption_lines(tile)
        assert lines[1].startswith("applied unknown: no shape in the record")
        assert lines[2] == sheet.NOT_PARSED == "host predates sky step 2: -cloud-type= not parsed"
        assert any(w in lines[1] for w in sheet.ALARM_WORDS)
        assert any(w in lines[2] for w in sheet.ALARM_WORDS)


def test_an_engine_mode_record_and_a_parsed_but_different_word_are_flagged():
    """FlightSimClouds.cpp's early returns (-beauty-clouds=engine, a material that
    did not load) write only clouds.drawn: applied unknown, with that string as
    the source. A record whose plan.cloud_type_switch is another word than the
    one asked did not honour this round's switch: switch_seen False."""
    got = sheet.applied_from(ENGINE_RECORD, "overcast")
    assert got["applied"] == sheet.UNKNOWN
    assert got["source"] == "as the scene built them (-beauty-clouds=engine)"
    assert got["switch_seen"] is False and got["hidden_layers"] == 0
    assert sheet.mismatch("overcast", got["applied"]) is True
    row = {"round": 1, "word": "overcast", "found": True, **got, "mismatch": True}
    assert sheet.caption_lines(row)[1] == ("applied unknown: no shape in the record "
                                           "(as the scene built them (-beauty-clouds=engine))")
    # the host parsed cumulus when overcast was asked: the shape matches cumulus, the switch does not
    other = sheet.applied_from(_record(layers=[_layer("cumulus")], switch="cumulus"), "overcast")
    assert other["applied"] == "cumulus" and other["switch_seen"] is False
    row = {"round": 2, "word": "overcast", "found": True, **other,
           "mismatch": sheet.mismatch("overcast", other["applied"])}
    assert row["mismatch"] is True
    assert sheet.caption_lines(row)[2] == "host parsed -cloud-type=cumulus, not overcast"
    # an empty switch string (the host parsed nothing) is not seen either
    assert sheet.applied_from(_record(layers=[_layer("cumulus")], switch=""), "cumulus")["switch_seen"] is False
    # without a word, any parsed switch counts as seen
    assert sheet.applied_from(_record(layers=[_layer("cumulus")], switch="cumulus"))["switch_seen"] is True


def test_a_frame_without_a_record_is_listed_under_no_record(fixture):
    root, runs = fixture
    (root / "round_111" / "summary.json").unlink()
    report = _report(_compare(root, runs, out=root / "n"))
    assert report["no_record"] == [111] and 111 not in report["mismatches"]
    tile = [t for t in report["tiles"] if t["round"] == 111][0]
    assert tile["found"] is True and tile["record"] is False and tile["applied"] is None
    assert sheet.caption_lines(tile)[1] == "no render.json record (applied unknown)"


def test_the_old_frame_is_found_in_the_fallback_root_like_visual_fix_round_does(tmp_path):
    """Round folders are committed to branch vis-windows, not the code branch, so
    visual_fix_round.ps1 step 4b looks in docs/visual then
    runs/vis-windows-wt/docs/visual. The sheet looks in the same two places, in
    the same order, for round M AND for the four rounds, and records the root."""
    first, second, runs = tmp_path / "visual", tmp_path / "wt" / "docs" / "visual", tmp_path / "runs"
    first.mkdir()
    _frame(second / f"round_{OLD}", 100)                       # the old look only in the worktree
    _round(first, runs, 110, 140, _record(hidden=[{"cloud_type_source": "switch"}], switch="clear"))
    _round(second, runs, 111, 60, _record(layers=[_layer("cumulus")], switch="cumulus"))   # only there
    _round(first, runs, 112, 90, _record(layers=[_layer("stratocumulus")], switch="stratocumulus"))
    _round(first, runs, 113, 200, _record(layers=[_layer("overcast")], switch="overcast"))
    _round(second, runs, 113, 20, _record(layers=[_layer("cumulus")], switch="overcast"),
           run_id="run113b")                                       # the first root wins
    out = sheet.compare(ROUNDS, SCENE, OLD, roots=[first, second], run_root=runs)
    assert out == first / "sky_compare" / "round_110"
    report = _report(out)
    assert report["roots"] == [str(first), str(second)]
    assert report["old_found"] is True and report["old_root"] == str(second)
    assert report["old_frame"] == f"round_{OLD}/{SCENE:02d}_a320_over_new_york.jpg"
    tiles = {t["round"]: t for t in report["tiles"]}
    assert tiles[110]["root"] == str(first) and tiles[111]["root"] == str(second)
    assert tiles[113]["root"] == str(first) and tiles[113]["applied"] == "overcast"
    assert report["missing"] == [] and report["mismatches"] == []
    assert "mean_abs_change" in tiles[111]["against_old"]        # compared against the worktree's old frame
    # the default roots are the two places visual_fix_round.ps1 reads, in its order
    assert sheet.ROOTS == (sheet.VISUAL, sheet.FALLBACK_VISUAL)
    assert sheet.FALLBACK_VISUAL == REPO / "runs" / "vis-windows-wt" / "docs" / "visual"
    assert 'runs\\vis-windows-wt\\docs\\visual\\$prevName' in FIX_PS1
    assert sheet.find_round(OLD, [first, second]) == second / f"round_{OLD}"
    assert sheet.find_round(7, [first, second]) is None


def test_the_flat_frames_render_json_is_read_after_the_run_s_and_before_the_cameras(tmp_path):
    """webapp/runs.py names frames/render.json for a run without a clip camera;
    visual_round.py reads <run>/render.json and frames/*/render.json. All three."""
    runs = tmp_path / "runs"
    flat = runs / "flat" / "frames"
    flat.mkdir(parents=True)
    (flat / "render.json").write_text(json.dumps(_record(layers=[_layer("overcast")])), encoding="utf-8")
    got = sheet.render_record("flat", runs)
    assert got and sheet.applied_from(got)["applied"] == "overcast"
    # order: the run's own record wins over the flat one, the flat one over a camera's
    (runs / "flat" / "render.json").write_text(json.dumps(_record(layers=[_layer("cumulus")])), encoding="utf-8")
    assert sheet.applied_from(sheet.render_record("flat", runs))["applied"] == "cumulus"
    (runs / "flat" / "render.json").unlink()
    cam = flat / "cam"
    cam.mkdir()
    (cam / "render.json").write_text(json.dumps(_record(layers=[_layer("stratocumulus")])), encoding="utf-8")
    assert sheet.applied_from(sheet.render_record("flat", runs))["applied"] == "overcast"
    (flat / "render.json").unlink()
    assert sheet.applied_from(sheet.render_record("flat", runs))["applied"] == "stratocumulus"
    assert sheet.render_record(None, runs) is None and sheet.render_record("nope", runs) is None
    assert 'else (frames / "render.json"))' in (REPO / "webapp" / "runs.py").read_text(encoding="utf-8")


def test_a_taller_old_frame_does_not_overflow_into_row_two(fixture):
    """A head sweep's aspect differs from a still's: the row height is the tallest
    tile including the old one."""
    root, runs = fixture
    _frame(root / "round_8", 100, size=(640, 640))             # a square old frame: 480x480 thumb
    out = _compare(root, runs, old=8, out=root / "t")
    with Image.open(out / "sheet.jpg") as im:
        assert im.height == 2 * (480 + sheet.CAPTION_PX) + sheet.GAP


def test_the_command_line_runs_and_refuses_an_unknown_word(fixture, capsys):
    root, runs = fixture
    argv = ["--rounds", "110,111,112,113", "--scene", str(SCENE), "--old", str(OLD),
            "--root", str(root), "--fallback-root", str(root / "none"), "--run-root", str(runs),
            "--flightsim-sky", "physical"]
    assert sheet.main(argv) == 0
    printed = capsys.readouterr().out
    assert f"old look: round {OLD} in {root}" in printed
    assert "round 112 -cloud-type=stratocumulus: MISSING" in printed
    assert "round 113 -cloud-type=overcast: frame, applied stratocumulus MISMATCH" in printed
    assert "mismatches: [113]" in printed and "unknown: []" in printed
    assert "switch_not_seen: []" in printed and "no_record: []" in printed and "missing: [112]" in printed
    assert "reading rule: " + sheet.READING_RULE in printed
    report = _report(root / "sky_compare" / "round_110")
    assert report["roots"] == [str(root), str(root / "none")]
    # the old-host case prints SWITCH NOT SEEN per tile
    (runs / "run111" / "frames" / "cam" / "render.json").write_text(json.dumps(OLD_HOST_RECORD), encoding="utf-8")
    assert sheet.main(argv) == 0
    assert "round 111 -cloud-type=cumulus: frame, applied unknown MISMATCH SWITCH NOT SEEN" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        sheet.main(argv + ["--words", "clear,cumulus,fog,overcast"])
    with pytest.raises(SystemExit):
        sheet.main(["--rounds", "1,2", "--scene", "3", "--old", "0", "--root", str(root)])


# -- the pins: the words, the layout, the record the sheet reads, the ps1 and the docs --


def test_the_four_words_are_the_brief_s_and_the_host_accepts_each():
    """Brief step 8: clear, scattered cumulus, broken stratocumulus, overcast. Each
    is a -cloud-type= word (world_beauty.PLAN_CLOUD_TYPES, the C++ list); clear
    applies no volumetric layer, the other three their CLOUDS row."""
    assert sheet.WORDS == ("clear", "cumulus", "stratocumulus", "overcast")
    for word in sheet.WORDS:
        assert word in wb.PLAN_CLOUD_TYPES
    assert sheet.expected_shape("clear") == sheet.NO_LAYER
    assert sheet.expected_shape("cirrus") == sheet.NO_LAYER
    for word in ("cumulus", "stratocumulus", "overcast"):
        assert sheet.expected_shape(word) == word
    assert sheet.mismatch("clear", None) is None
    assert sheet.mismatch("clear", sheet.NO_LAYER) is False
    assert sheet.mismatch("overcast", "cumulus") is True
    assert sheet.mismatch("overcast", sheet.UNKNOWN) is True
    assert sheet.UNKNOWN not in wb.PLAN_CLOUD_SHAPES and sheet.NO_LAYER not in wb.PLAN_CLOUD_SHAPES


def test_the_layout_constants_are_pinned_by_value():
    """Report geometry (not look values): a 480-px tile, a 58-px caption band of
    three 14-px lines, an 8-px gap; the sheet is 4 tiles wide."""
    assert (sheet.TILE, sheet.CAPTION_PX, sheet.GAP) == (480, 58, 8)
    assert sheet.CAPTION_PX >= 4 + 14 * 3
    assert sheet.ALARM_WORDS == ("MISMATCH", "MISSING", "unknown", "not parsed", "host parsed")


def test_the_sheet_reads_the_keys_the_host_writes():
    """The caption's fields are render.json's, written by FFlightSimWorldBeauty
    (look_applied.world_beauty.clouds.layers[].cloud_type_applied / _source, the
    hidden_layers a clear word leaves, march.tier, plan.cloud_type_switch (the
    switch string the host parsed), atmosphere.multi_scattering_factor, and the
    early returns' clouds.drawn), and the switch the ps1 passes is the one Build
    parses."""
    for key in ("cloud_type_applied", "cloud_type_source", "hidden_layers", "layers", "tier",
                "multi_scattering_factor", "cloud_type_switch", "drawn"):
        assert f'TEXT("{key}")' in CPP, key
    assert 'PlanOut->SetStringField(TEXT("cloud_type_switch"), CloudTypeSwitch);' in CPP
    assert 'FParse::Value(*Switches, TEXT("cloud-type="), CloudTypeSwitch);' in CPP
    assert 'TEXT("drawn"), TEXT("as the scene built them (-beauty-clouds=engine)")' in CPP
    assert wb.CLOUD_TYPE_SWITCH == "-cloud-type"
    assert 'Scene.LookApplied->SetObjectField(TEXT("world_beauty"), Record);' in CPP
    # the empty record and the record with a hidden layer, as applied_from reads them
    got = sheet.applied_from(None)
    assert got["record"] is False and got["applied"] is None and got["switch_seen"] is None
    got = sheet.applied_from(_record(hidden=[{"cloud_type_source": "plan"}], switch="clear"), "clear")
    assert got["applied"] == sheet.NO_LAYER and got["source"] == "plan" and got["switch_seen"] is True


def test_the_powershell_renders_four_rounds_of_one_scene_on_the_branch_it_stands_on():
    """sky_compare_round.ps1: FLIGHTSIM_SKY stated, the branch checked against origin
    before round 1 (visual_fix_round.ps1 checks out and fast-forwards -Branch FROM
    ORIGIN, default phase-3-completed; a host before sky step 2 ignores
    -cloud-type=), visual_fix_round.ps1 called once per word with -cloud-type=<word>,
    the same scene / old round / branch, then sky_contact_sheet.py into
    docs\\visual\\sky_compare\\round_<N> with the worktree as the fallback root;
    refusals by name; Windows PowerShell 5.1 rules (tests/test_powershell_scripts.py
    lints the syntax)."""
    assert '$ErrorActionPreference = "Continue"' in PS1
    assert 'if (-not $env:FLIGHTSIM_SKY) { $env:FLIGHTSIM_SKY = "physical" }' in PS1
    assert '[string]$Words = "clear,cumulus,stratocumulus,overcast"' in PS1
    assert "[int]$Scene = 3," in PS1            # the design's primary camera (D14)
    assert '$fixRound = Join-Path $PSScriptRoot "visual_fix_round.ps1"' in PS1
    assert '$sw = "-cloud-type=$word"' in PS1
    assert "& $fixRound @fixArgs" in PS1
    assert re.search(r"\$fixArgs = @\{ Round = \$thisRound; Scenes = \"\$Scene\"; Switches = \$sw; "
                     r"CompareWith = \"\$oldRound\"; Branch = \$Branch", PS1)
    assert "$rounds = @(0..3 | ForEach-Object { $Round + $_ })" in PS1
    assert '"scripts\\sky_contact_sheet.py", "--rounds", ($rounds -join ",")' in PS1
    assert '$out = Join-Path $repo "docs\\visual\\sky_compare\\round_$Round"' in PS1
    # the branch: the checkout's unless named; origin must carry steps 2 and 8
    assert '[string]$Branch = "",' in PS1
    assert 'if (-not $Branch) { $Branch = (git rev-parse --abbrev-ref HEAD).Trim() }' in PS1
    assert 'git cat-file -e "origin/${Branch}:scripts/sky_contact_sheet.py"' in PS1
    assert 'git show "origin/${Branch}:core/scene/world_beauty.py"' in PS1
    assert 'Select-String -Quiet -SimpleMatch "PLAN_CLOUD_SHAPES"' in PS1
    assert PS1.index('Refuse "compare.wrong_branch"') < PS1.index("& $fixRound @fixArgs")
    assert PS1.index('Refuse "compare.round_exists"') < PS1.index("& $fixRound @fixArgs")
    # visual_fix_round.ps1 took -Branch with the old hard-coded value as its default
    assert '[string]$Branch = "phase-3-completed",' in FIX_PS1
    assert '$branch = "phase-3-completed"' not in FIX_PS1
    assert "git checkout -q $branch" in FIX_PS1 and 'git merge -q --ff-only "origin/$branch"' in FIX_PS1
    # the old round's second home, the same as visual_fix_round.ps1 step 4b's
    assert '$wtVisual = Join-Path $wt "docs\\visual"' in PS1
    assert 'if (Test-Path $wtVisual) { $sheetArgs += @("--fallback-root", $wtVisual) }' in PS1
    # a second -cloud-type= would be ignored by FParse::Value (first wins)
    assert "if ($Switches -match '(^|\\s)-cloud-type=')" in PS1
    # an empty native argument is dropped by 5.1: both optional values are guarded
    assert 'if ($Switches) { $sheetArgs += @("--switches", "$Switches") }' in PS1
    assert 'if ($env:FLIGHTSIM_SKY) { $sheetArgs += @("--flightsim-sky"' in PS1
    for rule in ("python.venv", "compare.no_fix_round", "compare.no_scene", "compare.no_old",
                 "compare.four_words", "compare.old_in_set", "compare.switch_dup",
                 "compare.round_exists", "compare.wrong_branch", "git.fetch",
                 "compare.round_failed", "compare.no_round_folder", "compare.sheet",
                 "compare.no_sheet", "git.pull", "git.commit", "git.push"):
        assert f'Refuse "{rule}"' in PS1, rule
    assert 'Write-Host "REFUSED ${rule}: $words"' in PS1 and "exit 3" in PS1
    assert "UNMEASURED" in PS1
    assert "-Round 110 -Scene 3 -CompareWith 95" in PS1 and "-Round 115 -Scene 13" in PS1
    # it never names an engine version or path: visual_fix_round.ps1 owns the prep
    assert "UE_" not in PS1 and "UnrealEditor" not in PS1


def test_the_round_numbers_do_not_collide_with_steps_2_3_and_5():
    """VISUAL_FIDELITY_PLAN.md §8 gives steps 2, 3 and 5 rounds 98-105 on this
    branch; step 8's two sets are 110-113 (scene 3) and 115-118 (scene 13), and
    no step 8 doc names a 98 or 105 set any more."""
    used = set()
    for m in re.finditer(r"visual_fix_round\.ps1 -Round (\d+)", PLAN):
        used.add(int(m.group(1)))
    assert {98, 99, 100, 101, 102, 104, 105} <= used
    for n in range(110, 114):
        assert n not in used, n
    for n in range(115, 119):
        assert n not in used, n
    for text, name in ((PLAN, "plan"), (README, "readme"), (PS1, "ps1")):
        assert "sky_compare_round.ps1 -Round 98 " not in text, name
        assert "sky_compare_round.ps1 -Round 105 " not in text, name
        assert COMMAND_3 in text and COMMAND_13 in text, name


def test_the_docs_name_the_script_the_location_the_precondition_and_the_unmeasured_state():
    for text, name in ((DESIGN, "design"), (PLAN, "plan"), (README, "readme")):
        assert "scripts/sky_compare_round.ps1" in text or "sky_compare_round.ps1" in text, name
        assert "sky_contact_sheet.py" in text, name
        assert "docs/visual/sky_compare/round_" in text, name
        assert "UNMEASURED" in text, name
        # the precondition: visual_fix_round.ps1 renders origin's copy of a branch
        # the branch was renamed claude/vibrant-gauss-olema4 -> phase-3-completed
        # (2026-11-18); the dated docs keep the name they were written under
        assert ("phase-3-completed" in text or "claude/vibrant-gauss-olema4" in text) and "merged into" in text, name
        assert "-Branch" in text, name
        assert "switch_not_seen" in text, name
    assert "### Sky step 8" in PLAN
    # the reading rule, in the two places the owner reads
    for text in (PLAN, README):
        assert "mismatches" in text and "unknown" in text and "no_record" in text and "missing" in text
        assert "runs/vis-windows-wt/docs/visual" in text or "runs\\vis-windows-wt\\docs\\visual" in text
    # the false claim is gone from every doc
    for text, name in ((DESIGN, "design"), (PLAN, "plan"), (README, "readme")):
        assert "the four frames then compare the step 2/3/5 host against round 95" not in text, name
        assert "so the four frames compare the step 2/3/5 host" not in text, name
    # the design's §10 named sky_compare.py and multi_scattering_applied; the built script
    # is sky_contact_sheet.py reading multi_scattering_factor and the design says so
    assert "sky_compare.py" not in README
    assert re.search(r"Built.*sky_contact_sheet\.py", DESIGN, re.S)
    assert "multi_scattering_applied" in DESIGN and "multi_scattering_factor" in DESIGN
    assert re.search(r"Repair.*round 1", DESIGN)
    # scene 13's stratocumulus / overcast tiles: the deck stays above the 747
    assert "above" in README and "CumulusLayerLowered" in README
