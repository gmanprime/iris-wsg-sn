"""Generate representative hand-made test fixtures in Saxony coordinates.

Produces:
- tests/fixtures/zones_input.geojson (EPSG:25832): 9 zone features with all edge cases:
  * valid multipart polygon
  * invalid self-intersecting polygon (bowtie)
  * duplicate source ID (two features with same ID to test in-batch rejection)
  * unmapped zone code
  * missing ID (null)
  * stacked zone II nested inside zone III
  * standard single polygons
- tests/fixtures/zones_epsg25833.gpkg (EPSG:25833):
  * zone declared in EPSG:25833 (UTM 33N) to explicitly exercise reprojection to EPSG:25832
- tests/fixtures/parcels_input.geojson & tests/fixtures/parcels_input.gpkg:
  * parcel inside one zone
  * parcel outside all zones
  * parcel straddling two zones
  * parcel touching only along an edge
  * parcel inside stacked zones (nested II inside III)
  * parcel straddling stacked zone and outer zone
"""

import json
from pathlib import Path
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon, box

FIXTURES_DIR = Path("tests/fixtures")
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

CRS_25832 = "EPSG:25832"
CRS_25833 = "EPSG:25833"

def create_zones():
    features = [
        # 1. Valid multipart polygon (MultiPolygon)
        {
            "type": "Feature",
            "properties": {
                "wsg_id": "SN-WSG-001",
                "schutzzone": "IIIA",
                "wsg_name": "WSG Dresden Nordost (Multipart)",
                "rechtsstand": "festgesetzt",
                "festsetzungsdatum": "2018-05-12"
            },
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [
                    [[
                        [830000.0, 5650000.0],
                        [831000.0, 5650000.0],
                        [831000.0, 5651000.0],
                        [830000.0, 5651000.0],
                        [830000.0, 5650000.0]
                    ]],
                    [[
                        [831200.0, 5650000.0],
                        [832000.0, 5650000.0],
                        [832000.0, 5650800.0],
                        [831200.0, 5650800.0],
                        [831200.0, 5650000.0]
                    ]]
                ]
            }
        },
        # 2. Invalid self-intersecting polygon (Bowtie / Figure-8)
        {
            "type": "Feature",
            "properties": {
                "wsg_id": "SN-WSG-002",
                "schutzzone": "II",
                "wsg_name": "WSG Radebeul (Self-Intersecting)",
                "rechtsstand": "im Verfahren",
                "festsetzungsdatum": "2020-01-15"
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [832500.0, 5650000.0],
                    [833500.0, 5651000.0],
                    [832500.0, 5651000.0],
                    [833500.0, 5650000.0],
                    [832500.0, 5650000.0]
                ]]
            }
        },
        # 3. In-batch duplicate ID: First instance (conflicting with Feature 4)
        {
            "type": "Feature",
            "properties": {
                "wsg_id": "SN-WSG-003",
                "schutzzone": "III",
                "wsg_name": "WSG Pirna Version A",
                "rechtsstand": "festgesetzt",
                "festsetzungsdatum": "2015-11-01"
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [834000.0, 5650000.0],
                    [835000.0, 5650000.0],
                    [835000.0, 5651000.0],
                    [834000.0, 5651000.0],
                    [834000.0, 5650000.0]
                ]]
            }
        },
        # 4. In-batch duplicate ID: Second instance (conflicting with Feature 3)
        {
            "type": "Feature",
            "properties": {
                "wsg_id": "SN-WSG-003",
                "schutzzone": "III",
                "wsg_name": "WSG Pirna Version B",
                "rechtsstand": "festgesetzt",
                "festsetzungsdatum": "2019-03-20"
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [834000.0, 5650000.0],
                    [835100.0, 5650000.0],
                    [835100.0, 5651000.0],
                    [834000.0, 5651000.0],
                    [834000.0, 5650000.0]
                ]]
            }
        },
        # 5. Unmapped zone code (e.g. IV_HISTORIC)
        {
            "type": "Feature",
            "properties": {
                "wsg_id": "SN-WSG-004",
                "schutzzone": "IV_HISTORIC",
                "wsg_name": "WSG Meissen Alter Bestand",
                "rechtsstand": "vorlaeufig",
                "festsetzungsdatum": "1998-07-04"
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [836000.0, 5650000.0],
                    [837000.0, 5650000.0],
                    [837000.0, 5651000.0],
                    [836000.0, 5651000.0],
                    [836000.0, 5650000.0]
                ]]
            }
        },
        # 6. Missing source ID (None / null)
        {
            "type": "Feature",
            "properties": {
                "wsg_id": None,
                "schutzzone": "I",
                "wsg_name": "WSG Ohne Kennung",
                "rechtsstand": "unbekannt",
                "festsetzungsdatum": "2021-09-10"
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [838000.0, 5650000.0],
                    [839000.0, 5650000.0],
                    [839000.0, 5651000.0],
                    [838000.0, 5651000.0],
                    [838000.0, 5650000.0]
                ]]
            }
        },
        # 7. Stacked Outer Zone III (covers 830000..834000, 5653000..5657000)
        {
            "type": "Feature",
            "properties": {
                "wsg_id": "SN-WSG-005",
                "schutzzone": "III",
                "wsg_name": "WSG Coschuetz Outer (Zone III)",
                "rechtsstand": "festgesetzt",
                "festsetzungsdatum": "2016-04-18"
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [830000.0, 5653000.0],
                    [834000.0, 5653000.0],
                    [834000.0, 5657000.0],
                    [830000.0, 5657000.0],
                    [830000.0, 5653000.0]
                ]]
            }
        },
        # 8. Stacked Inner Zone II (nested inside Feature 7: 831500..832500, 5654500..5655500)
        {
            "type": "Feature",
            "properties": {
                "wsg_id": "SN-WSG-006",
                "schutzzone": "II",
                "wsg_name": "WSG Coschuetz Inner (Zone II)",
                "rechtsstand": "festgesetzt",
                "festsetzungsdatum": "2016-04-18"
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [831500.0, 5654500.0],
                    [832500.0, 5654500.0],
                    [832500.0, 5655500.0],
                    [831500.0, 5655500.0],
                    [831500.0, 5654500.0]
                ]]
            }
        },
        # 9. Standard Zone I (Wellhead: 835000..836000, 5654000..5655000)
        {
            "type": "Feature",
            "properties": {
                "wsg_id": "SN-WSG-007",
                "schutzzone": "I",
                "wsg_name": "WSG Coschuetz Fassungsbereich (Zone I)",
                "rechtsstand": "festgesetzt",
                "festsetzungsdatum": "2016-04-18"
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [835000.0, 5654000.0],
                    [836000.0, 5654000.0],
                    [836000.0, 5655000.0],
                    [835000.0, 5655000.0],
                    [835000.0, 5654000.0]
                ]]
            }
        }
    ]

    geojson = {
        "type": "FeatureCollection",
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:EPSG::25832"}
        },
        "features": features
    }

    out_path = FIXTURES_DIR / "zones_input.geojson"
    out_path.write_text(json.dumps(geojson, indent=2), encoding="utf-8")
    print(f"Generated {out_path} ({len(features)} features)")

def create_different_crs_fixture():
    # Feature declared in EPSG:25833 (UTM Zone 33N)
    # Box [410000, 5642000] to [411000, 5643000]
    # Reprojects to EPSG:25832 at roughly [831639, 5651833] to [832624, 5652850]
    geom = box(410000.0, 5642000.0, 411000.0, 5643000.0)
    gdf = gpd.GeoDataFrame(
        [
            {
                "wsg_id": "SN-WSG-CRS33",
                "schutzzone": "II",
                "wsg_name": "WSG Bautzen (Declared EPSG:25833)",
                "rechtsstand": "festgesetzt",
                "festsetzungsdatum": "2021-06-30",
                "geometry": geom
            }
        ],
        crs=CRS_25833
    )
    out_gpkg = FIXTURES_DIR / "zones_epsg25833.gpkg"
    gdf.to_file(out_gpkg, driver="GPKG", layer="water_protection_zones")
    print(f"Generated {out_gpkg} in CRS {CRS_25833} ({len(gdf)} feature)")

def create_clean_batch_fixture():
    # A clean single-batch fixture with unique valid IDs for testing double-load idempotency
    features = [
        {
            "wsg_id": "SN-WSG-001",
            "schutzzone": "IIIA",
            "wsg_name": "WSG Dresden Nordost (Clean Batch)",
            "rechtsstand": "festgesetzt",
            "festsetzungsdatum": "2018-05-12",
            "geometry": box(830000.0, 5650000.0, 831000.0, 5651000.0)
        },
        {
            "wsg_id": "SN-WSG-005",
            "schutzzone": "III",
            "wsg_name": "WSG Coschuetz Outer",
            "rechtsstand": "festgesetzt",
            "festsetzungsdatum": "2016-04-18",
            "geometry": box(830000.0, 5653000.0, 834000.0, 5657000.0)
        },
        {
            "wsg_id": "SN-WSG-006",
            "schutzzone": "II",
            "wsg_name": "WSG Coschuetz Inner",
            "rechtsstand": "festgesetzt",
            "festsetzungsdatum": "2016-04-18",
            "geometry": box(831500.0, 5654500.0, 832500.0, 5655500.0)
        },
        {
            "wsg_id": "SN-WSG-007",
            "schutzzone": "I",
            "wsg_name": "WSG Coschuetz Fassungsbereich",
            "rechtsstand": "festgesetzt",
            "festsetzungsdatum": "2016-04-18",
            "geometry": box(835000.0, 5654000.0, 836000.0, 5655000.0)
        }
    ]
    gdf = gpd.GeoDataFrame(features, crs=CRS_25832)
    out_gpkg = FIXTURES_DIR / "zones_clean_batch.gpkg"
    gdf.to_file(out_gpkg, driver="GPKG", layer="water_protection_zones")
    print(f"Generated {out_gpkg} ({len(gdf)} features)")

    # Also generate updated revision of the clean batch (SN-WSG-007 geometry/name updated)
    features_updated = [dict(f) for f in features]
    features_updated[3]["wsg_name"] = "WSG Coschuetz Fassungsbereich (Updated Revision)"
    features_updated[3]["geometry"] = box(835000.0, 5654000.0, 836100.0, 5655100.0)
    gdf_updated = gpd.GeoDataFrame(features_updated, crs=CRS_25832)
    out_updated_gpkg = FIXTURES_DIR / "zones_clean_batch_updated.gpkg"
    gdf_updated.to_file(out_updated_gpkg, driver="GPKG", layer="water_protection_zones")
    print(f"Generated {out_updated_gpkg} ({len(gdf_updated)} features)")

def create_parcels():
    features = [
        {
            "type": "Feature",
            "properties": {
                "parcel_id": "PARCEL-01",
                "flurnummer": "101/1",
                "gemarkung": "Dresden-Sued",
                "zone_i_m2": None, "zone_i_pct": None,
                "zone_ii_m2": None, "zone_ii_pct": None,
                "zone_iii_m2": None, "zone_iii_pct": None,
                "zone_iiia_m2": None, "zone_iiia_pct": None,
                "zone_iiib_m2": None, "zone_iiib_pct": None,
                "unknown_m2": None, "unknown_pct": None,
                "outside_m2": None, "outside_pct": None
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [835200.0, 5654200.0],
                    [835600.0, 5654200.0],
                    [835600.0, 5654600.0],
                    [835200.0, 5654600.0],
                    [835200.0, 5654200.0]
                ]]
            }
        },
        {
            "type": "Feature",
            "properties": {
                "parcel_id": "PARCEL-02",
                "flurnummer": "205/3",
                "gemarkung": "Klotzsche-Nord",
                "zone_i_m2": None, "zone_i_pct": None,
                "zone_ii_m2": None, "zone_ii_pct": None,
                "zone_iii_m2": None, "zone_iii_pct": None,
                "zone_iiia_m2": None, "zone_iiia_pct": None,
                "zone_iiib_m2": None, "zone_iiib_pct": None,
                "unknown_m2": None, "unknown_pct": None,
                "outside_m2": None, "outside_pct": None
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [845000.0, 5665000.0],
                    [845500.0, 5665000.0],
                    [845500.0, 5665500.0],
                    [845000.0, 5665500.0],
                    [845000.0, 5665000.0]
                ]]
            }
        },
        {
            "type": "Feature",
            "properties": {
                "parcel_id": "PARCEL-03",
                "flurnummer": "312/7",
                "gemarkung": "Dresden-Sued",
                "zone_i_m2": None, "zone_i_pct": None,
                "zone_ii_m2": None, "zone_ii_pct": None,
                "zone_iii_m2": None, "zone_iii_pct": None,
                "zone_iiia_m2": None, "zone_iiia_pct": None,
                "zone_iiib_m2": None, "zone_iiib_pct": None,
                "unknown_m2": None, "unknown_pct": None,
                "outside_m2": None, "outside_pct": None
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [835800.0, 5654200.0],
                    [836400.0, 5654200.0],
                    [836400.0, 5654600.0],
                    [835800.0, 5654600.0],
                    [835800.0, 5654200.0]
                ]]
            }
        },
        {
            "type": "Feature",
            "properties": {
                "parcel_id": "PARCEL-04",
                "flurnummer": "401/2",
                "gemarkung": "Bannewitz",
                "zone_i_m2": None, "zone_i_pct": None,
                "zone_ii_m2": None, "zone_ii_pct": None,
                "zone_iii_m2": None, "zone_iii_pct": None,
                "zone_iiia_m2": None, "zone_iiia_pct": None,
                "zone_iiib_m2": None, "zone_iiib_pct": None,
                "unknown_m2": None, "unknown_pct": None,
                "outside_m2": None, "outside_pct": None
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [836000.0, 5654100.0],
                    [836500.0, 5654100.0],
                    [836500.0, 5654500.0],
                    [836000.0, 5654500.0],
                    [836000.0, 5654100.0]
                ]]
            }
        },
        {
            "type": "Feature",
            "properties": {
                "parcel_id": "PARCEL-05",
                "flurnummer": "550/9",
                "gemarkung": "Coschuetz",
                "zone_i_m2": None, "zone_i_pct": None,
                "zone_ii_m2": None, "zone_ii_pct": None,
                "zone_iii_m2": None, "zone_iii_pct": None,
                "zone_iiia_m2": None, "zone_iiia_pct": None,
                "zone_iiib_m2": None, "zone_iiib_pct": None,
                "unknown_m2": None, "unknown_pct": None,
                "outside_m2": None, "outside_pct": None
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [831800.0, 5654800.0],
                    [832200.0, 5654800.0],
                    [832200.0, 5655200.0],
                    [831800.0, 5655200.0],
                    [831800.0, 5654800.0]
                ]]
            }
        },
        {
            "type": "Feature",
            "properties": {
                "parcel_id": "PARCEL-06",
                "flurnummer": "602/4",
                "gemarkung": "Coschuetz-Ost",
                "zone_i_m2": None, "zone_i_pct": None,
                "zone_ii_m2": None, "zone_ii_pct": None,
                "zone_iii_m2": None, "zone_iii_pct": None,
                "zone_iiia_m2": None, "zone_iiia_pct": None,
                "zone_iiib_m2": None, "zone_iiib_pct": None,
                "unknown_m2": None, "unknown_pct": None,
                "outside_m2": None, "outside_pct": None
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [832300.0, 5654800.0],
                    [832800.0, 5654800.0],
                    [832800.0, 5655200.0],
                    [832300.0, 5655200.0],
                    [832300.0, 5654800.0]
                ]]
            }
        }
    ]

    geojson = {
        "type": "FeatureCollection",
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:EPSG::25832"}
        },
        "features": features
    }

    out_geojson = FIXTURES_DIR / "parcels_input.geojson"
    out_geojson.write_text(json.dumps(geojson, indent=2), encoding="utf-8")
    print(f"Generated {out_geojson} ({len(features)} features)")

    gdf = gpd.read_file(out_geojson)
    gdf.set_crs(CRS_25832, inplace=True, allow_override=True)
    out_gpkg = FIXTURES_DIR / "parcels_input.gpkg"
    gdf.to_file(out_gpkg, driver="GPKG", layer="parcels")
    print(f"Generated {out_gpkg} ({len(gdf)} records in layer 'parcels')")

if __name__ == "__main__":
    create_zones()
    create_different_crs_fixture()
    create_clean_batch_fixture()
    create_parcels()
