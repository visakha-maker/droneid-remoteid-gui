from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .constants import ALERT_NON_THREAT, PRIORITY_LOW, now_string


@dataclass
class ExclusionZone:
    zone_id: str
    name: str
    zone_type: str
    priority: str
    enabled: bool
    buffer_radius_m: float
    created_timestamp: str
    center_lat: Optional[float] = None
    center_lon: Optional[float] = None
    radius_m: Optional[float] = None
    polygon_points: List[Tuple[float, float]] = field(default_factory=list)

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "id": self.zone_id,
            "name": self.name,
            "type": self.zone_type,
            "priority": self.priority,
            "centre": [self.center_lat, self.center_lon] if self.center_lat is not None and self.center_lon is not None else None,
            "radius": self.radius_m,
            "polygon_points": self.polygon_points,
            "buffer_radius": self.buffer_radius_m,
            "enabled_state": self.enabled,
            "created_timestamp": self.created_timestamp,
        }

    @classmethod
    def from_json_dict(cls, data: Dict[str, Any]) -> "ExclusionZone":
        centre = data.get("centre") or [None, None]
        polygon_points = [tuple(p) for p in data.get("polygon_points") or []]
        return cls(
            zone_id=str(data.get("id") or uuid.uuid4()),
            name=str(data.get("name") or ""),
            zone_type=str(data.get("type") or "Circular"),
            priority=str(data.get("priority") or PRIORITY_LOW),
            enabled=bool(data.get("enabled_state", True)),
            buffer_radius_m=float(data.get("buffer_radius", 0.0)),
            created_timestamp=str(data.get("created_timestamp") or now_string()),
            center_lat=None if centre[0] is None else float(centre[0]),
            center_lon=None if centre[1] is None else float(centre[1]),
            radius_m=None if data.get("radius") in (None, "") else float(data.get("radius")),
            polygon_points=[(float(lat), float(lon)) for lat, lon in polygon_points],
        )


@dataclass
class DroneAlertResult:
    drone_key: str
    alert_state: str = ALERT_NON_THREAT
    breached_zone_name: str = ""
    breached_zone_id: str = ""
    row_color_name: Optional[str] = None
