"""Decode a P3D "PV44" exterior .mdl into world-space triangles.

Nothing here is from a published spec. The layout was worked out by
measuring the A-4E model and is pinned by tests (test_a4_mesh.py):

* The file is a RIFF tree. ``MDLD`` holds the sections used here.
* ``VERB`` holds vertex buffers (``VERT`` chunks). Static buffers use a
  32-byte vertex: position (3 f32, metres), normal (3 f32), uv (2 f32,
  origin top-left). Axes are x right, y up, z forward.
* ``IND3`` is a uint32 index buffer.
* ``LODT`` > ``LODE`` > ``PART`` (36 bytes = 9 uint32) lists draw parts;
  only the first (highest-detail) LOD is read. Words: 1 scene node,
  2 material, 3 vertex buffer, 4 first vertex, 5 vertex count,
  6 first index, 7 index count. Indices are relative to the first vertex.
* ``TRAN`` is an array of 4x4 row-vector matrices (some carry inch->metre
  scale and a Z-up->Y-up swap).
* ``SCEN`` is the scene tree, 8 bytes per node: the low 16 bits of word 0
  are the first child, the high 16 bits the next sibling (0xFFFF = none).
  ``AMAP`` gives each node its ``TRAN`` index in word 1 (word 0 is a kind
  that does not change how it is used).
* A part's world matrix is the product of ``TRAN[AMAP[n]]`` over the node
  and every ancestor, node first. Node 0 parts are already in model space.
* ``SGVL`` is one uint16 per node indexing ``VISL`` records (0xFFFF = no
  condition). A node shows only if it and every ancestor pass. Conditions
  are MSFS RPN expressions over ``L:`` and ``A:`` variables.

Known limits: only the highest-detail LOD; conditions using ``if{``/``els{``
are not evaluated and count as hidden (they gate lights and fuel dump);
animation (``ANIB``) is not read, so every part is at its rest pose.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

STATIC_NODE = 0
NO_INDEX = 0xFFFF

#: Parts whose world bounds fall outside this box are helper volumes (the
#: model carries hit boxes and effect volumes), not airframe. Metres.
ENVELOPE_LO = np.array([-4.5, -2.6, -7.0])
ENVELOPE_HI = np.array([4.5, 3.2, 7.5])

#: Simulator variables for a parked, powered-down airplane. Every variable
#: not named here reads 0.
REST_ENV = {"Sim On Ground": 1.0}

_TOKEN = re.compile(
    r"\(([LAE]):[^)]*\)|-?\d+\.?\d*|!=|==|>=|<=|>|<|!|and|or|&&|\|\||if\{|els\{|\}",
    re.I)


@dataclass
class Part:
    index: int
    node: int
    material: int
    positions: np.ndarray   # (n, 3) world, metres
    normals: np.ndarray     # (n, 3) world, unit
    uvs: np.ndarray         # (n, 2)
    triangles: np.ndarray   # (t, 3) into the arrays above


def evaluate(expression: str, env: Dict[str, float]) -> Optional[bool]:
    """Evaluate the simple RPN subset; None if the expression needs more."""
    stack: List[float] = []
    try:
        for m in _TOKEN.finditer(expression):
            t = m.group(0)
            if t.startswith("("):
                name = re.match(r"\([LAE]:([^,)]*)", t, re.I).group(1).strip()
                stack.append(float(env.get(name, 0.0)))
            elif re.fullmatch(r"-?\d+\.?\d*", t):
                stack.append(float(t))
            elif t == "!":
                stack.append(0.0 if stack.pop() else 1.0)
            elif t in ("and", "&&", "or", "||", "==", "!=", ">", "<", ">=", "<="):
                b, a = stack.pop(), stack.pop()
                stack.append(float({
                    "and": bool(a) and bool(b), "&&": bool(a) and bool(b),
                    "or": bool(a) or bool(b), "||": bool(a) or bool(b),
                    "==": a == b, "!=": a != b, ">": a > b, "<": a < b,
                    ">=": a >= b, "<=": a <= b}[t]))
            else:
                return None
        return bool(stack[-1]) if stack else None
    except (IndexError, AttributeError):
        return None


class MdlScene:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        d = self.path.read_bytes()
        if d[:4] != b"RIFF" or d[8:12] != b"PV44":
            raise ValueError(f"{path} is not a PV44 model")
        self._d = d
        sections: Dict[bytes, tuple] = {}
        for cid, o, s in self._chunks(12, len(d)):
            if cid == b"MDLD":
                for c2, o2, s2 in self._chunks(o, o + s):
                    sections.setdefault(c2, (o2, s2))
        self._sections = sections

        o, s = sections[b"VERB"]
        self._buffers = [d[o3:o3 + s3] for c, o3, s3 in self._chunks(o, o + s)
                         if c == b"VERT"]
        o, s = sections[b"IND3"]
        self._indices = np.frombuffer(d[o:o + s - s % 4], dtype="<u4")
        o, s = sections[b"TRAN"]
        self._tran = np.frombuffer(d[o:o + s], dtype="<f4").reshape(-1, 4, 4)

        scen = np.frombuffer(self._blob(b"SCEN"), dtype="<u4").reshape(-1, 2)
        self._amap = np.frombuffer(self._blob(b"AMAP"), dtype="<u4").reshape(-1, 2)
        self._visibility = np.frombuffer(self._blob(b"SGVL"), dtype="<u2")
        self.node_count = len(scen)
        self._parent = [-1] * self.node_count
        for node in range(self.node_count):
            child = int(scen[node][0]) & 0xFFFF
            while child != NO_INDEX and child < self.node_count:
                self._parent[child] = node
                child = int(scen[child][0]) >> 16

        self._conditions = self._read_conditions(self._blob(b"VISL"))

        o, s = sections[b"LODT"]
        self._raw_parts: List[tuple] = []
        for c2, o2, s2 in self._chunks(o, o + s):
            self._raw_parts = [
                struct.unpack("<9I", d[o3:o3 + 36])
                for c3, o3, _ in self._chunks(o2 + 4, o2 + s2) if c3 == b"PART"]
            break

    # -- low level ---------------------------------------------------------

    def _chunks(self, off: int, end: int):
        d = self._d
        while off + 8 <= end:
            size = struct.unpack("<I", d[off + 4:off + 8])[0]
            yield d[off:off + 4], off + 8, size
            off += 8 + size

    def _blob(self, key: bytes) -> bytes:
        o, s = self._sections[key]
        return self._d[o:o + s]

    @staticmethod
    def _read_conditions(blob: bytes) -> List[tuple]:
        out, pos = [], 0
        while pos + 8 <= len(blob):
            tag = blob[pos:pos + 4].decode("latin1")
            size = struct.unpack("<I", blob[pos + 4:pos + 8])[0]
            text = blob[pos + 8:pos + 8 + size].rstrip(b"\0").decode("latin1")
            out.append((tag, text.strip()))
            pos += 8 + size
        return out

    # -- scene -------------------------------------------------------------

    @property
    def part_count(self) -> int:
        return len(self._raw_parts)

    def node_visible(self, node: int, env: Dict[str, float]) -> bool:
        while node != -1:
            ci = int(self._visibility[node])
            if ci != NO_INDEX and ci < len(self._conditions):
                tag, text = self._conditions[ci]
                if tag == "VISC" and not evaluate(text, env):
                    return False   # false, or not evaluable -> hidden
            node = self._parent[node]
        return True

    def world_matrix(self, node: int) -> np.ndarray:
        m = np.eye(4)
        while node != -1:
            idx = int(self._amap[node][1])
            if idx < len(self._tran):
                m = m @ self._tran[idx].astype(np.float64)
            node = self._parent[node]
        return m

    def part_local(self, index: int) -> tuple:
        """(positions, normals, uvs, triangles) before any transform."""
        _, node, mat, vb, first, count, istart, icount, _ = self._raw_parts[index]
        buf = np.frombuffer(self._buffers[vb], dtype="<f4").reshape(-1, 8)
        v = buf[first:first + count].astype(np.float64)
        tri = self._indices[istart:istart + icount].reshape(-1, 3)
        return v[:, 0:3], v[:, 3:6], v[:, 6:8], tri

    def parts(self, env: Optional[Dict[str, float]] = None,
              min_vertices: int = 4) -> List[Part]:
        """Visible airframe parts in world space (metres)."""
        env = REST_ENV if env is None else env
        out: List[Part] = []
        for i, raw in enumerate(self._raw_parts):
            node, mat, count = raw[1], raw[2], raw[5]
            if count < min_vertices or not self.node_visible(node, env):
                continue
            pos, nrm, uv, tri = self.part_local(i)
            if not (np.isfinite(pos).all() and np.isfinite(nrm).all()) \
                    or len(tri) == 0 or tri.max() >= count:
                continue
            m = np.eye(4) if node == STATIC_NODE else self.world_matrix(node)
            world = np.c_[pos, np.ones(len(pos))] @ m
            lo, hi = world[:, :3].min(0), world[:, :3].max(0)
            if not ((lo > ENVELOPE_LO).all() and (hi < ENVELOPE_HI).all()):
                continue
            n = nrm @ m[:3, :3]
            n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
            out.append(Part(i, node, mat, world[:, :3], n, uv, tri))
        return out
