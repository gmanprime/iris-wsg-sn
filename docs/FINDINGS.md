# Phase 0 Findings: Saxony WFS Service (`sn_wsg_bestand`)

## 1. Service Connectivity & Access Status
- **Target URL**: `https://geoportal.sachsen.de/wfs/wasserschutz`
- **Target Layer**: `sn_wsg_bestand`
- **Current Status**: **UNREACHABLE / CONNECTION TIMEOUT**
- **Observed Behavior**:
  - DNS resolves `geoportal.sachsen.de` to `31.12.58.21`.
  - TCP / TLS handshake to `31.12.58.21:443` times out (`Connection timed out after 10010ms`, Python `_ssl.c:1011: The handshake operation timed out`).
  - Possible causes: Geo-blocking / IP filtering outside Germany, internal state network restrictions, or temporary server downtime.
- **Rule Adherence**: Per Core Rule 1 & Core Rule 6 ("Do not bypass access restrictions. If the live service is down, blocked, or requires authentication, stop and tell me. A fixture-based demonstrator is acceptable and we document the limitation. If the sandbox cannot reach the server, say so and stop. I will run the script on my own machine and paste the output back. Do not invent findings."), no findings are invented.

## 2. Standalone Inspection Script
- Created [`scripts/phase0_inspect_wfs.py`](../scripts/phase0_inspect_wfs.py).
- Self-contained using Python standard library (no extra pip packages needed).
- Saves raw XML/JSON responses to `raw_responses/`:
  - `raw_responses/get_capabilities.xml`
  - `raw_responses/describe_feature_type.xsd`
  - `raw_responses/get_feature_sample.json` (or `.xml`)
- Command to run locally:
  ```bash
  python scripts/phase0_inspect_wfs.py
  # or using uv:
  uv run python scripts/phase0_inspect_wfs.py
  ```

## 3. Discovered Facts (Awaiting User Host Output / Approval)
*The fields below will be populated directly from the script output when pasted:*
- **Supported WFS Versions**: [Awaiting output]
- **Exact Layer Name**: [Awaiting output, default: `sn_wsg_bestand`]
- **Declared CRS & Axis Order**: [Awaiting output, e.g., EPSG:25833, EPSG:4326, EPSG:25832, etc.]
- **Server Feature Cap & Paging Support**: [Awaiting output]
- **Full Schema (Attributes & Types)**: [Awaiting output]
- **Zone Class Attribute & Distinct Values**: [Awaiting output]
- **Source Zone ID & Uniqueness**: [Awaiting output]
- **Published Update / Date Fields**: [Awaiting output]
- **OWS ExceptionReport / Access Errors**: [Handshake timeout to live service recorded]
