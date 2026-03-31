from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from shapely.geometry import Point, Polygon

from .constants import (
    ALERT_BUFFER,
    ALERT_EXCLUSION,
    ALERT_NON_THREAT,
    COLOR_BUFFER,
    COLOR_HIGH,
    COLOR_LOW,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    haversine_m,
    local_projector,
)
from .models import DroneAlertResult, ExclusionZone


class ZoneValidationError(ValueError):
    pass


class GeofenceEngine:
    """Zone storage, validation, persistence, map payloads, and drone evaluation."""

    def __init__(self) -> None:
        self.zones: List[ExclusionZone] = []
        self._cache: Dict[str, Dict[str, Any]] = {}

    def ensure_unique_name(self, name: str, ignore_zone_id: Optional[str] = None) -> None:
        target = name.strip().lower()
        for zone in self.zones:
            if ignore_zone_id and zone.zone_id == ignore_zone_id:
                continue
            if zone.name.strip().lower() == target:
                raise ZoneValidationError("Zone name already exists. Enter a unique Zone_Name.")

    def validate_zone(self, zone: ExclusionZone, ignore_zone_id: Optional[str] = None) -> None:
        if not zone.name.strip():
            raise ZoneValidationError("Zone_Name is required.")
        self.ensure_unique_name(zone.name, ignore_zone_id=ignore_zone_id)

        if zone.priority not in {PRIORITY_HIGH, PRIORITY_LOW}:
            raise ZoneValidationError("Zone priority must be High or Low.")
        if zone.zone_type not in {"Circular", "Polygon"}:
            raise ZoneValidationError("Zone type must be Circular or Polygon.")
        if zone.buffer_radius_m < 0:
            raise ZoneValidationError("Buffer Zone Radius must be greater than or equal to 0.")

        if zone.zone_type == "Circular":
            if zone.center_lat is None or zone.center_lon is None or zone.radius_m is None:
                raise ZoneValidationError("Circular zones require centre latitude, centre longitude, and zone radius.")
            self._validate_lat_lon(zone.center_lat, zone.center_lon)
            if float(zone.radius_m) <= 0:
                raise ZoneValidationError("Zone Radius must be greater than 0.")

        if zone.zone_type == "Polygon":
            if len(zone.polygon_points) < 3:
                raise ZoneValidationError("Polygon zones require at least 3 valid sequential points.")
            for lat, lon in zone.polygon_points:
                self._validate_lat_lon(lat, lon)
            for idx in range(1, len(zone.polygon_points)):
                if zone.polygon_points[idx] == zone.polygon_points[idx - 1]:
                    raise ZoneValidationError("Duplicate consecutive polygon points are not allowed.")

    @staticmethod
    def _validate_lat_lon(lat: float, lon: float) -> None:
        if lat is None or lon is None:
            raise ZoneValidationError("Latitude and longitude are required.")
        if not (-90.0 <= float(lat) <= 90.0):
            raise ZoneValidationError("Latitude must be between -90 and 90.")
        if not (-180.0 <= float(lon) <= 180.0):
            raise ZoneValidationError("Longitude must be between -180 and 180.")

    def add_zone(self, zone: ExclusionZone) -> None:
        self.validate_zone(zone)
        self.zones.append(zone)
        self._build_cache(zone)

    def update_zone(self, zone_id: str, new_zone: ExclusionZone) -> None:
        self.validate_zone(new_zone, ignore_zone_id=zone_id)
        for idx, zone in enumerate(self.zones):
            if zone.zone_id == zone_id:
                self.zones[idx] = new_zone
                self._build_cache(new_zone)
                return
        raise KeyError(f"Zone not found: {zone_id}")

    def delete_zone(self, zone_id: str) -> None:
        self.zones = [z for z in self.zones if z.zone_id != zone_id]
        self._cache.pop(zone_id, None)

    def set_zone_enabled(self, zone_id: str, enabled: bool) -> None:
        for zone in self.zones:
            if zone.zone_id == zone_id:
                zone.enabled = bool(enabled)
                return
        raise KeyError(f"Zone not found: {zone_id}")

    def save_json(self, file_path: str) -> None:
        data = [zone.to_json_dict() for zone in self.zones]
        Path(file_path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_json(self, file_path: str) -> None:
        data = json.loads(Path(file_path).read_text(encoding="utf-8"))
        self.zones = [ExclusionZone.from_json_dict(item) for item in data]
        self._cache = {}
        for zone in self.zones:
            self._build_cache(zone)

    def build_zone_rows(self, results: Optional[Dict[str, DroneAlertResult]] = None) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        results = results or {}
        for zone in self.zones:
            count = 0
            for result in results.values():
                if result.breached_zone_id == zone.zone_id and result.alert_state in {ALERT_BUFFER, ALERT_EXCLUSION}:
                    count += 1
            rows.append(
                {
                    "zone_id": zone.zone_id,
                    "name": zone.name,
                    "type": zone.zone_type,
                    "created": zone.created_timestamp,
                    "priority": zone.priority,
                    "buffer_radius": self._display_number(zone.buffer_radius_m),
                    "enabled": zone.enabled,
                    "drones_in_alert_area": count,
                }
            )
        return rows

    def map_payload(self) -> List[Dict[str, Any]]:
        payload: List[Dict[str, Any]] = []
        for zone in self.zones:
            base_color = COLOR_HIGH if zone.priority == PRIORITY_HIGH else COLOR_LOW
            common = {
                "id": zone.zone_id,
                "name": zone.name,
                "priority": zone.priority,
                "enabled": zone.enabled,
                "type": zone.zone_type,
                "baseColor": base_color,
                "bufferColor": COLOR_BUFFER,
                "bufferRadius": float(zone.buffer_radius_m),
            }
            if zone.zone_type == "Circular":
                payload.append({**common, "center": [zone.center_lat, zone.center_lon], "radius": float(zone.radius_m or 0.0)})
            else:
                payload.append({**common, "points": [[lat, lon] for lat, lon in zone.polygon_points]})
        return payload

    def _build_cache(self, zone: ExclusionZone) -> None:
        if zone.zone_type == "Circular":
            self._cache[zone.zone_id] = {
                "kind": "circle",
                "center": (float(zone.center_lat), float(zone.center_lon)),
                "radius": float(zone.radius_m or 0.0),
                "buffer_outer": float(zone.radius_m or 0.0) + float(zone.buffer_radius_m),
            }
            return

        pts = list(zone.polygon_points)
        if pts and pts[0] != pts[-1]:
            pts.append(pts[0])
        lat0 = sum(lat for lat, _ in pts[:-1]) / (len(pts) - 1)
        lon0 = sum(lon for _, lon in pts[:-1]) / (len(pts) - 1)
        projector = local_projector(lat0, lon0)
        xy = [projector(lon, lat) for lat, lon in pts]
        base_poly = Polygon(xy)
        buffer_poly = base_poly.buffer(float(zone.buffer_radius_m))
        self._cache[zone.zone_id] = {
            "kind": "polygon",
            "projector": projector,
            "base_poly": base_poly,
            "buffer_poly": buffer_poly,
        }

    @staticmethod
    def _display_number(value: float) -> str:
        as_float = float(value)
        if as_float.is_integer():
            return str(int(as_float))
        return f"{as_float:.2f}"

    def evaluate_point(self, drone_key: str, lat: Optional[float], lon: Optional[float]) -> DroneAlertResult:
        result = DroneAlertResult(drone_key=drone_key)
        if lat is None or lon is None:
            return result

        best_rank = 0
        for zone in self.zones:
            if not zone.enabled:
                continue
            state = self._classify_point(zone, float(lat), float(lon))
            rank = self._rank(state)
            if rank > best_rank:
                best_rank = rank
                result.alert_state = state
                result.breached_zone_name = zone.name if state != ALERT_NON_THREAT else ""
                result.breached_zone_id = zone.zone_id if state != ALERT_NON_THREAT else ""
                result.row_color_name = self._row_color(zone.priority, state)
        return result

    def evaluate_items(self, items: Sequence[Dict[str, Any]]) -> Dict[str, DroneAlertResult]:
        results: Dict[str, DroneAlertResult] = {}
        for item in items:
            key = str(item.get("key", "")).strip()
            if not key:
                continue
            lat = item.get("drone_lat")
            lon = item.get("drone_lon")
            results[key] = self.evaluate_point(key, lat, lon)
        return results

    def any_active_alert(self, results: Dict[str, DroneAlertResult]) -> bool:
        return any(r.alert_state in {ALERT_BUFFER, ALERT_EXCLUSION} for r in results.values())

    def _classify_point(self, zone: ExclusionZone, lat: float, lon: float) -> str:
        cache = self._cache.get(zone.zone_id)
        if cache is None:
            self._build_cache(zone)
            cache = self._cache[zone.zone_id]

        if cache["kind"] == "circle":
            center_lat, center_lon = cache["center"]
            dist = haversine_m(lat, lon, center_lat, center_lon)
            if dist <= cache["radius"]:
                return ALERT_EXCLUSION
            if dist <= cache["buffer_outer"]:
                return ALERT_BUFFER
            return ALERT_NON_THREAT

        px, py = cache["projector"](lon, lat)
        point = Point(px, py)
        if cache["base_poly"].covers(point):
            return ALERT_EXCLUSION
        if cache["buffer_poly"].covers(point):
            return ALERT_BUFFER
        return ALERT_NON_THREAT

    @staticmethod
    def _rank(state: str) -> int:
        return {ALERT_NON_THREAT: 0, ALERT_BUFFER: 1, ALERT_EXCLUSION: 2}.get(state, 0)

    @staticmethod
    def _row_color(priority: str, state: str):
        if state == ALERT_BUFFER:
            return COLOR_BUFFER
        if state == ALERT_EXCLUSION:
            return COLOR_HIGH if priority == PRIORITY_HIGH else COLOR_LOW
        return None
