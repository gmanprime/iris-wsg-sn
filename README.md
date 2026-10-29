# IRIS-WSG-SN: Saxony Drinking Water Protection Ingestion Pipeline

Python data ingestion and spatial screening module for Saxony (LfULG) drinking water protection zones (*Wasserschutzgebiete* / WSG).

---

## 1. Limitations & Assumptions

### Live WFS Service Connectivity
Attempts to connect directly to the official Saxony WFS endpoint (`https://geoportal.sachsen.de/wfs/wasserschutz`, layer `sn_wsg_bestand`) timed out during the SSL/TLS handshake:
```text
Connection timed out after 10010ms (_ssl.c:1011: The handshake operation timed out)
```
This is likely caused by state network geo-restrictions or IP filtering on their portal gateway. Because a timeout occured when testing the handshake, I implemented this as an offline fixture demonstrator as permitted in the candidate notes of the assignment.

### Schema Assumptions
- Field names (`wsg_id`, `schutzzone`) are assumed based on standard German environmental WFS patterns.
- All schema configurations are isolated in `config/wsg_config.json`. The pipeline never hardcodes column names in python code; if the live service returns different attributes, they only need to be adjusted in the config.
- Restriction categories and extraction rates are not assumed or filled in from German water law; they default explicitly to `not_published`.

---

## 2. Pipeline Overview

```
[ Raw GeoJSON / WFS Input ]
           │
           ▼
[ Schema Validation ] ───── (Missing required columns) ──► Stops with clear error
           │
           ▼
[ Row Checks ] ────────── (Null ID / Empty Geom / Conflicting Dups) ──► Rejection Log
           │
           ▼
[ Geometry Repair ] ─────► shapely.make_valid -> MultiPolygon (EPSG:25832)
           │
           ▼
[ Traceable Zone Mapping ] ─► config lookup (Unmapped codes -> "UNKNOWN")
           │
           ▼
[ PostGIS Upsert ] ──────► iris_staging.water_protection_zones
                            (ON CONFLICT DO UPDATE, skips unchanged rows via IS DISTINCT FROM)
           │
           ▼
[ Parcel Screening Demo ] ► Reads PostGIS zones -> Dissolves same classes ->
                            Priority overlay (I > II > IIIA > IIIB > III > UNKNOWN) ->
                            Outputs assessed GeoPackage (output/parcels_assessed.gpkg)
```

Each class is evaluated in a seperate priority step so higher protection levels take precedence over lower ones.

---

## 3. Data Contract & Provenance

- **Provenance**: Records loaded from fixtures are tagged with `source_url = "fixture:<path>"` (for example `fixture:tests/fixtures/zones_input.geojson`). They do not fake a live URL.
- **Staging Table (`iris_staging.water_protection_zones`)**:
  - Key: `(state_code, source_zone_id)`
  - Target CRS: `EPSG:25832` (ETRS89 / UTM Zone 32N)
  - Geometry: `GEOMETRY(MultiPolygon, 25832)` with GiST spatial indexing.
  - Raw attributes: Kept in full as JSONB in `source_attributes`.
  - Repair flag: `geometry_repaired` (boolean) tracks if topological fixing took place.
- **Run Tracking (`iris_staging.water_protection_runs`)**:
  - Logs execution timestamps, input count, accepted count, rejected count, inserted, updated, and unchanged counts.
  - Ensures clean auditability on the PostGIS persistance layer.

---

## 4. How to Run

### Option A: Quickstart with Docker Compose (Recommended)

1. Set up environment:
   ```bash
   cp .env.example .env
   ```
2. Build and run the entire pipeline:
   ```bash
   docker compose up --build
   ```
   This starts PostGIS, waits for the healthcheck to pass, runs the ingestion pipeline and parcel screening demo in the `app` container, and outputs the result to `output/parcels_assessed.gpkg`.

3. To keep PostGIS running in the background for local development:
   ```bash
   docker compose up -d postgis
   ```

### Option B: Local Python Environment

1. Create a virtual environment and install requirements:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Run the offline pipeline:
   ```bash
   python src/cli.py --mode fixture
   ```

3. Run the automated test suite:
   ```bash
   pytest -v
   ```

---

## 5. Parcel Screening Demo & Validation Query

The parcel assessment module reads `tests/fixtures/parcels_input.gpkg`, queries cached zones from PostGIS, and calculates:
- Exact coverage area in m² and percentage per zone class.
- `outside_m2` and `outside_pct`.
- Priority attribution: higher-priority zones preempt lower ones (`ZONE_I > ZONE_II > ZONE_IIIA > ZONE_IIIB > ZONE_III > UNKNOWN`).
- Area invariant: for every parcel, sum of zone areas + outside area equals total parcel area.

A standalone SQL validation query is provided in `sql/validation_query.sql`. You can execute it directly against PostGIS:
```bash
psql -h 127.0.0.1 -U iris -d iris_dev -f sql/validation_query.sql
```
Sample query output is documented in `docs/example_result.md`.
