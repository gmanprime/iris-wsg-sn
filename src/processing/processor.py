from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import geopandas as gpd
import pandas as pd
import shapely
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon


class SchemaMismatchError(ValueError):
    pass


@dataclass
class ProcessingStats:
    total_input_rows: int = 0
    accepted_rows: int = 0
    rejected_rows: int = 0
    repaired_geometries: int = 0
    unmapped_zones: int = 0
    rejection_breakdown: Dict[str, int] = field(default_factory=dict)

    @property
    def repaired(self) -> int:
        return self.repaired_geometries

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_input_rows": self.total_input_rows,
            "accepted_rows": self.accepted_rows,
            "rejected_rows": self.rejected_rows,
            "repaired_geometries": self.repaired_geometries,
            "repaired": self.repaired_geometries,
            "unmapped_zones": self.unmapped_zones,
            "rejection_breakdown": dict(self.rejection_breakdown),
        }


@dataclass
class ProcessingResult:
    accepted: gpd.GeoDataFrame
    rejected: pd.DataFrame
    stats: ProcessingStats


def load_config(config_path: Path | str) -> Dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_column_name(col_def: Any) -> str:
    if isinstance(col_def, dict):
        return col_def["name"]
    return str(col_def)


def _repair_geometry(geom: Any) -> Tuple[Optional[MultiPolygon], bool]:
    if geom is None or pd.isna(geom) or (hasattr(geom, "is_empty") and geom.is_empty):
        return None, False

    was_repaired = False
    repaired = geom

    if not geom.is_valid:
        repaired = shapely.make_valid(geom)
        was_repaired = True

    polygons: List[Polygon] = []
    if isinstance(repaired, Polygon):
        polygons = [repaired]
    elif isinstance(repaired, MultiPolygon):
        polygons = list(repaired.geoms)
    elif isinstance(repaired, GeometryCollection):
        polygons = [g for g in repaired.geoms if isinstance(g, Polygon)]
        for g in repaired.geoms:
            if isinstance(g, MultiPolygon):
                polygons.extend(list(g.geoms))
        was_repaired = True
    else:
        return None, False

    valid_polys = [p for p in polygons if p.is_valid and not p.is_empty and p.area > 0]
    if not valid_polys:
        return None, False

    return MultiPolygon(valid_polys), was_repaired


def process_zones(
    source_gdf: gpd.GeoDataFrame,
    config: Dict[str, Any],
    source_url: str = "fixture:tests/fixtures/zones_input.geojson"
) -> ProcessingResult:
    stats = ProcessingStats(total_input_rows=len(source_gdf))
    rejection_counts: Dict[str, int] = {}

    def record_rejection(reason: str):
        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

    id_col = _get_column_name(config["id_column"])
    zone_col = _get_column_name(config["zone_column"])
    target_crs = config.get("target_crs", "EPSG:25832")
    state_code = config.get("default_state_code", "SN")
    zone_lookup: Dict[str, str] = config.get("zone_lookup", {})

    missing_cols = [c for c in [id_col, zone_col] if c not in source_gdf.columns]
    if missing_cols:
        raise SchemaMismatchError(
            f"Configured required column(s) {missing_cols} missing from source dataset. "
            f"Available columns: {list(source_gdf.columns)}"
        )

    source_crs = str(source_gdf.crs) if source_gdf.crs is not None else config.get("source_crs", "EPSG:25832")

    conflicting_duplicate_ids: Set[Any] = set()
    id_groups = source_gdf.dropna(subset=[id_col]).groupby(id_col)
    for zone_id, group in id_groups:
        if len(group) > 1:
            zone_codes = group[zone_col].unique()
            geoms = group.geometry.tolist()
            geoms_equal = all(geoms[0].equals(g) for g in geoms[1:]) if all(g is not None and not g.is_empty for g in geoms) else False
            if len(zone_codes) > 1 or not geoms_equal or len(group.drop(columns=["geometry"]).drop_duplicates()) > 1:
                conflicting_duplicate_ids.add(zone_id)

    accepted_records = []
    rejected_records = []
    seen_accepted_ids: Set[str] = set()

    for idx, row in source_gdf.iterrows():
        raw_id = row[id_col]
        raw_geom = row.geometry
        raw_props = {k: v for k, v in row.items() if k != "geometry"}

        if pd.isna(raw_id) or str(raw_id).strip() == "" or str(raw_id).lower() == "none":
            record_rejection("ERR_MISSING_ID")
            rejected_records.append({
                **raw_props,
                "rejection_reason": "ERR_MISSING_ID",
                "geometry": raw_geom
            })
            continue

        zone_id = str(raw_id).strip()

        if zone_id in conflicting_duplicate_ids:
            record_rejection("ERR_DUPLICATE_ID_CONFLICT")
            rejected_records.append({
                **raw_props,
                "rejection_reason": "ERR_DUPLICATE_ID_CONFLICT",
                "geometry": raw_geom
            })
            continue

        if zone_id in seen_accepted_ids:
            continue

        if raw_geom is None or pd.isna(raw_geom) or (hasattr(raw_geom, "is_empty") and raw_geom.is_empty):
            record_rejection("ERR_EMPTY_GEOMETRY")
            rejected_records.append({
                **raw_props,
                "rejection_reason": "ERR_EMPTY_GEOMETRY",
                "geometry": raw_geom
            })
            continue

        repaired_geom, was_repaired = _repair_geometry(raw_geom)
        if repaired_geom is None:
            record_rejection("ERR_GEOMETRY_INVALID")
            rejected_records.append({
                **raw_props,
                "rejection_reason": "ERR_GEOMETRY_INVALID",
                "geometry": raw_geom
            })
            continue

        if was_repaired:
            stats.repaired_geometries += 1

        raw_zone = row.get(zone_col)
        raw_zone_str = str(raw_zone).strip() if pd.notna(raw_zone) else ""
        if raw_zone_str in zone_lookup:
            zone_class = zone_lookup[raw_zone_str]
        else:
            zone_class = "UNKNOWN"
            stats.unmapped_zones += 1

        clean_attrs = {}
        for k, v in raw_props.items():
            if pd.isna(v):
                clean_attrs[k] = None
            elif isinstance(v, (int, float, str, bool)):
                clean_attrs[k] = v
            else:
                clean_attrs[k] = str(v)

        seen_accepted_ids.add(zone_id)
        accepted_records.append({
            "state_code": state_code,
            "source_zone_id": zone_id,
            "zone_class": zone_class,
            "raw_zone_code": raw_zone_str if raw_zone_str else None,
            "restriction_category": "not_published",
            "extraction_rate": "not_published",
            "geometry_repaired": was_repaired,
            "source_attributes": json.dumps(clean_attrs, ensure_ascii=False),
            "source_crs": source_crs,
            "source_url": source_url,
            "geometry": repaired_geom,
        })

    if accepted_records:
        accepted_gdf = gpd.GeoDataFrame(accepted_records, crs=source_gdf.crs or source_crs)
        if str(accepted_gdf.crs) != target_crs:
            accepted_gdf = accepted_gdf.to_crs(target_crs)
    else:
        accepted_gdf = gpd.GeoDataFrame(
            columns=[
                "state_code", "source_zone_id", "zone_class", "raw_zone_code",
                "restriction_category", "extraction_rate", "geometry_repaired",
                "source_attributes", "source_crs", "source_url", "geometry"
            ],
            crs=target_crs
        )

    rejected_df = pd.DataFrame(rejected_records) if rejected_records else pd.DataFrame(columns=["rejection_reason"])

    stats.accepted_rows = len(accepted_gdf)
    stats.rejected_rows = len(rejected_df)
    stats.rejection_breakdown = rejection_counts

    return ProcessingResult(
        accepted=accepted_gdf,
        rejected=rejected_df,
        stats=stats
    )
