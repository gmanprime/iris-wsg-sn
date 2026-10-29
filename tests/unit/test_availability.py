"""Unit tests for WFS Service Availability and Fetch (Step 2).

All tests use strictly MOCKED HTTP responses. Never contacts live servers.
"""

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch
import pytest

from src.service.availability import check_availability, fetch_zones

MOCK_CAPABILITIES_VALID = b"""<?xml version="1.0" encoding="UTF-8"?>
<wfs:WFS_Capabilities version="2.0.0" xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:ows="http://www.opengis.net/ows/1.1">
  <wfs:FeatureTypeList>
    <wfs:FeatureType>
      <wfs:Name>sn_wsg_bestand</wfs:Name>
      <wfs:Title>Wasserschutzgebiete Sachsen</wfs:Title>
      <wfs:DefaultCRS>urn:ogc:def:crs:EPSG::25832</wfs:DefaultCRS>
    </wfs:FeatureType>
  </wfs:FeatureTypeList>
</wfs:WFS_Capabilities>
"""

MOCK_CAPABILITIES_LAYER_MISSING = b"""<?xml version="1.0" encoding="UTF-8"?>
<wfs:WFS_Capabilities version="2.0.0" xmlns:wfs="http://www.opengis.net/wfs/2.0">
  <wfs:FeatureTypeList>
    <wfs:FeatureType>
      <wfs:Name>other_unrelated_layer</wfs:Name>
      <wfs:Title>Other Layer</wfs:Title>
    </wfs:FeatureType>
  </wfs:FeatureTypeList>
</wfs:WFS_Capabilities>
"""

MOCK_EXCEPTION_REPORT_200 = b"""<?xml version="1.0" encoding="UTF-8"?>
<ows:ExceptionReport version="2.0.0" xmlns:ows="http://www.opengis.net/ows/1.1">
  <ows:Exception exceptionCode="OperationNotSupported">
    <ows:ExceptionText>Service is undergoing scheduled maintenance</ows:ExceptionText>
  </ows:Exception>
</ows:ExceptionReport>
"""

MOCK_GEOJSON_FEATURES = json.dumps({
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"wsg_id": "SN-001", "schutzzone": "I"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[830000, 5650000], [831000, 5650000], [831000, 5651000], [830000, 5651000], [830000, 5650000]]]
            }
        }
    ]
}).encode("utf-8")


def _make_mock_response(content: bytes, status: int = 200):
    mock_resp = MagicMock()
    mock_resp.read.return_value = content
    mock_resp.status = status
    mock_resp.__enter__.return_value = mock_resp
    return mock_resp


def test_availability_timeout():
    mock_client = MagicMock(side_effect=TimeoutError("The read operation timed out"))
    res = check_availability(http_client=mock_client)
    assert res.status == "DOWN"
    assert res.reason == "timeout"
    assert not res.is_up


def test_availability_connection_tls_error():
    mock_client = MagicMock(side_effect=urllib.error.URLError("SSL handshake operation timed out"))
    res = check_availability(http_client=mock_client)
    assert res.status == "DOWN"
    assert res.reason == "connection/TLS error"
    assert not res.is_up


def test_availability_http_500():
    mock_client = MagicMock(side_effect=urllib.error.HTTPError(
        url="http://mock", code=500, msg="Internal Server Error", hdrs={}, fp=io.BytesIO(b"error")
    ))
    res = check_availability(http_client=mock_client)
    assert res.status == "DOWN"
    assert res.reason == "HTTP 500"
    assert not res.is_up


def test_availability_http_404():
    mock_client = MagicMock(side_effect=urllib.error.HTTPError(
        url="http://mock", code=404, msg="Not Found", hdrs={}, fp=io.BytesIO(b"error")
    ))
    res = check_availability(http_client=mock_client)
    assert res.status == "DOWN"
    assert res.reason == "HTTP 404"
    assert not res.is_up


def test_availability_exception_report_in_200():
    mock_client = MagicMock(return_value=_make_mock_response(MOCK_EXCEPTION_REPORT_200))
    res = check_availability(http_client=mock_client)
    assert res.status == "DEGRADED"
    assert res.reason == "ExceptionReport inside a 200"
    assert "maintenance" in res.details.lower()
    assert not res.is_up


def test_availability_layer_missing():
    mock_client = MagicMock(return_value=_make_mock_response(MOCK_CAPABILITIES_LAYER_MISSING))
    res = check_availability(layer_name="sn_wsg_bestand", http_client=mock_client)
    assert res.status == "DEGRADED"
    assert res.reason == "layer missing"
    assert not res.is_up


def test_availability_healthy_up():
    mock_client = MagicMock(return_value=_make_mock_response(MOCK_CAPABILITIES_VALID))
    res = check_availability(layer_name="sn_wsg_bestand", http_client=mock_client)
    assert res.status == "UP"
    assert res.reason == "service healthy and layer found"
    assert res.is_up


def test_fetch_zones_refuses_when_down():
    mock_client = MagicMock(side_effect=TimeoutError("The read operation timed out"))
    with pytest.raises(RuntimeError) as exc_info:
        fetch_zones(http_client=mock_client)
    assert "Cannot fetch zones: WFS service is DOWN" in str(exc_info.value)


def test_fetch_zones_succeeds_when_up():
    # First call: GetCapabilities -> valid XML
    # Second call: GetFeature -> valid GeoJSON
    mock_resp_cap = _make_mock_response(MOCK_CAPABILITIES_VALID)
    mock_resp_feat = _make_mock_response(MOCK_GEOJSON_FEATURES)
    mock_client = MagicMock(side_effect=[mock_resp_cap, mock_resp_feat])

    gdf = fetch_zones(http_client=mock_client)
    assert len(gdf) == 1
    assert gdf.iloc[0]["wsg_id"] == "SN-001"
