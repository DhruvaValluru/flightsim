"""AC3D (.ac) model reader, for FlightGear aircraft assets.

Why a parser and not an importer plugin
---------------------------------------
The properly-licensed aircraft models with separate control-surface geometry
(§ Phase 6B.1) are FlightGear's, and FlightGear models are AC3D files. Unreal
does not read .ac. Converting through a GUI tool would break the build-time,
command-line requirement, so this module reads the format directly -- it is a
small, line-oriented text format -- and the converter in
:mod:`assets_pipeline.convert` writes OBJ that Unreal's import commandlet does
read.

Coordinate frames, measured rather than assumed
-----------------------------------------------
Three frames are involved, and the mapping between the first two was measured
against this repo's actual assets rather than taken from documentation:

* **.ac file frame**: the raw vertex coordinates.
* **FlightGear model frame**: +X aft, +Y right, +Z up. This is the frame the
  aircraft's animation XML states hinge lines in.
* **UE actor frame**: +X forward, +Y right, +Z up -- the frame the placeholder
  airframe and the surface animator already use.

Measured on both the 747-400 and the c172p (object bounding boxes against the
XML hinge coordinates for the same surfaces):

    model.x = ac.x        (aft positive)
    model.y = -ac.z
    model.z = ac.y

That mapping has determinant +1, so triangle winding survives it. The further
map to the UE actor frame negates X (model X is aft, UE X is forward), which
has determinant -1: the converter must reverse triangle winding exactly once.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple


class ACParseError(Exception):
    """The .ac file does not parse; refusing to guess at geometry."""


@dataclass
class ACMaterial:
    name: str
    rgb: Tuple[float, float, float]
    ambient: Tuple[float, float, float] = (0.2, 0.2, 0.2)
    emissive: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    specular: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    shininess: float = 0.0
    transparency: float = 0.0


@dataclass
class ACSurface:
    """One polygon: (vertex index, u, v) refs plus its material index."""

    flags: int
    material: int
    refs: List[Tuple[int, float, float]]

    @property
    def is_polygon(self) -> bool:
        # Low nibble: 0 polygon, 1 closed line, 2 open line.
        return (self.flags & 0x0F) == 0

    @property
    def two_sided(self) -> bool:
        return bool(self.flags & 0x20)


@dataclass
class ACObject:
    kind: str
    name: str = ""
    texture: Optional[str] = None
    #: 3x3 row-major rotation, applied to this object's and children's vertices.
    rot: Optional[Tuple[float, ...]] = None
    loc: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    vertices: List[Tuple[float, float, float]] = field(default_factory=list)
    surfaces: List[ACSurface] = field(default_factory=list)
    kids: List["ACObject"] = field(default_factory=list)

    def walk(self) -> Iterator["ACObject"]:
        yield self
        for kid in self.kids:
            yield from kid.walk()


@dataclass
class ACModel:
    materials: List[ACMaterial]
    root: ACObject
    path: Path

    def objects(self) -> Iterator[ACObject]:
        return self.root.walk()


def _apply(rot: Optional[Tuple[float, ...]], loc: Tuple[float, float, float],
           v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    x, y, z = v
    if rot is not None:
        r = rot
        x, y, z = (r[0] * x + r[1] * y + r[2] * z,
                   r[3] * x + r[4] * y + r[5] * z,
                   r[6] * x + r[7] * y + r[8] * z)
    return (x + loc[0], y + loc[1], z + loc[2])


def world_vertices(model: ACModel) -> Iterator[Tuple[ACObject, List[Tuple[float, float, float]]]]:
    """Each object with its vertices transformed by the ancestor loc/rot chain.

    AC3D's ``loc`` translates an object and everything under it; ``rot``
    likewise. Ignoring them would leave sub-assemblies (engine pods, gear
    trucks) piled at the origin -- silently, since every vertex still exists.
    """

    def descend(obj: ACObject, parent_transforms):
        # AC3D semantics: an object's rot/loc are relative to its parent, so
        # the innermost transform applies first and the ancestors' after it.
        transforms = parent_transforms + [(obj.rot, obj.loc)]
        if obj.vertices:
            out = []
            for v in obj.vertices:
                for rot, loc in reversed(transforms):
                    v = _apply(rot, loc, v)
                out.append(v)
            yield obj, out
        for kid in obj.kids:
            yield from descend(kid, transforms)

    yield from descend(model.root, [])


def parse_ac(path) -> ACModel:
    path = Path(path)
    lines = path.read_text(errors="replace").splitlines()
    if not lines or not lines[0].startswith("AC3D"):
        raise ACParseError(f"{path}: not an AC3D file (header {lines[:1]!r})")

    materials: List[ACMaterial] = []
    index = 1

    def take() -> str:
        nonlocal index
        if index >= len(lines):
            raise ACParseError(f"{path}: truncated at line {index}")
        line = lines[index]
        index += 1
        return line

    def parse_object() -> ACObject:
        nonlocal index
        header = take().split()
        if not header or header[0] != "OBJECT":
            raise ACParseError(f"{path}: expected OBJECT, got {header!r}")
        obj = ACObject(kind=header[1] if len(header) > 1 else "poly")
        while True:
            line = take()
            tokens = line.split()
            if not tokens:
                continue
            key = tokens[0]
            if key == "name":
                obj.name = shlex.split(line[len("name"):].strip())[0]
            elif key == "texture":
                # May carry a type suffix ("texture \"f.png\" base"); the path
                # is the first quoted token.
                obj.texture = shlex.split(line[len("texture"):].strip())[0]
            elif key == "rot":
                obj.rot = tuple(float(t) for t in tokens[1:10])
            elif key == "loc":
                obj.loc = (float(tokens[1]), float(tokens[2]), float(tokens[3]))
            elif key == "data":
                # Raw data block: the next line(s) hold that many bytes.
                # CRLF-authored files (measured: the FGMEMBERS p51d) count
                # the \r bytes in the total while splitlines() strips them;
                # without the slack the skip eats real keyword lines and the
                # parse desyncs into a bogus "expected OBJECT" error.
                count = int(tokens[1])
                taken = 0
                lines_taken = 0
                while taken < count - lines_taken:
                    taken += len(take()) + 1
                    lines_taken += 1
            elif key == "numvert":
                for _ in range(int(tokens[1])):
                    vt = take().split()
                    obj.vertices.append((float(vt[0]), float(vt[1]), float(vt[2])))
            elif key == "numsurf":
                for _ in range(int(tokens[1])):
                    surf_header = take().split()
                    if surf_header[0] != "SURF":
                        raise ACParseError(
                            f"{path}: expected SURF, got {surf_header!r}")
                    flags = int(surf_header[1], 0)
                    material = 0
                    refs: List[Tuple[int, float, float]] = []
                    line2 = take().split()
                    if line2[0] == "mat":
                        material = int(line2[1])
                        line2 = take().split()
                    if line2[0] != "refs":
                        raise ACParseError(f"{path}: expected refs, got {line2!r}")
                    for _ in range(int(line2[1])):
                        rt = take().split()
                        refs.append((int(rt[0]), float(rt[1]), float(rt[2])))
                    obj.surfaces.append(ACSurface(flags=flags, material=material,
                                                  refs=refs))
            elif key == "kids":
                for _ in range(int(tokens[1])):
                    # Tolerate stray duplicated "kids 0" terminators between
                    # children -- measured on the FGMEMBERS p51d, which
                    # doubles some of them; read strictly, the stray line
                    # lands where the next child's OBJECT header should be.
                    while index < len(lines) and (
                            not lines[index].split()
                            or lines[index].split() == ["kids", "0"]):
                        index += 1
                    if index >= len(lines):
                        # The same file also DECLARES more children than it
                        # contains; FlightGear's own loader tolerates the
                        # shortfall, so geometry that exists is kept rather
                        # than the whole model refused for a bad count.
                        return obj
                    obj.kids.append(parse_object())
                return obj
            # Unknown keys (crease, texrep, texoff, subdiv, hidden, locked,
            # folded, url, shader...) carry no geometry; skipped.

    while index < len(lines) and lines[index].startswith("MATERIAL"):
        line = lines[index]
        index += 1
        tokens = shlex.split(line)
        # MATERIAL "name" rgb r g b amb r g b emis r g b spec r g b shi s trans t
        # Keyword searches start AFTER the name token: a material may be
        # NAMED after a keyword -- measured on the FGMEMBERS dhc6, whose
        # MATERIAL "trans" made index("trans") find the name and read "rgb"
        # as a number.
        def find(word: str) -> int:
            try:
                return tokens.index(word, 2)
            except ValueError:
                return -1

        def triple(word: str, default) -> Tuple[float, float, float]:
            i = find(word)
            if i < 0:
                return default
            return (float(tokens[i + 1]), float(tokens[i + 2]), float(tokens[i + 3]))

        rgb_index = find("rgb")
        if rgb_index < 0:
            raise ACParseError(f"{path}: MATERIAL line without rgb: {line!r}")
        materials.append(ACMaterial(
            name=tokens[1],
            rgb=triple("rgb", None),
            ambient=triple("amb", (0.2, 0.2, 0.2)),
            emissive=triple("emis", (0.0, 0.0, 0.0)),
            specular=triple("spec", (0.0, 0.0, 0.0)),
            shininess=float(tokens[find("shi") + 1]) if find("shi") >= 0 else 0.0,
            transparency=float(tokens[find("trans") + 1]) if find("trans") >= 0 else 0.0,
        ))

    root = parse_object()
    return ACModel(materials=materials, root=root, path=path)


# -- frame conversion ----------------------------------------------------

def ac_to_model(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """.ac file frame -> FlightGear model frame (+X aft, +Y right, +Z up).

    Measured mapping (see module docstring). Determinant +1.
    """
    x, y, z = v
    return (x, -z, y)


def model_to_ue(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """FlightGear model frame -> UE actor frame (+X forward, +Y right, +Z up).

    Determinant -1: callers exporting triangles through this must reverse
    winding exactly once.
    """
    x, y, z = v
    return (-x, y, z)


def ac_to_ue(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return model_to_ue(ac_to_model(v))
