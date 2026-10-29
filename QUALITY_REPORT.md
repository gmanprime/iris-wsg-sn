# IRIS-WSG-SN: Data Quality & Acceptance Report

This quality report provides empirical evidence for system acceptance based on real test execution outputs and representative fixtures in realistic Saxony coordinates (EPSG:25832).

---

## 1. Live Access Limitation & Verification Scope

| Item | Status | Details / Evidence |
|:---|:---|:---|
| **Live WFS Reachability** | **UNVERIFIED (TIMEOUT)** | Handshake timed out connecting to `https://geoportal.sachsen.de/wfs/wasserschutz` (`_ssl.c:1011`). Documented per Core Rule 6. |
| **Source Schema & Field Names** | **ASSUMED** | Configured in `config/wsg_config.json` (`wsg_id`, `schutzzone`) based on German LfULG conventions. |
| **Zone Classification Lookup** | **VERIFIED (OFFLINE)** | Explicit mapping (`I` -> `ZONE_I`, `II` -> `ZONE_II`, etc.). Unmapped codes map strictly to `UNKNOWN`. |
| **Idempotent Upsert** | **VERIFIED (POSTGIS)** | Double-load test verified: `rows_inserted=0, rows_updated=0, rows_unchanged=4`, table row count strictly unchanged. |
| **Geometry Repair & Reprojection**| **VERIFIED (SHAPELY/GEOPANDAS)** | Repaired self-intersecting bowties to MultiPolygon. Reprojected EPSG:25833 to EPSG:25832. |
| **Parcel Screening & Priority** | **VERIFIED (GEOPACKAGE)** | Tested all 6 spatial cases with exclusive priority coverage. Area conservation invariant strictly holds. |

---

## 2. Ingestion & Validation Edge Cases (`tests/fixtures/zones_input.geojson`)

Across the 9 raw test features, the validation and normalization module produced the following breakdown:

### A. Accepted Features (6 Records)
1. **`SN-WSG-001` (Valid Multipart)**:
   - Input: `MultiPolygon` with 2 disjoint parts in EPSG:25832.
   - Result: Accepted without repair (`geometry_repaired = False`). Zone mapped to `ZONE_IIIA`.
2. **`SN-WSG-002` (Invalid Self-Intersecting Bowtie)**:
   - Input: Non-simple polygon with self-crossing boundary (`is_valid == False`).
   - Result: Repaired via `shapely.make_valid` into a valid 2-part `MultiPolygon`. Stored with `geometry_repaired = True`.
3. **`SN-WSG-004` (Unmapped Zone Classification)**:
   - Input: `schutzzone = "IV_HISTORIC"`.
   - Result: Traced against config lookup; key missing -> safely assigned to `zone_class = "UNKNOWN"` with `raw_zone_code = "IV_HISTORIC"`.
4. **`SN-WSG-005` (Stacked Outer Zone III)**:
   - Input: Large catchment polygon (4000m x 4000m).
   - Result: Accepted as `ZONE_III`.
5. **`SN-WSG-006` (Stacked Inner Zone II)**:
   - Input: Wellhead protection zone (1000m x 1000m) nested completely inside `SN-WSG-005`.
   - Result: Accepted as `ZONE_II`.
6. **`SN-WSG-007` (Standard Zone I)**:
   - Input: Immediate wellhead protection zone.
   - Result: Accepted as `ZONE_I`.

### B. Rejected Features (3 Records)
1. **`SN-WSG-003` Version A & Version B (`ERR_DUPLICATE_ID_CONFLICT`)**:
   - Cause: Two distinct records in the same batch shared the same source ID (`SN-WSG-003`) with conflicting geometries and attributes.
   - Handling: In accordance with data integrity requirements, the pipeline **rejected both records** rather than picking one arbitrarily or causing a PostgreSQL batch conflict.
2. **Missing ID Record (`ERR_MISSING_ID`)**:
   - Cause: Feature with `wsg_id = null`.
   - Handling: Rejected immediately before reaching the database.

---

## 3. Parcel Screening Verification Summary (`tests/fixtures/parcels_input.gpkg`)

Evaluated against PostGIS cached zones using priority order: `ZONE_I > ZONE_II > ZONE_IIIA > ZONE_IIIB > ZONE_III > UNKNOWN`.

| Parcel ID | Description | Total Area (m²) | Zone I (%) | Zone II (%) | Zone III (%) | Outside (%) | Intersecting Zones |
|:---|:---|---:|---:|---:|---:|---:|:---|
| **PARCEL-01** | Fully inside Zone I | 160,000.0 | **100.0%** | 0.0% | 0.0% | 0.0% | `SN-WSG-007` |
| **PARCEL-02** | Outside all zones | 250,000.0 | 0.0% | 0.0% | 0.0% | **100.0%** | *(None)* |
| **PARCEL-03** | Straddling Zone I | 240,000.0 | **33.33%** | 0.0% | 0.0% | **66.67%** | `SN-WSG-007` |
| **PARCEL-04** | Touch-only along edge | 200,000.0 | 0.0% | 0.0% | 0.0% | **100.0%** | *(Zero area touch)* |
| **PARCEL-05** | Inside stacked zones (II inside III) | 160,000.0 | 0.0% | **100.0%** | **0.0%** | 0.0% | `SN-WSG-005`, `SN-WSG-006` |
| **PARCEL-06** | Straddling stacked zones | 200,000.0 | 0.0% | **40.0%** | **60.0%** | 0.0% | `SN-WSG-005`, `SN-WSG-006` |

### Key Mathematical Invariants Verified
1. **Exact Area Conservation**: For every single parcel, $\sum \text{zone\_m2} + \text{outside\_m2} = \text{parcel\_area\_m2}$ passes with zero deviation beyond machine floating-point precision.
2. **Precedence Enforcement**: For `PARCEL-05`, although physically inside both `SN-WSG-005` (Zone III) and `SN-WSG-006` (Zone II), 100% of the area is exclusively attributed to the higher-priority `ZONE_II`.
3. **Idempotence**: Running the parcel assessment demo on already-assessed output files skips re-computation and yields identical timestamps and figures.

---

## 4. Test Suite Execution Summary

- **Total Tests**: 27 passed (21 unit tests + 4 PostGIS loader integration tests + 2 parcel screening integration tests).
- **Execution Environment**: Python 3.13.1, PostGIS 16-3.4 (Docker).
- **Pass Rate**: 100% (27 passed in 55.94s).
