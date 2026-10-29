"""Service availability and fetch module."""

from .availability import (
    ServiceStatus,
    check_availability,
    fetch_zones,
)

__all__ = [
    "ServiceStatus",
    "check_availability",
    "fetch_zones",
]
