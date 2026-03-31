from __future__ import annotations

import math
from typing import Optional, Tuple


def as_float(value) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def valid_lat_lon(lat: Optional[float], lon: Optional[float]) -> bool:
    if lat is None or lon is None:
        return False
    if lat == 0.0 and lon == 0.0:
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def distance_m(lat1, lon1, lat2, lon2) -> Optional[float]:
    if not valid_lat_lon(lat1, lon1) or not valid_lat_lon(lat2, lon2):
        return None
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_deg_true_north(lat1, lon1, lat2, lon2) -> Optional[float]:
    if not valid_lat_lon(lat1, lon1) or not valid_lat_lon(lat2, lon2):
        return None
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def distance_and_bearing(det_lat, det_lon, target_lat, target_lon) -> Tuple[Optional[float], Optional[float]]:
    return distance_m(det_lat, det_lon, target_lat, target_lon), bearing_deg_true_north(det_lat, det_lon, target_lat, target_lon)
