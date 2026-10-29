"""Parcel Protection Zone Screening & Assessment Module (Step 4).

Reads cached protection zones from PostGIS table `iris_staging.water_protection_zones`.
Reads input parcels GeoPackage with empty zone metrics.
Performs spatial overlay in EPSG:25832:
- Dissolves same-class zones first.
- Applies EXCLUSIVE coverage by priority order:
    ZONE_I > ZONE_II > ZONE_IIIA > ZONE_IIIB > ZONE_III > UNKNOWN
  Each area of a parcel is counted ONLY for the highest-priority zone covering it.
- Computes exact raw m² and % per zone class and outside_m2 / outside_pct.
- Identifies intersecting zone IDs and whether any repaired zone was involved.
- Skips parcels already assessed (idempotent demo execution).
- Writes updated parcels to an output GeoPackage.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
import pandas as pd
import shapely
from shapely.geometry import MultiPolygon, Polygon
from sqlalchemy.engine import Engine

from src.load.loader import get_engine
from src.processing.processor import load_config

DEFAULT_PRIORITY_ORDER = [
    "ZONE_I",
    "ZONE_II",
    "ZONE_IIIA",
    "ZONE_IIIB",
    "ZONE_III",
    "UNKNOWN",
]


def load_zones_from_postgis(engine: Engine, table: str = "iris_staging.water_protection_zones") -> gpd.GeoDataFrame:
    """Fetch stored protection zones from PostGIS."""
    sql = f"""
    SELECT 
        source_zone_id,
        zone_class,
        geometry_repaired,
        geom
    FROM {table};
    """
    gdf = gpd.read_postgis(sql, con=engine, geom_col="geom")
    if gdf.geometry.name != "geometry":
        gdf = gdf.rename_geometry("geometry")
    if gdf.crs is None:
        gdf.set_crs("EPSG:25832", inplace=True)
    elif gdf.crs.to_epsg() != 25832:
        gdf = gdf.to_crs("EPSG:25832")
    return gdf


def assess_parcels(
    parcels_gdf: gpd.GeoDataFrame,
    zones_gdf: gpd.GeoDataFrame,
    config: Dict[str, Any],
) -> gpd.GeoDataFrame:
    """Assess parcels against protection zones with exclusive priority coverage.

    Args:
        parcels_gdf: Input parcels GeoDataFrame
        zones_gdf: Protection zones GeoDataFrame (from PostGIS)
        config: Pipeline configuration dictionary

    Returns:
        Updated GeoDataFrame with zone coverage metrics filled.
    """
    target_crs = config.get("target_crs", "EPSG:25832")
    priority_order = config.get("priority_order", DEFAULT_PRIORITY_ORDER)

    # Ensure CRS alignment
    if parcels_gdf.crs is None:
        parcels_gdf.set_crs(target_crs, inplace=True)
    elif parcels_gdf.crs.to_epsg() != 25832:
        parcels_gdf = parcels_gdf.to_crs(target_crs)

    if zones_gdf.crs is None:
        zones_gdf.set_crs(target_crs, inplace=True)
    elif zones_gdf.crs.to_epsg() != 25832:
        zones_gdf = zones_gdf.to_crs(target_crs)

    # Dissolve same-class zones first
    dissolved_by_class: Dict[str, Any] = {}
    for zone_class, group in zones_gdf.groupby("zone_class"):
        dissolved_by_class[zone_class] = shapely.union_all(group.geometry.tolist())

    # Build list of metric columns from config priority order
    class_cols_m2 = [f"{cls.lower()}_m2" for cls in priority_order]
    class_cols_pct = [f"{cls.lower()}_pct" for cls in priority_order]

    # Ensure result columns exist
    result_gdf = parcels_gdf.copy()
    for col in ["parcel_area_m2", *class_cols_m2, "outside_m2", *class_cols_pct, "outside_pct", "zone_source_ids", "geometry_repaired_zone_involved", "assessed_at"]:
        if col not in result_gdf.columns:
            result_gdf[col] = None

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for idx, row in result_gdf.iterrows():
        # Check if parcel is already assessed (skip if already has area assigned)
        existing_area = row.get("parcel_area_m2")
        if pd.notna(existing_area) and float(existing_area) > 0 and pd.notna(row.get("assessed_at")):
            continue

        parcel_geom = row.geometry
        if parcel_geom is None or parcel_geom.is_empty:
            continue

        parcel_area = float(parcel_geom.area)
        result_gdf.at[idx, "parcel_area_m2"] = parcel_area

        # Find intersecting zones (touching or overlapping)
        intersecting_mask = zones_gdf.intersects(parcel_geom)
        intersecting_zones = zones_gdf[intersecting_mask]

        # Only list source IDs that have non-zero area or touch
        intersecting_ids: List[str] = []
        repaired_involved = False

        for _, z_row in intersecting_zones.iterrows():
            inter = parcel_geom.intersection(z_row.geometry)
            if inter and not inter.is_empty and inter.area > 0:
                intersecting_ids.append(str(z_row["source_zone_id"]))
                if bool(z_row.get("geometry_repaired", False)):
                    repaired_involved = True

        result_gdf.at[idx, "zone_source_ids"] = ",".join(sorted(intersecting_ids))
        result_gdf.at[idx, "geometry_repaired_zone_involved"] = repaired_involved

        # EXCLUSIVE coverage by priority order
        covered_so_far = None
        total_covered_area = 0.0

        for zone_class in priority_order:
            col_m2 = f"{zone_class.lower()}_m2"
            col_pct = f"{zone_class.lower()}_pct"

            if zone_class in dissolved_by_class:
                class_geom = dissolved_by_class[zone_class]
                candidate = parcel_geom.intersection(class_geom)

                if candidate is None or candidate.is_empty or candidate.area == 0:
                    area_c = 0.0
                else:
                    if covered_so_far is None or covered_so_far.is_empty:
                        exclusive_geom = candidate
                    else:
                        exclusive_geom = candidate.difference(covered_so_far)

                    area_c = float(exclusive_geom.area) if (exclusive_geom and not exclusive_geom.is_empty) else 0.0
                    covered_so_far = candidate if (covered_so_far is None or covered_so_far.is_empty) else covered_so_far.union(candidate)
            else:
                area_c = 0.0

            pct_c = (area_c / parcel_area) * 100.0 if parcel_area > 0 else 0.0
            result_gdf.at[idx, col_m2] = area_c
            result_gdf.at[idx, col_pct] = pct_c
            total_covered_area += area_c

        outside_m2 = max(0.0, parcel_area - total_covered_area)
        outside_pct = (outside_m2 / parcel_area) * 100.0 if parcel_area > 0 else 0.0

        result_gdf.at[idx, "outside_m2"] = outside_m2
        result_gdf.at[idx, "outside_pct"] = outside_pct
        result_gdf.at[idx, "assessed_at"] = now_iso

    # Explicitly cast numeric columns to float64
    numeric_cols = ["parcel_area_m2", *class_cols_m2, "outside_m2", *class_cols_pct, "outside_pct"]
    for col in numeric_cols:
        result_gdf[col] = pd.to_numeric(result_gdf[col], errors="coerce").fillna(0.0).astype(float)

    return result_gdf


def run_parcel_demo(
    parcels_input_path: Path | str,
    output_gpkg_path: Path | str,
    config_path: Path | str = "config/wsg_config.json",
    engine: Optional[Engine] = None,
) -> gpd.GeoDataFrame:
    """Run end-to-end parcel screening demo from PostGIS cached zones."""
    eng = engine or get_engine()
    cfg = load_config(config_path)

    # 1. Read cached zones from PostGIS
    zones_gdf = load_zones_from_postgis(eng)

    # 2. Read input parcels GeoPackage
    parcels_gdf = gpd.read_file(parcels_input_path)

    # 3. Assess parcels
    assessed_gdf = assess_parcels(parcels_gdf, zones_gdf, cfg)

    # 4. Write output GeoPackage
    out_path = Path(output_gpkg_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    assessed_gdf.to_file(out_path, driver="GPKG", layer="parcels")

    return assessed_gdf
