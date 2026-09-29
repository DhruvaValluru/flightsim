"""S3, the IR proxy (core/capture/thermal.py): Planck against
Stefan-Boltzmann, the recovery temperature, the cached ASTER rows and the
provenanced (synthetic) transmittance table refused by name when absent,
the proxy image on a synthetic bundle with its two null tests, the camera
field absent-canonical (every committed example keeps its digest), the
manifest's per-camera sensing.ir block with its records, the post-render
IR frames and the verifier's ir_proxy_declared on clean and corrupted
bundles, the catalogue and the VALIDITY 2.5 amendment. One real 2 s
headless capture exercises the capture command end to end."""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest

from core.capture import thermal as T
from core.messages import is_catalogued
from core.records import read_records
from core.scenario.camera import CameraSpec
from core.scenario.spec import ScenarioSpec

REPO = Path(__file__).resolve().parents[1]
IR = {"band": "LWIR", "thermal_table": "proxy_v1"}


# -- Planck, the bands, the recovery temperature -----------------------------------------

@pytest.mark.parametrize("temperature", [150.0, 200.0, 288.15, 500.0, 1000.0, 1500.0])
def test_the_planck_band_integral_over_0_1_to_1000_um_is_stefan_boltzmann_within_1_percent(temperature):
    check = T.stefan_boltzmann_check([temperature])[0]
    assert check["relative_error"] < T.PLANCK_INTEGRAL_TOL
    assert check["relative_error"] < 1e-4            # measured 4e-5 at 150 K, 5e-8 at 1500 K
    assert T.PLANCK_INTEGRAL_TOL == 0.01 and T.SB_RANGE_UM == (0.1, 1000.0)


def test_sigma_is_formed_from_the_si_constants_and_is_codata_s():
    assert T.STEFAN_BOLTZMANN == pytest.approx(5.670374419e-8, rel=1e-9)
    assert T.C2 == pytest.approx(1.438776877e-2, rel=1e-9)


def test_the_bands_are_lwir_8_12_and_mwir_3_5_and_the_integral_is_additive():
    assert T.BANDS_UM == {"LWIR": (8.0, 12.0), "MWIR": (3.0, 5.0)}
    parts = sum(T.band_integral(300.0, b) for b in ((3.0, 5.0), (5.0, 8.0), (8.0, 12.0)))
    assert parts == pytest.approx(T.band_integral(300.0, (3.0, 12.0)), rel=1e-6)
    # An array of temperatures keeps its shape and matches the scalar path.
    many = T.band_integral(np.array([[250.0, 300.0]]), (8.0, 12.0))
    assert many.shape == (1, 2) and many[0, 1] == pytest.approx(T.band_integral(300.0, (8.0, 12.0)))


def test_the_skin_temperature_is_the_recovery_temperature_with_r_0_89_by_hand():
    assert T.RECOVERY_FACTOR == 0.89 and T.GAMMA_AIR == 1.4
    assert T.skin_temperature(250.0, 0.8) == pytest.approx(250.0 * (1.0 + 0.89 * 0.2 * 0.64), rel=1e-12)
    assert T.skin_temperature(250.0, 0.0) == 250.0
    for bad in (float("nan"), -0.1, True):
        with pytest.raises(T.ThermalError) as info:
            T.skin_temperature(250.0, bad)
        assert info.value.constraint == "sensing.ir_state"


def test_the_near_surface_air_follows_p1_s_standard_lapse_and_the_sky_names_its_model():
    # 1500 m above the ground: 6.5 K/km x 1.5 km warmer at the ground.
    assert T.near_surface_air_temperature(278.4, 1500.0, 0.0) == pytest.approx(278.4 + 9.75, abs=0.02)
    dry = T.sky_downwelling((8.0, 12.0), 288.15, 0.0)
    wet = T.sky_downwelling((8.0, 12.0), 288.15, 1500.0)
    assert dry["model"] == "swinbank_1963" and wet["model"] == "brutsaert_1975"
    assert dry["effective_emissivity"] == pytest.approx(5.31e-13 * 288.15 ** 2 / T.STEFAN_BOLTZMANN)
    assert wet["effective_emissivity"] == pytest.approx(1.24 * (15.0 / 288.15) ** (1.0 / 7.0))
    assert wet["radiance_w_m2_sr"] == pytest.approx(
        wet["effective_emissivity"] * T.band_integral(288.15, (8.0, 12.0)))


# -- the cached tables and their refusals ----------------------------------------------------

def test_the_emissivity_rows_are_cached_with_sidecars_and_provenance_and_give_band_emissivities():
    table = T.load_thermal_table()
    assert len(table.rows) == 9
    provenance = json.loads((T.EMISSIVITY_DIR / T.EMISSIVITY_PROVENANCE).read_text(encoding="utf-8"))
    recorded = {r["file"]: r["sha256"] for r in provenance["rows"]}
    for name, row in table.rows.items():
        assert recorded[name] == row.sha256 == hashlib.sha256(Path(row.path).read_bytes()).hexdigest()
    by_word = {w: table.rows[c["emissivity_row"]] for w, c in table.classes.items() if c["emissivity_row"]}
    lwir = {w: T.band_emissivity(r, T.BANDS_UM["LWIR"], 288.15) for w, r in by_word.items()}
    assert lwir["aircraft_skin"] == pytest.approx(0.050, abs=0.005)     # bare aluminium
    assert lwir["valley"] == pytest.approx(0.981, abs=0.005)            # green grass
    assert lwir["snow"] == pytest.approx(0.995, abs=0.005)
    assert all(0.0 <= e <= 1.0 for e in lwir.values())


def _copy_assets(tmp_path):
    thermal = tmp_path / "thermal"
    emissivity = tmp_path / "emissivity"
    shutil.copytree(T.THERMAL_DIR, thermal)
    shutil.copytree(T.EMISSIVITY_DIR, emissivity)
    return thermal, emissivity


def test_an_absent_or_altered_emissivity_row_refuses_sensing_ir_table(tmp_path):
    thermal, emissivity = _copy_assets(tmp_path)
    grass = "jhu.becknic.vegetation.grass.green.solid.gras.spectrum.txt"
    (emissivity / grass).unlink()
    with pytest.raises(T.ThermalError) as info:
        T.load_thermal_table("proxy_v1", thermal, emissivity)
    assert info.value.constraint == "sensing.ir_table" and "absent" in info.value.message
    shutil.copy(T.EMISSIVITY_DIR / grass, emissivity / grass)
    with open(emissivity / grass, "ab") as handle:
        handle.write(b"14.5 1.0\n")
    with pytest.raises(T.ThermalError) as info:
        T.load_thermal_table("proxy_v1", thermal, emissivity)
    assert info.value.constraint == "sensing.ir_table" and "digests" in info.value.message


@pytest.mark.parametrize("edit, fragment", [
    (lambda d: d.update(proxy=False), "proxy: true"),
    (lambda d: d.update(source=""), "cites no source"),
    (lambda d: d.update(bands=["SWIR"]), "not among"),
    (lambda d: d["classes"]["rock"].update(temperature_model="guessed"), "temperature model"),
    (lambda d: d.update(terrain_default="lava"), "not one of its classes"),
])
def test_a_malformed_thermal_table_refuses_sensing_ir_table(tmp_path, edit, fragment):
    thermal, emissivity = _copy_assets(tmp_path)
    data = json.loads((thermal / "proxy_v1.json").read_text(encoding="utf-8"))
    edit(data)
    (thermal / "proxy_v1.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(T.ThermalError) as info:
        T.load_thermal_table("proxy_v1", thermal, emissivity)
    assert info.value.constraint == "sensing.ir_table" and fragment in info.value.message


def test_the_ir_request_is_band_and_table_and_refuses_by_name():
    assert T.ir_request_problem(IR) is None
    assert T.ir_request_problem({"band": "MWIR", "thermal_table": "proxy_v1"}) is None
    for bad in ({"band": "SWIR", "thermal_table": "proxy_v1"}, {"band": "LWIR"},
                {"band": "LWIR", "thermal_table": "nowhere"}, "LWIR"):
        assert T.ir_request_problem(bad).constraint == "sensing.ir_table", bad


def test_the_shipped_transmittance_table_is_synthetic_and_reproduces_its_stated_formula():
    table = T.load_transmittance("transmittance_synthetic")
    assert table.synthetic is True and "SYNTHETIC" in table.source
    k = table.provenance["generator"]["k_per_km"]
    for band in ("LWIR", "MWIR"):
        for r, tau in zip(table.range_m, table.tau[band]):
            assert tau == pytest.approx(math.exp(-k[band] * r / 1000.0), abs=5e-7)
    # Interpolated inside, NaN beyond the last row or before 0 -- never extrapolated.
    assert table.at("LWIR", 5.0) == pytest.approx(0.9995)
    assert math.isnan(table.at("LWIR", 100000.5)) and math.isnan(table.at("LWIR", -1.0))
    assert math.isnan(table.at("LWIR", float("inf")))


@pytest.mark.parametrize("damage, fragment", [
    ("absent", "absent"),
    ("sidecar", "digests"),
    ("provenance", "no provenance"),
    ("tau0", "tau(0 m) = 1"),
    ("unstated", "source and whether"),
])
def test_a_transmittance_table_without_provenance_or_intact_bytes_refuses_sensing_ir_transmittance(
        tmp_path, damage, fragment):
    thermal, _ = _copy_assets(tmp_path)
    csv = thermal / "transmittance_synthetic.csv"
    provenance = thermal / "transmittance_synthetic.provenance.json"
    if damage == "absent":
        csv.unlink()
    elif damage == "sidecar":
        csv.write_bytes(csv.read_bytes().replace(b"0,1.000000,1.000000", b"0,1.000000,0.999999"))
    elif damage == "provenance":
        provenance.unlink()
    elif damage in ("tau0", "unstated"):
        if damage == "tau0":
            data = csv.read_bytes().replace(b"0,1.000000,1.000000", b"0,0.990000,1.000000")
            csv.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            (thermal / "transmittance_synthetic.csv.sha256").write_text(f"{digest}  x\n", encoding="utf-8")
            document = json.loads(provenance.read_text(encoding="utf-8"))
            document["sha256"] = digest
        else:
            document = json.loads(provenance.read_text(encoding="utf-8"))
            del document["synthetic"]
        provenance.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(T.ThermalError) as info:
        T.load_transmittance("transmittance_synthetic", thermal)
    assert info.value.constraint == "sensing.ir_transmittance" and fragment in info.value.message


# -- the proxy image on a synthetic bundle --------------------------------------------------

def _bundle():
    """A 3 x 8 frame: row 0 sky, row 1 aircraft skin, row 2 terrain,
    each at ranges 0 .. 100 km; objects aircraft (1) and terrain (2)."""
    table = T.load_thermal_table()
    tau = T.load_transmittance(table.transmittance)
    ranges = np.array([0.0, 100.0, 1000.0, 5000.0, 10000.0, 20000.0, 50000.0, 100000.0])
    mask = np.array([[0] * 8, [1] * 8, [2] * 8], dtype=np.uint8)
    depth = np.vstack([np.full(8, np.inf), ranges, ranges])
    objects = [{"int_id": 1, "class": "aircraft"}, {"int_id": 2, "class": "terrain"}]
    return table, tau, mask, depth, objects


def test_the_proxy_is_the_stated_equation_and_the_eps_1_null_is_the_planck_map():
    table, tau, mask, depth, objects = _bundle()
    image, basis = T.class_image(mask, depth, objects, table)
    assert (image[0] == T.SKY).all() and "default 'valley'" in basis["surface"]
    assert (image[1] == table.words.index("aircraft_skin")).all()
    assert (image[2] == table.words.index("valley")).all()
    temps, eps = T.class_values(table, "LWIR", skin_k=260.0, ground_air_k=288.0)
    assert temps["engine"] is None and eps["engine"] is None and temps["snow"] == 273.15
    sky = T.sky_downwelling(T.BANDS_UM["LWIR"], 288.0, 0.0)["radiance_w_m2_sr"]
    L, pixels = T.proxy_radiance(image, depth, table, tau, "LWIR", temps, eps, 250.0, sky)
    assert (L[0] == sky).all() and pixels["sky_px"] == 8 and pixels["beyond_table_px"] == 0
    b_skin, b_air = T.band_integral(260.0, (8, 12)), T.band_integral(250.0, (8, 12))
    t = tau.at("LWIR", depth[1])
    e = eps["aircraft_skin"]
    assert np.allclose(L[1], t * (e * b_skin + (1 - e) * sky) + (1 - t) * b_air, rtol=1e-12)
    planck, _ = T.proxy_radiance(image, depth, table, tau, "LWIR", temps, eps, 250.0, sky,
                                 tau_one=True, eps_one=True)
    assert np.array_equal(planck[1], np.full(8, b_skin))                      # bit for bit
    assert np.array_equal(planck[2], np.full(8, T.band_integral(288.0, (8, 12))))


def test_tau_1_against_tau_r_the_difference_grows_with_range():
    table, tau, mask, depth, objects = _bundle()
    image, _ = T.class_image(mask, depth, objects, table)
    temps, eps = T.class_values(table, "LWIR", skin_k=260.0, ground_air_k=288.0)
    sky = T.sky_downwelling(T.BANDS_UM["LWIR"], 288.0, 0.0)["radiance_w_m2_sr"]
    with_tau, _ = T.proxy_radiance(image, depth, table, tau, "LWIR", temps, eps, 250.0, sky)
    without, _ = T.proxy_radiance(image, depth, table, tau, "LWIR", temps, eps, 250.0, sky, tau_one=True)
    for row in (1, 2):
        difference = np.abs(with_tau[row] - without[row])
        assert difference[0] == 0.0 and np.all(np.diff(difference) > 0.0), difference


def test_land_cover_and_the_palette_pick_the_surface_class_and_water_is_unmodelled():
    table, tau, mask, depth, objects = _bundle()
    codes = np.full(mask.shape, 70)
    codes[2, :4] = 80                                    # water: no row, unmodelled
    image, basis = T.class_image(mask, depth, objects, table, landcover_codes=codes)
    assert "land cover" in basis["surface"]
    assert (image[2, 4:] == table.words.index("snow")).all()
    temps, eps = T.class_values(table, "LWIR", skin_k=260.0, ground_air_k=288.0)
    L, pixels = T.proxy_radiance(image, depth, table, tau, "LWIR", temps, eps, 250.0, 20.0)
    assert np.isnan(L[2, :4]).all() and pixels["unmodelled_class_px"] == {"water": 4}
    rgb = np.zeros(mask.shape + (3,))
    rgb[2] = table.palette["rock"]
    image, basis = T.class_image(mask, depth, objects, table, basecolor_rgb=rgb)
    assert "palette" in basis["surface"] and (image[2] == table.words.index("rock")).all()


def test_depth_is_turned_into_range_along_each_pixel_s_ray():
    depth = np.full((2, 2), 100.0)
    r = T.range_from_depth(depth, 1.0, 1.0, 1.0, 1.0)
    assert r[0, 0] == pytest.approx(100.0 * math.sqrt(1.0 + 0.25 + 0.25))


# -- the camera field -------------------------------------------------------------------------

def test_the_ir_field_is_absent_canonical_and_every_example_keeps_its_digest():
    from tests.test_registry import EXAMPLE_DIGESTS

    camera = CameraSpec.defaulted(camera_id="c0", preset="chase", aircraft="c172p")
    assert not camera.ir_stated() and "ir" not in camera.to_dict()
    assert CameraSpec.from_dict(camera.to_dict()).to_dict() == camera.to_dict()
    camera.set("ir", dict(IR), frm="test")
    assert camera.ir_stated() and camera.to_dict()["ir"]["value"] == IR
    again = CameraSpec.from_dict(json.loads(json.dumps(camera.to_dict())))
    assert again.ir.value == IR and again.to_dict() == camera.to_dict()
    for path, digest in EXAMPLE_DIGESTS.items():
        assert ScenarioSpec.read(REPO / path).digest() == digest, path


def test_the_validator_refuses_a_bad_ir_request_by_name():
    from core.capture.validate import validate_cameras
    from core.nl.compiler import compile_prompt

    spec = compile_prompt("fly the c172p at 1500 m and 100 kt for 2 seconds")
    camera = CameraSpec.defaulted(camera_id="c0", preset="chase", aircraft="c172p")
    spec.cameras = [camera]
    assert not [v for v in validate_cameras(spec) if v.constraint.startswith("sensing.ir")]
    camera.set("ir", {"band": "SWIR", "thermal_table": "proxy_v1"}, frm="test")
    assert [v.constraint for v in validate_cameras(spec)] == ["sensing.ir_table"]


# -- the manifest, the records, the frames, the verifier ---------------------------------------

def _manifest(ir=True):
    from core.capture.manifest import build_capture_manifest
    from core.capture.poses import solve_pose_track
    from core.capture.schedule import solve_schedule
    from tests.test_camera_manifest import spec_with_cameras
    from tests.test_camera_poses import FRAME, make_columns

    spec = spec_with_cameras()
    if ir:
        spec.cameras[0].set("ir", dict(IR), frm="test")
    columns = make_columns(duration_s=10.0)
    n = len(columns["t"])
    columns["mach"] = [0.8] * n
    columns["temperature_k"] = [250.0] * n
    columns["vapour_pressure_pa"] = [0.0] * n
    tracks = [solve_pose_track(columns, c, FRAME) for c in spec.cameras]
    schedules = [solve_schedule(columns, c, FRAME) for c in spec.cameras]
    return build_capture_manifest(spec, columns, FRAME, tracks, schedules,
                                  output_digest="0" * 64, scene={"key": "flat", "terrain": None})


def test_the_manifest_carries_sensing_ir_frame_keys_and_two_records_with_measured_nulls():
    manifest = _manifest()
    blocks = {c["camera_id"]: c for c in manifest["cameras"]}
    ir = blocks["chase0"]["sensing"]["ir"]
    assert blocks["chase0"]["sensing"]["requested_by"] == ["camera.ir"]
    assert "sensing" not in blocks["tower0"]
    assert ir["proxy"] is True and ir["band"] == "LWIR" and ir["band_um"] == [8.0, 12.0]
    assert ir["transmittance"]["synthetic"] is True
    assert set(ir["tables_sha256"]) == {"thermal_table", "transmittance"} | {
        f"emissivity:{f}" for f in ir["emissivity_rows"]}
    skin = 250.0 * (1.0 + 0.89 * 0.2 * 0.64)
    assert ir["reference_frame"]["t_skin_k"] == pytest.approx(skin)
    assert ir["planck_check"]["relative_error"] < 0.01
    cg = ir["reference_frame"]["cg_range_m"]
    assert ir["reference_frame"]["tau_cg"] == pytest.approx(
        T.load_transmittance("transmittance_synthetic").at("LWIR", cg))
    for frame in manifest["frames"]:
        if frame["camera_id"] == "chase0":
            assert frame["ir"]["proxy"] is True and frame["ir"]["file"] is None
            assert frame["ir"]["t_skin_k"] == pytest.approx(skin)
        else:
            assert "ir" not in frame
    records = {r["name"]: r for r in read_records(manifest["applied_variables"])}
    for name in ("sensing.ir", "sensing.ir_transmittance"):
        assert records[name]["null_test"]["ok"] is True, records[name]["null_test"]
        assert records[name]["readback"]["agrees"] is True
        assert records[name]["parameters"]["proxy"] is True
    assert records["sensing.ir"]["value"] == pytest.approx(skin)
    assert records["sensing.ir"]["null_test"]["kind"] == "bounded"
    assert records["sensing.ir"]["null_test"]["with"] == 0.0
    assert records["sensing.ir_transmittance"]["null_test"]["kind"] == "reached"
    assert records["sensing.ir_transmittance"]["parameters"]["grows_with_range"] is True


def test_a_manifest_without_an_ir_request_carries_no_ir_key_or_record():
    manifest = _manifest(ir=False)
    assert all("sensing" not in c for c in manifest["cameras"])
    assert all("ir" not in f for f in manifest["frames"])
    names = [r["name"] for r in read_records(manifest["applied_variables"])]
    assert not [n for n in names if n.startswith("sensing.ir")]


def _render_bundle(tmp_path, manifest, frames=2):
    """A synthetic render bundle for chase0's first ``frames`` frames:
    a 40 x 30 ID image (sky above, aircraft in the middle, terrain
    below) and a planar depth."""
    from PIL import Image

    folder = tmp_path / "frames" / "chase0"
    folder.mkdir(parents=True)
    ids = {o["class"]: o["int_id"] for o in manifest["objects"]}
    records = []
    own = [f for f in manifest["frames"] if f["camera_id"] == "chase0"][:frames]
    for frame in own:
        frame.update(width_px=40, height_px=30, fx_px=40.0, fy_px=40.0, principal_point_px=[20.0, 15.0])
        stem = Path(frame["file"]).stem
        mask = np.zeros((30, 40), dtype=np.uint8)
        mask[12:18, 15:25] = ids["aircraft"]
        mask[20:, :] = ids["terrain"]
        depth = np.full((30, 40), np.inf, dtype="<f4")
        depth[12:18, 15:25] = 120.0
        depth[20:, :] = np.linspace(300.0, 5000.0, 10)[:, None]
        Image.fromarray(mask).save(folder / f"{stem}_mask.png")
        depth.tofile(folder / f"{stem}_depth.f32")
        records.append({"frame": Path(frame["file"]).name,
                        "labels": {"mask": f"{stem}_mask.png", "depth_f32": f"{stem}_depth.f32"}})
    (folder / "render.json").write_text(json.dumps({"frame_records": records}), encoding="utf-8")
    return folder


def test_the_ir_frames_are_written_declared_and_pass_ir_proxy_declared(tmp_path):
    from core.capture.verify import verify_ir_proxy_declared

    manifest = _manifest()
    assert verify_ir_proxy_declared(manifest, None).status == "NOT RUN"
    assert verify_ir_proxy_declared(manifest, tmp_path).status == "NOT RUN"
    folder = _render_bundle(tmp_path, manifest)
    summary = T.render_ir_frames(tmp_path, manifest)
    assert summary["cameras"] == 1 and summary["written"] == 2 and summary["without_bundle"] >= 1
    image = np.fromfile(folder / "frame_0000_ir.f32", dtype="<f4").reshape(30, 40)
    declaration = json.loads((folder / "frame_0000_ir.json").read_text(encoding="utf-8"))
    assert declaration["proxy"] is True and declaration["pixels"]["sky_px"] == 40 * 30 - 60 - 400
    sky = declaration["sky"]["radiance_w_m2_sr"]
    assert image[0, 0] == pytest.approx(sky, rel=1e-6) and np.isfinite(image).all()
    assert manifest["frames"][0]["ir"]["file"] == "frame_0000_ir.f32"
    assert (tmp_path / declaration["preview"]["file"]).is_file()          # the human clause's image
    check = verify_ir_proxy_declared(manifest, tmp_path)
    assert check.status == "PASS", check.detail


@pytest.mark.parametrize("corrupt, fragment", [
    ("undeclared", "no readable proxy declaration"),
    ("not_proxy", "proxy: true"),
    ("table_sha", "differ from the manifest's (transmittance)"),
    ("band", "declared band"),
    ("image", "sha256 or size"),
    ("no_block", "declares no sensing.ir block"),
])
def test_a_frame_without_its_proxy_declaration_or_with_foreign_tables_fails_annotation_ir_proxy(
        tmp_path, corrupt, fragment):
    from core.capture.verify import verify_ir_proxy_declared

    manifest = _manifest()
    folder = _render_bundle(tmp_path, manifest, frames=1)
    T.render_ir_frames(tmp_path, manifest)
    path = folder / "frame_0000_ir.json"
    declaration = json.loads(path.read_text(encoding="utf-8"))
    if corrupt == "undeclared":
        path.unlink()
    elif corrupt == "not_proxy":
        declaration["proxy"] = False
    elif corrupt == "table_sha":
        declaration["tables_sha256"]["transmittance"] = "0" * 64
    elif corrupt == "band":
        declaration["band"] = "MWIR"
    elif corrupt == "image":
        with open(folder / "frame_0000_ir.f32", "ab") as handle:
            handle.write(b"\0\0\0\0")
    elif corrupt == "no_block":
        del manifest["cameras"][0]["sensing"]["ir"]
    if corrupt in ("not_proxy", "table_sha", "band"):
        path.write_text(json.dumps(declaration), encoding="utf-8")
    check = verify_ir_proxy_declared(manifest, tmp_path)
    assert check.status == "FAIL" and check.failure == "annotation.ir_proxy"
    assert fragment in check.detail, check.detail


def test_the_verifier_check_imports_nothing_from_the_producer():
    from core.capture import verify

    source = inspect.getsource(verify.verify_ir_proxy_declared)
    assert "import" not in source and "thermal" not in source.split('"""')[2]
    assert 'run("ir_proxy_declared", verify_ir_proxy_declared, manifest, run_dir)' in inspect.getsource(verify)


def test_the_names_are_catalogued_and_the_registry_carries_the_two_observers():
    from core.registry import NO_NULL, REGISTRY

    for name in ("sensing.ir_table", "sensing.ir_transmittance", "sensing.ir_state",
                 "annotation.ir_proxy", "check.ir_proxy_declared"):
        assert is_catalogued(name), name
    for name in ("sensing.ir", "sensing.ir_transmittance"):
        entry = REGISTRY.get(name)
        assert entry.spec_path is None and entry.null_value is NO_NULL and entry.null_basis


def test_validity_2_5_is_amended_and_still_stands():
    text = (REPO / "docs/VALIDITY.md").read_text(encoding="utf-8")
    section = text[text.index("### 2.5 No EO/IR sensor fidelity exists"):]
    section = " ".join(section[:section.index("\n---")].split())
    for phrase in ("still stands", "**no heat balance**", "**no plume**", "**no sub-object temperatures**",
                   "**no validation**", "**user-provided transmittance table**", "synthetic",
                   "IR preview of one real render inspected once"):
        assert phrase in section, phrase


def test_every_file_the_item_ships_is_ascii():
    for path in [T.THERMAL_DIR / "proxy_v1.json", T.THERMAL_DIR / "README.md",
                 T.THERMAL_DIR / "transmittance_synthetic.csv", T.EMISSIVITY_DIR / "README.md",
                 REPO / "core/capture/thermal.py", *T.EMISSIVITY_DIR.glob("*.txt")]:
        path.read_bytes().decode("ascii")


# -- one real headless capture --------------------------------------------------------------

def test_a_headless_capture_with_an_ir_camera_writes_the_block_and_the_check_is_not_run(tmp_path):
    from core.capture.verify import verify_ir_proxy_declared
    from core.nl.compiler import compile_prompt
    from flightsim.capture import main as capture_main

    spec = compile_prompt("fly the c172p at 1500 m and 100 kt for 2 seconds")
    spec.set("hold_state", False, frm="test")
    camera = CameraSpec.defaulted(camera_id="chase0", preset="chase", aircraft="c172p")
    camera.set("ir", dict(IR), frm="test")
    spec.cameras = [camera]
    spec.write(tmp_path / "spec.yaml")
    assert capture_main([str(tmp_path / "spec.yaml"), "--out", str(tmp_path / "run"),
                         "--max-previews", "0"]) == 0
    manifest = json.loads((tmp_path / "run" / "capture_manifest.json").read_text(encoding="utf-8"))
    ir = manifest["cameras"][0]["sensing"]["ir"]
    ref = ir["reference_frame"]
    assert ir["proxy"] is True and 0.1 < ref["mach"] < 0.3
    assert ref["t_skin_k"] == pytest.approx(ref["air_temperature_k"] * (1 + 0.178 * ref["mach"] ** 2))
    assert ir["sky"]["model"] == "swinbank_1963"          # JSBSim's standard day is dry
    names = [r["name"] for r in read_records(manifest["applied_variables"])]
    assert "sensing.ir" in names and "sensing.ir_transmittance" in names
    assert verify_ir_proxy_declared(manifest, tmp_path / "run").status == "NOT RUN"
