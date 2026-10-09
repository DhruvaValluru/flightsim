"""Derive stand-in normal maps for the five drape textures.

    python scripts/derive_drape_normals.py [assets/xplane/terrain/drape]

Writes <role>_nrm_derived.png beside each texture (core/xplane/normals.py
says how). The drape uses one only when the extraction recorded no real
normal for that role.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.xplane.normals import derive_drape_normals  # noqa: E402

if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parents[1] / "assets" / "xplane" / "terrain" / "drape")
    print(json.dumps(derive_drape_normals(root), indent=1))
