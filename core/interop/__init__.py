"""Interoperability: the standard forms in which a run's state leaves
this system (docs/PHASE3_GAP_ANALYSIS.md I1).

* :mod:`core.interop.geodesy` -- WGS 84 geodetic <-> ECEF, the NED and
  body frames in ECEF, and the DIS Euler convention, own implementation
  (pyproj is the independent reference in the tests, never the producer).
* :mod:`core.interop.dis` -- IEEE 1278.1-2012 Entity State PDUs
  (protocol version 7, PDU type 1) encoded from a run's telemetry, one
  per sample, into a binary stream with a JSON sidecar.

What is NOT claimed: no PDU is sent on a network here (no socket, no
multicast, no exercise management); HLA (IEEE 1516), CIGI and CDB are
out of scope (gap analysis I2, I3).
"""
