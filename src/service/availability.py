"""WFS Service Availability and Fetch Module (Step 2).

Provides:
- check_availability(): Tests service health, returning status (UP, DEGRADED, DOWN)
  and reason (timeout, connection/TLS error, HTTP 4xx/5xx, ExceptionReport inside 200, layer missing).
- fetch_zones(): Refuses to fetch unless service availability is UP.
"""

from __future__ import annotations

import io
import ssl
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Dict, Optional

import geopandas as gpd


@dataclass
class ServiceStatus:
    status: str  # "UP", "DEGRADED", "DOWN"
    reason: str
    details: Optional[str] = None

    @property
    def is_up(self) -> bool:
        return self.status == "UP"


def _strip_ns(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def check_availability(
    endpoint_url: str = "https://geoportal.sachsen.de/wfs/wasserschutz",
    layer_name: str = "sn_wsg_bestand",
    timeout: int = 10,
    http_client=None,
) -> ServiceStatus:
    """Check health and layer availability of a WFS service.

    Returns:
        ServiceStatus with status in ("UP", "DEGRADED", "DOWN") and explicit reason.
    """
    cap_url = f"{endpoint_url.rstrip('?')}?SERVICE=WFS&REQUEST=GetCapabilities"
    client = http_client or urllib.request.urlopen

    try:
        req = urllib.request.Request(
            cap_url,
            headers={"User-Agent": "IRIS-WSG-SN/1.0", "Accept": "application/xml, text/xml, */*"},
        )
        with client(req, timeout=timeout) as resp:
            content = resp.read() if hasattr(resp, "read") else b""
            status_code = getattr(resp, "status", 200)

    except urllib.error.HTTPError as he:
        return ServiceStatus(status="DOWN", reason=f"HTTP {he.code}", details=str(he))
    except (TimeoutError, urllib.error.URLError) as ue:
        reason_str = str(ue.reason) if hasattr(ue, "reason") else str(ue)
        if any(term in reason_str.lower() for term in ["ssl", "tls", "handshake", "certificate"]):
            return ServiceStatus(status="DOWN", reason="connection/TLS error", details=reason_str)
        if "timed out" in reason_str.lower() or isinstance(ue, TimeoutError):
            return ServiceStatus(status="DOWN", reason="timeout", details=reason_str)
        if any(term in reason_str.lower() for term in ["getaddrinfo", "refused", "name or service not known"]):
            return ServiceStatus(status="DOWN", reason="connection/TLS error", details=reason_str)
        return ServiceStatus(status="DOWN", reason="connection/TLS error", details=reason_str)
    except Exception as ex:
        msg = str(ex).lower()
        if "timed out" in msg:
            return ServiceStatus(status="DOWN", reason="timeout", details=str(ex))
        return ServiceStatus(status="DOWN", reason="connection/TLS error", details=str(ex))

    # Parse XML response
    try:
        root = ET.fromstring(content)
    except ET.ParseError as pe:
        return ServiceStatus(status="DEGRADED", reason="Invalid XML response", details=str(pe))

    # Check for OWS / WFS ExceptionReport inside HTTP 200
    root_tag = _strip_ns(root.tag).lower()
    if "exception" in root_tag:
        text_elems = [el.text.strip() for el in root.iter() if el.text and el.text.strip()]
        exc_summary = " ".join(text_elems[:3])
        return ServiceStatus(
            status="DEGRADED",
            reason="ExceptionReport inside a 200",
            details=exc_summary or "OWS ExceptionReport returned",
        )

    # Search for layer_name in FeatureTypeList
    layers_found = []
    for elem in root.iter():
        if _strip_ns(elem.tag) == "FeatureType":
            for child in elem:
                if _strip_ns(child.tag) == "Name" and child.text:
                    layers_found.append(child.text.strip())

    if layer_name in layers_found or any(layer_name in name for name in layers_found):
        return ServiceStatus(status="UP", reason="service healthy and layer found")

    return ServiceStatus(
        status="DEGRADED",
        reason="layer missing",
        details=f"Layer '{layer_name}' not listed in capabilities. Available: {layers_found[:5]}",
    )


def fetch_zones(
    endpoint_url: str = "https://geoportal.sachsen.de/wfs/wasserschutz",
    layer_name: str = "sn_wsg_bestand",
    timeout: int = 15,
    http_client=None,
    count: Optional[int] = None,
) -> gpd.GeoDataFrame:
    """Fetch protection zones from WFS. Refuses to fetch unless availability is UP."""
    status = check_availability(
        endpoint_url=endpoint_url,
        layer_name=layer_name,
        timeout=timeout,
        http_client=http_client,
    )

    if not status.is_up:
        raise RuntimeError(
            f"Cannot fetch zones: WFS service is {status.status} ({status.reason}). Details: {status.details}"
        )

    # Request GeoJSON feature collection
    count_clause = f"&COUNT={count}" if count else ""
    feat_url = f"{endpoint_url.rstrip('?')}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&typeNames={layer_name}&OUTPUTFORMAT=application/json{count_clause}"

    client = http_client or urllib.request.urlopen
    req = urllib.request.Request(feat_url, headers={"User-Agent": "IRIS-WSG-SN/1.0"})
    with client(req, timeout=timeout) as resp:
        content = resp.read()

    return gpd.read_file(io.BytesIO(content))
