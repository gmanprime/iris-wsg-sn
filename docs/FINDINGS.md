# Investigation Notes: Saxony WFS Service (`sn_wsg_bestand`)

## 1. Service Connectivity & Access Status
- **Target URL**: `https://geoportal.sachsen.de/wfs/wasserschutz`
- **Target Layer**: `sn_wsg_bestand`
- **Observed Behavior**:
  - DNS lookup resolves `geoportal.sachsen.de` to IP `31.12.58.21`.
  - Connecting directly to port 443 fails during the SSL/TLS handshake: `Connection timed out after 10010ms` (Python `_ssl.c:1011: The handshake operation timed out`).
  - Most likely explanation is regional geo-blocking or IP filtering enforced by the state network for Saxony public portals, or temporary maintenance on their gateway.
  - Rather than making up live data or attempting to bypass network controls, I switched to the fixture-based approach explicitly allowed in the assignment notes.

## 2. Standalone Inspection Tool
To inspect the live service once network access is available, I wrote `scripts/phase0_inspect_wfs.py`. It uses only the Python standard library so it does not need extra dependencies:
```bash
python scripts/phase0_inspect_wfs.py
```
This queries `GetCapabilities`, `DescribeFeatureType`, and downloads a small sample of features into `raw_responses/` for schema verification.

## 3. Assumptions Made for the Demonstrator
Because the live schema could not be retrieved over the wire:
- Field names `wsg_id` and `schutzzone` are assumed and flagged as such in `config/wsg_config.json`.
- Zone codes (`I`, `II`, `IIIA`, `IIIB`, `III`) are mapped through the config lookup.
- If the real service uses different attribute names once reached, only `config/wsg_config.json` needs to be updated, the ingestion code itself does not hardcode any column names.
