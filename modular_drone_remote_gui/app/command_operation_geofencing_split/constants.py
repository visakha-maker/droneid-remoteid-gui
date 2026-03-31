from __future__ import annotations

import math
from datetime import datetime
from typing import Tuple

EARTH_RADIUS_M = 6371008.8

ALERT_NON_THREAT = "Non-Threat"
ALERT_BUFFER = "Buffer Alert"
ALERT_EXCLUSION = "Exclusion Alert"

PRIORITY_HIGH = "High"
PRIORITY_LOW = "Low"

COLOR_BUFFER = "yellow"
COLOR_LOW = "orange"
COLOR_HIGH = "red"


def now_string() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_r, lon1_r, lat2_r, lon2_r = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def local_projector(lat0: float, lon0: float):
    lat0_r = math.radians(lat0)

    def project(lon: float, lat: float) -> Tuple[float, float]:
        x = math.radians(lon - lon0) * EARTH_RADIUS_M * math.cos(lat0_r)
        y = math.radians(lat - lat0) * EARTH_RADIUS_M
        return x, y

    return project
