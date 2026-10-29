-- Initialize PostGIS extension and staging schema for IRIS-WSG-SN
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS iris_staging;

-- Water Protection Zones staging table
CREATE TABLE IF NOT EXISTS iris_staging.water_protection_zones (
    id BIGSERIAL PRIMARY KEY,
    state_code VARCHAR(10) NOT NULL DEFAULT 'SN',
    source_zone_id VARCHAR(100) NOT NULL,
    zone_class VARCHAR(50) NOT NULL,
    raw_zone_code VARCHAR(100),
    restriction_category VARCHAR(100) NOT NULL DEFAULT 'not_published',
    extraction_rate VARCHAR(100) NOT NULL DEFAULT 'not_published',
    geometry_repaired BOOLEAN NOT NULL DEFAULT FALSE,
    source_attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_crs VARCHAR(50),
    source_url TEXT,
    fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    geom GEOMETRY(MultiPolygon, 25832) NOT NULL,
    CONSTRAINT uq_wsg_state_source_id UNIQUE (state_code, source_zone_id)
);

CREATE INDEX IF NOT EXISTS idx_water_protection_zones_geom 
    ON iris_staging.water_protection_zones USING GIST (geom);

-- Pipeline execution metadata run log
CREATE TABLE IF NOT EXISTS iris_staging.water_protection_runs (
    run_id UUID PRIMARY KEY,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    source_url TEXT,
    records_input INT DEFAULT 0,
    records_accepted INT DEFAULT 0,
    records_rejected INT DEFAULT 0,
    records_loaded INT DEFAULT 0,
    records_updated INT DEFAULT 0,
    records_unchanged INT DEFAULT 0,
    status VARCHAR(50) DEFAULT 'RUNNING',
    error_summary TEXT
);
