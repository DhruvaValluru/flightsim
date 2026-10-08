"""Build a derived aircraft from a stock one, without editing the stock file.

The autopilot has to live inside the aircraft model (§5 Phase 2) so it runs at
FDM rate and travels with the airframe. But editing a stock JSBSim XML in place
would destroy the thing that makes a run traceable: the SHA-256 of the model we
claim to have flown.

So the stock file is never touched. A *derived* aircraft is generated into
``build/aircraft/<name><suffix>/``, containing

    <name><suffix>.xml   the stock XML, rewritten by the selected injections
    Systems/<x>.xml      one system file per injection that carries one

and the manifest records the hash of the stock file, the hash of every
template, and the hash of the generated result. Anyone can regenerate it and
compare.

The injection pipeline (ADVANCEMENTS_BLUEPRINT section 1, work item P2)
--------------------------------------------------------------------------
Physics that must live INSIDE the aero/FCS model enters the same way TECS
does: by rewriting the aircraft XML, never the vendored data. Each
:class:`Injection` is applied in the fixed order

    tecs? -> failures -> icing -> icing_alpha -> gust_rotation -> rain

and is independently selectable; the derivation's suffix encodes the set
(``c172p-fail-ice-gust`` vs ``c172p-tecs-fail-ice-gust``), so two
different sets can never share a name or a hash. Every injection first runs
its ``anchor_test`` over the CURRENT text (so a later injection sees the
earlier rewrites) and refuses by name before anything is written:

* ``derivation.anchor_missing`` -- the element the rewrite hangs on is not
  in the airframe, or is there more than once where one is needed (the
  surface command read outside an ``<input>``, two alpha tables in the
  LIFT axis, two roll-rate terms in the ROLL axis: an ambiguous anchor is
  a missing one; the module never guesses which);
* ``derivation.injection_conflict`` -- an unknown or repeated injection
  name, an empty set, or a base airframe that already declares what an
  injection introduces (deriving a derived airframe again);
* ``derivation.hash_mismatch`` -- a built file whose bytes no longer hash
  to what the derivation recorded (:func:`verify_hashes`, called by
  ``FlightDynamics.with_injections`` before JSBSim loads the file).

What each injection rewrites (measured on the c172p in
tests/test_derive_injections.py; the corrections that shaped them are the
blueprint's 1 and the icing_alpha template's own note):

* ``failures`` -- the airframe's ``<flight_control>`` ``<input>
  fcs/<s>-cmd-norm </input>`` for each of elevator, aileron and rudder is
  RE-ANCHORED to ``failure/<s>/cmd-in``, which the injected chain (a
  ``<pure_gain>`` by ``failure/<s>/authority``, a JSBSim ``<actuator>``
  with its malfunction switches, ``<clipto>`` -1..1) writes from the
  host's untouched ``fcs/<s>-cmd-norm``. A chain writing the host's own
  property back would apply the gain cumulatively (authority 0.5 with a
  command written once decays to zero in ~10 steps: the blueprint's
  correction 1, re-measured here as the re-anchor guard's failing test).
* ``icing`` -- every ``<function>`` of the six axes is wrapped in a
  ``<product>`` with ``icing/<axis>-factor``.
* ``icing_alpha`` -- a pre-axis ``<function name="icing/alpha-effective-rad">``
  (alpha + shift, evaluated by FGAerodynamics with this step's alpha; a
  ``<system>`` would lag a step, measured) and the LIFT axis's one alpha
  table re-pointed at it.
* ``gust_rotation`` -- the ROLL axis's ``velocities/p-aero-rad_sec`` term
  becomes a ``<sum>`` with ``gust/p-equivalent-rad_sec``.
* ``rain`` -- every ``<function>`` of the LIFT and DRAG axes is wrapped in
  a ``<product>`` with ``rain/lift-factor`` / ``rain/drag-factor`` (beside
  icing's, the products nest), and a BODY-frame ``<external_reactions>``
  force ``rain-momentum`` is added at the AERORP (into the airframe's own
  block when it has one). Neutral: factors 1.0, magnitude 0.

At neutral values every injection is bit-identical to the stock airframe
(x * 1.0, x + 0.0 and a unit-gain pass-through are exact in IEEE 754; the
test measures it over 8 s of a trimmed elevator step, worst |diff| 0.0).

Idempotent: regenerating from the same inputs produces byte-identical
output (the existing rule), so the derived hash is a stable part of the
run manifest. ``derive(name)`` with no selection is the TECS derivation
exactly as before this module became a pipeline (same name, same files,
same hashes).

The controller is a template for exactly one reason: engine count is a
property of the airframe. The B747 has four engines and the global5000
two, and a hand-written output list would silently drive only some of
them -- a §2.7 failure that would look like an underpowered aircraft
rather than a bug. The failures file is a template for the mirror reason:
three surfaces, one chain each, stamped from one fragment so they cannot
drift apart.

NOT claimed: no engine has loaded a derived airframe (the aircraft root is
hard-coded in the vendored plugin; the blueprint's correction 2 names a
fifth local patch as the next step, not touched here); the rewrites are
textual and hang on the stock files' spelling of the anchors (a stock
model whose FCS lives in a shared ``<system file=...>`` outside the
airframe XML -- the DHC6 -- refuses the failures injection by name rather
than being patched through the vendored systems tree); no injection
validates any physics -- each moves a stated property into a stated
place, and the records say by how much on the c172p.
"""

from __future__ import annotations

import hashlib
import re
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ..fdm import aircraft as ac
from ..fdm.errors import FDMError
from ..records import AppliedVariable, JsbsimWrite, Model, NullTest, Readback

#: The controller template, versioned with the repository.
TECS_TEMPLATE = Path(__file__).parent / "systems" / "tecs.xml"
SYSTEMS_DIR = Path(__file__).parent / "systems"
FAILURES_TEMPLATE = SYSTEMS_DIR / "failures.xml.tmpl"
ICING_TEMPLATE = SYSTEMS_DIR / "icing.xml"
ICING_ALPHA_TEMPLATE = SYSTEMS_DIR / "icing_alpha.xml"
GUST_ROTATION_TEMPLATE = SYSTEMS_DIR / "gust_rotation.xml"
RAIN_TEMPLATE = SYSTEMS_DIR / "rain.xml"

#: Where generated aircraft land. Gitignored: they are reproducible artefacts,
#: not source, and checking them in would invite editing the copy.
DEFAULT_BUILD_DIR = Path(__file__).resolve().parents[2] / "build" / "aircraft"

SUFFIX = "-tecs"

#: The fixed application order; a selection is applied in this order
#: whatever order it was given in.
INJECTION_ORDER = ("tecs", "failures", "icing", "icing_alpha", "gust_rotation", "rain")
#: The default selection: the TECS derivation as it always was.
DEFAULT_INJECTIONS = ("tecs",)

#: The three surfaces the failures chain covers, in stamping order.
SURFACES = ("elevator", "aileron", "rudder")
#: JSBSim's six aerodynamic axes and the icing factor each one takes.
AXIS_FACTORS = {"LIFT": "icing/lift-factor", "DRAG": "icing/drag-factor",
                "SIDE": "icing/side-factor", "ROLL": "icing/roll-factor",
                "PITCH": "icing/pitch-factor", "YAW": "icing/yaw-factor"}

ALPHA_PROPERTY = "aero/alpha-rad"
ALPHA_EFFECTIVE_PROPERTY = "icing/alpha-effective-rad"
ALPHA_SHIFT_PROPERTY = "icing/alpha-shift-rad"
ROLL_RATE_PROPERTY = "velocities/p-aero-rad_sec"
GUST_P_PROPERTY = "gust/p-equivalent-rad_sec"
#: The rain injection: the two wetted-wing factors and the drops' force.
RAIN_AXIS_FACTORS = {"LIFT": "rain/lift-factor", "DRAG": "rain/drag-factor"}
RAIN_FORCE_NAME = "rain-momentum"


class DerivationError(FDMError):
    """The derived aircraft could not be built, refused by name
    (``.constraint``: ``derivation.anchor_missing``,
    ``derivation.injection_conflict``, ``derivation.hash_mismatch``; a
    programming-level message carries an empty constraint)."""

    def __init__(self, constraint: str, message: Optional[str] = None) -> None:
        if message is None:
            constraint, message = "", constraint
        self.constraint = constraint
        self.message = message
        super().__init__(f"{constraint}: {message}" if constraint else message)


@dataclass(frozen=True)
class InjectionRecord:
    """One applied injection, as the provenance records it."""

    name: str
    suffix: str
    system_file: Optional[str]          # "Systems/failures.xml" or None
    template_sha256: str                # the repository template's bytes
    written_sha256: Optional[str]       # the expanded system file's bytes
    anchors: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "suffix": self.suffix, "system_file": self.system_file,
                "template_sha256": self.template_sha256,
                "written_sha256": self.written_sha256, "anchors": dict(self.anchors)}


@dataclass(frozen=True)
class DerivedAircraft:
    """A generated aircraft and everything needed to trust it."""

    name: str                  #: e.g. "B747-tecs"
    base_name: str             #: e.g. "B747"
    aircraft_path: Path        #: directory to hand JSBSim as the aircraft path
    xml_path: Path
    engine_path: Path
    systems_path: Path
    engine_count: int
    base_sha256: str
    template_sha256: Optional[str]      #: the TECS template's, when tecs is in the set
    derived_sha256: str
    injections: Tuple[InjectionRecord, ...] = ()
    suffix: str = SUFFIX

    @property
    def injection_names(self) -> Tuple[str, ...]:
        return tuple(i.name for i in self.injections)

    def provenance(self) -> Dict[str, object]:
        return {
            "derived_from": self.base_name,
            "base_sha256": self.base_sha256,
            "tecs_template_sha256": self.template_sha256,
            "derived_sha256": self.derived_sha256,
            "engine_count": self.engine_count,
            "suffix": self.suffix,
            "injections": [i.to_dict() for i in self.injections],
        }


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _count_engines(xml_text: str) -> int:
    """Engines declared in the stock model's <propulsion> section."""
    propulsion = re.search(r"<propulsion.*?</propulsion>", xml_text, re.S)
    if not propulsion:
        return 0
    return len(re.findall(r"<engine\b", propulsion.group(0)))


def _throttle_outputs(engine_count: int) -> str:
    """One <output> per engine, indexed the way JSBSim stores them.

    Index 0 is unsubscripted -- ``fcs/throttle-cmd-norm`` -- and only later
    engines carry a subscript. Writing ``[0]`` would work by aliasing but would
    not match the catalog, so the unsubscripted form is used.
    """
    lines = []
    for i in range(engine_count):
        prop = "fcs/throttle-cmd-norm" if i == 0 else f"fcs/throttle-cmd-norm[{i}]"
        lines.append(f"    <output> {prop} </output>")
    return "\n".join(lines)


def _insert_system(xml_text: str, system: str = "tecs") -> str:
    """Add ``<system file="<system>"/>`` ahead of the aircraft's own flight control.

    Order matters. TECS writes ``fcs/*-cmd-norm``; the failures chain reads
    those and writes ``failure/*/cmd-in``; the aircraft's ``<flight_control>``
    reads those and drives the surfaces. Loading the systems first, in
    pipeline order, means a command reaches the actuator on the same step
    rather than one step late. Each insertion lands on the line before the
    anchor, after any system inserted earlier.
    """
    marker = f'\n    <system file="{system}"/>\n'
    for anchor in ("<flight_control", "<autopilot", "<ground_reactions"):
        idx = xml_text.find(anchor)
        if idx != -1:
            line_start = xml_text.rfind("\n", 0, idx) + 1
            return xml_text[:line_start] + marker + xml_text[line_start:]
    raise DerivationError(
        "derivation.anchor_missing",
        "could not find <flight_control>, <autopilot> or <ground_reactions> in "
        "the stock aircraft; refusing to guess where the controller belongs"
    )


def _write_atomic(path: Path, data: bytes) -> bool:
    """Write ``data`` to ``path`` so that no reader ever sees a partial
    file, and not at all when the file already holds exactly ``data``.

    Every capture derives the same airframe into the same build
    directory. Two captures running at once (a batch with workers > 1)
    used to rewrite tecs.xml in place, and JSBSim in the other process
    read it half-written: "XML parse error: no element found" on a file
    that was correct a millisecond later. Writing to a temporary name
    in the same directory and renaming over the target is atomic on
    POSIX and on NTFS (os.replace), so a reader gets the old complete
    file or the new complete file; and skipping an identical rewrite
    means the steady state never touches the file at all. Returns
    whether the file was written."""
    path = Path(path)
    try:
        if path.is_file() and path.read_bytes() == data:
            return False
    except OSError:
        pass
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return True


# -- the XML anchors -------------------------------------------------------------

def _section(xml_text: str, tag: str) -> Optional[Tuple[int, int]]:
    """Span of ``<tag ...> ... </tag>`` (the first one), or None."""
    m = re.search(rf"<{tag}\b[^>]*>.*?</{tag}>", xml_text, re.S)
    return None if m is None else m.span()


def _axis_span(aero_text: str, axis: str) -> Optional[Tuple[int, int]]:
    m = re.search(rf'<axis\s+name="{re.escape(axis)}"[^>]*>.*?</axis>', aero_text, re.S)
    return None if m is None else m.span()


def _input_pattern(prop: str) -> "re.Pattern":
    return re.compile(r"<input>\s*" + re.escape(prop) + r"\s*</input>")


def _alpha_var_pattern(prop: str) -> "re.Pattern":
    return re.compile(r"(<independentVar\b[^>]*>\s*)" + re.escape(prop) + r"(\s*</independentVar>)")


def _property_pattern(prop: str) -> "re.Pattern":
    return re.compile(r"([ \t]*)<property>\s*" + re.escape(prop) + r"\s*</property>")


# -- the injections --------------------------------------------------------------

@dataclass(frozen=True)
class _Context:
    """What a rewrite may read: the base name and its engine count."""

    base_name: str
    engine_count: int


@dataclass(frozen=True)
class Injection:
    """One rewrite of the airframe XML, with the system file it carries.

    ``anchor_test(xml_text) -> dict`` refuses ``derivation.anchor_missing``
    and returns the anchor counts the provenance records; ``rewrite(xml_text,
    context) -> str`` returns the rewritten airframe; ``expand(template_text,
    context) -> str`` returns the system file to write (None when the
    injection writes none); ``introduces`` are the property names the base
    must not already declare (``derivation.injection_conflict``).
    """

    name: str
    template: Optional[Path]
    rewrite: Callable[[str, _Context], str]
    anchor_test: Callable[[str], Dict[str, Any]]
    suffix: str
    system_file: Optional[str] = None
    expand: Optional[Callable[[str, _Context], str]] = None
    introduces: Tuple[str, ...] = ()


def _tecs_anchor(xml_text: str) -> Dict[str, Any]:
    for anchor in ("<flight_control", "<autopilot", "<ground_reactions"):
        if anchor in xml_text:
            return {"system_anchor": anchor}
    raise DerivationError(
        "derivation.anchor_missing",
        "could not find <flight_control>, <autopilot> or <ground_reactions> in "
        "the stock aircraft; refusing to guess where the controller belongs")


def _tecs_expand(template_text: str, ctx: _Context) -> str:
    if ctx.engine_count == 0:
        raise DerivationError(
            f"{ctx.base_name!r} declares no engines; TECS commands thrust and "
            f"cannot be attached to an unpowered model")
    if "<!--THROTTLE_OUTPUTS-->" not in template_text:
        raise DerivationError(
            f"{TECS_TEMPLATE} has no THROTTLE_OUTPUTS placeholder; the throttle "
            f"would drive no engines at all")
    return template_text.replace("<!--THROTTLE_OUTPUTS-->", _throttle_outputs(ctx.engine_count))


def _failures_anchor(xml_text: str) -> Dict[str, Any]:
    """Every surface's command is read by the airframe's <flight_control>
    through <input> elements and nowhere else in it."""
    span = _section(xml_text, "flight_control")
    if span is None:
        raise DerivationError("derivation.anchor_missing",
                              "the airframe has no <flight_control> block to re-anchor")
    fcs = xml_text[span[0]:span[1]]
    counts: Dict[str, Any] = {}
    for surface in SURFACES:
        prop = f"fcs/{surface}-cmd-norm"
        inputs = len(_input_pattern(prop).findall(fcs))
        mentions = len(re.findall(re.escape(prop), fcs))
        if inputs == 0:
            raise DerivationError(
                "derivation.anchor_missing",
                f"the airframe's <flight_control> reads no <input> {prop} </input>, so the "
                f"{surface} command has nothing to re-anchor to failure/{surface}/cmd-in "
                f"(an FCS held in a shared <system file=...> outside the airframe XML is "
                f"not rewritten)")
        if mentions != inputs:
            raise DerivationError(
                "derivation.anchor_missing",
                f"{prop} is read {mentions - inputs} time(s) in <flight_control> outside an "
                f"<input> element; a re-anchor of the <input>s alone would leave the "
                f"{surface} command partly un-failed, so the anchor is ambiguous")
        counts[f"{surface}_inputs"] = inputs
    return counts


def _failures_rewrite(xml_text: str, ctx: _Context) -> str:
    span = _section(xml_text, "flight_control")
    assert span is not None  # the anchor test ran first
    fcs = xml_text[span[0]:span[1]]
    for surface in SURFACES:
        fcs = _input_pattern(f"fcs/{surface}-cmd-norm").sub(
            f"<input>failure/{surface}/cmd-in</input>", fcs)
    rewritten = xml_text[:span[0]] + fcs + xml_text[span[1]:]
    return _insert_system(rewritten, "failures")


def _fragment(template_text: str, tag: str) -> str:
    m = re.search(rf"<!--{tag}\n(.*?)\n{tag}-->", template_text, re.S)
    if m is None:
        raise DerivationError(f"{FAILURES_TEMPLATE} has no {tag} fragment; the chain would "
                              f"cover no surface at all")
    return m.group(1)


def _failures_expand(template_text: str, ctx: _Context) -> str:
    props = _fragment(template_text, "SURFACE_PROPERTIES")
    chan = _fragment(template_text, "SURFACE_CHANNEL")
    body = re.sub(r"\n<!--SURFACE_PROPERTIES\n.*?\nSURFACE_PROPERTIES-->", "", template_text, flags=re.S)
    body = re.sub(r"\n<!--SURFACE_CHANNEL\n.*?\nSURFACE_CHANNEL-->", "", body, flags=re.S)
    for placeholder in ("<!--PROPERTIES-->", "<!--CHANNELS-->"):
        if placeholder not in body:
            raise DerivationError(f"{FAILURES_TEMPLATE} has no {placeholder} placeholder")
    body = body.replace("<!--PROPERTIES-->",
                        "\n".join(props.replace("@SURFACE@", s) for s in SURFACES))
    body = body.replace("<!--CHANNELS-->",
                        "\n\n".join(chan.replace("@SURFACE@", s) for s in SURFACES))
    return body


def _icing_anchor(xml_text: str) -> Dict[str, Any]:
    span = _section(xml_text, "aerodynamics")
    if span is None:
        raise DerivationError("derivation.anchor_missing",
                              "the airframe has no <aerodynamics> block to wrap")
    aero = xml_text[span[0]:span[1]]
    names = re.findall(r'<axis\s+name="([^"]+)"', aero)
    unknown = [n for n in names if n not in AXIS_FACTORS]
    if unknown:
        raise DerivationError(
            "derivation.anchor_missing",
            f"the airframe's aerodynamics use axis name(s) {unknown}, not the six "
            f"wind-axis names the icing factors are defined for ({sorted(AXIS_FACTORS)})")
    counts: Dict[str, Any] = {}
    for axis in AXIS_FACTORS:
        aspan = _axis_span(aero, axis)
        if aspan is None:
            raise DerivationError("derivation.anchor_missing",
                                  f"the airframe's aerodynamics declare no <axis name=\"{axis}\">")
        body = aero[aspan[0]:aspan[1]]
        functions = re.findall(r"<function\b[^>]*>.*?</function>", body, re.S)
        for fn in functions:
            if fn.count("<function") != 1:
                raise DerivationError(
                    "derivation.anchor_missing",
                    f"a function in the {axis} axis nests another <function>; the wrap "
                    f"would not know which expression is the axis's")
        counts[f"{axis.lower()}_functions"] = len(functions)
    return counts


def _wrap_function(fn_text: str, factor: str) -> str:
    """``<function ...> [<description>..</description>] EXPR </function>`` ->
    the same with EXPR inside ``<product><property>factor</property> EXPR </product>``."""
    open_tag = re.match(r"<function\b[^>]*>", fn_text)
    assert open_tag is not None
    head_end = open_tag.end()
    desc = re.match(r"\s*<description>.*?</description>", fn_text[head_end:], re.S)
    if desc is not None:
        head_end += desc.end()
    body_end = fn_text.rfind("</function>")
    body = fn_text[head_end:body_end]
    # The indentation of the expression's first line, kept for the wrapper.
    indent = re.match(r"\s*\n([ \t]*)", body)
    pad = indent.group(1) if indent else "    "
    wrapped = (f"\n{pad}<product>\n{pad}    <property>{factor}</property>"
               f"{body.rstrip()}\n{pad}</product>\n{pad[:-4] if len(pad) >= 4 else ''}")
    return fn_text[:head_end] + wrapped + fn_text[body_end:]


def _icing_rewrite(xml_text: str, ctx: _Context) -> str:
    span = _section(xml_text, "aerodynamics")
    assert span is not None
    aero = xml_text[span[0]:span[1]]
    for axis, factor in AXIS_FACTORS.items():
        aspan = _axis_span(aero, axis)
        assert aspan is not None
        body = aero[aspan[0]:aspan[1]]
        body = re.sub(r"<function\b[^>]*>.*?</function>",
                      lambda m: _wrap_function(m.group(0), factor), body, flags=re.S)
        aero = aero[:aspan[0]] + body + aero[aspan[1]:]
    rewritten = xml_text[:span[0]] + aero + xml_text[span[1]:]
    return _insert_system(rewritten, "icing")


def _icing_alpha_anchor(xml_text: str) -> Dict[str, Any]:
    span = _section(xml_text, "aerodynamics")
    if span is None:
        raise DerivationError("derivation.anchor_missing",
                              "the airframe has no <aerodynamics> block for the alpha shift")
    aero = xml_text[span[0]:span[1]]
    lspan = _axis_span(aero, "LIFT")
    if lspan is None:
        raise DerivationError("derivation.anchor_missing",
                              "the airframe's aerodynamics declare no <axis name=\"LIFT\">")
    lift = aero[lspan[0]:lspan[1]]
    tables = re.findall(r"<table\b[^>]*>.*?</table>", lift, re.S)
    with_alpha = [t for t in tables if _alpha_var_pattern(ALPHA_PROPERTY).search(t)]
    if len(with_alpha) != 1:
        raise DerivationError(
            "derivation.anchor_missing",
            f"the LIFT axis has {len(with_alpha)} table(s) with {ALPHA_PROPERTY} as an "
            f"independent variable; the stall-onset shift needs exactly one (an alpha in "
            f"degrees, or several alpha tables, is not re-pointed by guess)")
    return {"lift_alpha_tables": 1,
            "lift_alpha_vars": len(_alpha_var_pattern(ALPHA_PROPERTY).findall(with_alpha[0]))}


def _icing_alpha_rewrite(xml_text: str, ctx: _Context) -> str:
    span = _section(xml_text, "aerodynamics")
    assert span is not None
    aero = xml_text[span[0]:span[1]]
    lspan = _axis_span(aero, "LIFT")
    assert lspan is not None
    lift = aero[lspan[0]:lspan[1]]
    lift = re.sub(r"<table\b[^>]*>.*?</table>",
                  lambda m: _alpha_var_pattern(ALPHA_PROPERTY).sub(
                      rf"\g<1>{ALPHA_EFFECTIVE_PROPERTY}\g<2>", m.group(0)),
                  lift, count=0, flags=re.S)
    aero = aero[:lspan[0]] + lift + aero[lspan[1]:]
    open_tag = re.match(r"<aerodynamics\b[^>]*>", aero)
    assert open_tag is not None
    function = (
        f'\n        <function name="{ALPHA_EFFECTIVE_PROPERTY}">'
        f"\n            <description>Effective_angle_of_attack_for_the_LIFT_table:"
        f"_alpha_plus_the_icing_stall-onset_shift_(injected_by_core/control/derive.py)"
        f"</description>"
        f"\n            <sum>"
        f"\n                <property>{ALPHA_PROPERTY}</property>"
        f"\n                <property>{ALPHA_SHIFT_PROPERTY}</property>"
        f"\n            </sum>"
        f"\n        </function>\n")
    aero = aero[:open_tag.end()] + function + aero[open_tag.end():]
    rewritten = xml_text[:span[0]] + aero + xml_text[span[1]:]
    return _insert_system(rewritten, "icing_alpha")


def _gust_anchor(xml_text: str) -> Dict[str, Any]:
    span = _section(xml_text, "aerodynamics")
    if span is None:
        raise DerivationError("derivation.anchor_missing",
                              "the airframe has no <aerodynamics> block for the gust sum")
    aero = xml_text[span[0]:span[1]]
    rspan = _axis_span(aero, "ROLL")
    if rspan is None:
        raise DerivationError("derivation.anchor_missing",
                              "the airframe's aerodynamics declare no <axis name=\"ROLL\">")
    roll = aero[rspan[0]:rspan[1]]
    terms = len(_property_pattern(ROLL_RATE_PROPERTY).findall(roll))
    mentions = len(re.findall(re.escape(ROLL_RATE_PROPERTY), roll))
    if terms != 1 or mentions != 1:
        raise DerivationError(
            "derivation.anchor_missing",
            f"the ROLL axis reads {ROLL_RATE_PROPERTY} {mentions} time(s) ({terms} as a "
            f"<property> term); the gust sum needs exactly one roll-damping term")
    return {"roll_rate_terms": 1}


def _gust_rewrite(xml_text: str, ctx: _Context) -> str:
    span = _section(xml_text, "aerodynamics")
    assert span is not None
    aero = xml_text[span[0]:span[1]]
    rspan = _axis_span(aero, "ROLL")
    assert rspan is not None
    roll = aero[rspan[0]:rspan[1]]

    def as_sum(m: "re.Match") -> str:
        pad = m.group(1)
        return (f"{pad}<sum>\n{pad}    <property>{ROLL_RATE_PROPERTY}</property>"
                f"\n{pad}    <property>{GUST_P_PROPERTY}</property>\n{pad}</sum>")

    roll = _property_pattern(ROLL_RATE_PROPERTY).sub(as_sum, roll, count=1)
    aero = aero[:rspan[0]] + roll + aero[rspan[1]:]
    rewritten = xml_text[:span[0]] + aero + xml_text[span[1]:]
    return _insert_system(rewritten, "gust_rotation")


def _aerorp(xml_text: str) -> Tuple[str, Tuple[str, str, str]]:
    """The aerodynamic reference point's unit and (x, y, z) as written."""
    m = re.search(r'<location\s+name="AERORP"\s+unit="([^"]+)"\s*>(.*?)</location>',
                  xml_text, re.S)
    if m is None:
        raise DerivationError("derivation.anchor_missing",
                              "the airframe's metrics declare no <location name=\"AERORP\" "
                              "unit=...>; the drops' force has no point to act at")
    coords = []
    for axis in "xyz":
        c = re.search(rf"<{axis}>\s*([^<]+?)\s*</{axis}>", m.group(2))
        if c is None:
            raise DerivationError("derivation.anchor_missing",
                                  f"the AERORP location has no <{axis}>")
        coords.append(c.group(1))
    return m.group(1), (coords[0], coords[1], coords[2])


def _rain_anchor(xml_text: str) -> Dict[str, Any]:
    span = _section(xml_text, "aerodynamics")
    if span is None:
        raise DerivationError("derivation.anchor_missing",
                              "the airframe has no <aerodynamics> block for the rain factors")
    aero = xml_text[span[0]:span[1]]
    counts: Dict[str, Any] = {}
    for axis in RAIN_AXIS_FACTORS:
        aspan = _axis_span(aero, axis)
        if aspan is None:
            raise DerivationError("derivation.anchor_missing",
                                  f"the airframe's aerodynamics declare no <axis name=\"{axis}\">")
        body = aero[aspan[0]:aspan[1]]
        functions = re.findall(r"<function\b[^>]*>.*?</function>", body, re.S)
        for fn in functions:
            if fn.count("<function") != 1:
                raise DerivationError(
                    "derivation.anchor_missing",
                    f"a function in the {axis} axis nests another <function>; the wrap "
                    f"would not know which expression is the axis's")
        counts[f"{axis.lower()}_functions"] = len(functions)
    if re.search(r"<external_reactions\s*/>", xml_text):
        raise DerivationError("derivation.anchor_missing",
                              "the airframe declares an empty <external_reactions/>; the rain "
                              "force would have to replace it")
    unit, _ = _aerorp(xml_text)
    counts["aerorp_unit"] = unit
    counts["external_reactions"] = "existing" if "<external_reactions" in xml_text else "added"
    return counts


def _rain_rewrite(xml_text: str, ctx: _Context) -> str:
    span = _section(xml_text, "aerodynamics")
    assert span is not None
    aero = xml_text[span[0]:span[1]]
    for axis, factor in RAIN_AXIS_FACTORS.items():
        aspan = _axis_span(aero, axis)
        assert aspan is not None
        body = aero[aspan[0]:aspan[1]]
        body = re.sub(r"<function\b[^>]*>.*?</function>",
                      lambda m: _wrap_function(m.group(0), factor), body, flags=re.S)
        aero = aero[:aspan[0]] + body + aero[aspan[1]:]
    rewritten = xml_text[:span[0]] + aero + xml_text[span[1]:]
    unit, (x, y, z) = _aerorp(rewritten)
    force = (f'        <force name="{RAIN_FORCE_NAME}" frame="BODY">\n'
             f'            <!-- the swept-up rain\'s momentum (core/environment/rain.py): '
             f'direction and magnitude written every step -->\n'
             f'            <location unit="{unit}">\n'
             f'                <x> {x} </x>\n                <y> {y} </y>\n'
             f'                <z> {z} </z>\n            </location>\n'
             f'            <direction>\n                <x> -1 </x>\n                <y> 0 </y>\n'
             f'                <z> 0 </z>\n            </direction>\n        </force>\n')
    close = rewritten.find("</external_reactions>")
    if close != -1:
        line_start = rewritten.rfind("\n", 0, close) + 1
        rewritten = rewritten[:line_start] + force + rewritten[line_start:]
    else:
        idx = rewritten.find("<aerodynamics")
        line_start = rewritten.rfind("\n", 0, idx) + 1
        rewritten = (rewritten[:line_start] + "    <external_reactions>\n" + force
                     + "    </external_reactions>\n\n" + rewritten[line_start:])
    return _insert_system(rewritten, "rain")


def _static(template_text: str, ctx: _Context) -> str:
    return template_text


INJECTIONS: Dict[str, Injection] = {
    "tecs": Injection(
        name="tecs", template=TECS_TEMPLATE, rewrite=lambda t, c: _insert_system(t, "tecs"),
        anchor_test=_tecs_anchor, suffix="tecs", system_file="Systems/tecs.xml",
        expand=_tecs_expand, introduces=("ap/enable", '<system file="tecs"')),
    "failures": Injection(
        name="failures", template=FAILURES_TEMPLATE, rewrite=_failures_rewrite,
        anchor_test=_failures_anchor, suffix="fail", system_file="Systems/failures.xml",
        expand=_failures_expand,
        introduces=tuple(f"failure/{s}/" for s in SURFACES) + ('<system file="failures"',)),
    "icing": Injection(
        name="icing", template=ICING_TEMPLATE, rewrite=_icing_rewrite,
        anchor_test=_icing_anchor, suffix="ice", system_file="Systems/icing.xml",
        expand=_static, introduces=tuple(AXIS_FACTORS.values()) + ("icing/eta", '<system file="icing"')),
    "icing_alpha": Injection(
        name="icing_alpha", template=ICING_ALPHA_TEMPLATE, rewrite=_icing_alpha_rewrite,
        anchor_test=_icing_alpha_anchor, suffix="alpha", system_file="Systems/icing_alpha.xml",
        expand=_static, introduces=(ALPHA_SHIFT_PROPERTY, ALPHA_EFFECTIVE_PROPERTY,
                                    '<system file="icing_alpha"')),
    "gust_rotation": Injection(
        name="gust_rotation", template=GUST_ROTATION_TEMPLATE, rewrite=_gust_rewrite,
        anchor_test=_gust_anchor, suffix="gust", system_file="Systems/gust_rotation.xml",
        expand=_static, introduces=(GUST_P_PROPERTY, '<system file="gust_rotation"')),
    "rain": Injection(
        name="rain", template=RAIN_TEMPLATE, rewrite=_rain_rewrite,
        anchor_test=_rain_anchor, suffix="rain", system_file="Systems/rain.xml",
        expand=_static, introduces=tuple(RAIN_AXIS_FACTORS.values())
        + ("rain/lwc-gm3", f'name="{RAIN_FORCE_NAME}"', '<system file="rain"')),
}


def select_injections(names: Sequence[str]) -> Tuple[Injection, ...]:
    """The selection in pipeline order; refuses ``derivation.injection_conflict``
    for an unknown name, a repeated name or an empty set."""
    names = tuple(names)
    if not names:
        raise DerivationError("derivation.injection_conflict",
                              "no injection selected; a derivation that changes nothing "
                              "would be the stock airframe under a second name")
    unknown = [n for n in names if n not in INJECTIONS]
    if unknown:
        raise DerivationError("derivation.injection_conflict",
                              f"unknown injection(s) {unknown}; the pipeline knows "
                              f"{list(INJECTION_ORDER)}")
    if len(set(names)) != len(names):
        raise DerivationError("derivation.injection_conflict",
                              f"an injection is selected twice: {list(names)}")
    return tuple(INJECTIONS[n] for n in INJECTION_ORDER if n in names)


def suffix_for(names: Sequence[str]) -> str:
    """The name suffix that encodes the set, e.g. ``-tecs-fail-ice-gust``."""
    return "".join(f"-{i.suffix}" for i in select_injections(names))


def derive(
    base_aircraft: str,
    build_dir: Optional[Path] = None,
    root_dir: Optional[Path] = None,
    injections: Sequence[str] = DEFAULT_INJECTIONS,
) -> DerivedAircraft:
    """Generate a derived copy of ``base_aircraft`` with the selected injections.

    Idempotent: regenerating from the same inputs produces byte-identical
    output, so the derived hash is a stable part of the run manifest. The
    default selection is the TECS derivation exactly as before.
    """
    selected = select_injections(injections)
    base = ac.resolve(base_aircraft, root_dir)
    build_dir = Path(build_dir) if build_dir else DEFAULT_BUILD_DIR

    base_text = base.xml_path.read_text(encoding="utf-8")
    engine_count = _count_engines(base_text)
    ctx = _Context(base_name=base_aircraft, engine_count=engine_count)

    # A base that already carries an injection's properties is a derived
    # airframe (or a stock one that happens to spell them): injecting twice
    # would double the chain or the wrap, and is refused, never merged.
    for inj in selected:
        clash = [p for p in inj.introduces if p in base_text]
        if clash:
            raise DerivationError(
                "derivation.injection_conflict",
                f"{base.name!r} already declares {clash}; the {inj.name} injection would be "
                f"applied on top of itself")

    derived_text = base_text
    system_texts: Dict[str, str] = {}
    records: List[InjectionRecord] = []
    for inj in selected:
        template_text = inj.template.read_text(encoding="utf-8") if inj.template else ""
        anchors = inj.anchor_test(derived_text)
        derived_text = inj.rewrite(derived_text, ctx)
        written = None
        if inj.system_file is not None:
            assert inj.expand is not None
            system_texts[inj.system_file] = inj.expand(template_text, ctx)
            written = _sha256_text(system_texts[inj.system_file])
        records.append(InjectionRecord(
            name=inj.name, suffix=inj.suffix, system_file=inj.system_file,
            template_sha256=_sha256_text(template_text), written_sha256=written,
            anchors=anchors))

    suffix = "".join(f"-{i.suffix}" for i in selected)
    name = f"{base.name}{suffix}"
    aircraft_dir = build_dir / name
    systems_dir = aircraft_dir / "Systems"
    systems_dir.mkdir(parents=True, exist_ok=True)

    xml_path = aircraft_dir / f"{name}.xml"
    _write_atomic(xml_path, derived_text.encode("utf-8"))
    for rel, text in system_texts.items():
        _write_atomic(aircraft_dir / rel, text.encode("utf-8"))

    # Aircraft-local files the stock model may reference by relative name,
    # and the aircraft-local SUBDIRECTORIES some stock models keep their
    # engine, thruster and system files in (the DHC6: Engines/PT6A-27.xml,
    # Engines/Propeller.xml, Systems/*.xml -- without them the derived DHC6
    # refuses to load, "Could not open file: Propeller", measured by P5).
    # An injected system file written above is never overwritten by a stock
    # file of the same relative name.
    for sibling in base.xml_path.parent.iterdir():
        if sibling.is_file() and sibling != base.xml_path:
            _write_atomic(aircraft_dir / sibling.name, sibling.read_bytes())
        elif sibling.is_dir():
            for inner in sorted(p for p in sibling.rglob("*") if p.is_file()):
                rel = inner.relative_to(base.xml_path.parent).as_posix()
                if rel in system_texts:
                    continue
                (aircraft_dir / rel).parent.mkdir(parents=True, exist_ok=True)
                _write_atomic(aircraft_dir / rel, inner.read_bytes())

    tecs = next((r for r in records if r.name == "tecs"), None)
    return DerivedAircraft(
        name=name,
        base_name=base.name,
        aircraft_path=build_dir,
        xml_path=xml_path,
        engine_path=base.root_dir / "engine",
        systems_path=base.root_dir / "systems",
        engine_count=engine_count,
        base_sha256=base.sha256,
        template_sha256=None if tecs is None else tecs.template_sha256,
        derived_sha256=_sha256_text(derived_text),
        injections=tuple(records),
        suffix=suffix,
    )


def verify_hashes(derived: DerivedAircraft,
                  expected_derived_sha256: Optional[str] = None) -> Dict[str, str]:
    """Re-hash the built files and refuse ``derivation.hash_mismatch`` when
    any differs from what the derivation recorded -- the build copy was
    edited (or half-written) since it was generated -- or when the
    derivation's own hash is not the one the caller expected (a manifest's
    ``derived_sha256``: the airframe checked at the door, the discipline the
    engine's patch 5 mirrors). Returns the hashes read, keyed by file.
    Nothing is loaded before this passes."""
    if (expected_derived_sha256 is not None
            and derived.derived_sha256 != expected_derived_sha256):
        raise DerivationError(
            "derivation.hash_mismatch",
            f"{derived.name!r} derives to {derived.derived_sha256[:12]}..., not the expected "
            f"{expected_derived_sha256[:12]}...; a template or the stock airframe changed "
            f"since that hash was recorded, so this is not the airframe that was flown")
    read: Dict[str, str] = {}
    expected = {derived.xml_path.name: derived.derived_sha256}
    for rec in derived.injections:
        if rec.system_file is not None and rec.written_sha256 is not None:
            expected[rec.system_file] = rec.written_sha256
    root = derived.xml_path.parent
    for rel, want in expected.items():
        path = root / rel
        try:
            actual = _sha256_bytes(path.read_bytes())
        except OSError as exc:
            raise DerivationError("derivation.hash_mismatch",
                                  f"{path} cannot be read ({exc}); the derived airframe "
                                  f"is not the one recorded") from None
        read[rel] = actual
        if actual != want:
            raise DerivationError(
                "derivation.hash_mismatch",
                f"{path} hashes to {actual[:12]}..., the derivation recorded {want[:12]}...; "
                f"the build copy was changed since it was generated -- regenerate it, "
                f"never edit it")
    return read


# -- the record every injected property returns ------------------------------------

#: The variables the injections introduce: name -> (injection, JSBSim
#: property, unit, neutral value). Returned as registry text for
#: core/registry.py (owned by another item); the records built here
#: through :func:`injection_variable` carry the same names so a later
#: physics item lifts them unchanged.
INJECTION_VARIABLES: Dict[str, Tuple[str, str, str, float]] = {
    "failures.elevator_authority": ("failures", "failure/elevator/authority", "1", 1.0),
    "failures.aileron_authority": ("failures", "failure/aileron/authority", "1", 1.0),
    "failures.rudder_authority": ("failures", "failure/rudder/authority", "1", 1.0),
    "icing.lift_factor": ("icing", "icing/lift-factor", "1", 1.0),
    "icing.drag_factor": ("icing", "icing/drag-factor", "1", 1.0),
    "icing.side_factor": ("icing", "icing/side-factor", "1", 1.0),
    "icing.roll_factor": ("icing", "icing/roll-factor", "1", 1.0),
    "icing.pitch_factor": ("icing", "icing/pitch-factor", "1", 1.0),
    "icing.yaw_factor": ("icing", "icing/yaw-factor", "1", 1.0),
    "icing.eta": ("icing", "icing/eta", "1", 0.0),
    "icing.alpha_shift_rad": ("icing_alpha", "icing/alpha-shift-rad", "rad", 0.0),
    "gust.p_equivalent_rad_s": ("gust_rotation", "gust/p-equivalent-rad_sec", "rad/s", 0.0),
}

#: The property store reads back exactly what was written for every one of
#: these (measured in tests/test_derive_injections.py on the c172p, before
#: and after stepping): a declared <property> that only JSBSim's function
#: tree reads is never recomputed.
READBACK_BASIS = ("measured here on the c172p (JSBSim 1.2.4): a <property> declared by an "
                  "injected system reads back the value written to the last bit, before and "
                  "after stepping; nothing in the model rewrites it")

INJECTION_REFERENCES = (
    "ADVANCEMENTS_BLUEPRINT section 1, 'The chosen way' and corrections 1-3 (work item P2)",
    "JSBSim 1.2.4 FGActuator.cpp (fail_stuck / fail_zero / fail_hardover), FGFCS component "
    "order, FGAerodynamics pre-axis functions [source read in the research; measured here]",
    "Bragg, Hutchison, Merret, Oltman, Pokhariyal, AIAA 2000-0360 (the eta k coefficient "
    "form the icing factors carry) [unverified here]",
)


def injection_variable(
    name: str,
    value: float,
    derived: DerivedAircraft,
    readback_value: float,
    null_test: Optional[NullTest],
    telemetry_columns: Sequence[str] = (),
    source: str = "user",
    frm: Optional[str] = None,
    extra_not_claimed: Sequence[str] = (),
) -> AppliedVariable:
    """The record (core/records.py, record 2 under version 1) for one
    injected property as applied to one derivation: the value written, the
    readback graded exact, the injection's template and derived hashes as
    the model parameters, the null test the caller measured. A later
    physics item (P3, P5, P6, P7) lifts this into its own producer."""
    injection, prop, unit, neutral = INJECTION_VARIABLES[name]
    record = next((r for r in derived.injections if r.name == injection), None)
    if record is None:
        raise DerivationError("derivation.injection_conflict",
                              f"{name} needs the {injection} injection, which "
                              f"{derived.name!r} was not derived with ({derived.injection_names})")
    return AppliedVariable(
        name=name, value=float(value), unit=unit, source=source,
        model_name=f"JSBSim XML injection '{injection}' (core/control/derive.py)",
        parameters={"injection": injection, "property": prop, "neutral_value": neutral,
                    "derived_aircraft": derived.name, "base_sha256": derived.base_sha256,
                    "template_sha256": record.template_sha256,
                    "written_sha256": record.written_sha256,
                    "derived_sha256": derived.derived_sha256, "anchors": dict(record.anchors)},
        references=INJECTION_REFERENCES,
        properties_written=(prop,),
        telemetry_columns=tuple(telemetry_columns),
        frame_keys=tuple(telemetry_columns),
        null_test=null_test,
        not_claimed=(
            "the injection moves a stated property into a stated place in the stock model; "
            "no physics is validated by it",
            "no engine has loaded a derived airframe (vendored plugin aircraft root; "
            "blueprint correction 2)",
            "a neutral value is bit-identical to the stock airframe by IEEE 754 exactness "
            "of x * 1.0, x + 0.0 and a unit gain, measured on the c172p only",
        ) + tuple(extra_not_claimed),
        frm=frm,
        readback=Readback(property=prop, value=float(readback_value), written=float(value),
                          tolerance=0.0, tolerance_kind="absolute", basis=READBACK_BASIS),
        jsbsim_writes=(JsbsimWrite(prop, "after load; held by the property store every step"),),
        model=Model(
            name=f"XML injection '{injection}'",
            standard="none: a stated multiplier / shift / gain in the stock JSBSim model",
            version=record.template_sha256[:12],
            parameters={"property": prop, "neutral_value": neutral,
                        "derived_sha256": derived.derived_sha256},
            references=INJECTION_REFERENCES),
    )
