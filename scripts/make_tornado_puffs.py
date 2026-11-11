"""Build assets/looks/tornado/puffs_atlas.png from Kenney's CC0 smoke puffs.

Lane C of the visual push (2026-11-11): the tornado's dust cloud and the
wall cloud's scud are camera-facing smoke puffs (FlightSimTornadoBeauty.cpp,
beauty only). Four of Kenney's "Smoke Particles" white puffs (CC0-1.0, pinned
in assets/looks/tornado/PIN.json and THIRD_PARTY_VISUAL.md) are packed into one
512 x 512 grey + alpha PNG, a 2 x 2 atlas of 256 px tiles, so one material
(M_TornadoPuff, PuffTile 0..3) draws every puff.

Standard library only (no imaging library on the render machine's editor
Python, nor here): the upstream palette PNGs are decoded by hand, each is
fitted into its tile (aspect kept, PUFF_TILE_FILL of the tile, centred,
transparent around it) by box-filtered resampling on premultiplied grey, and
the atlas is written as an 8-bit grey + alpha PNG. Deterministic: the same
inputs give the same bytes (PIN.json records the output's sha256 and
tests/test_tornado_look.py checks it).

    python scripts/make_tornado_puffs.py --fetch     # download the pinned inputs
    python scripts/make_tornado_puffs.py <dir>       # inputs already in <dir>
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import urllib.request
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "assets" / "looks" / "tornado"
PIN = OUT_DIR / "PIN.json"
ATLAS = OUT_DIR / "puffs_atlas.png"
TILE = 256
#: The share of the tile the puff's longer side fills (a transparent margin
#: keeps a rotated puff off its neighbours: M_TornadoPuff clamps to the tile).
PUFF_TILE_FILL = 0.94


def _pin():
    return json.loads(PIN.read_text(encoding="utf-8"))


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def decode_png(data: bytes):
    """(width, height, [(grey 0..255 as float, alpha 0..1)] row-major) for an
    8-bit palette (type 3, optional tRNS), grey, grey+alpha, RGB or RGBA PNG."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, palette, trns = 8, b"", None, None
    width = height = depth = ctype = None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or interlace != 0:
                raise ValueError("only 8-bit, non-interlaced PNGs")
        elif kind == b"PLTE":
            palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif kind == b"tRNS":
            trns = list(body)
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(idat)
    stride = width * channels
    rows, prev, off = [], bytearray(stride), 0
    for _ in range(height):
        filt = raw[off]
        line = bytearray(raw[off + 1:off + 1 + stride])
        off += 1 + stride
        for i in range(stride):
            a = line[i - channels] if i >= channels else 0
            b = prev[i]
            c = prev[i - channels] if i >= channels else 0
            if filt == 1:
                line[i] = (line[i] + a) & 0xFF
            elif filt == 2:
                line[i] = (line[i] + b) & 0xFF
            elif filt == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 0xFF
            elif filt == 4:
                line[i] = (line[i] + _paeth(a, b, c)) & 0xFF
        rows.append(line)
        prev = line
    pixels = []
    for line in rows:
        for x in range(width):
            px = line[x * channels:(x + 1) * channels]
            if ctype == 3:
                r, g, b = palette[px[0]]
                alpha = (trns[px[0]] if trns is not None and px[0] < len(trns) else 255)
            elif ctype == 0:
                r = g = b = px[0]
                alpha = 255
            elif ctype == 4:
                r = g = b = px[0]
                alpha = px[1]
            elif ctype == 2:
                r, g, b = px
                alpha = 255
            else:
                r, g, b, alpha = px
            pixels.append((0.2126 * r + 0.7152 * g + 0.0722 * b, alpha / 255.0))
    return width, height, pixels


def fit_into_tile(width, height, pixels, tile=TILE, fill=PUFF_TILE_FILL):
    """The puff box-filtered into a tile x tile grid of (grey, alpha), aspect
    kept, centred; premultiplied while filtering (no dark fringe)."""
    scale = fill * tile / max(width, height)
    w_out, h_out = max(1, round(width * scale)), max(1, round(height * scale))
    x0, y0 = (tile - w_out) // 2, (tile - h_out) // 2
    out = [(0.0, 0.0)] * (tile * tile)
    for oy in range(h_out):
        sy0, sy1 = oy / scale, (oy + 1) / scale
        for ox in range(w_out):
            sx0, sx1 = ox / scale, (ox + 1) / scale
            acc_g = acc_a = area = 0.0
            for sy in range(int(sy0), min(height, int(sy1) + 1)):
                wy = min(sy + 1, sy1) - max(sy, sy0)
                if wy <= 0:
                    continue
                for sx in range(int(sx0), min(width, int(sx1) + 1)):
                    wx = min(sx + 1, sx1) - max(sx, sx0)
                    if wx <= 0:
                        continue
                    grey, alpha = pixels[sy * width + sx]
                    acc_g += grey * alpha * wx * wy
                    acc_a += alpha * wx * wy
                    area += wx * wy
            alpha = acc_a / area if area else 0.0
            grey = acc_g / acc_a if acc_a > 0 else 0.0
            out[(y0 + oy) * tile + x0 + ox] = (grey, alpha)
    return out


def encode_grey_alpha(width, height, pixels) -> bytes:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            grey, alpha = pixels[y * width + x]
            raw.append(max(0, min(255, round(grey))))
            raw.append(max(0, min(255, round(alpha * 255.0))))

    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 4, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def build(inputs: Path) -> bytes:
    pin = _pin()
    size = 2 * TILE
    atlas = [(0.0, 0.0)] * (size * size)
    for index, name in enumerate(pin["atlas"]["tiles"]):
        entry = pin["files"][name]
        data = (inputs / name).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry["sha256"]:
            raise SystemExit(f"{name}: sha256 {digest} is not the pinned {entry['sha256']}")
        tile = fit_into_tile(*decode_png(data))
        tx, ty = (index % 2) * TILE, (index // 2) * TILE
        for y in range(TILE):
            atlas[(ty + y) * size + tx:(ty + y) * size + tx + TILE] = tile[y * TILE:(y + 1) * TILE]
    return encode_grey_alpha(size, size, atlas)


def fetch(into: Path) -> None:
    for name, entry in _pin()["files"].items():
        data = urllib.request.urlopen(entry["url"]).read()   # noqa: S310 (pinned https)
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry["sha256"]:
            raise SystemExit(f"{entry['url']}: sha256 {digest} is not the pinned {entry['sha256']}")
        (into / name).write_bytes(data)


def main(argv) -> int:
    if argv and argv[0] == "--fetch":
        inputs = Path(tempfile.mkdtemp(prefix="flightsim_puffs_"))
        fetch(inputs)
    elif argv:
        inputs = Path(argv[0])
    else:
        print(__doc__)
        return 2
    data = build(inputs)
    ATLAS.write_bytes(data)
    print(f"{ATLAS.relative_to(REPO)}: {len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
