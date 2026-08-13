"""Terrain: one raster format, two producers, and metres that survive.

The property under test throughout is §3.2's: real and procedural terrain reach
the FDM through the *same* interface, so terrain statistics can be swept as an
independent variable without also changing the code path.
"""

import math

import numpy as np
import pytest

from core.terrain import dem, landscape, synthesis
from core.terrain.ground import TerrainGround, terrain_field_from
from core.terrain.heightfield import U16_MAX, Georeference, Heightfield
from core.terrain.synthesis import TerrainStatistics

UTM = "EPSG:32633"


@pytest.fixture(scope="module")
def procedural():
    return synthesis.generate(
        size=128, pixel_size_m=60.0, seed=5,
        statistics=TerrainStatistics(hurst=0.8, rms_slope_deg=20.0,
                                     outer_scale_m=4000.0),
    )


@pytest.fixture(scope="module")
def reference_dem(tmp_path_factory):
    path = tmp_path_factory.mktemp("dem") / "ref.tif"
    size = 160
    cc, rr = np.meshgrid(np.arange(size), np.arange(size))
    z = 700.0 + 250.0 * np.cos(2 * math.pi * cc / 50.0) + 0.4 * rr
    dem.write_geotiff(path, z, "EPSG:4326", 12.0, 46.0 + size * 0.001, 0.001)
    return path, z


# -- the shared format ---------------------------------------------------


def test_both_producers_return_the_same_type(procedural, reference_dem):
    """§3.2: the ground callback must not be able to tell them apart."""
    path, _ = reference_dem
    real = dem.ingest(path, target_crs=UTM, ground_sample_distance_m=60.0)
    assert type(real) is type(procedural) is Heightfield
    assert type(TerrainGround(real)) is type(TerrainGround(procedural))


def test_samples_are_uint16_like_a_real_dem(procedural):
    assert procedural.samples.dtype == np.uint16
    assert procedural.quantisation_m > 0


def test_elevation_query_is_bilinear_not_nearest():
    """A ground callback that steps between pixels would jolt the aircraft."""
    z = np.array([[0.0, 0.0], [0.0, 100.0]])
    field = Heightfield.from_elevations(
        z, Georeference(UTM, origin_x_m=0.0, origin_y_m=10.0, pixel_size_m=10.0)
    )
    # Midway along the bottom edge, between 0 and 100.
    assert field.elevation_at(5.0, 0.0) == pytest.approx(50.0, abs=0.1)
    corner = field.elevation_at(5.0, 5.0)
    assert 20.0 < corner < 30.0            # bilinear centre of 0,0,0,100


def test_queries_outside_the_raster_clamp_rather_than_raise(procedural):
    """A ground callback runs on every tick, including during a trim excursion."""
    far = procedural.elevation_at(-1e6, -1e6)
    assert math.isfinite(far)
    assert not procedural.contains(-1e6, -1e6)


def test_persistence_is_bit_identical(procedural, tmp_path):
    procedural.write(tmp_path / "field")
    reloaded = Heightfield.read(tmp_path / "field")
    assert reloaded.digest() == procedural.digest()
    assert reloaded.elevation_at(500.0, 500.0) == procedural.elevation_at(500.0, 500.0)


def test_corrupted_raster_is_detected(procedural, tmp_path):
    """A truncated or edited raster must not load as if it were intact."""
    raw = procedural.write(tmp_path / "field")
    data = bytearray(raw.read_bytes())
    data[10] ^= 0xFF
    raw.write_bytes(bytes(data))
    with pytest.raises(ValueError, match="does not match the recorded SHA-256"):
        Heightfield.read(tmp_path / "field")


# -- synthesis -----------------------------------------------------------


def test_synthesis_is_deterministic():
    a = synthesis.generate(size=64, seed=3, pixel_size_m=60.0)
    b = synthesis.generate(size=64, seed=3, pixel_size_m=60.0)
    assert a.digest() == b.digest()
    assert synthesis.generate(size=64, seed=4, pixel_size_m=60.0).digest() != a.digest()


def test_spectral_exponent_is_prescribed_not_emergent():
    """The reason for Fourier synthesis over summed octaves of noise."""
    def measured_hurst(target):
        rng = np.random.default_rng(2)
        z = synthesis.spectral_surface(256, target, rng, 30.0, None)
        lags = np.array([1, 2, 4, 8, 16, 32])
        rms = [np.sqrt(((z[:-L] - z[L:]) ** 2).mean()) for L in lags]
        return np.polyfit(np.log(lags * 30.0), np.log(rms), 1)[0]

    assert measured_hurst(0.5) == pytest.approx(0.5, abs=0.1)
    assert measured_hurst(0.8) > measured_hurst(0.5)


def test_rms_slope_is_the_control_and_it_works():
    """Slope, not height, is what decides physical plausibility."""
    previous = 0.0
    for target in (10.0, 20.0, 30.0):
        field = synthesis.generate(
            size=128, pixel_size_m=60.0, seed=9,
            statistics=TerrainStatistics(rms_slope_deg=target, outer_scale_m=4000.0),
        )
        median = float(np.percentile(field.slope_degrees(), 50))
        assert median > previous
        previous = median
        # Prescribing 30 must not produce a landscape of cliffs.
        assert float(np.percentile(field.slope_degrees(), 99)) < 45.0


def test_prescribing_both_height_and_slope_is_refused():
    """They over-constrain the surface; one of them would silently lose."""
    with pytest.raises(ValueError, match="exactly one"):
        TerrainStatistics(rms_slope_deg=20.0, rms_height_m=250.0)
    with pytest.raises(ValueError, match="exactly one"):
        TerrainStatistics(rms_slope_deg=None, rms_height_m=None)


def test_implausible_slope_is_refused():
    with pytest.raises(ValueError, match="plausible landscape"):
        TerrainStatistics(rms_slope_deg=75.0)


def test_thermal_erosion_conserves_material_and_limits_slope():
    rng = np.random.default_rng(1)
    z = synthesis.spectral_surface(64, 0.6, rng, 30.0, None)
    z *= 200.0 / z.std()
    eroded = synthesis.thermal_erosion(z, 30.0, repose_deg=35.0, iterations=60)
    # Talus, not decapitation: the mean is preserved because material moves.
    assert eroded.mean() == pytest.approx(z.mean(), abs=1e-6)
    before = np.abs(np.diff(z, axis=0)).max()
    after = np.abs(np.diff(eroded, axis=0)).max()
    assert after < before


def test_erosion_produces_drainage_not_just_smoothing():
    """Flow accumulation must be heavy-tailed: channels, not uniform sheet flow."""
    rng = np.random.default_rng(4)
    z = synthesis.spectral_surface(96, 0.8, rng, 30.0, None)
    z *= 150.0 / z.std()
    area = synthesis.flow_accumulation(z)
    # A few cells should carry far more than the median: that is a channel.
    assert area.max() > 50.0 * np.median(area)


# -- DEM ingestion -------------------------------------------------------


def test_dem_without_a_crs_is_refused(tmp_path):
    """An unreferenced raster cannot be placed on the Earth."""
    import rasterio
    from rasterio.transform import from_origin

    path = tmp_path / "nocrs.tif"
    with rasterio.open(path, "w", driver="GTiff", height=8, width=8, count=1,
                       dtype="float32",
                       transform=from_origin(0, 0, 1, 1)) as dst:
        dst.write(np.zeros((8, 8), dtype=np.float32), 1)
    with pytest.raises(dem.DEMError, match="declares no CRS"):
        dem.ingest(path)


def test_ingestion_crops_to_real_data(reference_dem):
    """Reprojection leaves empty corners; filling them fabricates terrain.

    Measured on the gate fixture: 10781 pixels, 7% of the raster, producing
    slopes to 84.9 degrees where p99 of the real data is 23.3.
    """
    path, _ = reference_dem
    cropped = dem.ingest(path, target_crs=UTM, ground_sample_distance_m=60.0)
    padded = dem.ingest(path, target_crs=UTM, ground_sample_distance_m=60.0,
                        crop_to_valid=False)
    assert cropped.provenance["voids_filled"] == 0
    assert cropped.provenance["pixels_cropped_as_outside_source"] > 0
    assert padded.provenance["voids_filled"] > 0
    assert cropped.slope_degrees().max() < padded.slope_degrees().max()


def test_ingested_elevations_match_the_source(reference_dem):
    import rasterio
    from pyproj import Transformer

    path, source = reference_dem
    field = dem.ingest(path, target_crs=UTM, ground_sample_distance_m=60.0)
    with rasterio.open(path) as src:
        to_utm = Transformer.from_crs(src.crs, UTM, always_xy=True)
        errors = []
        for r in range(20, source.shape[0] - 20, 17):
            for c in range(20, source.shape[1] - 20, 17):
                lon, lat = src.transform * (c + 0.5, r + 0.5)
                x, y = to_utm.transform(lon, lat)
                if field.contains(x, y):
                    errors.append(abs(field.elevation_at(x, y) - source[r, c]))
    gradient = np.abs(np.diff(source, axis=1)).mean()
    assert errors and max(errors) < 4.0 * gradient


# -- Landscape export ----------------------------------------------------


def test_z_scale_matches_the_documented_constant():
    """§6.3: Z_scale = relief_m * 100 * (1/512)."""
    assert landscape.z_scale_for(512.0) == pytest.approx(100.0)
    assert landscape.z_scale_for(1000.0) == pytest.approx(1000.0 * 100.0 / 512.0)


def test_landscape_resolutions_are_importable():
    for layout in landscape.valid_layouts(max_resolution=1024):
        assert (layout.resolution - 1) % layout.quads_per_section == 0
        assert layout.quads_per_section in landscape.VALID_QUADS_PER_SECTION


def test_landscape_round_trip_returns_the_same_metres(procedural, tmp_path):
    spec = landscape.export(procedural, tmp_path / "ls")
    result = landscape.verify_round_trip(procedural, spec)
    assert result["max_error_m"] < 4.0 * result["quantisation_m"]
    assert result["relief_error_m"] < 4.0 * result["quantisation_m"]


def test_non_square_raster_keeps_its_aspect_ratio(reference_dem, tmp_path):
    """A single scale for a non-square raster squashes the ground.

    Every elevation still reads back correctly, so this is a failure that looks
    like working terrain -- the gate fixture bakes to 294x434 and was being
    compressed by 1.47x.
    """
    path, _ = reference_dem
    field = dem.ingest(path, target_crs=UTM, ground_sample_distance_m=60.0)
    assert field.width != field.height
    spec = landscape.export(field, tmp_path / "ls")
    assert spec.scale_x != pytest.approx(spec.scale_y)
    source_aspect = (field.width - 1) / (field.height - 1)
    assert spec.scale_x / spec.scale_y == pytest.approx(source_aspect, rel=1e-9)


# -- ground callback and orographic coupling -----------------------------


def test_ground_writes_terrain_elevation_into_the_fdm(procedural):
    from core.fdm import FlightDynamics
    from core.fdm import units as u

    ground = TerrainGround(procedural)
    lon, lat = ground.centre_lonlat()
    fdm = FlightDynamics("B747")
    fdm.set_initial_conditions(
        {"h-sl-ft": u.m_to_ft(4000.0), "vc-kts": 250.0, "gamma-deg": 0.0,
         "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
         "lat-geod-deg": lat, "long-gc-deg": lon, "terrain-elevation-ft": 0.0}
    )
    written = ground.apply(fdm)
    reported = u.ft_to_m(fdm.props.get("position/terrain-elevation-asl-ft"))
    assert reported == pytest.approx(written, abs=0.01)
    assert written == pytest.approx(ground.elevation_at(lat, lon), abs=0.01)


def test_orographic_lift_runs_over_baked_terrain(procedural):
    """Closes the Phase 3 gap: the model no longer needs an analytic ridge."""
    from core.environment.terrain_field import OrographicWind

    terrain = terrain_field_from(procedural)
    provider = OrographicWind(terrain, 15.0, 180.0)
    extent_y = procedural.extent_m[1]
    samples = [provider.linear_updraught(n, 0.0)
               for n in np.linspace(-extent_y * 0.45, extent_y * 0.45, 61)]
    assert max(samples) > 0.05 and min(samples) < -0.05


def test_both_terrain_kinds_drive_orographic_lift_identically(procedural,
                                                              reference_dem):
    """The provider must not branch on which producer made the raster."""
    from core.environment.terrain_field import OrographicWind

    path, _ = reference_dem
    real = dem.ingest(path, target_crs=UTM, ground_sample_distance_m=60.0)
    for field in (real, procedural):
        provider = OrographicWind(terrain_field_from(field), 15.0, 180.0)
        assert math.isfinite(provider.linear_updraught(0.0, 0.0))
        assert 0.0 < provider.decay_height_m <= 1500.0


# The Gate 5 host-parity comparator used to be tested here, from the days when
# it was the only part of Gate 5 that could run. It now has a home of its own:
# tests/test_host_parity.py.


def test_phase9_bakes_are_pickable_and_their_table_matches_the_raster():
    """Every Phase 9 location with a bake on this machine: pick_scene
    selects it from its own origin, and the LLM prompt's terrain-elevation
    table entry matches the raster at that origin (measured, not typed)."""
    from pathlib import Path

    from core.nl.compiler import compile_prompt
    from core.nl.llm_compiler import LOCATION_TERRAIN_ELEVATION_M
    from core.terrain.glo30 import LOCATIONS
    from core.terrain.ground import TerrainGround
    from webapp.runs import REPO, pick_scene

    checked = 0
    for key in ("fuji", "everest", "grand_canyon", "flint_hills"):
        raster = REPO / "runs" / "terrain" / f"{key}.r16"
        if not raster.is_file():
            continue
        location = LOCATIONS[key]
        spec = compile_prompt("fly the 747 at 9000 m and 250 kt")
        spec.set("latitude", location.origin_lat, frm="test")
        spec.set("longitude", location.origin_lon, frm="test")
        scene = pick_scene(spec)
        assert scene["key"] == key, (key, scene["key"])
        ground = TerrainGround(Heightfield.read(raster.with_suffix("")))
        measured = ground.elevation_at(location.origin_lat,
                                       location.origin_lon)
        table = LOCATION_TERRAIN_ELEVATION_M[key]
        assert abs(measured - table) < 2.0, (key, measured, table)
        checked += 1
    if checked == 0:
        pytest.skip("no Phase 9 bakes on this machine")


def test_source_verification_is_slope_aware_not_loosened():
    """The verification gate excuses exactly the slope-proportional
    resampling regime (|grad h| x half-pixel per sample) and nothing else:
    flat ground still faces the original 30 m gate, and the mean gate that
    caught the out-of-coverage-zeros bake is untouched."""
    import inspect

    from core.terrain import glo30

    source = inspect.getsource(glo30.verify_against_source)
    assert 'report["p95_excess_m"] < 30.0' in source
    assert 'abs(report["mean_m"]) < 5.0' in source
    assert "pixel_size_m / 2.0" in source
