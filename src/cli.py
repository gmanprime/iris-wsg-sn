"""Command Line Interface for IRIS-WSG-SN Pipeline.

Supports:
- --mode fixture: Runs complete offline pipeline (process -> load -> parcel demo)
  using hand-made test fixtures and PostGIS staging database.
"""

import argparse
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import geopandas as gpd

from src.load.loader import get_engine, init_db, upsert_zones
from src.parcels.assessor import run_parcel_demo
from src.processing.processor import load_config, process_zones


def run_fixture_mode(
    config_path: str = "config/wsg_config.json",
    zones_fixture: str = "tests/fixtures/zones_input.geojson",
    parcels_fixture: str = "tests/fixtures/parcels_input.gpkg",
    output_parcels: str = "output/parcels_assessed.gpkg",
) -> int:
    print("=================================================================")
    print("=== IRIS-WSG-SN Pipeline: Offline Fixture Demonstrator Mode   ===")
    print("=================================================================")

    # 1. Load config
    cfg_file = Path(config_path)
    if not cfg_file.exists():
        print(f"[ERROR] Config file not found: {cfg_file}", file=sys.stderr)
        return 1
    config = load_config(cfg_file)
    print(f"[1/4] Loaded configuration from {cfg_file}")

    # 2. Database initialization
    print("[2/4] Connecting to PostGIS and ensuring schema exists...")
    try:
        engine = get_engine()
        init_db(engine)
    except Exception as e:
        print(f"[ERROR] Database connection failed: {e}", file=sys.stderr)
        return 1

    # 3. Process & Validate zones
    print(f"[3/4] Processing zones from fixture: {zones_fixture} ...")
    zones_path = Path(zones_fixture)
    if not zones_path.exists():
        print(f"[ERROR] Zones fixture not found: {zones_path}", file=sys.stderr)
        return 1

    source_gdf = gpd.read_file(zones_path)
    proc_result = process_zones(source_gdf, config, source_url=f"fixture:{zones_path.as_posix()}")

    print(f"      - Input records:       {proc_result.stats.total_input_rows}")
    print(f"      - Accepted records:    {proc_result.stats.accepted_rows}")
    print(f"      - Rejected records:    {proc_result.stats.rejected_rows}")
    print(f"      - Repaired geometries: {proc_result.stats.repaired}")
    print(f"      - Unmapped zone codes: {proc_result.stats.unmapped_zones}")
    if proc_result.stats.rejection_breakdown:
        print(f"      - Rejection breakdown: {proc_result.stats.rejection_breakdown}")

    # 4. Upsert into PostGIS
    load_summary = upsert_zones(
        engine,
        proc_result.accepted,
        source_url=f"fixture:{zones_path.as_posix()}",
        records_input=proc_result.stats.total_input_rows,
        records_rejected=proc_result.stats.rejected_rows,
    )
    print(f"      - PostGIS loaded:      {load_summary.rows_inserted} inserted, {load_summary.rows_updated} updated, {load_summary.rows_unchanged} unchanged")
    print(f"      - Staging table total: {load_summary.total_table_rows} rows")

    # 5. Run Parcel Assessment Demo
    print(f"[4/4] Running parcel screening demo on {parcels_fixture} ...")
    parcels_path = Path(parcels_fixture)
    if not parcels_path.exists():
        print(f"[ERROR] Parcels fixture not found: {parcels_path}", file=sys.stderr)
        return 1

    assessed_gdf = run_parcel_demo(
        parcels_input_path=parcels_path,
        output_gpkg_path=output_parcels,
        config_path=config_path,
        engine=engine,
    )

    print(f"      - Assessed parcels:    {len(assessed_gdf)}")
    print(f"      - Output saved to:     {output_parcels}")
    print("\n[SUCCESS] Pipeline execution completed successfully.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="IRIS-WSG-SN Ingestion Pipeline")
    parser.add_argument(
        "--mode",
        choices=["fixture"],
        default="fixture",
        help="Pipeline execution mode (default: fixture)",
    )
    parser.add_argument(
        "--config",
        default="config/wsg_config.json",
        help="Path to configuration file",
    )
    parser.add_argument(
        "--zones",
        default="tests/fixtures/zones_input.geojson",
        help="Path to zones input fixture",
    )
    parser.add_argument(
        "--parcels",
        default="tests/fixtures/parcels_input.gpkg",
        help="Path to parcels input GeoPackage",
    )
    parser.add_argument(
        "--output",
        default="output/parcels_assessed.gpkg",
        help="Path to write assessed parcels GeoPackage",
    )

    args = parser.parse_args()
    if args.mode == "fixture":
        sys.exit(
            run_fixture_mode(
                config_path=args.config,
                zones_fixture=args.zones,
                parcels_fixture=args.parcels,
                output_parcels=args.output,
            )
        )


if __name__ == "__main__":
    main()
