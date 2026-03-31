from __future__ import annotations

"""
Standalone geofencing module for the Command Operation tab.

Designed for the current PySide6 CommandOperationTab and existing Leaflet HTML.
This keeps geofencing out of the main tab file and injects its own JavaScript layer
manager into the current map page at runtime, so the HTML file does not need to be
edited just to draw zones and show the alert indicator.

Typical integration in command_operation_tab.py:

    from app.command_operation_geofencing_separate import (
        GeofenceEngine,
        CommandOperationGeofencePanel,
        CommandOperationGeofenceController,
    )

    self.geofence_engine = GeofenceEngine()
    self.geofence_ctrl = CommandOperationGeofenceController(
        webview=self.web,
        detected_table=self.table,
        engine=self.geofence_engine,
        parent=self,
    )
    self.geofence_panel = CommandOperationGeofencePanel(
        engine=self.geofence_engine,
        parent=self,
        on_zones_changed=self._on_geofence_zones_changed,
    )
    self.web.loadFinished.connect(lambda ok: self.geofence_ctrl.install_map_bridge() if ok else None)
    right.addWidget(self.geofence_panel)

    def _on_geofence_zones_changed(self):
        self.geofence_ctrl.render_zones()
        self.refresh_view()

    # at the end of refresh_view(), after rebuilding self.table rows:
    self.geofence_ctrl.decorate_detected_table(items)
    self.geofence_panel.refresh_zone_table(self.geofence_ctrl.latest_results)
    self.geofence_ctrl.update_map_alert(items)

The controller expects each store item to follow the current tab structure where
"key" identifies the drone/track and drone_lat/drone_lon contain the drone position.
"""

import json
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from shapely.geometry import Point, Polygon

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QFileDialog,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


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


@dataclass
class ExclusionZone:
    zone_id: str
    name: str
    zone_type: str  # Circular | Polygon
    priority: str   # High | Low
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


class ZoneValidationError(ValueError):
    pass


class GeofenceEngine:
    """Zone storage, validation, persistence, map payloads, and drone evaluation."""

    def __init__(self) -> None:
        self.zones: List[ExclusionZone] = []
        self._cache: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Zone section
    # ------------------------------------------------------------------
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
                payload.append(
                    {
                        **common,
                        "center": [zone.center_lat, zone.center_lon],
                        "radius": float(zone.radius_m or 0.0),
                    }
                )
            else:
                payload.append(
                    {
                        **common,
                        "points": [[lat, lon] for lat, lon in zone.polygon_points],
                    }
                )
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

    # ------------------------------------------------------------------
    # Alert section
    # ------------------------------------------------------------------
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
    def _row_color(priority: str, state: str) -> Optional[str]:
        if state == ALERT_BUFFER:
            return COLOR_BUFFER
        if state == ALERT_EXCLUSION:
            return COLOR_HIGH if priority == PRIORITY_HIGH else COLOR_LOW
        return None


class CommandOperationGeofencePanel(QGroupBox):
    """Standalone UI block to add below the Detected Drones box on the Command Operation tab."""

    ZONE_COLUMNS = [
        "Name",
        "Zone Type",
        "Date Created",
        "Priority",
        "Buffer Zone Radius",
        "Enabled",
        "Drones in Alert Area",
    ]

    def __init__(
        self,
        engine: GeofenceEngine,
        parent: Optional[QWidget] = None,
        on_zones_changed: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__("Exclusion Zones", parent)
        self.engine = engine
        self.on_zones_changed = on_zones_changed
        self.editing_zone_id: Optional[str] = None
        self._build_ui()
        self._set_create_mode()
        self.refresh_zone_table({})

    # ------------------------------------------------------------------
    # Zone section UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        form_box = QGroupBox("Zone Properties")
        outer.addWidget(form_box)
        form = QGridLayout(form_box)

        self.zone_type = QComboBox()
        self.zone_type.addItems(["Circular", "Polygon"])
        self.zone_name = QLineEdit()
        self.priority = QComboBox()
        self.priority.addItems([PRIORITY_HIGH, PRIORITY_LOW])
        self.center_lat = QLineEdit()
        self.center_lon = QLineEdit()
        self.zone_radius = QLineEdit()
        self.buffer_radius = QLineEdit()

        form.addWidget(QLabel("Zone Type"), 0, 0)
        form.addWidget(self.zone_type, 0, 1)
        form.addWidget(QLabel("Zone_Name"), 0, 2)
        form.addWidget(self.zone_name, 0, 3)
        form.addWidget(QLabel("Priority Level"), 0, 4)
        form.addWidget(self.priority, 0, 5)

        form.addWidget(QLabel("Centre Lat"), 1, 0)
        form.addWidget(self.center_lat, 1, 1)
        form.addWidget(QLabel("Centre Lon"), 1, 2)
        form.addWidget(self.center_lon, 1, 3)
        form.addWidget(QLabel("Zone Radius (m)"), 1, 4)
        form.addWidget(self.zone_radius, 1, 5)
        form.addWidget(QLabel("Buffer Zone Radius (m)"), 1, 6)
        form.addWidget(self.buffer_radius, 1, 7)

        self.zone_type.currentTextChanged.connect(self._on_zone_type_changed)

        poly_box = QGroupBox("Polygon Points")
        outer.addWidget(poly_box)
        poly_layout = QGridLayout(poly_box)
        self.polygon_rows: List[Tuple[QLineEdit, QLineEdit]] = []
        for idx in range(6):
            lat_edit = QLineEdit()
            lon_edit = QLineEdit()
            self.polygon_rows.append((lat_edit, lon_edit))
            poly_layout.addWidget(QLabel(f"P{idx + 1} Lat"), idx, 0)
            poly_layout.addWidget(lat_edit, idx, 1)
            poly_layout.addWidget(QLabel(f"P{idx + 1} Lon"), idx, 2)
            poly_layout.addWidget(lon_edit, idx, 3)
        self.poly_box = poly_box

        button_row = QHBoxLayout()
        outer.addLayout(button_row)
        self.btn_create = QPushButton("Create Zone")
        self.btn_edit = QPushButton("Edit Zone")
        self.btn_update = QPushButton("Update Zone")
        self.btn_delete = QPushButton("Delete Zone")
        self.btn_save = QPushButton("Save Zones")
        self.btn_load = QPushButton("Load Zones")
        for btn in [self.btn_create, self.btn_edit, self.btn_update, self.btn_delete, self.btn_save, self.btn_load]:
            button_row.addWidget(btn)

        self.zone_table = QTableWidget(0, len(self.ZONE_COLUMNS))
        self.zone_table.setHorizontalHeaderLabels(self.ZONE_COLUMNS)
        self.zone_table.verticalHeader().setVisible(False)
        self.zone_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.zone_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.zone_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.zone_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        outer.addWidget(self.zone_table)

        self.zone_table.itemSelectionChanged.connect(self._populate_from_selected_zone)
        self.btn_create.clicked.connect(self._create_zone)
        self.btn_edit.clicked.connect(self._edit_zone)
        self.btn_update.clicked.connect(self._update_zone)
        self.btn_delete.clicked.connect(self._delete_zone)
        self.btn_save.clicked.connect(self._save_zones)
        self.btn_load.clicked.connect(self._load_zones)

        self._on_zone_type_changed(self.zone_type.currentText())

    def _clear_form(self) -> None:
        self.zone_type.setCurrentText("Circular")
        self.zone_name.clear()
        self.priority.setCurrentText(PRIORITY_HIGH)
        self.center_lat.clear()
        self.center_lon.clear()
        self.zone_radius.clear()
        self.buffer_radius.clear()
        for lat_edit, lon_edit in self.polygon_rows:
            lat_edit.clear()
            lon_edit.clear()

    def _set_form_enabled(self, enabled: bool) -> None:
        for widget in [self.zone_type, self.zone_name, self.priority, self.center_lat, self.center_lon, self.zone_radius, self.buffer_radius]:
            widget.setEnabled(enabled)
        for lat_edit, lon_edit in self.polygon_rows:
            lat_edit.setEnabled(enabled)
            lon_edit.setEnabled(enabled)

    def _set_create_mode(self) -> None:
        self.editing_zone_id = None
        self.btn_create.setEnabled(True)
        self.btn_update.setEnabled(False)
        self._set_form_enabled(True)

    def _set_update_mode(self) -> None:
        self.btn_create.setEnabled(False)
        self.btn_update.setEnabled(True)
        self._set_form_enabled(True)

    def _on_zone_type_changed(self, zone_type: str) -> None:
        is_circle = zone_type == "Circular"
        self.center_lat.setEnabled(is_circle)
        self.center_lon.setEnabled(is_circle)
        self.zone_radius.setEnabled(is_circle)
        self.poly_box.setVisible(not is_circle)

    def _selected_zone_id(self) -> Optional[str]:
        row = self.zone_table.currentRow()
        if row < 0:
            return None
        item = self.zone_table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _show_selection_prompt(self) -> None:
        QMessageBox.information(self, "No zone selected", "Select a zone row first.")

    def _populate_from_selected_zone(self) -> None:
        zone_id = self._selected_zone_id()
        if not zone_id:
            return
        zone = next((z for z in self.engine.zones if z.zone_id == zone_id), None)
        if not zone:
            return
        self.zone_type.setCurrentText(zone.zone_type)
        self.zone_name.setText(zone.name)
        self.priority.setCurrentText(zone.priority)
        self.center_lat.setText("" if zone.center_lat is None else str(zone.center_lat))
        self.center_lon.setText("" if zone.center_lon is None else str(zone.center_lon))
        self.zone_radius.setText("" if zone.radius_m is None else str(zone.radius_m))
        self.buffer_radius.setText(str(zone.buffer_radius_m))
        for idx, (lat_edit, lon_edit) in enumerate(self.polygon_rows):
            if idx < len(zone.polygon_points):
                lat_edit.setText(str(zone.polygon_points[idx][0]))
                lon_edit.setText(str(zone.polygon_points[idx][1]))
            else:
                lat_edit.clear()
                lon_edit.clear()

    def _float_or_none(self, edit: QLineEdit) -> Optional[float]:
        text = edit.text().strip()
        if not text:
            return None
        return float(text)

    def _polygon_points_from_form(self) -> List[Tuple[float, float]]:
        points: List[Tuple[float, float]] = []
        found_blank = False
        for idx, (lat_edit, lon_edit) in enumerate(self.polygon_rows, start=1):
            lat_text = lat_edit.text().strip()
            lon_text = lon_edit.text().strip()
            has_text = bool(lat_text or lon_text)
            if not has_text:
                found_blank = True
                continue
            if found_blank:
                raise ZoneValidationError("Polygon rows must be filled sequentially from top to bottom.")
            if not lat_text or not lon_text:
                raise ZoneValidationError(f"Polygon point {idx} requires both latitude and longitude.")
            points.append((float(lat_text), float(lon_text)))
        return points

    def _zone_from_form(self, existing_id: Optional[str] = None, created_timestamp: Optional[str] = None) -> ExclusionZone:
        zone_type = self.zone_type.currentText()
        zone = ExclusionZone(
            zone_id=existing_id or str(uuid.uuid4()),
            name=self.zone_name.text().strip(),
            zone_type=zone_type,
            priority=self.priority.currentText(),
            enabled=True,
            buffer_radius_m=float(self.buffer_radius.text().strip() or 0.0),
            created_timestamp=created_timestamp or now_string(),
        )
        if zone_type == "Circular":
            zone.center_lat = self._float_or_none(self.center_lat)
            zone.center_lon = self._float_or_none(self.center_lon)
            zone.radius_m = self._float_or_none(self.zone_radius)
        else:
            zone.polygon_points = self._polygon_points_from_form()
        return zone

    def _selected_zone(self) -> Optional[ExclusionZone]:
        zone_id = self._selected_zone_id()
        if not zone_id:
            return None
        return next((z for z in self.engine.zones if z.zone_id == zone_id), None)

    def _create_zone(self) -> None:
        try:
            zone = self._zone_from_form()
            self.engine.add_zone(zone)
        except Exception as exc:
            QMessageBox.warning(self, "Invalid zone", str(exc))
            return
        self.refresh_zone_table({})
        self._clear_form()
        self._set_create_mode()
        self._emit_changed()

    def _edit_zone(self) -> None:
        zone = self._selected_zone()
        if not zone:
            self._show_selection_prompt()
            return
        self.editing_zone_id = zone.zone_id
        self._set_update_mode()

    def _update_zone(self) -> None:
        zone = self._selected_zone()
        if not zone or not self.editing_zone_id:
            self._show_selection_prompt()
            return
        try:
            updated = self._zone_from_form(existing_id=zone.zone_id, created_timestamp=zone.created_timestamp)
            updated.enabled = zone.enabled
            self.engine.update_zone(zone.zone_id, updated)
        except Exception as exc:
            QMessageBox.warning(self, "Invalid zone", str(exc))
            return
        self.refresh_zone_table({})
        self._clear_form()
        self._set_create_mode()
        self._emit_changed()

    def _delete_zone(self) -> None:
        zone = self._selected_zone()
        if not zone:
            self._show_selection_prompt()
            return
        reply = QMessageBox.question(self, "Delete zone", f"Delete zone '{zone.name}'?")
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.engine.delete_zone(zone.zone_id)
        self.refresh_zone_table({})
        self._clear_form()
        self._set_create_mode()
        self._emit_changed()

    def _save_zones(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(self, "Save zones", "zones.json", "JSON Files (*.json)")
        if not file_path:
            return
        try:
            self.engine.save_json(file_path)
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", str(exc))

    def _load_zones(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Load zones", "", "JSON Files (*.json)")
        if not file_path:
            return
        try:
            self.engine.load_json(file_path)
        except Exception as exc:
            QMessageBox.warning(self, "Load failed", str(exc))
            return
        self.refresh_zone_table({})
        self._clear_form()
        self._set_create_mode()
        self._emit_changed()

    def refresh_zone_table(self, results: Dict[str, DroneAlertResult]) -> None:
        rows = self.engine.build_zone_rows(results)
        self.zone_table.setRowCount(0)
        for row_index, row in enumerate(rows):
            self.zone_table.insertRow(row_index)
            name_item = QTableWidgetItem(row["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, row["zone_id"])
            self.zone_table.setItem(row_index, 0, name_item)
            self.zone_table.setItem(row_index, 1, QTableWidgetItem(row["type"]))
            self.zone_table.setItem(row_index, 2, QTableWidgetItem(row["created"]))
            self.zone_table.setItem(row_index, 3, QTableWidgetItem(row["priority"]))
            self.zone_table.setItem(row_index, 4, QTableWidgetItem(row["buffer_radius"]))

            toggle_btn = QPushButton("Disable" if row["enabled"] else "Enable")
            toggle_btn.clicked.connect(lambda checked=False, zid=row["zone_id"], enabled=row["enabled"]: self._toggle_enabled(zid, enabled))
            self.zone_table.setCellWidget(row_index, 5, toggle_btn)
            self.zone_table.setItem(row_index, 6, QTableWidgetItem(str(row["drones_in_alert_area"])))

    def _toggle_enabled(self, zone_id: str, currently_enabled: bool) -> None:
        self.engine.set_zone_enabled(zone_id, not currently_enabled)
        self.refresh_zone_table({})
        self._emit_changed()

    def _emit_changed(self) -> None:
        if self.on_zones_changed:
            self.on_zones_changed()


class CommandOperationGeofenceController:
    """Alert and map bridge for the existing Command Operation tab.

    This controller keeps the geofencing logic separate from command_operation_tab.py.
    It appends the geofence alert columns to the existing detected-drone table, colours
    rows, and injects Leaflet drawing/alert-indicator JavaScript into the current HTML.
    """

    def __init__(
        self,
        webview,
        detected_table: QTableWidget,
        engine: GeofenceEngine,
        parent: Optional[QWidget] = None,
    ) -> None:
        self.webview = webview
        self.detected_table = detected_table
        self.engine = engine
        self.parent = parent
        self.latest_results: Dict[str, DroneAlertResult] = {}
        self._map_js_installed = False
        self._previous_global_alert = False

    # ------------------------------------------------------------------
    # Alert section: table + global indicator
    # ------------------------------------------------------------------
    def ensure_table_columns(self) -> None:
        desired = [
            "Track", "DroneID", "Remote ID", "Drone Lat", "Drone Lon",
            "Controller Lat", "Controller Lon", "Detector Lat/Lon",
            "Breached Zone", "Alert State",
        ]
        if self.detected_table.columnCount() != len(desired):
            self.detected_table.setColumnCount(len(desired))
        self.detected_table.setHorizontalHeaderLabels(desired)

    def decorate_detected_table(self, items: Sequence[Dict[str, Any]]) -> Dict[str, DroneAlertResult]:
        self.ensure_table_columns()
        self.latest_results = self.engine.evaluate_items(items)
        for row, item in enumerate(items):
            key = str(item.get("key", "")).strip()
            result = self.latest_results.get(key, DroneAlertResult(drone_key=key))
            self._set_table_text(row, 8, result.breached_zone_name)
            self._set_table_text(row, 9, result.alert_state)
            self._apply_row_colour(row, result.row_color_name)
        return self.latest_results

    def update_map_alert(self, items: Sequence[Dict[str, Any]]) -> None:
        if not self._map_js_installed:
            self.install_map_bridge()
        results = self.latest_results or self.engine.evaluate_items(items)
        active = self.engine.any_active_alert(results)
        entering = active and not self._previous_global_alert
        self._previous_global_alert = active
        self.webview.page().runJavaScript(
            f"window.__cmdopGeoFence && window.__cmdopGeoFence.setAlertState({json.dumps({'active': active, 'entering': entering})});"
        )

    def _set_table_text(self, row: int, col: int, text: str) -> None:
        item = self.detected_table.item(row, col)
        if item is None:
            item = QTableWidgetItem()
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.detected_table.setItem(row, col, item)
        item.setText(text)

    def _apply_row_colour(self, row: int, color_name: Optional[str]) -> None:
        brush = None
        if color_name == COLOR_BUFFER:
            brush = QBrush(QColor(255, 235, 59, 120))
        elif color_name == COLOR_LOW:
            brush = QBrush(QColor(255, 165, 0, 120))
        elif color_name == COLOR_HIGH:
            brush = QBrush(QColor(255, 0, 0, 110))

        for col in range(self.detected_table.columnCount()):
            item = self.detected_table.item(row, col)
            if item is None:
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self.detected_table.setItem(row, col, item)
            if brush is None:
                item.setBackground(QBrush())
            else:
                item.setBackground(brush)

    # ------------------------------------------------------------------
    # Map rendering section
    # ------------------------------------------------------------------
    def install_map_bridge(self) -> None:
        if self._map_js_installed:
            return
        js = r'''
(function() {
  if (window.__cmdopGeoFence || typeof map === 'undefined' || typeof L === 'undefined') return;

  function rgba(base, alpha) {
    if (base === 'red') return 'rgba(255,0,0,' + alpha + ')';
    if (base === 'orange') return 'rgba(255,165,0,' + alpha + ')';
    return 'rgba(255,235,59,' + alpha + ')';
  }

  function localProjector(lat0, lon0) {
    const R = 6371008.8;
    const lat0r = lat0 * Math.PI / 180.0;
    return {
      forward: function(lat, lon) {
        const x = (lon - lon0) * Math.PI / 180.0 * R * Math.cos(lat0r);
        const y = (lat - lat0) * Math.PI / 180.0 * R;
        return [x, y];
      },
      inverse: function(x, y) {
        const lat = lat0 + (y / R) * 180.0 / Math.PI;
        const lon = lon0 + (x / (R * Math.cos(lat0r))) * 180.0 / Math.PI;
        return [lat, lon];
      }
    };
  }

  function polygonCentroid(points) {
    let lat = 0, lon = 0;
    for (const p of points) {
      lat += p[0];
      lon += p[1];
    }
    return [lat / points.length, lon / points.length];
  }

  function bufferedPolygonLatLngs(points, bufferMeters) {
    if (!points || points.length < 3 || bufferMeters <= 0) return points;
    const centroid = polygonCentroid(points);
    const proj = localProjector(centroid[0], centroid[1]);
    const closed = points.slice();
    if (points[0][0] !== points[points.length - 1][0] || points[0][1] !== points[points.length - 1][1]) {
      closed.push(points[0]);
    }
    const xy = closed.map(p => proj.forward(p[0], p[1]));

    // simple outward offset approximation based on vertex normals; lightweight and enough for visual buffer display
    const out = [];
    for (let i = 0; i < closed.length - 1; i++) {
      const prev = xy[(i - 1 + xy.length - 1) % (xy.length - 1)];
      const curr = xy[i];
      const next = xy[(i + 1) % (xy.length - 1)];
      const vx1 = curr[0] - prev[0], vy1 = curr[1] - prev[1];
      const vx2 = next[0] - curr[0], vy2 = next[1] - curr[1];
      const n1len = Math.hypot(vx1, vy1) || 1;
      const n2len = Math.hypot(vx2, vy2) || 1;
      const n1 = [-vy1 / n1len, vx1 / n1len];
      const n2 = [-vy2 / n2len, vx2 / n2len];
      const nx = n1[0] + n2[0];
      const ny = n1[1] + n2[1];
      const nlen = Math.hypot(nx, ny) || 1;
      const [lat, lon] = proj.inverse(curr[0] + bufferMeters * nx / nlen, curr[1] + bufferMeters * ny / nlen);
      out.push([lat, lon]);
    }
    return out;
  }

  const zoneLayer = L.layerGroup().addTo(map);
  const labelLayer = L.layerGroup().addTo(map);

  const alertControl = L.control({position: 'topleft'});
  alertControl.onAdd = function() {
    const div = L.DomUtil.create('div', 'leaflet-bar');
    div.id = 'cmdop-alert-indicator';
    div.style.background = 'rgba(255,255,255,0.92)';
    div.style.padding = '8px 12px';
    div.style.fontWeight = '700';
    div.style.borderRadius = '6px';
    div.style.boxShadow = '0 2px 8px rgba(0,0,0,0.22)';
    div.style.minWidth = '110px';
    div.style.textAlign = 'center';
    div.textContent = 'Alert: Clear';
    return div;
  };
  alertControl.addTo(map);

  let blinkTimer = null;
  function setAlertState(state) {
    const el = document.getElementById('cmdop-alert-indicator');
    if (!el) return;
    if (!state || !state.active) {
      if (blinkTimer) { clearInterval(blinkTimer); blinkTimer = null; }
      el.textContent = 'Alert: Clear';
      el.style.background = 'rgba(255,255,255,0.92)';
      el.style.color = '#111';
      return;
    }

    el.textContent = 'Alert: ACTIVE';
    el.style.color = '#fff';
    if (state.entering) {
      let on = true;
      if (blinkTimer) clearInterval(blinkTimer);
      blinkTimer = setInterval(function() {
        el.style.background = on ? 'rgba(220,0,0,0.95)' : 'rgba(255,170,0,0.95)';
        on = !on;
      }, 350);
      setTimeout(function() {
        if (blinkTimer) {
          clearInterval(blinkTimer);
          blinkTimer = null;
        }
        el.style.background = 'rgba(220,0,0,0.95)';
      }, 2200);
    } else {
      if (blinkTimer) { clearInterval(blinkTimer); blinkTimer = null; }
      el.style.background = 'rgba(220,0,0,0.95)';
    }
  }

  function drawZones(zones) {
    zoneLayer.clearLayers();
    labelLayer.clearLayers();
    if (!Array.isArray(zones)) return;

    for (const zone of zones) {
      const baseColor = zone.baseColor || 'orange';
      const bufferColor = zone.bufferColor || 'yellow';
      if (zone.type === 'Circular' && zone.center && zone.center.length === 2) {
        if (zone.bufferRadius > 0) {
          L.circle(zone.center, {
            radius: zone.radius + zone.bufferRadius,
            color: bufferColor,
            weight: 3,
            fillColor: bufferColor,
            fillOpacity: 0.14,
          }).addTo(zoneLayer);
        }
        L.circle(zone.center, {
          radius: zone.radius,
          color: baseColor,
          weight: 3,
          fillColor: baseColor,
          fillOpacity: 0.24,
        }).addTo(zoneLayer);
        L.marker(zone.center, {
          interactive: false,
          icon: L.divIcon({
            className: '',
            html: '<div style="font-weight:700;font-size:12px;background:rgba(255,255,255,0.75);padding:2px 6px;border-radius:5px;">' + zone.name + '</div>',
            iconSize: [120, 22],
            iconAnchor: [60, 11]
          })
        }).addTo(labelLayer);
      } else if (zone.type === 'Polygon' && Array.isArray(zone.points) && zone.points.length >= 3) {
        if (zone.bufferRadius > 0) {
          const bufferPts = bufferedPolygonLatLngs(zone.points, zone.bufferRadius);
          L.polygon(bufferPts, {
            color: bufferColor,
            weight: 3,
            fillColor: bufferColor,
            fillOpacity: 0.14,
          }).addTo(zoneLayer);
        }
        const poly = L.polygon(zone.points, {
          color: baseColor,
          weight: 3,
          fillColor: baseColor,
          fillOpacity: 0.24,
        }).addTo(zoneLayer);
        const centre = poly.getBounds().getCenter();
        L.marker([centre.lat, centre.lng], {
          interactive: false,
          icon: L.divIcon({
            className: '',
            html: '<div style="font-weight:700;font-size:12px;background:rgba(255,255,255,0.75);padding:2px 6px;border-radius:5px;">' + zone.name + '</div>',
            iconSize: [120, 22],
            iconAnchor: [60, 11]
          })
        }).addTo(labelLayer);
      }
    }
  }

  window.__cmdopGeoFence = {
    drawZones: drawZones,
    setAlertState: setAlertState,
  };
})();
'''
        self.webview.page().runJavaScript(js)
        self._map_js_installed = True
        self.render_zones()

    def render_zones(self) -> None:
        if not self._map_js_installed:
            return
        payload = self.engine.map_payload()
        self.webview.page().runJavaScript(
            f"window.__cmdopGeoFence && window.__cmdopGeoFence.drawZones({json.dumps(payload)});"
        )

