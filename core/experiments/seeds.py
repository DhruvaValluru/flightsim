"""Seed derivation: one experiment seed, one generator per stochastic subsystem.

§7.4 is specific about this and the specificity is the point:

    "never rely on global RNG state. One explicit RNG per stochastic subsystem
     (turbulence, sensor noise, dispersion), each derived from a single
     top-level experiment seed via a documented scheme --
     hash(experiment_seed, subsystem_name, replicate_index)."

Two failure modes it prevents.

**Correlated subsystems.** If turbulence and sensor noise draw from one stream,
their sequences are locked together: replicate 3's turbulence always arrives
with replicate 3's noise. A sweep over one then silently varies the other, and
any interaction between them is an artefact of the seeding.

**Irreproducible runs.** ``seed=None`` produces a run nobody can repeat. The
actual integer used is always recorded, and there is no code path that leaves it
unset.

Implementation uses ``numpy.random.SeedSequence``, which exists for exactly this
and spawns statistically independent streams rather than merely different ones.
The generator is PCG64, a counter-based design; §7.4 prefers these over Mersenne
Twister for parallel work because independence is provable rather than hoped for.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

import numpy as np

#: Subsystems that consume randomness. Naming them explicitly means a new one
#: cannot quietly share a stream with an existing one -- it has to be added
#: here, and adding it changes nothing about the others' sequences.
SUBSYSTEMS = (
    "turbulence",
    "gust",
    "terrain",
    "sensor_noise",
    "dispersion",
)

DERIVATION = (
    "SeedSequence(entropy=experiment_seed, "
    "spawn_key=(stable_hash(subsystem), replicate)) mod MAX_SEED"
)

#: Largest seed value any consumer can represent. JSBSim stores
#: ``atmosphere/randomseed`` as a double and casts it to a C int, so anything
#: at or above INT_MAX saturates: measured on the pinned build, seeds
#: 7173749350325947451 and 4610176084448916245 both read back as 2147483647 and
#: produced *bit-identical* turbulence. Every replicate of a sweep silently got
#: the same realisation while the manifest recorded two different seeds.
#:
#: 2^31 - 2 keeps the value exactly representable in a double, inside a signed
#: 32-bit int, and clear of the saturation boundary itself.
MAX_SEED = 2 ** 31 - 2


def stable_hash(text: str) -> int:
    """A hash that is the same in every process and every Python version.

    ``hash()`` is salted per process by default, so a seed derived from it
    would change between runs of the same experiment -- which is the one thing
    a seed must never do.
    """
    digest = hashlib.sha256(text.encode()).digest()
    return int.from_bytes(digest[:8], "big")


@dataclass(frozen=True)
class SeedSet:
    """Every seed a single case used, recorded for the manifest."""

    experiment_seed: int
    replicate: int
    seeds: Dict[str, int]

    def for_subsystem(self, name: str) -> int:
        if name not in self.seeds:
            raise KeyError(
                f"no seed derived for subsystem {name!r}; known: "
                f"{sorted(self.seeds)}. Add it to SUBSYSTEMS rather than "
                f"reusing another subsystem's stream."
            )
        return self.seeds[name]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_seed": self.experiment_seed,
            "replicate": self.replicate,
            "derivation": DERIVATION,
            "generator": "PCG64",
            "seeds": dict(self.seeds),
        }


def derive(experiment_seed: int, replicate: int = 0,
           subsystems: Iterable[str] = SUBSYSTEMS) -> SeedSet:
    """Derive one independent seed per subsystem.

    Deterministic in ``(experiment_seed, subsystem, replicate)`` and nothing
    else, so re-running a case reproduces its randomness exactly and running
    case 7 does not depend on whether cases 1-6 ran first.
    """
    if experiment_seed is None:
        raise ValueError(
            "experiment_seed must be an explicit integer. A run seeded with "
            "None cannot be reproduced, and §7.4 forbids logging seed=None."
        )
    seeds = {}
    for name in subsystems:
        sequence = np.random.SeedSequence(
            entropy=int(experiment_seed),
            spawn_key=(stable_hash(name), int(replicate)),
        )
        # Folded into a range every consumer can represent exactly. See
        # MAX_SEED: a wider value does not fail, it saturates, which is worse.
        raw = int(sequence.generate_state(1, dtype=np.uint64)[0])
        seeds[name] = 1 + (raw % MAX_SEED)
    return SeedSet(int(experiment_seed), int(replicate), seeds)


def generator(experiment_seed: int, subsystem: str, replicate: int = 0
              ) -> np.random.Generator:
    """A PCG64 generator for one subsystem of one replicate."""
    if subsystem not in SUBSYSTEMS:
        raise KeyError(
            f"unknown subsystem {subsystem!r}; add it to SUBSYSTEMS so its "
            f"stream is declared rather than borrowed"
        )
    sequence = np.random.SeedSequence(
        entropy=int(experiment_seed),
        spawn_key=(stable_hash(subsystem), int(replicate)),
    )
    return np.random.Generator(np.random.PCG64(sequence))
