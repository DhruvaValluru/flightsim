"""Phase 10, package 6: many runs, one dataset.

``batch`` turns a matrix (a base spec, factors, seeds) into runs --
content-addressed by spec digest, ledgered, resumable, verified --
and ``export`` turns verified runs into a labelled dataset (COCO,
KITTI or WebDataset) with a card that says what it is and what it is
not, split by simulation identity so one flight never sits on both
sides of a train/test line.
"""
