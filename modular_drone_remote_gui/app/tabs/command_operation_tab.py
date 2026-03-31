import json
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QFormLayout,
    QPushButton, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QDialog, QDialogButtonBox, QLineEdit, QComboBox,
    QSizePolicy, QScrollArea
)

from app.maps import COMMAND_OPERATION_HTML
from app.utils.geo import distance_m, bearing_deg_true_north
from app.utils.webview import make_webview
from app.command_operation_geofencing_split import (
    GeofenceEngine,
    CommandOperationGeofencePanel,
    CommandOperationGeofenceController,
)


class DetectorLocationDialog(QDialog):
    def __init__(self, lat=None, lon=None, alt=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Detector Location")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.lat_edit = QLineEdit("" if lat is None else str(lat))
        self.lon_edit = QLineEdit("" if lon is None else str(lon))
        self.alt_edit = QLineEdit("" if alt is None else str(alt))

        form.addRow("Latitude:", self.lat_edit)
        form.addRow("Longitude:", self.lon_edit)
        form.addRow("Altitude (m):", self.alt_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        lat = float(self.lat_edit.text().strip())
        lon = float(self.lon_edit.text().strip())
        alt_text = self.alt_edit.text().strip()
        alt = float(alt_text) if alt_text else 0.0
        return lat, lon, alt


class CommandOperationTab(QWidget):
    def __init__(self, store, detector_state):
        super().__init__()
        self.store = store
        self.detector_state = detector_state
        self.store.updated.connect(self.refresh_view)
        self.detector_state.changed.connect(self._on_detector_changed)

        self.droneid_tab = None
        self.remoteid_tab = None
        self._map_ready = False

        self.geofence_engine = GeofenceEngine()
        self.geofence_controller = None
        self.zone_panel = None

        self.web = make_webview(self)
        self.web.loadFinished.connect(self._on_map_loaded)

        summary_box = QGroupBox("Detected Drones")
        summary_layout = QVBoxLayout()
        summary_layout.setContentsMargins(8, 8, 8, 8)
        summary_layout.setSpacing(6)

        combo_row = QHBoxLayout()
        combo_row.addWidget(QLabel("Select drone:"))
        self.cmb_detected = QComboBox()
        combo_row.addWidget(self.cmb_detected, 1)
        summary_layout.addLayout(combo_row)

        self.selected_table = QTableWidget(1, 5)
        self.selected_table.setHorizontalHeaderLabels([
            "Drone Lat",
            "Drone Lon",
            "Altitude",
            "Detector→Drone Distance (m)",
            "Detector→Drone Angle (°T)"
        ])
        self.selected_table.verticalHeader().setVisible(False)
        self.selected_table.setAlternatingRowColors(False)
        self.selected_table.setSelectionMode(self.selected_table.SelectionMode.NoSelection)
        self.selected_table.setEditTriggers(self.selected_table.EditTrigger.NoEditTriggers)

        selected_header = self.selected_table.horizontalHeader()
        selected_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        selected_header.setStretchLastSection(True)

        self.selected_table.resizeColumnsToContents()
        self.selected_table.setWordWrap(True)
        self.selected_table.setMaximumHeight(90)
        self.selected_table.setMinimumHeight(90)
        self.selected_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        summary_layout.addWidget(self.selected_table)

        summary_box.setLayout(summary_layout)
        summary_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self.cmb_detected.currentTextChanged.connect(self.on_selected_drone_changed)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "Track", "DroneID", "Remote ID", "Drone Lat", "Drone Lon",
            "Controller Lat", "Controller Lon", "Detector Lat/Lon"
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.btn_start_droneid = QPushButton("Start DroneID")
        self.btn_start_remoteid = QPushButton("Start RemoteID")
        self.btn_refresh = QPushButton("Refresh")
        self.btn_detector = QPushButton("Detector GPS")

        self.btn_start_droneid.clicked.connect(self.start_droneid)
        self.btn_start_remoteid.clicked.connect(self.start_remoteid)
        self.btn_refresh.clicked.connect(self.refresh_view)
        self.btn_detector.clicked.connect(self.edit_detector_location)

        btn_box = QHBoxLayout()
        btn_box.addWidget(self.btn_start_droneid)
        btn_box.addWidget(self.btn_start_remoteid)
        btn_box.addWidget(self.btn_refresh)
        btn_box.addWidget(self.btn_detector)
        btn_box.addStretch(1)

        right = QVBoxLayout()
        right.addLayout(btn_box)
        right.addWidget(summary_box)

        self.zone_panel = CommandOperationGeofencePanel(
            self.geofence_engine,
            self,
            on_zones_changed=self._on_zones_changed,
        )
        right.addWidget(self.zone_panel)

        right.addWidget(QLabel("Combined Parsed Data"))
        right.addWidget(self.table, 1)

        right_widget = QWidget()
        right_widget.setLayout(right)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(right_widget)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        root = QHBoxLayout()
        root.addWidget(self.web, 1)
        root.addWidget(right_scroll, 1)
        self.setLayout(root)

        self.geofence_controller = CommandOperationGeofenceController(
            webview=self.web,
            detected_table=self.table,
            engine=self.geofence_engine,
            parent=self,
        )

        self.web.setHtml(COMMAND_OPERATION_HTML)

        self._refresh_detected_dropdown()
        self.refresh_view()

    def attach_sources(self, droneid_tab, remoteid_tab):
        self.droneid_tab = droneid_tab
        self.remoteid_tab = remoteid_tab

    def start_droneid(self):
        if self.droneid_tab is None:
            QMessageBox.warning(self, "Unavailable", "DroneID tab is not attached.")
            return
        self.droneid_tab.start_reader()

    def start_remoteid(self):
        if self.remoteid_tab is None:
            QMessageBox.warning(self, "Unavailable", "RemoteID tab is not attached.")
            return
        self.remoteid_tab.start_reader()

    def edit_detector_location(self):
        lat, lon, alt = self.detector_state.get_location()
        dlg = DetectorLocationDialog(lat, lon, alt, self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            lat, lon, alt = dlg.values()
        except Exception as e:
            QMessageBox.warning(self, "Invalid detector location", str(e))
            return

        self.detector_state.set_location(lat, lon, alt)
        self.store.update_detector(lat, lon, alt)
        self.refresh_view()

    @staticmethod
    def _f(v) -> str:
        try:
            return f"{float(v):.6f}"
        except Exception:
            return ""

    @staticmethod
    def _f2(v) -> str:
        try:
            return f"{float(v):.2f}"
        except Exception:
            return ""

    def _distance_and_bearing(self, drone_lat, drone_lon):
        det_lat, det_lon, _ = self.detector_state.get_location()
        if det_lat is None or det_lon is None:
            return None, None
        try:
            drone_lat = float(drone_lat)
            drone_lon = float(drone_lon)
        except Exception:
            return None, None

        dist = distance_m(det_lat, det_lon, drone_lat, drone_lon)
        ang = bearing_deg_true_north(det_lat, det_lon, drone_lat, drone_lon)
        return dist, ang

    def _refresh_detected_dropdown(self):
        current = self.cmb_detected.currentText()
        keys = sorted(str(item.get("key", "")) for item in self.store.items())

        self.cmb_detected.blockSignals(True)
        self.cmb_detected.clear()
        self.cmb_detected.addItem("None")
        self.cmb_detected.addItems([k for k in keys if k])
        if current in keys or current == "None":
            self.cmb_detected.setCurrentText(current)
        else:
            self.cmb_detected.setCurrentIndex(0)
        self.cmb_detected.blockSignals(False)

    def _update_selected_drone_table(self, track_key: Optional[str]):
        values = ["", "", "", "", ""]
        if track_key and track_key != "None":
            for item in self.store.items():
                if str(item.get("key")) == track_key:
                    drone_lat = item.get("drone_lat")
                    drone_lon = item.get("drone_lon")
                    drone_alt = item.get("drone_alt")
                    dist, ang = self._distance_and_bearing(drone_lat, drone_lon)

                    values = [
                        self._f(drone_lat),
                        self._f(drone_lon),
                        self._f2(drone_alt),
                        "" if dist is None else f"{dist:.1f}",
                        "" if ang is None else f"{ang:.1f}",
                    ]
                    break

        for col, text in enumerate(values):
            cell = QTableWidgetItem(text)
            cell.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.selected_table.setItem(0, col, cell)

    def on_selected_drone_changed(self, track_key: str):
        track_key = track_key.strip()
        if not track_key or track_key == "None":
            self._update_selected_drone_table(None)
            if self._map_ready:
                self.web.page().runJavaScript("selectTrack(null);")
            return

        self._update_selected_drone_table(track_key)
        if self._map_ready:
            self.web.page().runJavaScript(f"selectTrack({json.dumps(track_key)});")

    def _on_map_loaded(self, ok: bool):
        if not ok:
            return

        self._map_ready = True

        if self.geofence_controller is not None:
            self.geofence_controller.install_map_bridge(fit_after=False)

        self._on_detector_changed()
        self.refresh_view()

    def _on_zones_changed(self):
        if self.geofence_controller is not None and self._map_ready:
            self.geofence_controller.install_map_bridge(fit_after=True)
        self.refresh_view()

    def _apply_geofence_updates(self, items):
        if self.geofence_controller is None or self.zone_panel is None:
            return

        results = self.geofence_controller.decorate_detected_table(items)
        self.zone_panel.refresh_zone_table(results)

        if self._map_ready:
            self.geofence_controller.update_map_alert(items)

    def _on_detector_changed(self):
        if not self._map_ready:
            return

        lat, lon, alt = self.detector_state.get_location()
        if lat is None or lon is None:
            self.web.page().runJavaScript("selectTrack(null);")
            return

        payload = {"detector_lat": lat, "detector_lon": lon, "detector_alt_m": alt}
        self.web.page().runJavaScript(f"updateDetector({json.dumps(payload)});")

        selected_key = self.cmb_detected.currentText().strip()
        if selected_key and selected_key != "None":
            self.web.page().runJavaScript(f"selectTrack({json.dumps(selected_key)});")
        else:
            self.web.page().runJavaScript("selectTrack(null);")

        if self.geofence_controller is not None:
            self.geofence_controller.install_map_bridge(fit_after=False)

    def refresh_view(self):
        items = self.store.items()
        lat, lon, alt = self.detector_state.get_location()

        for item in items:
            item["detector_lat"] = lat
            item["detector_lon"] = lon
            item["detector_alt"] = alt
            item["detector_alt_m"] = alt

        self._refresh_detected_dropdown()

        if self._map_ready:
            self.web.page().runJavaScript(f"updateCombined({json.dumps(items)});")

        selected_key = self.cmb_detected.currentText().strip()
        self._update_selected_drone_table(selected_key if selected_key and selected_key != "None" else None)

        if self._map_ready:
            if selected_key and selected_key != "None":
                self.web.page().runJavaScript(f"selectTrack({json.dumps(selected_key)});")
            else:
                self.web.page().runJavaScript("selectTrack(null);")

        self.table.setRowCount(0)
        for item in items:
            row = self.table.rowCount()
            self.table.insertRow(row)

            detector_txt = ""
            if item.get("detector_lat") is not None and item.get("detector_lon") is not None:
                detector_txt = f"{self._f(item.get('detector_lat'))}, {self._f(item.get('detector_lon'))}"

            values = [
                str(item.get("key", "")),
                "Yes" if item.get("source_droneid") else "",
                "Yes" if item.get("source_remoteid") else "",
                self._f(item.get("drone_lat")),
                self._f(item.get("drone_lon")),
                self._f(item.get("controller_lat")),
                self._f(item.get("controller_lon")),
                detector_txt,
            ]

            for col, text in enumerate(values):
                cell = QTableWidgetItem(text)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self.table.setItem(row, col, cell)

        self._apply_geofence_updates(items)
