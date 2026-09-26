"""The flightsim command surface: thin entry points over core/.

``python -m flightsim.capture``  -- validate, run headlessly, solve
camera geometry, schedule captures, write the capture manifest and
geometry previews (rendering only where the UE half exists; refused by
name -- ue.platform -- everywhere else).

``python -m flightsim.verify``   -- the phase's verification summary
over a captured run directory (and its verification.json).

``python -m flightsim.batch``    -- a matrix of specs (base, factors,
seeds) captured and verified, one ledger line per run, resumable.

``python -m flightsim.export``   -- verified runs as a COCO, KITTI,
WebDataset, YOLO or Pascal VOC dataset (core.dataset.export.FORMATS)
with a card, split by simulation digest.

``python -m flightsim.campaign`` -- one prompt and a frame target run
as index-seeded cases by a worker pool, the ledger the only truth.

``python -m flightsim.agent``    -- the same campaign driven by the
typed tools under a stated policy, with a trace beside the dataset.

Nothing lives here but argument parsing and wiring: every behaviour is
core/'s, tested there.
"""
