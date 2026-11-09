"""Unity builds merge every .cpp of a module into a few translation units
(NEXT.md gotcha 3), but only for files clean in git, so two files that
define the same name at file scope or in an anonymous namespace compile all
session and break after commit. This scans every FlightSimBridge .cpp for
names declared at file scope or in an anonymous namespace, for macros, and
for log categories, and fails on any name two files define.

Integration of the visual overhaul (2026-11-09): the five lanes' new files
(FlightSimBeautyLook, FlightSimClouds, FlightSimGroundDetail,
FlightSimAircraftFX) were checked together with the edited ones; the only
collision found was older (WeatherCmPerMetre in FlightSimWeather.cpp and
FlightSimWeatherLook.cpp), now renamed.
"""

import collections
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = [ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private",
           ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridgeEditor/Private"]

_DECLS = [
    re.compile(r"^\s*(?:static\s+)?(?:inline\s+)?(?:constexpr|const)\s+[\w:<>\s\*&]+?\s+(\w+)\s*(?:\[[^\]]*\])?\s*="),
    re.compile(r"^\s*(?:struct|class|enum(?:\s+class)?)\s+(\w+)\b(?!.*;\s*$)"),
    re.compile(r"^\s*(?:static\s+)?(?:inline\s+)?[\w:<>\*&]+(?:\s+[\w:<>\*&]+)*\s+\*?&?(\w+)\s*\([^;]*$"),
    re.compile(r"^\s*using\s+(\w+)\s*="),
]
_SKIP = {"if", "for", "while", "switch", "return", "else", "namespace", "operator", "TEXT"}


def _names(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', text)
    found = set()
    stack, prev = [], ""
    for line in text.split("\n"):
        stripped = line.strip()
        macro = re.match(r"#\s*define\s+(\w+)", stripped)
        if macro:
            found.add(("macro", macro.group(1)))
        for log in re.finditer(r"DEFINE_LOG_CATEGORY(?:_STATIC)?\s*\(\s*(\w+)", stripped):
            found.add(("log category", log.group(1)))
        if all(kind == "anon" for kind in stack) and not stripped.startswith("#"):
            for pattern in _DECLS:
                match = pattern.match(line)
                if match:
                    name = match.group(1)
                    if name not in _SKIP and "::" not in line.split("(")[0]:
                        found.add(("name", name))
                    break
        for i, ch in enumerate(line):
            if ch == "{":
                before = line[:i] if line[:i].strip() else prev
                if re.search(r"\bnamespace\s*$", before):
                    stack.append("anon")
                elif re.search(r"\bnamespace\s+[\w:]+\s*$", before):
                    stack.append("named")
                else:
                    stack.append("block")
            elif ch == "}" and stack:
                stack.pop()
        if stripped:
            prev = stripped
    return found


def test_no_two_files_of_a_module_define_the_same_file_scope_name():
    for module in MODULES:
        owners = collections.defaultdict(list)
        for path in sorted(module.rglob("*.cpp")):
            for key in _names(path):
                owners[key].append(path.name)
        clashes = {f"{kind} {name}": files for (kind, name), files in owners.items() if len(files) > 1}
        assert not clashes, f"{module.name}: {clashes}"


def test_the_scan_sees_the_new_lanes_names():
    """A scan that finds nothing proves nothing: it must see each new file's
    own file-scope names."""
    private = MODULES[0]
    expected = {"FlightSimBeautyLook.cpp": "BeautyLookState", "FlightSimClouds.cpp": "WorldCmPerMetre",
                "FlightSimGroundDetail.cpp": "ScatterCmPerMetre", "FlightSimAircraftFX.cpp": "AircraftFxCmPerMetre",
                "FlightSimRenderCommandlet.cpp": "RenderPinShowFlags"}
    for file, name in expected.items():
        assert ("name", name) in _names(private / file), (file, name)
    assert ("log category", "LogFlightSimWorldBeauty") in _names(private / "FlightSimClouds.cpp")
