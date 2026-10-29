"""Unit tests for Water Protection Zones Processing Module (Step 2)."""

import json
from pathlib import Path
import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, MultiPolygon, Polygon, box

from src.processing.processor import (
    ProcessingResult,
    SchemaMismatchError,
    load_config,
    process_zones,
)

CONFIG_PATH = Path("config/wsg_config.json")
FIXTURES_DIR = Path("tests/fixtures")


@pytest.fixture
def config():
    return load_config(CONFIG_PATH)


def test_schema_mismatch_raises_error(config):
    # GeoDataFrame missing the required zone column
    bad_gdf = gpd.GeoDataFrame(
        [{"wsg_id": "SN-001", "some_other_col": "val"}],
        geometry=[box(830000, 5650000, 831000, 5651000)],
        crs="EPSG:25832",
    )

    with pytest.raises(SchemaMismatchError) as exc_info:
        process_zones(bad_gdf, config)

    err_msg = str(exc_info.value)
    assert "schutzzone" in err_msg
    assert "Available columns" in err_msg
    assert "some_other_col" in err_msg


def test_in_batch_duplicate_conflict_rejection(config):
    # Two features with same ID and conflicting attributes
    conflicting_gdf = gpd.GeoDataFrame(
        [
            {"wsg_id": "DUP-01", "schutzzone": "II", "notes": "Version A"},
            {"wsg_id": "DUP-01", "schutzzone": "III", "notes": "Version B"},
        ],
        geometry=[
            box(830000, 5650000, 831000, 5651000),
            box(830000, 5650000, 831500, 5651000),
        ],
        crs="EPSG:25832",
    )

    result = process_zones(conflicting_gdf, config)
    assert result.stats.accepted_rows == 0
    assert result.stats.rejected_rows == 2
    assert (
        result.stats.rejection_breakdown["ERR_DUPLICATE_ID_CONFLICT"] == 2
    )

    reasons = result.rejected["rejection_reason"].tolist()
    assert reasons == [
        "ERR_DUPLICATE_ID_CONFLICT",
        "ERR_DUPLICATE_ID_CONFLICT",
    ]


def test_identical_duplicate_collapse(config):
    # Two identical features with the same ID and same geometry/attributes
    identical_gdf = gpd.GeoDataFrame(
        [
            {"wsg_id": "IDENT-01", "schutzzone": "II", "notes": "Identical"},
            {"wsg_id": "IDENT-01", "schutzzone": "II", "notes": "Identical"},
        ],
        geometry=[
            box(830000, 5650000, 831000, 5651000),
            box(830000, 5650000, 831000, 5651000),
        ],
        crs="EPSG:25832",
    )

    result = process_zones(identical_gdf, config)
    assert result.stats.accepted_rows == 1
    assert result.stats.rejected_rows == 0
    assert result.accepted.iloc[0]["source_zone_id"] == "IDENT-01"


def test_missing_id_and_empty_geometry_rejection(config):
    test_gdf = gpd.GeoDataFrame(
        [
            {"wsg_id": None, "schutzzone": "I"},
            {"wsg_id": "   ", "schutzzone": "I"},
            {"wsg_id": "VALID-01", "schutzzone": "I"},
        ],
        geometry=[
            box(830000, 5650000, 831000, 5651000),
            box(830000, 5650000, 831000, 5651000),
            None,  # Empty / null geometry
        ],
        crs="EPSG:25832",
    )

    result = process_zones(test_gdf, config)
    assert result.stats.accepted_rows == 0
    assert result.stats.rejected_rows == 3
    assert result.stats.rejection_breakdown["ERR_MISSING_ID"] == 2
    assert result.stats.rejection_breakdown["ERR_EMPTY_GEOMETRY"] == 1


def test_invalid_geometry_repair_and_rejection(config):
    # 1. Repairable bowtie polygon
    bowtie = Polygon(
        [(0, 0), (100, 100), (0, 100), (100, 0), (0, 0)]
    )
    # 2. Unrepairable non-areal geometry (LineString passed as geom)
    line = LineString([(0, 0), (50, 50), (100, 100)])

    test_gdf = gpd.GeoDataFrame(
        [
            {"wsg_id": "REPAIR-01", "schutzzone": "II"},
            {"wsg_id": "COLLAPSE-02", "schutzzone": "II"},
        ],
        geometry=[bowtie, line],
        crs="EPSG:25832",
    )

    result = process_zones(test_gdf, config)
    assert result.stats.accepted_rows == 1
    assert result.stats.repaired_geometries == 1
    assert result.stats.repaired == 1
    assert result.stats.rejected_rows == 1
    assert (
        result.stats.rejection_breakdown["ERR_GEOMETRY_INVALID"] == 1
    )

    repaired_row = result.accepted.iloc[0]
    assert bool(repaired_row["geometry_repaired"]) is True
    repaired = repaired_row.geometry
    assert isinstance(repaired, MultiPolygon)
    assert repaired.is_valid


def test_zone_class_explicit_lookup_and_unknown(config):
    test_gdf = gpd.GeoDataFrame(
        [
            {"wsg_id": "Z1", "schutzzone": "I"},
            {"wsg_id": "Z2", "schutzzone": "IIIA"},
            {"wsg_id": "Z3", "schutzzone": "UNKNOWN_CUSTOM_CODE"},
        ],
        geometry=[
            box(830000, 5650000, 831000, 5651000),
            box(831000, 5650000, 832000, 5651000),
            box(832000, 5650000, 833000, 5651000),
        ],
        crs="EPSG:25832",
    )

    result = process_zones(test_gdf, config)
    assert result.stats.accepted_rows == 3
    assert result.stats.unmapped_zones == 1

    accepted = result.accepted.set_index("source_zone_id")
    assert accepted.loc["Z1", "zone_class"] == "ZONE_I"
    assert accepted.loc["Z2", "zone_class"] == "ZONE_IIIA"
    assert accepted.loc["Z3", "zone_class"] == "UNKNOWN"
    assert (
        accepted.loc["Z3", "raw_zone_code"] == "UNKNOWN_CUSTOM_CODE"
    )

    # Defaults
    assert (
        accepted["restriction_category"] == "not_published"
    ).all()
    assert (accepted["extraction_rate"] == "not_published").all()
    assert (accepted["state_code"] == "SN").all()


def test_full_processing_on_fixture_file(config):
    zones_gdf = gpd.read_file(FIXTURES_DIR / "zones_input.geojson")
    assert len(zones_gdf) == 9

    result = process_zones(zones_gdf, config)

    # 9 rows total:
    # - 2 rejected: SN-WSG-003 duplicate ID conflict
    # - 1 rejected: null ID
    # - 6 accepted (including repaired bowtie and unmapped code)
    assert result.stats.total_input_rows == 9
    assert result.stats.rejected_rows == 3
    assert result.stats.accepted_rows == 6
    assert result.stats.repaired_geometries == 1
    assert result.stats.unmapped_zones == 1

    assert (
        result.stats.rejection_breakdown["ERR_DUPLICATE_ID_CONFLICT"]
        == 2
    )
    assert result.stats.rejection_breakdown["ERR_MISSING_ID"] == 1

    # Check accepted rows
    accepted = result.accepted
    assert accepted.crs.to_epsg() == 25832
    for geom in accepted.geometry:
        assert isinstance(geom, MultiPolygon)
        assert geom.is_valid

    # Verify source_attributes JSON preservation
    for attrs_json in accepted["source_attributes"]:
        parsed = json.loads(attrs_json)
        assert isinstance(parsed, dict)
        assert "wsg_name" in parsed


def test_processing_reprojects_different_crs_fixture(config):
    gpkg_path = FIXTURES_DIR / "zones_epsg25833.gpkg"
    gdf_33 = gpd.read_file(gpkg_path)
    assert gdf_33.crs.to_epsg() == 25833

    result = process_zones(gdf_33, config)
    assert result.stats.accepted_rows == 1
    assert result.accepted.crs.to_epsg() == 25832

    geom = result.accepted.geometry.iloc[0]
    minx, miny, maxx, maxy = geom.bounds
    assert 831000.0 < minx < 832000.0
    assert 832000.0 < maxx < 833000.0
