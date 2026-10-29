"""Integration tests for PostGIS Idempotent Loader (Step 3).

Verifies against live PostGIS container:
(a) Load fixture twice -> row count unchanged, 2nd run has rows_unchanged == 4.
(b) Load modified copy -> only changed row is updated, count unchanged.
(c) Rejected rows are never in the table; exact accepted vs rejected rows verified.
(d) Every stored geometry is valid and has SRID 25832.
(e) Run log table records execution metadata per run.
"""

import json
from pathlib import Path
import geopandas as gpd
import pytest
from sqlalchemy import text

from src.load.loader import get_db_url, get_engine, init_db, upsert_zones
from src.processing.processor import load_config, process_zones

CONFIG_PATH = Path("config/wsg_config.json")
FIXTURES_DIR = Path("tests/fixtures")


@pytest.fixture(scope="session")
def engine():
    eng = get_engine()
    init_db(eng)
    return eng


@pytest.fixture(scope="session")
def config():
    return load_config(CONFIG_PATH)


@pytest.fixture(autouse=True)
def clean_tables(engine):
    """Truncate staging tables before and after each test."""
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE iris_staging.water_protection_zones RESTART IDENTITY CASCADE;"))
        conn.execute(text("TRUNCATE TABLE iris_staging.water_protection_runs RESTART IDENTITY CASCADE;"))
    yield
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE iris_staging.water_protection_zones RESTART IDENTITY CASCADE;"))
        conn.execute(text("TRUNCATE TABLE iris_staging.water_protection_runs RESTART IDENTITY CASCADE;"))


def test_idempotent_double_load(engine, config):
    """(a) Load the fixture twice, row count unchanged; unchanged rows skipped."""
    batch_gdf = gpd.read_file(FIXTURES_DIR / "zones_clean_batch.gpkg")
    assert len(batch_gdf) == 4

    result = process_zones(batch_gdf, config)
    assert result.stats.accepted_rows == 4
    assert result.stats.rejected_rows == 0

    # First load: 4 rows inserted
    load1 = upsert_zones(engine, result.accepted)
    assert load1.rows_processed == 4
    assert load1.rows_inserted == 4
    assert load1.rows_updated == 0
    assert load1.rows_unchanged == 0
    assert load1.total_table_rows == 4

    # Second load with identical data: 0 inserted, 0 updated, 4 unchanged
    load2 = upsert_zones(engine, result.accepted)
    assert load2.rows_processed == 4
    assert load2.rows_inserted == 0
    assert load2.rows_updated == 0
    assert load2.rows_unchanged == 4
    # Critical assertion: row count strictly unchanged
    assert load2.total_table_rows == 4

    # Verify run log table has 2 recorded runs
    with engine.connect() as conn:
        runs = conn.execute(
            text("SELECT records_loaded, records_updated, records_unchanged, status FROM iris_staging.water_protection_runs ORDER BY started_at")
        ).fetchall()
        assert len(runs) == 2
        assert runs[0] == (4, 0, 0, "COMPLETED")
        assert runs[1] == (0, 0, 4, "COMPLETED")


def test_modified_load_updates_row_and_count_unchanged(engine, config):
    """(b) Load a modified copy: only the changed row is updated, unchanged rows skipped, count unchanged."""
    batch_gdf = gpd.read_file(FIXTURES_DIR / "zones_clean_batch.gpkg")
    result1 = process_zones(batch_gdf, config)
    upsert_zones(engine, result1.accepted)

    # Load modified revision where SN-WSG-007 is updated (the other 3 rows are identical)
    updated_gdf = gpd.read_file(FIXTURES_DIR / "zones_clean_batch_updated.gpkg")
    result2 = process_zones(updated_gdf, config)
    load_updated = upsert_zones(engine, result2.accepted)

    assert load_updated.rows_processed == 4
    assert load_updated.rows_inserted == 0
    assert load_updated.rows_updated == 1     # Only SN-WSG-007 updated
    assert load_updated.rows_unchanged == 3   # The remaining 3 skipped
    assert load_updated.total_table_rows == 4

    # Verify that SN-WSG-007 reflects updated attributes and geometry in the database
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT source_attributes, ST_AsText(geom) FROM iris_staging.water_protection_zones "
                "WHERE source_zone_id = 'SN-WSG-007'"
            )
        ).fetchone()

        attrs = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        assert "Updated Revision" in attrs["wsg_name"]
        assert "836100" in row[1]


def test_rejected_rows_are_never_in_table(engine, config):
    """(c) Rejected rows are never in the table; exact breakdown of 9 fixture rows verified."""
    full_gdf = gpd.read_file(FIXTURES_DIR / "zones_input.geojson")
    assert len(full_gdf) == 9

    result = process_zones(full_gdf, config)
    # Exact breakdown of the 9 fixture rows:
    # ACCEPTED (6):
    # - SN-WSG-001 (Multipart)
    # - SN-WSG-002 (Bowtie repaired)
    # - SN-WSG-004 (Unmapped code -> UNKNOWN)
    # - SN-WSG-005 (Outer Zone III)
    # - SN-WSG-006 (Inner Zone II)
    # - SN-WSG-007 (Zone I)
    # REJECTED (3):
    # - SN-WSG-003 Version A (ERR_DUPLICATE_ID_CONFLICT)
    # - SN-WSG-003 Version B (ERR_DUPLICATE_ID_CONFLICT)
    # - Missing ID (ERR_MISSING_ID)
    assert result.stats.rejected_rows == 3
    assert result.stats.accepted_rows == 6

    load = upsert_zones(
        engine,
        result.accepted,
        records_input=result.stats.total_input_rows,
        records_rejected=result.stats.rejected_rows,
    )
    assert load.rows_inserted == 6
    assert load.total_table_rows == 6

    with engine.connect() as conn:
        # 1. Conflicting duplicate ID SN-WSG-003 must not exist
        res_dup = conn.execute(
            text("SELECT COUNT(*) FROM iris_staging.water_protection_zones WHERE source_zone_id = 'SN-WSG-003'")
        ).scalar()
        assert res_dup == 0

        # 2. No null or blank IDs must exist
        res_null = conn.execute(
            text("SELECT COUNT(*) FROM iris_staging.water_protection_zones WHERE source_zone_id IS NULL OR TRIM(source_zone_id) = ''")
        ).scalar()
        assert res_null == 0

        # 3. Exactly the 6 accepted source_zone_ids exist
        loaded_ids = set(
            conn.execute(
                text("SELECT source_zone_id FROM iris_staging.water_protection_zones")
            ).scalars().all()
        )
        expected_ids = {"SN-WSG-001", "SN-WSG-002", "SN-WSG-004", "SN-WSG-005", "SN-WSG-006", "SN-WSG-007"}
        assert loaded_ids == expected_ids


def test_stored_geometries_are_valid_and_srid_25832(engine, config):
    """(d) Every stored geometry is valid and has SRID 25832."""
    full_gdf = gpd.read_file(FIXTURES_DIR / "zones_input.geojson")
    result = process_zones(full_gdf, config)
    upsert_zones(engine, result.accepted)

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT source_zone_id, ST_IsValid(geom) AS is_valid, ST_SRID(geom) AS srid, "
                "GeometryType(geom) AS geom_type, ST_Area(geom) AS area, source_url "
                "FROM iris_staging.water_protection_zones"
            )
        ).fetchall()

        assert len(rows) == 6
        for r in rows:
            zone_id, is_valid, srid, geom_type, area, source_url = r
            assert is_valid is True, f"Geometry for {zone_id} is not valid"
            assert srid == 25832, f"Geometry for {zone_id} has SRID {srid}, expected 25832"
            assert geom_type == "MULTIPOLYGON", f"Geometry for {zone_id} has type {geom_type}, expected MULTIPOLYGON"
            assert area > 0, f"Geometry for {zone_id} has area {area}, expected > 0"
            assert source_url.startswith("fixture:"), f"source_url {source_url} must start with fixture:"
            assert "geoportal.sachsen.de" not in source_url
