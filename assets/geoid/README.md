# The geoid grid: EGM96, 15-minute, GeographicLib PGM packaging

`egm96-15.pgm` is the EGM96 geoid undulation N (metres, ellipsoidal height =
orthometric height + N, WGS 84 ellipsoid) on a 15-minute grid, in the PGM
form the GeographicLib `Geoid` class reads. `core/terrain/geoid.py` loads
it, checks its SHA-256 on every load (a mismatch or an absent file refuses
by name: `terrain.geoid`) and evaluates N by bilinear interpolation.

## Source

* Tarball: `egm96-15.tar.bz2`, 1,490,277 bytes, fetched 2026-09-28 from
  https://sourceforge.net/projects/geographiclib/files/geoids-distrib/egm96-15.tar.bz2/download
  SHA-256 `8b1ebad1ebae0a045502d0edb9cc51553da1d3914f01e07470c11b3bed75048e`
* This file: `geoids/egm96-15.pgm` from that tarball, 2,076,888 bytes, unchanged.
  SHA-256 `2a12f13b6df65cdea52432c7fa1b43f34b007148eb817bf032af5af710905caa`
  (the tarball's `.wld` and `.pgm.aux.xml` sidecars are not needed and are
  not committed).
* Header (from the file itself): `Description WGS84 EGM96, 15-minute grid`,
  `MaxBilinearError 1.152`, `RMSBilinearError 0.040`, `Offset -108`,
  `Scale 0.003`, `Origin 90N 0E`, `AREA_OR_POINT Point`, `Vertical_Datum
  WGS84`; 1440 x 721 big-endian uint16 samples, N = Offset + Scale * value.

## Licence

EGM96 is a model of the US National Geospatial-Intelligence Agency (NGA,
then NIMA) and the NASA Goddard Space Flight Center; as a work of the US
government it is in the public domain. The PGM packaging (the resampled
grid, its header and its error figures) is GeographicLib's, by Charles
F. F. Karney, distributed under the MIT/X11 licence (permissive: use,
copy, modify and redistribute with the copyright and permission notice
kept). The tarball itself carries no licence file (measured: it holds the
three `geoids/` files only), so the licence text is not reproduced here;
the statement is GeographicLib's published one for its geoid datasets and
is not verified against a copy fetched here (the GeographicLib site is
unreachable through this container's proxy).

## What is not claimed

The GLO-30 bakes' heights are EGM2008 orthometric; this grid is EGM96.
The difference between the two models was MEASURED here from
GeographicLib's `egm2008-5.pgm` (tarball SHA-256
`9a57c14330ac609132d324906822a9da9de265ad9b9087779793eb7080852970`, grid
SHA-256 `96d55e88db186ddae892b00c5f8cc42a37cdac8ddb69b6de00af8c75dffb34a3`,
not committed: 18.7 MB): at every one of the 1,038,240 EGM96 grid nodes
the largest |EGM2008 - EGM96| is 11.985 m (28.5 N, 94.5 E, eastern
Himalaya), RMS 0.72 m; at the six curated scene origins it is +2.23
(Matterhorn), +0.51 (Yosemite), +0.94 (Fuji), +0.87 (Everest), -0.02
(Grand Canyon), +0.23 m (Flint Hills). `core/terrain/geoid.py` states the
bound as 13.7 m (the node maximum plus both grids' bilinear error bounds).
Pavlis et al. 2012 (JGR 117, B04406, the EGM2008 paper) is the reference
for the model itself; it could not be fetched here and is cited unverified.
