# PostGIS Validation Query & Real Output Example

This document demonstrates real spatial screening results executed directly against the live PostGIS staging database (`iris_staging.water_protection_zones`) populated from the Saxony test fixtures.

## 1. Validation Query ([`sql/validation_query.sql`](file:///c:/Users/yonat/Documents/@Projects/IRIS%20Project%20Application/sql/validation_query.sql))

```sql
WITH input_parcel AS (
    -- Example test parcel: PARCEL-05 (Coschütz, 400m x 400m = 160,000 m²)
    -- Coordinates in EPSG:25832
    SELECT 
        'PARCEL-05' AS parcel_id,
        'Coschütz' AS gemarkung,
        '550/9' AS flurnummer,
        ST_SetSRID(
            ST_GeomFromText('POLYGON((831800 5654800, 832200 5654800, 832200 5655200, 831800 5655200, 831800 5654800))'),
            25832
        ) AS geom
)
SELECT 
    p.parcel_id,
    p.gemarkung,
    p.flurnummer,
    ST_Area(p.geom) AS parcel_area_m2,
    z.source_zone_id,
    z.zone_class,
    z.raw_zone_code,
    z.restriction_category,
    z.extraction_rate,
    z.geometry_repaired,
    CASE 
        WHEN ST_Contains(z.geom, p.geom) THEN 'CONTAINED_IN'
        WHEN ST_Touches(z.geom, p.geom) THEN 'TOUCH_ONLY'
        ELSE 'INTERSECTS'
    END AS spatial_relationship,
    ROUND(CAST(ST_Area(ST_Intersection(z.geom, p.geom)) AS numeric), 2) AS intersection_m2,
    ROUND(CAST((ST_Area(ST_Intersection(z.geom, p.geom)) / ST_Area(p.geom) * 100.0) AS numeric), 2) AS coverage_pct
FROM input_parcel p
JOIN iris_staging.water_protection_zones z
    ON ST_Intersects(z.geom, p.geom)
ORDER BY 
    intersection_m2 DESC,
    z.zone_class;
```

---

## 2. Real Execution Result

Executed against local PostGIS container:

| parcel_id | gemarkung | flurnummer | parcel_area_m2 | source_zone_id | zone_class | raw_zone_code | restriction_category | extraction_rate | geometry_repaired | spatial_relationship | intersection_m2 | coverage_pct |
|:---|:---|:---|---:|:---|:---|:---|:---|:---|:---|:---|---:|---:|
| **PARCEL-05** | Coschütz | 550/9 | 160000.0 | **SN-WSG-006** | ZONE_II | II | not_published | not_published | False | **CONTAINED_IN** | 160000.0 | 100.0% |
| **PARCEL-05** | Coschütz | 550/9 | 160000.0 | **SN-WSG-005** | ZONE_III | III | not_published | not_published | False | **CONTAINED_IN** | 160000.0 | 100.0% |

### Key Observations
1. **Stacked Zone Containment**:
   - `PARCEL-05` is completely inside the nested wellhead protection zone `SN-WSG-006` (`ZONE_II`, 160,000 m² = 100%).
   - Simultaneously, it is completely inside the outer catchment zone `SN-WSG-005` (`ZONE_III`, 160,000 m² = 100%).
2. **Exclusive Coverage in Parcel Assessment Module**:
   - In the GeoPackage parcel assessment pipeline ([`src/parcels/assessor.py`](file:///c:/Users/yonat/Documents/@Projects/IRIS%20Project%20Application/src/parcels/assessor.py)), priority rules (`ZONE_I > ZONE_II > ZONE_IIIA > ZONE_IIIB > ZONE_III > UNKNOWN`) assign 100% of this area to `ZONE_II` exclusively (`zone_ii_m2 = 160000.0`, `zone_iii_m2 = 0.0`), while preserving both IDs in `zone_source_ids = "SN-WSG-005,SN-WSG-006"`.
3. **Explicit Defaults**:
   - Unpublished restriction categories and extraction rates default strictly to `'not_published'`.
