"""Integration tests for Parcel Screening and Assessment (Step 4).

Verifies:
- All 6 parcel cases (inside one zone, outside, straddling, edge-touch only, inside stacked zones, straddling stacked zones).
- Exclusive coverage by priority order (ZONE_I > ZONE_II > ZONE_IIIA > ZONE_IIIB > ZONE_III > UNKNOWN).
- For every parcel: sum(class_m2) + outside_m2 == parcel_area_m2.
- Running the demo twice gives the same output (idempotence).
"""

from pathlib import Path
import geopandas as gpd
import pytest

from src.load.loader import get_engine, init_db, upsert_zones
from src.parcels.assessor import run_parcel_demo
from src.processing.processor import load_config, process_zones

CONFIG_PATH = Path("config/wsg_config.json")
FIXTURES_DIR = Path("tests/fixtures")
OUTPUT_DIR = Path("output")


@pytest.fixture(scope="module")
def prepared_db():
    engine = get_engine()
    init_db(engine)
    config = load_config(CONFIG_PATH)

    # Ingest the 9 fixture zones so PostGIS has the complete test dataset cached
    zones_gdf = gpd.read_file(FIXTURES_DIR / "zones_input.geojson")
    proc_result = process_zones(zones_gdf, config)
    upsert_zones(engine, proc_result.accepted)

    return engine, config


def test_parcel_screening_all_cases(prepared_db, tmp_path):
    engine, config = prepared_db
    parcels_input = FIXTURES_DIR / "parcels_input.gpkg"
    output_gpkg = tmp_path / "parcels_assessed.gpkg"

    # Run the parcel assessment demo
    assessed_gdf = run_parcel_demo(
        parcels_input_path=parcels_input,
        output_gpkg_path=output_gpkg,
        config_path=CONFIG_PATH,
        engine=engine,
    )

    assert output_gpkg.exists()
    assert len(assessed_gdf) == 6

    # Verify that GPKG was written and can be re-read
    from_file = gpd.read_file(output_gpkg)
    assert len(from_file) == 6

    by_id = assessed_gdf.set_index("parcel_id")

    # Case 1: PARCEL-01 (Fully inside Zone I, SN-WSG-007)
    p1 = by_id.loc["PARCEL-01"]
    assert p1["parcel_area_m2"] == 160000.0
    assert p1["zone_i_m2"] == 160000.0
    assert p1["zone_i_pct"] == 100.0
    assert p1["outside_m2"] == 0.0
    assert p1["outside_pct"] == 0.0
    assert "SN-WSG-007" in p1["zone_source_ids"]

    # Case 2: PARCEL-02 (Completely outside all zones)
    p2 = by_id.loc["PARCEL-02"]
    assert p2["parcel_area_m2"] == 250000.0
    assert p2["zone_i_m2"] == 0.0
    assert p2["zone_ii_m2"] == 0.0
    assert p2["zone_iii_m2"] == 0.0
    assert p2["outside_m2"] == 250000.0
    assert p2["outside_pct"] == 100.0
    assert p2["zone_source_ids"] == ""

    # Case 3: PARCEL-03 (Straddling Zone I and outside)
    p3 = by_id.loc["PARCEL-03"]
    assert p3["parcel_area_m2"] == 240000.0
    assert p3["zone_i_m2"] == 80000.0
    assert pytest.approx(p3["zone_i_pct"], 0.01) == 33.33
    assert p3["outside_m2"] == 160000.0
    assert pytest.approx(p3["outside_pct"], 0.01) == 66.67
    assert p3["zone_source_ids"] == "SN-WSG-007"

    # Case 4: PARCEL-04 (Touching Zone I only along an exterior boundary line)
    p4 = by_id.loc["PARCEL-04"]
    assert p4["parcel_area_m2"] == 200000.0
    assert p4["zone_i_m2"] == 0.0
    assert p4["zone_ii_m2"] == 0.0
    assert p4["zone_iii_m2"] == 0.0
    assert p4["outside_m2"] == 200000.0
    assert p4["outside_pct"] == 100.0

    # Case 5: PARCEL-05 (Inside stacked zones: Zone II nested inside Zone III)
    # Exclusive priority: Zone II has higher priority -> counted in Zone II, 0 in Zone III!
    p5 = by_id.loc["PARCEL-05"]
    assert p5["parcel_area_m2"] == 160000.0
    assert p5["zone_ii_m2"] == 160000.0
    assert p5["zone_ii_pct"] == 100.0
    assert p5["zone_iii_m2"] == 0.0
    assert p5["zone_iii_pct"] == 0.0
    assert p5["outside_m2"] == 0.0
    assert "SN-WSG-005" in p5["zone_source_ids"]
    assert "SN-WSG-006" in p5["zone_source_ids"]

    # Case 6: PARCEL-06 (Straddling stacked Zone II and outer Zone III)
    # 80,000 m2 in Zone II, remaining 120,000 m2 in Zone III
    p6 = by_id.loc["PARCEL-06"]
    assert p6["parcel_area_m2"] == 200000.0
    assert p6["zone_ii_m2"] == 80000.0
    assert p6["zone_ii_pct"] == 40.0
    assert p6["zone_iii_m2"] == 120000.0
    assert p6["zone_iii_pct"] == 60.0
    assert p6["outside_m2"] == 0.0
    assert "SN-WSG-005" in p6["zone_source_ids"]
    assert "SN-WSG-006" in p6["zone_source_ids"]

    # Invariant check across all 6 parcels: class m2 + outside_m2 == parcel_area_m2
    zone_cols = ["zone_i_m2", "zone_ii_m2", "zone_iiia_m2", "zone_iiib_m2", "zone_iii_m2", "unknown_m2"]
    for pid, row in by_id.iterrows():
        total_zone = sum(float(row[c] or 0.0) for c in zone_cols)
        outside = float(row["outside_m2"] or 0.0)
        parcel_area = float(row["parcel_area_m2"])
        assert total_zone + outside == pytest.approx(parcel_area, abs=1e-3), (
            f"Area sum mismatch for {pid}: {total_zone} + {outside} != {parcel_area}"
        )


def test_parcel_demo_double_run_idempotency(prepared_db, tmp_path):
    """Running the demo twice gives the same output and skips already-assessed parcels."""
    engine, config = prepared_db
    parcels_input = FIXTURES_DIR / "parcels_input.gpkg"
    output_gpkg = tmp_path / "parcels_idempotent.gpkg"

    run1 = run_parcel_demo(parcels_input, output_gpkg, CONFIG_PATH, engine)
    assessed_timestamps_1 = run1["assessed_at"].tolist()

    # Second run using the output of the first run as input
    run2 = run_parcel_demo(output_gpkg, output_gpkg, CONFIG_PATH, engine)
    assessed_timestamps_2 = run2["assessed_at"].tolist()

    # Timestamps should be identical because already-assessed parcels were skipped
    assert assessed_timestamps_1 == assessed_timestamps_2

    # Areas and percentages must match identically
    assert (run1["parcel_area_m2"].astype(float) == run2["parcel_area_m2"].astype(float)).all()
    assert (run1["outside_m2"].astype(float) == run2["outside_m2"].astype(float)).all()
    assert (run1["zone_ii_m2"].astype(float) == run2["zone_ii_m2"].astype(float)).all()
