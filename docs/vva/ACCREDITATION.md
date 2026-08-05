# Accreditation Statement

## Intended use

`flightsim` is accredited by its authors for **internal research into aircraft
response to environmental conditions** — specifically, measuring how trajectory,
attitude, load factor and control activity respond to terrain-induced wind,
turbulence, discrete gusts and boundary-layer shear, under controlled and
reproducible conditions.

## What it may be used for

* Comparative studies where the **same airframe** is flown through **different
  conditions**, and the finding is about the difference.
* Parameter sweeps with prescribed terrain statistics, where terrain is a
  controlled independent variable.
* Reproducible generation of trajectory data with full provenance.

Those uses rest on verification, not validation: the system is reproducible and
internally consistent, and comparisons *within* it are meaningful.

## What it may NOT be used for

* **Any absolute performance claim about a real aircraft.** Stock JSBSim models
  carry an explicit disclaimer that they are validated "only to the extent that
  it seems to fly right". No claim of a validated B747, 737 or Global 5000 is
  supportable with the data in this repository.
* **Certification, qualification or training credit** of any kind. FAA 14 CFR
  Part 60 tolerances are used here as an engineering yardstick; no qualification
  process has been undertaken.
* **Handling-qualities assessment.** No gain or phase margins have been
  measured, and the control gains are tuned at a single flight condition on a
  single airframe.
* **Anything involving sensor imagery.** No EO/IR modelling exists.
* **Statements about a real place.** Synthesised terrain has prescribed
  statistics and models nowhere in particular.

## Limitations material to any result

1. Aerodynamic data pedigree is the binding constraint. Everything downstream
   inherits it.
2. Control gains are unscheduled and validated at one point of one envelope.
3. The orographic model assumes flow separation wherever a crest is upstream,
   with no Froude-number or inversion dependence. It is the weakest model here.
4. Physics is bit-reproducible; **rendering is not, and does not currently
   build at all**.
5. Turbulence intensity words map to a target σ_w through a measured POE index;
   the intensity bands themselves are an operational convention.

## Basis

Verification: Gates 0–4 and 7 pass, with evidence in `docs/vva/VV_REPORT.md`.
Validation: mostly **inconclusive**, for want of referents.
Credibility: NASA-STD-7009A scorecard published at `runs/gate7/scorecard.txt`,
against a threshold of 2 declared in advance.

Accreditation is by the authors for internal use. It is not an independent
assessment, and no independent review has taken place.
