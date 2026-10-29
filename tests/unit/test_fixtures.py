
import json
from pathlib import Path
import geopandas as gpd
import pytest
from shapely.geometry import MultiPolygon, Polygon

FIXTURES_DIR = Path("tests/fixtures")
CONFIG_PATH = Path("config/wsg_config.json")


def test_config_loads_and_has_required_keys():
    assert CONFIG_PATH.exists()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["layer_name"] == "sn_wsg_bestand"
    # Verify assumed markings
    assert config["id_column"]["name"] == "wsg_id"
    assert config["id_column"]["assumed"] is True
    assert config["zone_column"]["name"] == "schutzzone"
    assert config["zone_column"]["assumed"] is True
    assert "zone_lookup" in config
    assert config["zone_lookup"]["I"] == "ZONE_I"
    assert config["zone_lookup"]["II"] == "ZONE_II"
    assert config["zone_lookup"]["III"] == "ZONE_III"
    assert config["zone_lookup"]["IIIA"] == "ZONE_IIIA"
    assert config["zone_lookup"]["IIIB"] == "ZONE_IIIB"


def test_zones_fixture_properties_and_edge_cases():
    zones_path = FIXTURES_DIR / "zones_input.geojson"
    assert zones_path.exists()

    gdf = gpd.read_file(zones_path)
    assert len(gdf) == 9
    assert gdf.crs.to_epsg() == 25832

    # 1. Valid multipart polygon
    multipart_rows = gdf[gdf.geometry.geom_type == "MultiPolygon"]
    assert len(multipart_rows) == 1
    mp = multipart_rows.iloc[0]
    assert mp["wsg_id"] == "SN-WSG-001"
    assert mp.geometry.is_valid
    assert len(mp.geometry.geoms) == 2

    # 2. Invalid self-intersecting polygon
    invalid_rows = gdf[~gdf.geometry.is_valid]
    assert len(invalid_rows) == 1
    inv = invalid_rows.iloc[0]
    assert inv["wsg_id"] == "SN-WSG-002"
    assert not inv.geometry.is_valid

    # 3. In-batch duplicate source ID
    id_counts = gdf["wsg_id"].value_counts(dropna=False)
    assert id_counts["SN-WSG-003"] == 2

    # 4. Unmapped zone code
    unmapped = gdf[gdf["schutzzone"] == "IV_HISTORIC"]
    assert len(unmapped) == 1
    assert unmapped.iloc[0]["wsg_id"] == "SN-WSG-004"

    # 5. Missing / null source ID
    missing_id = gdf[gdf["wsg_id"].isna() | (gdf["wsg_id"] == "")]
    assert len(missing_id) == 1
    assert missing_id.iloc[0]["schutzzone"] == "I"

    # 6. Stacked zone II inside zone III
    outer_zone_iii = gdf[gdf["wsg_id"] == "SN-WSG-005"].iloc[0].geometry
    inner_zone_ii = gdf[gdf["wsg_id"] == "SN-WSG-006"].iloc[0].geometry
    assert outer_zone_iii.contains(inner_zone_ii)


def test_different_crs_fixture_reprojection():
    gpkg_path = FIXTURES_DIR / "zones_epsg25833.gpkg"
    assert gpkg_path.exists()

    gdf = gpd.read_file(gpkg_path)
    assert len(gdf) == 1
    # Check declared CRS read by GeoPandas / pyogrio
    assert gdf.crs.to_epsg() == 25833

    # Reproject to target EPSG:25832
    gdf_reprojected = gdf.to_crs("EPSG:25832")
    assert gdf_reprojected.crs.to_epsg() == 25832

    geom_25832 = gdf_reprojected.geometry.iloc[0]
    minx, miny, maxx, maxy = geom_25832.bounds

    # Transformed coordinates must land in expected Saxony range in EPSG:25832
    assert 831000.0 < minx < 832000.0
    assert 832000.0 < maxx < 833000.0
    assert 5651000.0 < miny < 5652500.0
    assert 5652500.0 < maxy < 5653500.0


def test_parcels_fixtures_geojson_and_gpkg():
    geojson_path = FIXTURES_DIR / "parcels_input.geojson"
    gpkg_path = FIXTURES_DIR / "parcels_input.gpkg"

    assert geojson_path.exists()
    assert gpkg_path.exists()

    gdf_json = gpd.read_file(geojson_path)
    gdf_gpkg = gpd.read_file(gpkg_path)

    assert len(gdf_json) == 6
    assert len(gdf_gpkg) == 6

    assert gdf_json.crs.to_epsg() == 25832
    assert gdf_gpkg.crs.to_epsg() == 25832

    expected_ids = {
        "PARCEL-01",
        "PARCEL-02",
        "PARCEL-03",
        "PARCEL-04",
        "PARCEL-05",
        "PARCEL-06",
    }
    assert set(gdf_json["parcel_id"]) == expected_ids
    assert set(gdf_gpkg["parcel_id"]) == expected_ids
    assert all(gdf_json.geometry.is_valid)
    assert all(gdf_gpkg.geometry.is_valid)

    for col in ["zone_i_m2", "zone_ii_m2", "zone_iii_m2", "outside_m2"]:
        assert col in gdf_gpkg.columns
        assert gdf_gpkg[col].isna().all()
