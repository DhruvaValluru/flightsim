"""Cross-platform support (Part B): one dispatch module, named refusals.

The platform story is code, not luck: OS dispatch lives in
core/util/platform.py alone, missing tools refuse by name with the
per-OS fix, fonts degrade honestly instead of crashing, the UE half
refuses ue.platform off-mac, and the UTF-8 discipline is enforced
statically so it cannot rot.
"""

import re
import sys
from pathlib import Path

import pytest

from core.util import platform as plat

REPO = Path(__file__).resolve().parents[1]


def test_os_name_dispatch(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert plat.os_name() == "mac" and plat.is_mac()
    monkeypatch.setattr(sys, "platform", "linux")
    assert plat.os_name() == "linux" and not plat.is_mac()
    monkeypatch.setattr(sys, "platform", "win32")
    assert plat.os_name() == "windows"


def test_ue_dispatch_windows_needs_engine_and_bridge(monkeypatch, tmp_path):
    """Windows gets the UE half only once BOTH pieces exist -- the
    engine's UnrealEditor-Cmd.exe and a built FlightSimBridge DLL -- so a
    bare clone refuses ue.platform by name instead of failing mid-run.
    UE_ROOT overrides the engine location like FLIGHTSIM_FFMPEG does for
    ffmpeg."""
    monkeypatch.setattr(sys, "platform", "win32")
    root = tmp_path / "UE_5.5"
    monkeypatch.setenv("UE_ROOT", str(root))
    assert plat.find_ue_root() == root
    editor = plat.ue_editor_path()
    assert editor == (root / "Engine" / "Binaries" / "Win64"
                      / "UnrealEditor-Cmd.exe")
    assert plat.ue_available() is False          # nothing installed

    editor.parent.mkdir(parents=True)
    editor.write_bytes(b"")
    bridge = tmp_path / "UnrealEditor-FlightSimBridge.dll"
    monkeypatch.setattr(plat, "ue_bridge_binary", lambda repo: bridge)
    assert plat.ue_available() is False          # engine alone: not enough

    bridge.write_bytes(b"")
    assert plat.ue_available() is True           # engine + built bridge


def test_ue_dispatch_mac_and_linux_unchanged(monkeypatch):
    """mac keeps its measured behavior (available, editor at the default
    install); Linux still has no UE half at all."""
    monkeypatch.delenv("UE_ROOT", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert plat.ue_available() is True
    assert plat.ue_editor_path() == Path(
        "/Users/Shared/Epic Games/UE_5.5/Engine/Binaries/Mac/UnrealEditor-Cmd")
    assert plat.ue_bridge_binary(REPO).suffix == ".dylib"

    monkeypatch.setattr(sys, "platform", "linux")
    assert plat.ue_available() is False
    assert plat.ue_editor_path() is None


def test_ffmpeg_env_override_wins(monkeypatch, tmp_path):
    fake = tmp_path / "my-ffmpeg"
    monkeypatch.setenv("FLIGHTSIM_FFMPEG", str(fake))
    assert plat.find_ffmpeg() == fake


def test_missing_ffmpeg_is_a_named_refusal(monkeypatch):
    """ffmpeg.missing, with the per-OS install command in the message --
    raised at the point of use so everything short of encoding works."""
    monkeypatch.delenv("FLIGHTSIM_FFMPEG", raising=False)
    monkeypatch.setattr(plat.shutil, "which", lambda name: None)
    monkeypatch.setattr(plat, "_FFMPEG_FALLBACKS",
                        {k: () for k in plat._FFMPEG_FALLBACKS})
    with pytest.raises(plat.FfmpegMissingError, match="ffmpeg.missing"):
        plat.find_ffmpeg()
    try:
        plat.find_ffmpeg()
    except plat.FfmpegMissingError as exc:
        assert "install" in str(exc).lower()
        assert exc.constraint == "ffmpeg.missing"


def test_font_chain_and_honest_degradation(monkeypatch, tmp_path, capsys):
    """Env override wins; with nothing resolvable the caller gets
    Pillow's bitmap font WITH a logged warning -- an ugly panel beats no
    clip, and the warning keeps the degradation honest."""
    override = tmp_path / "mono.ttf"
    monkeypatch.setenv("FLIGHTSIM_FONT", str(override))
    assert plat.find_mono_font() == str(override)

    monkeypatch.delenv("FLIGHTSIM_FONT", raising=False)
    monkeypatch.setattr(plat, "_FONT_CHAINS",
                        {k: () for k in plat._FONT_CHAINS})
    assert plat.find_mono_font() is None
    fonts = plat.mono_fonts((15, 12))
    assert len(fonts) == 2
    assert "WARNING" in capsys.readouterr().out


def test_webapp_refuses_ue_platform_off_mac(monkeypatch):
    """Off-mac a render request is the NAMED ue.platform refusal on the
    page, never a 500; the headless half stays available."""
    from fastapi.testclient import TestClient

    from core.nl.compiler import compile_prompt
    from webapp.server import app

    monkeypatch.setattr(plat, "ue_available", lambda: False)
    # About the platform refusal, not the scene or the mesh rule: pin the
    # flat scene and hold the mesh gate open so the test measures the
    # same thing on a machine with or without local bakes and models.
    import webapp.runs as runs_module
    import webapp.server as server_module

    monkeypatch.setattr(runs_module, "pick_scene",
                        lambda spec: {"key": "flat", "kind": "flat",
                                      "terrain": None, "imagery": None,
                                      "label": "flat (test)"})
    monkeypatch.setattr(server_module, "refuse_placeholder_mesh",
                        lambda spec: None)
    spec = compile_prompt("fly the 747 at 3000 m and 250 kt")
    client = TestClient(app)
    reply = client.post("/run", json={"spec": spec.to_dict()})
    assert reply.status_code == 409
    body = reply.json()
    assert body.get("constraint") == "ue.platform"
    assert "macOS" in body["refused"]

    status = client.get("/status").json()
    assert status["platform"] in ("mac", "linux", "windows")
    assert isinstance(status["render_available"], bool)


def test_no_shadowed_locals_in_the_bridge():
    """MSVC's C4456 is an ERROR under UE's warnings-as-errors, and clang
    on mac does not raise it: two shadowed `Current` index variables in
    FlightSimScenarioWorld.cpp compiled clean for the whole life of the
    mac-only build and stopped the first Windows build dead. Enforced
    statically here because the bridge cannot be compiled on CI (no
    engine), so nothing else would catch a reintroduction until someone
    with a Windows machine hit it again.
    """
    decl = re.compile(
        r"^\s*(?:const\s+)?(?:static\s+)?"
        r"(?:int32|int|uint32|double|float|bool|FString|FVector|FRotator"
        r"|FText|FName|auto|TArray<[^;]*?>|TMap<[^;]*?>)\s+(\w+)\s*(?:=|;|\()")

    def without_comments(text):
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        return "\n".join(re.sub(r"//.*$", "", ln) for ln in text.split("\n"))

    offenders = []
    source = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source"
    for path in sorted(source.rglob("*.cpp")):
        scopes = [{}]
        for number, line in enumerate(
                without_comments(path.read_text(encoding="utf-8")).split("\n"),
                start=1):
            match = decl.match(line)
            if match:
                name = match.group(1)
                for outer in scopes[:-1]:
                    if name in outer and len(scopes) > 1:
                        offenders.append(
                            f"{path.relative_to(REPO)}:{number}: '{name}' "
                            f"hides the declaration at line {outer[name]}")
                        break
                scopes[-1][name] = number
            for _ in range(line.count("{")):
                scopes.append({})
            for _ in range(line.count("}")):
                if len(scopes) > 1:
                    scopes.pop()
    assert not offenders, (
        "shadowed locals (MSVC C4456 is an error under UE's "
        "warnings-as-errors): " + ", ".join(offenders))


def test_no_text_io_without_utf8_encoding():
    """The Windows-twin of gotcha 13, enforced statically: every
    text-mode file read/write call in core/, webapp/, experiments/,
    scripts/ and tests/ states encoding="utf-8" -- Windows' cp1252
    default corrupts the UTF-8 provenance sidecar on first write, and
    this test keeps the sweep from rotting."""
    binary = re.compile(r"""['"][rwax]\+?b['"]|['"]b[rwax]['"]""")
    # Patterns built by concatenation so this file's own source never
    # contains the literal tokens the scan looks for.
    targets = [re.compile(r"(?<![\w.])" + "open" + r"\("),
               re.compile(r"\." + "read_text" + r"\("),
               re.compile(r"\." + "write_text" + r"\(")]

    def args_of(text, start):
        depth, i, in_str = 0, start, None
        while i < len(text):
            c = text[i]
            if in_str:
                if c == "\\":
                    i += 2
                    continue
                if text.startswith(in_str, i):
                    i += len(in_str)
                    in_str = None
                    continue
                i += 1
                continue
            for q in ('"""', "'''", '"', "'"):
                if text.startswith(q, i):
                    in_str = q
                    i += len(q)
                    break
            else:
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                    if depth == 0:
                        return text[start + 1:i]
                i += 1
        return text[start + 1:]

    offenders = []
    for root in ("core", "webapp", "experiments", "scripts", "tests"):
        for path in sorted((REPO / root).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for pat in targets:
                for m in pat.finditer(text):
                    args = args_of(text, m.end() - 1)
                    if "encoding" in args or binary.search(args):
                        continue
                    line = text[:m.start()].count("\n") + 1
                    offenders.append(f"{path.relative_to(REPO)}:{line}")
    assert not offenders, (
        "text I/O without encoding='utf-8' (Windows cp1252 hazard): "
        + ", ".join(offenders))
