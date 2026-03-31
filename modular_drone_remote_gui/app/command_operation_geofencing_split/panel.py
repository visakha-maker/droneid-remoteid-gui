from __future__ import annotations

import uuid
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
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

from .constants import PRIORITY_HIGH, PRIORITY_LOW, now_string
from .engine import GeofenceEngine, ZoneValidationError
from .models import DroneAlertResult, ExclusionZone


class CommandOperationGeofencePanel(QGroupBox):
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
        self.zone_table.setMaximumHeight(220)
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
