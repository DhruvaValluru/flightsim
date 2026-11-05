"""Source-reading tests over scripts/check_bridge_api.sh (A5 retry, UE 5.5.4 measured; pin is now 5.7)."""
import re
import shutil
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_bridge_api.sh"
TEXT = SCRIPT.read_text(encoding="utf-8")
BUILD_CS = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/FlightSimBridge.Build.cs"


# On Windows a bare "bash" is System32's WSL stub (UTF-16 output, no distro);
# the script is written for Git Bash.
_GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")
BASH = str(_GIT_BASH) if os.name == "nt" and _GIT_BASH.is_file() else "bash"

def run(*args):
    return subprocess.run([BASH, str(SCRIPT), *args], capture_output=True, text=True, cwd=ROOT)


def test_module_list_comes_from_dependency_lists_only(tmp_path):
    cs = tmp_path / "X.Build.cs"
    cs.write_text(
        'PublicDependencyModuleNames.AddRange(new string[] {\n'
        '  "Core", "Json", // "CommentOnly"\n'
        '  "Niagara",\n});\n'
        'string p = Path.Combine(Dir, "Plugins", "Marketplace");\n'
        'PublicDependencyModuleNames.Add("CesiumRuntime");\n'
        'PrivateDependencyModuleNames.Add("Slate");\n',
        encoding="utf-8",
    )
    got = run("--list-modules", str(cs)).stdout.split()
    assert got == ["CesiumRuntime", "Core", "Json", "Niagara", "Slate"]


def test_real_build_cs_has_no_path_words_as_modules():
    got = run("--list-modules").stdout.split()
    assert "Plugins" not in got and "Marketplace" not in got
    assert "CesiumRuntime" in got and "JSBSimFlightDynamicsModel" in got
    assert "grep -oE '\"[A-Za-z]+\"'" not in TEXT


def test_every_show_flag_pattern_matches_engine_forms(tmp_path):
    flags = re.findall(r"^showflag_check (\w+)$", TEXT, re.M)
    assert flags == ["Cloud", "LumenGlobalIllumination", "LumenReflections",
                     "Grain", "SceneColorFringe", "Vignette"]
    inl = tmp_path / "ShowFlagsValues.inl"
    for f in flags:
        pat = run("--showflag-pattern", f).stdout.strip()
        for line in (f"SHOWFLAG_FIXED_IN_SHIPPING(1, {f}, SFG_PostProcess, LOCTEXT(\"x\", \"y\"))",
                     f"SHOWFLAG_ALWAYS_ACCESSIBLE({f}, SFG_Normal, LOCTEXT(\"x\", \"y\"))"):
            inl.write_text(line + "\n", encoding="utf-8")
            assert subprocess.run(["grep", "-qE", "--", pat, str(inl)]).returncode == 0, line
        inl.write_text(f"SHOWFLAG_FIXED_IN_SHIPPING(1, {f}Extra, SFG_Normal, x)\n", encoding="utf-8")
        assert subprocess.run(["grep", "-qE", "--", pat, str(inl)]).returncode != 0


def test_module_search_covers_project_plugins_and_engine():
    m = re.search(r'find "\$UE_ROOT/Engine" "\$PLUGIN" ue/Plugins -name "\$m\.Build\.cs"', TEXT)
    assert m, "project-level ue/Plugins must be searched beside the engine tree"
    assert 'bad "module $m" "no $m.Build.cs anywhere"' in TEXT  # still a FAIL when absent


def test_python_prefers_venv(tmp_path):
    order = re.search(r"for c in (.+); do", TEXT).group(1).split()
    assert order == [".venv/bin/python", ".venv/Scripts/python.exe", "python3", "python"]
    assert "python3 - <<" not in TEXT
    fn = re.search(r"^pick_python\(\) \{.*?^\}", TEXT, re.M | re.S).group(0)
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    py = venv / "python"
    py.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    py.chmod(0o755)
    r = subprocess.run([BASH, "-c", fn + "\npick_python"], capture_output=True, text=True, cwd=tmp_path)
    assert r.stdout == ".venv/bin/python"
    # no venv: falls through to a real interpreter on PATH, never fails here
    shutil.rmtree(tmp_path / ".venv")
    r = subprocess.run([BASH, "-c", fn + "\npick_python"], capture_output=True, text=True, cwd=tmp_path)
    assert r.stdout in ("python3", "python")
