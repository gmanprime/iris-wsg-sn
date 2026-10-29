from __future__ import annotations

import datetime
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import geopandas as gpd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


@dataclass
class LoadSummary:
    rows_processed: int
    rows_inserted: int
    rows_updated: int
    rows_unchanged: int
    total_table_rows: int
    run_id: str


def get_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        return url
    user = os.getenv("POSTGRES_USER", "iris")
    password = os.getenv("POSTGRES_PASSWORD", "iris_dev_pass")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "iris_dev")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


def get_engine(db_url: Optional[str] = None) -> Engine:
    return create_engine(db_url or get_db_url(), echo=False)


def init_db(engine: Engine, sql_path: Optional[Path | str] = None) -> None:
    path = Path(sql_path or (Path(__file__).parent.parent.parent / "sql" / "init_schema.sql"))
    if not path.exists():
        raise FileNotFoundError(f"Schema SQL file not found: {path}")

    sql_statements = path.read_text(encoding="utf-8")
    with engine.begin() as conn:
        for stmt in sql_statements.split(";"):
            cleaned = stmt.strip()
            if cleaned:
                conn.execute(text(cleaned))
        conn.execute(text("ALTER TABLE iris_staging.water_protection_runs ADD COLUMN IF NOT EXISTS records_unchanged INT DEFAULT 0;"))


def upsert_zones(
    engine: Engine,
    accepted_gdf: gpd.GeoDataFrame,
    run_id: Optional[uuid.UUID | str] = None,
    source_url: str = "fixture:tests/fixtures/zones_input.geojson",
    records_input: int = 0,
    records_rejected: int = 0,
) -> LoadSummary:
    active_run_id = str(run_id or uuid.uuid4())
    started_at = datetime.datetime.now(datetime.timezone.utc)

    if accepted_gdf is None or len(accepted_gdf) == 0:
        with engine.connect() as conn:
            total = conn.execute(
                text("SELECT COUNT(*) FROM iris_staging.water_protection_zones")
            ).scalar() or 0
        return LoadSummary(
            rows_processed=0,
            rows_inserted=0,
            rows_updated=0,
            rows_unchanged=0,
            total_table_rows=total,
            run_id=active_run_id,
        )

    upsert_sql = text("""
    INSERT INTO iris_staging.water_protection_zones AS target (
        state_code,
        source_zone_id,
        zone_class,
        raw_zone_code,
        restriction_category,
        extraction_rate,
        geometry_repaired,
        source_attributes,
        source_crs,
        source_url,
        geom,
        updated_at
    ) VALUES (
        :state_code,
        :source_zone_id,
        :zone_class,
        :raw_zone_code,
        :restriction_category,
        :extraction_rate,
        :geometry_repaired,
        CAST(:source_attributes AS jsonb),
        :source_crs,
        :source_url,
        ST_SetSRID(ST_GeomFromWKB(:geom_wkb), 25832),
        NOW()
    )
    ON CONFLICT (state_code, source_zone_id) DO UPDATE SET
        zone_class = EXCLUDED.zone_class,
        raw_zone_code = EXCLUDED.raw_zone_code,
        restriction_category = EXCLUDED.restriction_category,
        extraction_rate = EXCLUDED.extraction_rate,
        geometry_repaired = EXCLUDED.geometry_repaired,
        source_attributes = EXCLUDED.source_attributes,
        source_crs = EXCLUDED.source_crs,
        source_url = EXCLUDED.source_url,
        geom = EXCLUDED.geom,
        updated_at = NOW()
    WHERE
        target.zone_class IS DISTINCT FROM EXCLUDED.zone_class
        OR target.raw_zone_code IS DISTINCT FROM EXCLUDED.raw_zone_code
        OR target.restriction_category IS DISTINCT FROM EXCLUDED.restriction_category
        OR target.extraction_rate IS DISTINCT FROM EXCLUDED.extraction_rate
        OR target.geometry_repaired IS DISTINCT FROM EXCLUDED.geometry_repaired
        OR target.source_attributes IS DISTINCT FROM EXCLUDED.source_attributes
        OR target.source_crs IS DISTINCT FROM EXCLUDED.source_crs
        OR target.source_url IS DISTINCT FROM EXCLUDED.source_url
        OR NOT ST_Equals(target.geom, EXCLUDED.geom)
    RETURNING (xmax = 0) AS is_inserted;
    """)

    inserted = 0
    updated = 0
    unchanged = 0

    with engine.begin() as conn:
        for _, row in accepted_gdf.iterrows():
            params = {
                "state_code": row["state_code"],
                "source_zone_id": row["source_zone_id"],
                "zone_class": row["zone_class"],
                "raw_zone_code": row.get("raw_zone_code"),
                "restriction_category": row.get("restriction_category", "not_published"),
                "extraction_rate": row.get("extraction_rate", "not_published"),
                "geometry_repaired": bool(row.get("geometry_repaired", False)),
                "source_attributes": row["source_attributes"],
                "source_crs": row.get("source_crs"),
                "source_url": row.get("source_url"),
                "geom_wkb": row.geometry.wkb,
            }
            res = conn.execute(upsert_sql, params).fetchone()
            if res is None:
                unchanged += 1
            elif res[0] is True:
                inserted += 1
            else:
                updated += 1

        final_count = conn.execute(
            text("SELECT COUNT(*) FROM iris_staging.water_protection_zones")
        ).scalar() or 0

        conn.execute(
            text("""
            INSERT INTO iris_staging.water_protection_runs (
                run_id,
                started_at,
                completed_at,
                source_url,
                records_input,
                records_accepted,
                records_rejected,
                records_loaded,
                records_updated,
                records_unchanged,
                status
            ) VALUES (
                :run_id,
                :started_at,
                NOW(),
                :source_url,
                :records_input,
                :records_accepted,
                :records_rejected,
                :records_loaded,
                :records_updated,
                :records_unchanged,
                'COMPLETED'
            )
            """),
            {
                "run_id": active_run_id,
                "started_at": started_at,
                "source_url": source_url,
                "records_input": records_input or len(accepted_gdf),
                "records_accepted": len(accepted_gdf),
                "records_rejected": records_rejected,
                "records_loaded": inserted,
                "records_updated": updated,
                "records_unchanged": unchanged,
            },
        )

    return LoadSummary(
        rows_processed=len(accepted_gdf),
        rows_inserted=inserted,
        rows_updated=updated,
        rows_unchanged=unchanged,
        total_table_rows=final_count,
        run_id=active_run_id,
    )
