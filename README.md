# IRIS-WSG-SN: Saxony Drinking Water Protection Ingestion Pipeline

A production-grade Python data ingestion and spatial screening module for Saxony (LfULG) drinking water protection zones (*Wasserschutzgebiete* / WSG).

---

## 1. Important Limitations & Project Assumptions

> [!WARNING]
> **Live WFS Unreachable**: Direct connection attempts to the official Saxony WFS (`https://geoportal.sachsen.de/wfs/wasserschutz`, layer `sn_wsg_bestand`) timed out during the TLS handshake (`Connection timed out after 10010ms` / `_ssl.c:1011: The handshake operation timed out`) due to network/firewall geo-restrictions.

- **Fixture-Based Demonstrator**: As explicitly permitted in the assignment specification, this pipeline implements the complete ingestion, normalization, PostGIS storage, and parcel screening flow using offline hand-made fixtures.
- **Assumed Schema**: Source field names (`wsg_id`, `schutzzone`, etc.) are **ASSUMED** based on typical German environmental authority WFS specifications. All attribute names and zone lookup mappings are unverified against live Saxony data.
- **Config-Driven Architecture**: Schema mapping is strictly isolated in [`config/wsg_config.json`](file:///c:/Users/yonat/Documents/@Projects/IRIS%20Project%20Application/config/wsg_config.json). The pipeline never hardcodes schema names. If input data differs from the configuration, it stops with a descriptive error listing the columns actually present.
- **Unpublished Legal Fields**: Restriction categories and extraction rates are not assumed or guessed from general German water law; they default explicitly to `'not_published'`.

---

## 2. Pipeline Architecture & Workflow

```
[ Raw WFS / Fixture GeoJSON ]
             │
             ▼
  [ Schema Validation ] ────── (Missing required columns) ──► Fail immediately (SchemaMismatchError)
             │
             ▼
   [ Row-Level Checks ] ────── (Null ID / Empty Geom / Duplicate Conflict) ──► Rejected Log
             │
             ▼
[ Geometry Repair & Normalization ] ──► shapely.make_valid -> MultiPolygon (EPSG:25832)
             │
             ▼
 [ Traceable Zone Lookup ] ──► config["zone_lookup"] (Unmapped -> "UNKNOWN")
             │
             ▼
 [ Idempotent PostGIS Upsert ] ──► iris_staging.water_protection_zones ON CONFLICT (state_code, source_zone_id)
                                    (Skips unchanged records via IS DISTINCT FROM)
                                    (Records run log to iris_staging.water_protection_runs)
             │
             ▼
[ Parcel Screening Demo ] ──► Reads cached PostGIS zones -> Dissolves by class ->
                              Exclusive priority overlay (I > II > IIIA > IIIB > III > UNKNOWN) ->
                              Generates assessed GeoPackage (output/parcels_assessed.gpkg)
```

---

## 3. Provenance & Staging Data Contract

- **Provenance Format**: Records ingested from test files carry `source_url = "fixture:<path>"` (e.g. `fixture:tests/fixtures/zones_input.geojson`). They never fabricate the live geoportal URL.
- **Staging Table (`iris_staging.water_protection_zones`)**:
  - Key: `(state_code, source_zone_id)`
  - Target CRS: `EPSG:25832` (ETRS89 / UTM Zone 32N)
  - `geom`: `GEOMETRY(MultiPolygon, 25832)` with GiST spatial index.
  - Raw attributes: Complete unmodified input attributes preserved as `JSONB` in `source_attributes`.
  - Flags: `geometry_repaired` (`bool`) flags any polygon that required topological repair.
- **Run Log Table (`iris_staging.water_protection_runs`)**:
  - Tracks `run_id`, timestamps, records input, accepted, rejected, inserted, updated, unchanged, and status.

---

## 4. Run Instructions

### Prerequisites
- Docker & Docker Compose
- Python 3.11+ (Python 3.13 recommended)

### Quickstart with Docker Compose

1. **Start PostGIS and Run Pipeline**:
   ```bash
   # Copy environment config
   cp .env.example .env

   # Bring up PostGIS and execute the pipeline container
   docker compose up --build
   ```
   The `app` container will wait for `postgis` to report healthy, execute the complete fixture pipeline, and write the screened parcels to `output/parcels_assessed.gpkg`.

2. **Run PostGIS only (for local development & testing)**:
   ```bash
   docker compose up -d postgis
   ```

### Local Python Environment

1. **Create and activate venv**:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate
   ```

2. **Install pinned dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the Offline Pipeline CLI**:
   ```bash
   python src/cli.py --mode fixture
   ```

4. **Run the Full Test Suite**:
   ```bash
   pytest -v
   ```

---

## 5. Parcel Screening Demo & Validation Query

The parcel demo reads `tests/fixtures/parcels_input.gpkg`, queries PostGIS cached zones, and computes:
- Exact area coverage in m² and percentage per zone class.
- `outside_m2` and `outside_pct`.
- **Exclusive Priority**: Higher priority zones preempt lower ones (`ZONE_I > ZONE_II > ZONE_IIIA > ZONE_IIIB > ZONE_III > UNKNOWN`).
- Tested invariants: $\sum \text{zone\_m2} + \text{outside\_m2} = \text{parcel\_area\_m2}$ (exact within float tolerance).

To run the standalone PostGIS validation query:
```bash
# See sql/validation_query.sql and docs/example_result.md
psql -h 127.0.0.1 -U iris -d iris_dev -f sql/validation_query.sql
```
