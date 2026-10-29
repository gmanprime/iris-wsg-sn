-- ============================================================================
-- IRIS-WSG-SN: Validation Query
-- Demonstrates PostGIS spatial screening of drinking water protection zones
-- against an input parcel geometry (e.g. PARCEL-05 in Saxony, EPSG:25832).
-- ============================================================================

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
