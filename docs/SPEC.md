# IRIS-WSG-SN: Saxony Drinking Water Protection WFS Ingestion Specification

## 1. Project Overview & Objective
- **Task ID**: TASK 074 | IRIS-WSG-SN
- **Source Endpoint**: `https://geoportal.sachsen.de/wfs/wasserschutz`
- **WFS Layer**: `sn_wsg_bestand`
- **Integration Pattern**: OGC WFS / GeoPandas / PostGIS
- **Data Destination**: `iris_staging.water_protection_zones`
- **Objective**: Build a robust, idempotent Python data-ingestion pipeline that pulls drinking-water protection zone polygons for Saxony (LfULG) from the public WFS, validates and normalizes them, reprojects them to EPSG:25832, loads them idempotently into PostGIS, provides parcel containment/intersection testing, and records provenance and run metadata for site-permitting and groundwater restriction screening.

## 2. Implementation Scope
- **Service Inspection & Fetch**: Inspect WFS capabilities, version, layer schema, axis order, paging, and retrieve zone geometries and source attributes. Support smoke, bbox, and full-load fetch modes.
- **Validation & Mapping**: Map official zone codes to normalized zone classes via an explicit lookup table. Mark absent or unpopulated attributes (e.g. restriction categories, extraction rates) explicitly as "not published" or unknown. Preserve raw source attributes in JSONB. Reject invalid records with explicit reason codes into a rejected log.
- **Geospatial Processing**: Validate and clean polygon geometries (handling multipart/MultiPolygon consistency and repairing or rejecting invalid geometries with documented methods), reproject from the declared source CRS to EPSG:25832.
- **Parcel Screening**: Test parcel-level geospatial relationships (containment, intersection, touch-only) against protection zones, accounting for stacked or overlapping zones (e.g., Zone II inside Zone III).
- **Idempotent Storage & Provenance**: Upsert into PostGIS table `iris_staging.water_protection_zones` keyed on `(state_code, source_zone_id)` (default `state_code = 'SN'`). Maintain spatial index (GIST). Log execution runs and metadata (row counts, provenance, timestamps, errors, limitations) into a dedicated run-log table.

## 3. Acceptance Criteria
- Official zone classifications trace to a real source attribute via an explicit lookup table and are not inferred from fragile substring matching or regex guessing.
- Geospatial processing correctly handles MultiPolygons, reprojection to EPSG:25832, and parcel intersection tests.
- Duplicate-load validation succeeds: re-running ingestion leaves row count unchanged and updates modified rows idempotently.
- Tests must fail when code or behavior is deliberately broken.

## 4. Deliverables
- Python 3.11+ source code adhering to modular architecture.
- Pinned dependency configuration (`requirements.txt` / `pyproject.toml`).
- Configuration via environment variables with `.env.example` (no secrets in repo).
- Containerization: `Dockerfile` and `docker-compose.yml` (app + PostGIS).
- Comprehensive automated test suite with representative offline fixtures/mocks.
- `README.md` covering provenance, run instructions, schema mapping, assumptions, limitations, and example validation query.
- `QUALITY_REPORT.md` analyzing run metrics, accepted vs. rejected counts, edge cases, and acceptance evidence.

## 5. Core Rules (Mandatory Across All Sub-Agents)
1. **Do not assume the source schema.** Field names, zone code values, ID uniqueness and CRS are unknown until Phase 0 output exists and I have approved it.
2. **Zone classes trace to a real source attribute via an explicit lookup table.** No substring or regex guessing (for example, "III" contains "II"). Unmapped values become `UNKNOWN` and are counted.
3. **Verify library APIs** against the installed version's docs or source. Do not rely on remembered behavior. If something cannot be verified, say so.
4. **No secrets in the repo.** Config comes from environment variables, with a `.env.example`.
5. **Staging only.** Never write to `iris_core` or any production schema. DB work targets the docker-compose PostGIS.
6. **Do not bypass access restrictions.** If the live service is down, blocked, or requires authentication, stop and tell me. A fixture-based demonstrator is acceptable and we document the limitation.
7. **Do not clone, run, or copy third-party repos**, including `amaurisantosjr/iris-sample` mentioned in the email.
8. **Python 3.11+, pinned dependencies.**
9. **Run the tests and show real output.** Never claim something works without running it. If something could not be run, say so.
