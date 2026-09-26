"""What the capture command says on its default path, for a reader who
is not going to read code: no library banner over the spec line and the
refusals, every refusal by name, the help stating the engine actually
pinned.

Measured before the fixes (7b0a39a): `python -m flightsim.capture
examples/cameras_multi.yaml --max-previews 0` printed the JSBSim
startup banner 12 times before "spec ... valid"; `--help` said
"UE 5.5" after the pin moved to 5.7; three `REFUSED --` lines carried
no rule name (an unreadable spec, the host-flight error in its
bracketed form, the render wrapper's exit).
"""

import os
import re
import threading
from pathlib import Path

import pytest

import flightsim
from core.util.platform import UE_ENGINE_VERSION
from flightsim.capture import (
    LIBRARY_BANNER_PREFIXES, _relay_without_banners, main as capture_main,
    quiet_library_banners,
)

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"
CAPTURE_SOURCE = REPO / "flightsim" / "capture.py"

BANNER = (b"\n\n     JSBSim Flight Dynamics Model v1.2.4 Feb  7 2026 11:12:49\n"
          b"            [JSBSim-ML v2.0]\n\nJSBSim startup beginning ...\n\n")


def _relay(payload: bytes) -> bytes:
    """Push bytes through the relay exactly as the pipe would."""
    read_end, write_end = os.pipe()
    out_read, out_write = os.pipe()
    thread = threading.Thread(target=_relay_without_banners,
                              args=(read_end, out_write))
    thread.start()
    os.write(write_end, payload)
    os.close(write_end)
    thread.join()
    os.close(out_write)
    chunks = []
    while True:
        chunk = os.read(out_read, 65536)
        if not chunk:
            break
        chunks.append(chunk)
    os.close(out_read)
    return b"".join(chunks)


def test_the_relay_drops_the_banner_and_keeps_every_other_line():
    payload = (b"first line\n" + BANNER + BANNER + b"spec abc valid\n"
               b"\n" b"a blank line of our own above\n" + BANNER[:-1])
    out = _relay(payload)
    assert out == (b"first line\n" b"spec abc valid\n" b"\n"
                   b"a blank line of our own above\n")
    for prefix in LIBRARY_BANNER_PREFIXES:
        assert prefix not in out
    # Nothing but banners: nothing at all, not even their blank frame.
    assert _relay(BANNER * 3) == b""
    # A line without its newline still arrives.
    assert _relay(b"partial") == b"partial"


def test_the_context_manager_filters_what_c_writes_to_fd_1(capfd):
    """Bytes written straight to file descriptor 1, as the C++ library
    writes them (fd-level only here: under capfd a Python print goes
    through a separately opened handle with its own file offset, which
    no terminal or pipe has)."""
    with quiet_library_banners():
        os.write(1, b"kept\n" + BANNER + b"also kept\n")
    os.write(1, b"after\n")
    out = capfd.readouterr().out
    assert out == "kept\nalso kept\nafter\n"
    # Disabled, the same bytes pass untouched.
    with quiet_library_banners(enabled=False):
        os.write(1, BANNER)
    assert "JSBSim startup beginning" in capfd.readouterr().out


def test_the_default_path_prints_no_library_banner(tmp_path, capfd):
    """The two-camera example, exactly as the README runs it: the first
    line a person sees is the spec line, not a flight model's banner."""
    code = capture_main([str(EXAMPLES / "cameras_multi.yaml"),
                         "--out", str(tmp_path / "run"), "--max-previews", "0"])
    assert code == 0
    out = capfd.readouterr().out
    assert "JSBSim" not in out, out[:400]
    assert out.startswith("spec "), out[:200]
    assert "valid; running headlessly" in out


def test_verbose_keeps_the_library_banner(tmp_path, capfd):
    code = capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--verbose",
                         "--out", str(tmp_path / "run"), "--max-previews", "0"])
    assert code == 0
    out = capfd.readouterr().out
    assert "JSBSim Flight Dynamics Model" in out
    assert "valid; running headlessly" in out


def test_the_help_names_the_engine_version_that_is_pinned(capsys):
    with pytest.raises(SystemExit) as caught:
        capture_main(["--help"])
    assert caught.value.code == 0
    helptext = capsys.readouterr().out
    assert f"UE {UE_ENGINE_VERSION}" in helptext
    assert "UE 5.5" not in helptext
    assert "--verbose" in helptext


NAME = r"[a-z_]+(?:\.[a-z_]+)*"
NAMED_FORMS = (
    re.compile(r"REFUSED -- " + NAME + ":"),               # a literal name
    re.compile(r"REFUSED -- \{[a-z_]+(?:\.constraint|\['constraint'\])\}:"),
    re.compile(r"REFUSED -- by name:"),                    # _refuse(): one per line
)


def test_every_refusal_the_capture_command_prints_carries_its_name():
    """Static, over the source: every `REFUSED --` line names its rule,
    either as a literal or as the error's own `.constraint`; the one
    other form, `{exc}` for a ScheduleError, is allowed because that
    error's text begins with its name (asserted below, not assumed)."""
    from core.capture.schedule import ScheduleError

    assert str(ScheduleError("x")).startswith(f"{ScheduleError.constraint}: ")
    source = CAPTURE_SOURCE.read_text(encoding="utf-8").splitlines()
    unnamed = []
    for number, line in enumerate(source, 1):
        if "REFUSED -- " not in line:
            continue
        if any(form.search(line) for form in NAMED_FORMS):
            continue
        if "REFUSED -- {exc}" in line:
            above = "\n".join(source[max(0, number - 4):number])
            if "except ScheduleError" in above:
                continue
        unnamed.append(f"L{number}: {line.strip()}")
    assert not unnamed, "\n".join(unnamed)


def test_an_unreadable_spec_is_refused_by_name(tmp_path, capfd):
    bad = tmp_path / "not_a_spec.yaml"
    bad.write_text("spec_version: 1\n", encoding="utf-8")
    code = capture_main([str(bad), "--out", str(tmp_path / "run")])
    assert code == 2
    out = capfd.readouterr().out
    assert out.startswith("REFUSED -- spec.read: "), out


def test_the_package_docstring_names_every_command_and_format():
    from core.dataset.export import FORMATS

    doc = flightsim.__doc__
    for module in ("capture", "verify", "batch", "export", "campaign", "agent"):
        assert f"flightsim.{module}" in doc, module
        assert (REPO / "flightsim" / f"{module}.py").is_file()
    spelled = {"coco": "COCO", "kitti": "KITTI", "webdataset": "WebDataset",
               "yolo": "YOLO", "voc": "Pascal VOC"}
    assert set(spelled) == set(FORMATS), FORMATS
    for word in spelled.values():
        assert word in doc, word
