from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import geopandas as gpd
import pandas as pd
import shapely
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
    target_crs = config.get("target_crs", "EPSG:25832")
    priority_order = config.get("priority_order", DEFAULT_PRIORITY_ORDER)

    if parcels_gdf.crs is None:
        parcels_gdf.set_crs(target_crs, inplace=True)
    elif parcels_gdf.crs.to_epsg() != 25832:
        parcels_gdf = parcels_gdf.to_crs(target_crs)

    if zones_gdf.crs is None:
        zones_gdf.set_crs(target_crs, inplace=True)
    elif zones_gdf.crs.to_epsg() != 25832:
        zones_gdf = zones_gdf.to_crs(target_crs)

    dissolved_by_class: Dict[str, Any] = {}
    for zone_class, group in zones_gdf.groupby("zone_class"):
        dissolved_by_class[zone_class] = shapely.union_all(group.geometry.tolist())

    class_cols_m2 = [f"{cls.lower()}_m2" for cls in priority_order]
    class_cols_pct = [f"{cls.lower()}_pct" for cls in priority_order]

    result_gdf = parcels_gdf.copy()
    for col in ["parcel_area_m2", *class_cols_m2, "outside_m2", *class_cols_pct, "outside_pct", "zone_source_ids", "geometry_repaired_zone_involved", "assessed_at"]:
        if col not in result_gdf.columns:
            result_gdf[col] = None

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for idx, row in result_gdf.iterrows():
        existing_area = row.get("parcel_area_m2")
        if pd.notna(existing_area) and float(existing_area) > 0 and pd.notna(row.get("assessed_at")):
            continue

        parcel_geom = row.geometry
        if parcel_geom is None or parcel_geom.is_empty:
            continue

        parcel_area = float(parcel_geom.area)
        result_gdf.at[idx, "parcel_area_m2"] = parcel_area

        intersecting_mask = zones_gdf.intersects(parcel_geom)
        intersecting_zones = zones_gdf[intersecting_mask]

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

            pct_c = (area_c / parcel_area * 100.0) if parcel_area > 0 else 0.0
            total_covered_area += area_c

            result_gdf.at[idx, col_m2] = area_c
            result_gdf.at[idx, col_pct] = pct_c

        outside_m2 = max(0.0, parcel_area - total_covered_area)
        outside_pct = (outside_m2 / parcel_area * 100.0) if parcel_area > 0 else 0.0

        result_gdf.at[idx, "outside_m2"] = outside_m2
        result_gdf.at[idx, "outside_pct"] = outside_pct
        result_gdf.at[idx, "assessed_at"] = now_iso

    numeric_cols = ["parcel_area_m2", *class_cols_m2, "outside_m2", *class_cols_pct, "outside_pct"]
    for col in numeric_cols:
        result_gdf[col] = pd.to_numeric(result_gdf[col], errors="coerce").astype("float64")

    return result_gdf


def run_parcel_demo(
    parcels_input_path: Path | str = "tests/fixtures/parcels_input.gpkg",
    output_gpkg_path: Path | str = "output/parcels_assessed.gpkg",
    config_path: Path | str = "config/wsg_config.json",
    engine: Optional[Engine] = None,
) -> gpd.GeoDataFrame:
    config = load_config(config_path)
    db_engine = engine or get_engine()

    parcels_path = Path(parcels_input_path)
    if not parcels_path.exists():
        raise FileNotFoundError(f"Input parcels file not found: {parcels_path}")

    input_parcels = gpd.read_file(parcels_path)
    zones_gdf = load_zones_from_postgis(db_engine)

    assessed = assess_parcels(input_parcels, zones_gdf, config)

    out_file = Path(output_gpkg_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    assessed.to_file(out_file, driver="GPKG", layer="assessed_parcels")
    return assessed
