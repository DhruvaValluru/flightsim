"""Ground truth for the FDM: terrain elevation under the aircraft, every step.

This is the headless equivalent of the engine's ground callback. In the embedded
host, ``UEGroundCallback`` line-traces against world geometry; here the same
question is answered by a direct array lookup into a baked raster.

Both answer from the *same* source of truth, which is the point of §3.2: Cesium's
visual terrain is not queried for physics, because its answer is asynchronous and
depends on which LOD happens to be streamed in. A ground callback needs a
deterministic answer on every tick.

Coordinates
-----------
The aircraft reports geodetic latitude and longitude; the raster is in a metric
projected CRS. The transformation between them is done properly through pyproj
rather than by a flat-Earth approximation, because a scene can span tens of
kilometres and a small-angle error in position becomes a large error in
elevation over steep terrain -- which is exactly where it matters.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

from ..fdm import units as u
from .heightfield import Heightfield


class TerrainGround:
    """Writes terrain elevation under the aircraft into the FDM each step."""

    def __init__(self, heightfield: Heightfield) -> None:
        self.heightfield = heightfield
        self._transformer = None
        crs = heightfield.georeference.crs
        if crs and crs.upper() not in ("EPSG:4326", "OGC:CRS84"):
            try:
                from pyproj import Transformer

                self._transformer = Transformer.from_crs(
                    "EPSG:4326", crs, always_xy=True
                )
            except ImportError:  # pragma: no cover - environment dependent
                raise RuntimeError(
                    f"terrain is in {crs} but pyproj is unavailable, so "
                    f"latitude/longitude cannot be converted to it. Refusing "
                    f"to approximate: an error here places the ground in the "
                    f"wrong place under the aircraft."
                )

    # -- coordinates ----------------------------------------------------

    def project(self, latitude_deg: float, longitude_deg: float) -> Tuple[float, float]:
        """Geodetic to the raster's own CRS, in metres."""
        if self._transformer is None:
            return longitude_deg, latitude_deg
        x, y = self._transformer.transform(longitude_deg, latitude_deg)
        return float(x), float(y)

    def elevation_at(self, latitude_deg: float, longitude_deg: float) -> float:
        x, y = self.project(latitude_deg, longitude_deg)
        return self.heightfield.elevation_at(x, y)

    def contains(self, latitude_deg: float, longitude_deg: float) -> bool:
        x, y = self.project(latitude_deg, longitude_deg)
        return self.heightfield.contains(x, y)

    # -- application ----------------------------------------------------

    def apply(self, fdm) -> float:
        """Write the terrain elevation under the aircraft. Call every step."""
        state = fdm.state()
        elevation_m = self.elevation_at(state.lat_deg, state.lon_deg)
        fdm.props.set("position/terrain-elevation-asl-ft", u.m_to_ft(elevation_m))
        return elevation_m

    def centre_lonlat(self) -> Tuple[float, float]:
        """Longitude and latitude of the raster centre, for placing a scenario."""
        min_x, min_y, max_x, max_y = self.heightfield.bounds_m()
        cx, cy = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0
        if self._transformer is None:
            return cx, cy
        from pyproj import Transformer

        inverse = Transformer.from_crs(
            self.heightfield.georeference.crs, "EPSG:4326", always_xy=True
        )
        lon, lat = inverse.transform(cx, cy)
        return float(lon), float(lat)

    def provenance(self) -> Dict[str, Any]:
        return {
            "name": "terrain_ground",
            "heightfield": self.heightfield.name,
            "sha256": self.heightfield.digest(),
            "crs": self.heightfield.georeference.crs,
            "pixel_size_m": self.heightfield.georeference.pixel_size_m,
            "statistics": self.heightfield.statistics(),
            "producer": self.heightfield.provenance.get("producer"),
        }


def terrain_field_from(heightfield: Heightfield,
                       wavelength_m: Optional[float] = None):
    """Adapt a baked raster to the interface the orographic provider expects.

    This is what closes the gap Phase 3 left open. Until now the orographic
    model ran against an analytic sinusoid, so "ridge lift over this ridge" was
    a precise number about nothing. Behind this adapter the provider queries
    real or synthesised terrain through the identical call, and never learns
    which -- so terrain roughness becomes an independent variable that can be
    swept while everything else is held fixed.
    """
    from ..environment.terrain_field import TerrainField

    ground = TerrainGround(heightfield)
    origin_lon, origin_lat = ground.centre_lonlat()
    origin_x, origin_y = ground.project(origin_lat, origin_lon)

    def elevation(north_m: float, east_m: float) -> float:
        # The orographic provider works in local north/east metres about the
        # scene origin; the raster works in projected easting/northing.
        return heightfield.elevation_at(origin_x + east_m, origin_y + north_m)

    if wavelength_m is None:
        # Autocorrelation length is not known a priori for a real DEM, so a
        # scale is taken from the raster extent. It sets only the vertical decay
        # height of the perturbation, and is recorded so it is not mistaken for
        # a measured property of the landscape.
        width_m, _ = heightfield.extent_m
        wavelength_m = max(width_m / 8.0, 200.0)

    return TerrainField(elevation, wavelength_m=wavelength_m,
                        name=f"{heightfield.name} (baked raster)")
