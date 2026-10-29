"""Phase 0: Standalone read-only WFS inspection script for IRIS-WSG-SN.

Queries GetCapabilities, DescribeFeatureType, and GetFeature (sample of ~10 features).
Saves raw responses to raw_responses/ and prints structured inspection details.
Uses only Python standard library so it runs in any standard Python 3.10+ environment.
"""

import json
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

BASE_URL = "https://geoportal.sachsen.de/wfs/wasserschutz"
RAW_DIR = Path("raw_responses")
RAW_DIR.mkdir(parents=True, exist_ok=True)


def fetch_url(url: str, timeout: int = 30) -> bytes:
    print(f"Fetching: {url}")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) IRIS-WSG-SN-Inspection/1.0",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def strip_ns(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def main():
    print("==================================================")
    print("=== Phase 0: Saxony WFS Service Inspection     ===")
    print("==================================================")

    # 1. GetCapabilities
    cap_url = f"{BASE_URL}?SERVICE=WFS&REQUEST=GetCapabilities"
    try:
        cap_bytes = fetch_url(cap_url)
        cap_path = RAW_DIR / "get_capabilities.xml"
        cap_path.write_bytes(cap_bytes)
        print(f"[OK] Saved GetCapabilities ({len(cap_bytes)} bytes) -> {cap_path}")
    except Exception as e:
        print(f"\n[FAIL] ERROR reaching GetCapabilities at {BASE_URL}:", file=sys.stderr)
        print(f"       {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        cap_root = ET.fromstring(cap_bytes)
    except ET.ParseError as pe:
        print(f"[FAIL] Unable to parse GetCapabilities XML: {pe}", file=sys.stderr)
        print(cap_bytes[:1000].decode("utf-8", errors="replace"))
        sys.exit(1)

    # Check for ExceptionReport
    if "ExceptionReport" in strip_ns(cap_root.tag):
        print(f"[FAIL] Server returned OWS ExceptionReport:")
        print(cap_bytes.decode("utf-8", errors="replace"))
        sys.exit(1)

    default_version = cap_root.attrib.get("version", "unknown")
    print(f"\n* Default WFS Version: {default_version}")

    # Inspect all supported versions
    versions = set()
    if default_version != "unknown":
        versions.add(default_version)
    for elem in cap_root.iter():
        clean = strip_ns(elem.tag)
        if clean in ("ServiceTypeVersion", "DefaultVersion"):
            if elem.text:
                versions.add(elem.text.strip())
        elif clean == "Value" and elem.text and (elem.text.startswith("1.") or elem.text.startswith("2.")):
            versions.add(elem.text.strip())
    print(f"* Supported WFS Versions: {sorted(list(versions))}")

    # Inspect Operations & Constraints (CountDefault, ResultType, paging)
    print("\n* Inspecting Operations & Constraints:")
    for elem in cap_root.iter():
        clean = strip_ns(elem.tag)
        if clean == "Constraint":
            name = elem.attrib.get("name")
            vals = [v.text.strip() for v in elem.iter() if strip_ns(v.tag) == "Value" and v.text]
            if name in ("CountDefault", "ResultType", "Paging", "StandardResponse", "InspireConformity"):
                print(f"  - Constraint {name}: {vals}")

    # Inspect FeatureTypeList
    feature_types = []
    for elem in cap_root.iter():
        if strip_ns(elem.tag) == "FeatureType":
            name, title, default_crs, other_crs = None, None, None, []
            for child in elem:
                ctag = strip_ns(child.tag)
                if ctag == "Name":
                    name = child.text.strip() if child.text else None
                elif ctag == "Title":
                    title = child.text.strip() if child.text else None
                elif ctag in ("DefaultCRS", "DefaultSRS"):
                    default_crs = child.text.strip() if child.text else None
                elif ctag in ("OtherCRS", "OtherSRS"):
                    if child.text:
                        other_crs.append(child.text.strip())
            if name:
                feature_types.append({
                    "name": name,
                    "title": title,
                    "default_crs": default_crs,
                    "other_crs": other_crs
                })

    print(f"\n* Found {len(feature_types)} FeatureType(s):")
    target_ft = None
    for ft in feature_types:
        print(f"  - Name: {ft['name']}")
        print(f"    Title: {ft['title']}")
        print(f"    Default CRS: {ft['default_crs']}")
        print(f"    Other CRS count: {len(ft['other_crs'])}")
        if "sn_wsg_bestand" in ft["name"]:
            target_ft = ft

    if not target_ft:
        print("  [WARN] 'sn_wsg_bestand' not found in exact matching! Using 'sn_wsg_bestand' directly.")
        layer_name = "sn_wsg_bestand"
    else:
        layer_name = target_ft["name"]
        print(f"\n=> Target layer resolved: '{layer_name}'")

    chosen_version = "2.0.0" if "2.0.0" in versions else ("1.1.0" if "1.1.0" in versions else "1.0.0")
    type_param = "typeNames" if chosen_version == "2.0.0" else "typeName"
    count_param = "count=10" if chosen_version == "2.0.0" else "maxFeatures=10"
    print(f"* Selected WFS Version for queries: {chosen_version} (Param: {type_param})")

    # 2. DescribeFeatureType
    desc_url = f"{BASE_URL}?SERVICE=WFS&VERSION={chosen_version}&REQUEST=DescribeFeatureType&{type_param}={layer_name}"
    try:
        desc_bytes = fetch_url(desc_url)
        desc_path = RAW_DIR / "describe_feature_type.xsd"
        desc_path.write_bytes(desc_bytes)
        print(f"[OK] Saved DescribeFeatureType ({len(desc_bytes)} bytes) -> {desc_path}")
        
        desc_root = ET.fromstring(desc_bytes)
        print("\n=== DescribeFeatureType: Schema Attributes ===")
        fields = []
        for elem in desc_root.iter():
            if strip_ns(elem.tag) == "element" and "name" in elem.attrib:
                fname = elem.attrib.get("name")
                ftype = elem.attrib.get("type", "complex/embedded")
                nillable = elem.attrib.get("nillable", "unspecified")
                min_occurs = elem.attrib.get("minOccurs", "1")
                fields.append((fname, ftype, nillable, min_occurs))
                print(f"  - {fname:<25} Type: {ftype:<30} (nillable={nillable}, minOccurs={min_occurs})")
    except Exception as e:
        print(f"[FAIL] DescribeFeatureType query failed: {e}")

    # 3. GetFeature (Sample 10 features)
    # Try GeoJSON first, fall back to GML/XML
    feat_json_url = f"{BASE_URL}?SERVICE=WFS&VERSION={chosen_version}&REQUEST=GetFeature&{type_param}={layer_name}&{count_param}&OUTPUTFORMAT=application/json"
    feat_xml_url = f"{BASE_URL}?SERVICE=WFS&VERSION={chosen_version}&REQUEST=GetFeature&{type_param}={layer_name}&{count_param}"

    records = []
    print("\n* Requesting sample features (GeoJSON test)...")
    try:
        resp_json = fetch_url(feat_json_url)
        json_path = RAW_DIR / "get_feature_sample.json"
        json_path.write_bytes(resp_json)
        print(f"[OK] Saved GeoJSON response ({len(resp_json)} bytes) -> {json_path}")
        data = json.loads(resp_json)
        features = data.get("features", [])
        print(f"[OK] Parsed GeoJSON successfully. Feature count: {len(features)}")
        for f in features:
            props = dict(f.get("properties", {}))
            props["__geom_type__"] = f.get("geometry", {}).get("type")
            records.append(props)
    except Exception as e:
        print(f"[INFO] GeoJSON failed or not supported ({e}). Fetching XML/GML...")
        try:
            resp_xml = fetch_url(feat_xml_url)
            xml_path = RAW_DIR / "get_feature_sample.xml"
            xml_path.write_bytes(resp_xml)
            print(f"[OK] Saved XML response ({len(resp_xml)} bytes) -> {xml_path}")
            xroot = ET.fromstring(resp_xml)
            # Find feature members
            for member in xroot.iter():
                clean_tag = strip_ns(member.tag)
                if clean_tag in ("sn_wsg_bestand", "featureMember", "member"):
                    # Inspect children of feature
                    props = {}
                    for child in member:
                        ctag = strip_ns(child.tag)
                        if "geom" in ctag.lower() or "the_geom" in ctag.lower() or "shape" in ctag.lower():
                            props["__geom_type__"] = ctag
                        else:
                            props[ctag] = child.text
                    if props:
                        records.append(props)
            print(f"[OK] Parsed XML. Feature count extracted: {len(records)}")
        except Exception as e2:
            print(f"[FAIL] XML GetFeature query failed: {e2}")

    # 4. Analyze Sample Records
    if records:
        print("\n==================================================")
        print("=== Feature Sample Analysis Summary             ===")
        print("==================================================")
        print(f"Total sample features analyzed: {len(records)}")
        all_keys = sorted(list(set(k for r in records for k in r.keys() if not k.startswith("__"))))
        print(f"\nAll attributes found across features ({len(all_keys)}):")
        for k in all_keys:
            sample_vals = [r.get(k) for r in records if r.get(k) is not None]
            unique_count = len(set(sample_vals))
            print(f"  - {k:<25} Present: {len(sample_vals)}/{len(records)} | Unique vals: {unique_count} | Examples: {sample_vals[:3]}")

        print("\n* Candidate ID attributes (check uniqueness):")
        for k in all_keys:
            vals = [r.get(k) for r in records]
            if len(set(vals)) == len(records) and None not in vals:
                print(f"  [CANDIDATE ID] '{k}' is 100% unique across all {len(records)} records")

        print("\n* Candidate Zone Class attributes (look for Zone I, II, III, IIIA, etc.):")
        for k in all_keys:
            vals = [str(r.get(k)) for r in records if r.get(k) is not None]
            counter = Counter(vals)
            # Look for values typical of zone classes
            if any(term in " ".join(counter.keys()) for term in ["I", "II", "III", "Zone", "Schutz", "WSG"]):
                print(f"  [CANDIDATE ZONE] '{k}' distinct values: {dict(counter)}")

        print("\n* Date / Update attributes:")
        for k in all_keys:
            if any(t in k.lower() for t in ["datum", "date", "aktual", "stand", "erstell", "aend"]):
                vals = [r.get(k) for r in records if r.get(k) is not None]
                print(f"  [DATE FIELD] '{k}': sample values {vals[:3]}")
    else:
        print("\n[WARN] No sample features could be parsed.")

    print("\nPhase 0 inspection complete.")

if __name__ == "__main__":
    main()
