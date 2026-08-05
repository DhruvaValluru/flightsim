"""The run manifest: everything needed to reproduce a result.

§7.4 lists what goes in it -- git commit, SHA-256 of every input, container
image digest, the full parameter set including all seeds, JSBSim version, host
info, SHA-256 of every output -- and the list is the specification.

Two claims are kept deliberately apart, because they are not equally strong.

**Physics reproducibility** is the strict claim: the same spec must produce the
same telemetry, bit for bit. Gate 1 demonstrates it and this manifest is what
makes it checkable by someone else.

**Rendering reproducibility** is not available at all. Movie Render Queue is not
bit-deterministic and Epic documents no fix. When rendering exists it will be
described as reproducible-within-tolerance, and this manifest records which kind
of claim a given artefact carries.

Floating point
--------------
§7.4 also notes that IEEE-754 is not bit-reproducible across compilers,
optimisation levels or vectorisation. The manifest therefore records the host
and interpreter, so a digest mismatch on another machine can be attributed
rather than argued about. What it cannot do is make the mismatch not happen:
where bit-identity is unavailable, the honest position is a documented tolerance
band, not a stronger claim.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

MANIFEST_VERSION = 1


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def git_provenance(repo: Optional[Path] = None) -> Dict[str, Any]:
    """Commit, and whether the tree was dirty when the run started.

    ``dirty`` matters more than the commit does. A result produced from an
    uncommitted tree cannot be recovered from the commit alone, and recording
    the hash without the dirty flag would imply that it can.
    """
    repo = Path(repo) if repo else Path(__file__).resolve().parents[2]

    def git(*args) -> Optional[str]:
        try:
            out = subprocess.run(["git", "-C", str(repo), *args],
                                 capture_output=True, text=True, timeout=15)
            return out.stdout.strip() if out.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    status = git("status", "--porcelain")
    return {
        "commit": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(status) if status is not None else None,
        "dirty_files": len(status.splitlines()) if status else 0,
    }


def host_provenance() -> Dict[str, Any]:
    import numpy

    try:
        import jsbsim
        jsbsim_version = jsbsim.FGJSBBase().get_version()
    except Exception:                                    # pragma: no cover
        jsbsim_version = None

    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "numpy": numpy.__version__,
        "jsbsim": jsbsim_version,
        # §7.4 asks for a container image digest. There is no container here,
        # and saying so is more useful than omitting the field: it tells a
        # reader the environment was the host's, not a pinned image.
        "container_image_digest": None,
    }


@dataclass
class RunManifest:
    """A record from which a run can be reproduced and checked."""

    name: str
    inputs: Dict[str, str] = field(default_factory=dict)
    outputs: Dict[str, str] = field(default_factory=dict)
    parameters: Dict[str, Any] = field(default_factory=dict)
    seeds: Dict[str, Any] = field(default_factory=dict)
    components: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    #: What kind of reproducibility this artefact carries.
    reproducibility: str = "bit-identical (physics)"

    def add_input(self, label: str, path) -> "RunManifest":
        self.inputs[label] = sha256_file(path)
        return self

    def add_input_text(self, label: str, text: str) -> "RunManifest":
        self.inputs[label] = sha256_text(text)
        return self

    def add_output(self, label: str, path) -> "RunManifest":
        self.outputs[label] = sha256_file(path)
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manifest_version": MANIFEST_VERSION,
            "name": self.name,
            "git": git_provenance(),
            "host": host_provenance(),
            "parameters": self.parameters,
            "seeds": self.seeds,
            "components": self.components,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "reproducibility": self.reproducibility,
            "notes": list(self.notes),
        }

    def write(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=1, sort_keys=True))
        return path

    @staticmethod
    def read(path) -> Dict[str, Any]:
        return json.loads(Path(path).read_text())


def verify_reproduction(manifest_path, produced: Dict[str, str]
                        ) -> Dict[str, Any]:
    """Compare freshly produced output hashes against a recorded manifest.

    This is what makes a manifest a claim rather than a decoration: Gate 7
    re-runs from the manifest and checks the digests match. A manifest nobody
    has ever reproduced from is an assertion.
    """
    recorded = RunManifest.read(manifest_path)
    expected = recorded.get("outputs", {})
    checked, mismatched, missing = [], [], []
    for label, digest in expected.items():
        if label not in produced:
            missing.append(label)
        elif produced[label] != digest:
            mismatched.append(label)
        else:
            checked.append(label)
    return {
        "ok": not mismatched and not missing,
        "matched": checked,
        "mismatched": mismatched,
        "missing": missing,
        "git_commit": recorded.get("git", {}).get("commit"),
        "git_dirty": recorded.get("git", {}).get("dirty"),
    }
