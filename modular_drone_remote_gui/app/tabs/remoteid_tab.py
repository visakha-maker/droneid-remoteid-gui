import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QFormLayout,
    QPushButton, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QGridLayout, QComboBox, QSizePolicy
)

from app.maps import REMOTEID_HTML
from app.readers.mqtt_reader import MqttReader
from app.utils.geo import distance_m, bearing_deg_true_north
from app.utils.webview import make_webview


class RemoteIdTab(QWidget):
    def __init__(self, detector_state):
        super().__init__()
        self.reader: Optional[MqttReader] = None
        self._running = False
        self.rx_count = 0
        self.max_rows = 2000
        self.store = None

        self.detector_state = detector_state
        self.detector_state.changed.connect(self._on_detector_changed)

        self.remote_tracks: Dict[str, Dict[str, Any]] = {}
        self.max_detector_range_m: float = 10000.0

        self.web = make_webview(self)
        self.web.setHtml(REMOTEID_HTML)

        info_box = QGroupBox("Latest Decode")
        info_grid = QGridLayout()

        self.lbl_status = QLabel("Idle")
        self.lbl_sensor = QLabel("-")
        self.lbl_id = QLabel("-")
        self.lbl_ua_type = QLabel("-")
        self.lbl_id_type = QLabel("-")
        self.lbl_time = QLabel("-")
        self.lbl_rssi = QLabel("-")
        self.lbl_channel = QLabel("-")
        self.lbl_controller = QLabel("-")
        self.lbl_drone = QLabel("-")
        self.lbl_alt = QLabel("-")
        self.lbl_detector = QLabel("-")
        self.lbl_drone_vec = QLabel("-")
        self.lbl_controller_vec = QLabel("-")

        for lbl in [
            self.lbl_status, self.lbl_sensor, self.lbl_id, self.lbl_ua_type,
            self.lbl_id_type, self.lbl_time, self.lbl_rssi, self.lbl_channel,
            self.lbl_controller, self.lbl_drone, self.lbl_alt,
            self.lbl_detector, self.lbl_drone_vec, self.lbl_controller_vec
        ]:
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)

        left_form = QFormLayout()
        left_form.addRow("Status:", self.lbl_status)
        left_form.addRow("Sensor ID:", self.lbl_sensor)
        left_form.addRow("Remote ID:", self.lbl_id)
        left_form.addRow("UA type:", self.lbl_ua_type)
        left_form.addRow("ID type:", self.lbl_id_type)
        left_form.addRow("Timestamp (UTC):", self.lbl_time)
        left_form.addRow("RSSI:", self.lbl_rssi)

        right_form = QFormLayout()
        right_form.addRow("Channel:", self.lbl_channel)
        right_form.addRow("Controller lat/lon:", self.lbl_controller)
        right_form.addRow("Drone lat/lon:", self.lbl_drone)
        right_form.addRow("Altitude:", self.lbl_alt)
        right_form.addRow("Detector lat/lon/alt:", self.lbl_detector)
        right_form.addRow("Detector → Drone:", self.lbl_drone_vec)
        right_form.addRow("Detector → Controller:", self.lbl_controller_vec)

        info_grid.addLayout(left_form, 0, 0)
        info_grid.addLayout(right_form, 0, 1)
        info_box.setLayout(info_grid)

        selection_box = QGroupBox("Detected Drones")
        selection_layout = QVBoxLayout()
        selection_layout.setContentsMargins(8, 8, 8, 8)
        selection_layout.setSpacing(6)

        combo_row = QHBoxLayout()
        combo_row.addWidget(QLabel("Select drone:"))
        self.cmb_detected = QComboBox()
        combo_row.addWidget(self.cmb_detected, 1)
        selection_layout.addLayout(combo_row)

        self.selected_table = QTableWidget(1, 3)
        self.selected_table.setHorizontalHeaderLabels(["Drone Lat", "Drone Lon", "Altitude"])
        self.selected_table.verticalHeader().setVisible(False)
        self.selected_table.setAlternatingRowColors(False)
        self.selected_table.setSelectionMode(self.selected_table.SelectionMode.NoSelection)
        self.selected_table.setEditTriggers(self.selected_table.EditTrigger.NoEditTriggers)
        self.selected_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.selected_table.setMaximumHeight(82)
        self.selected_table.setMinimumHeight(82)
        self.selected_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        selection_layout.addWidget(self.selected_table)

        selection_box.setLayout(selection_layout)
        selection_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.cmb_detected.currentTextChanged.connect(self.on_selected_drone_changed)

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            "RX#", "Track Key", "Remote ID", "Sensor ID", "RSSI", "Channel",
            "Controller Lat", "Controller Lon", "Drone Lat", "Drone Lon"
        ])
        self._setup_table(self.table)

        btn_box = QHBoxLayout()
        self.btn_start = QPushButton("Start")
        self.btn_stop = QPushButton("Stop")
        self.btn_clear = QPushButton("Clear Table")
        self.btn_stop.setEnabled(False)

        btn_box.addWidget(self.btn_start)
        btn_box.addWidget(self.btn_stop)
        btn_box.addWidget(self.btn_clear)
        btn_box.addStretch(1)

        self.btn_start.clicked.connect(self.start_reader)
        self.btn_stop.clicked.connect(self.stop_reader)
        self.btn_clear.clicked.connect(self.clear_table)

        right = QVBoxLayout()
        right.addLayout(btn_box)
        right.addWidget(selection_box)
        right.addWidget(info_box)
        right.addWidget(QLabel("Parsed Incoming Data"))
        right.addWidget(self.table, 1)

        right_widget = QWidget()
        right_widget.setLayout(right)

        root = QHBoxLayout()
        root.addWidget(self.web, 1)
        root.addWidget(right_widget, 1)
        self.setLayout(root)

        self._refresh_detected_dropdown()
        self._on_detector_changed()

    def _setup_table(self, table: QTableWidget):
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(table.SelectionBehavior.SelectRows)
        table.setEditTriggers(table.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)

    def _detector_location(self):
        return self.detector_state.get_location()

    def _on_detector_changed(self):
        lat, lon, alt = self._detector_location()
        if lat is not None and lon is not None:
            self.lbl_detector.setText(f"{lat:.6f}, {lon:.6f}, {alt:.1f} m")
            payload = {"detector_lat": lat, "detector_lon": lon, "detector_alt_m": alt}
            self.web.page().runJavaScript(f"updateDetector({json.dumps(payload)});")
            selected_key = self.cmb_detected.currentText().strip()
            if selected_key and selected_key != "None":
                self.web.page().runJavaScript(f"selectTrack({json.dumps(selected_key)});")
        else:
            self.lbl_detector.setText("-")
            self.web.page().runJavaScript("selectTrack(null);")

    @staticmethod
    def _f(val) -> str:
        try:
            return f"{float(val):.6f}"
        except Exception:
            return ""

    @staticmethod
    def _f2(val) -> str:
        try:
            return f"{float(val):.2f}"
        except Exception:
            return ""

    @staticmethod
    def _as_float(value):
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _fmt_time_ms(ts_ms) -> str:
        try:
            return datetime.fromtimestamp(int(ts_ms) / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return ""

    @staticmethod
    def _valid_lat_lon(lat, lon) -> bool:
        try:
            lat = float(lat)
            lon = float(lon)
        except Exception:
            return False

        if lat == 0.0 and lon == 0.0:
            return False

        return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0

    @staticmethod
    def _within_detector_range(det_lat, det_lon, target_lat, target_lon, max_range_m: float) -> bool:
        if det_lat is None or det_lon is None:
            return True
        if target_lat is None or target_lon is None:
            return False
        return distance_m(det_lat, det_lon, target_lat, target_lon) <= max_range_m

    def _filter_point_by_range(self, lat, lon):
        if not self._valid_lat_lon(lat, lon):
            return None, None
        lat_f = self._as_float(lat)
        lon_f = self._as_float(lon)
        det_lat, det_lon, _ = self._detector_location()
        if not self._within_detector_range(det_lat, det_lon, lat_f, lon_f, self.max_detector_range_m):
            return None, None
        return lat_f, lon_f

    def _passes_basic_filter(self, p: Dict[str, Any]) -> bool:
        valid_points = []
        for lat_key, lon_key in (
            ("operator_lat", "operator_lon"),
            ("drone_lat", "drone_lon"),
        ):
            lat = self._as_float(p.get(lat_key))
            lon = self._as_float(p.get(lon_key))
            if self._valid_lat_lon(lat, lon):
                valid_points.append((lat, lon))

        if not valid_points:
            return False

        det_lat, det_lon, _ = self._detector_location()
        if det_lat is not None and det_lon is not None:
            in_range = any(
                self._within_detector_range(
                    det_lat,
                    det_lon,
                    lat,
                    lon,
                    self.max_detector_range_m,
                )
                for lat, lon in valid_points
            )
            if not in_range:
                return False

        return True

    def _match_existing_track(self, payload: Dict[str, Any]) -> str:
        for key in ("basic_id", "mac", "sensor_id"):
            value = payload.get(key)
            if value not in (None, ""):
                return str(value)
        return "unknown-track"

    def _distance_and_bearing(self, target_lat, target_lon):
        det_lat, det_lon, _ = self._detector_location()
        if det_lat is None or det_lon is None or target_lat is None or target_lon is None:
            return None, None

        return (
            distance_m(det_lat, det_lon, target_lat, target_lon),
            bearing_deg_true_north(det_lat, det_lon, target_lat, target_lon),
        )

    def _refresh_detected_dropdown(self):
        current = self.cmb_detected.currentText()
        keys = sorted(self.remote_tracks.keys())

        self.cmb_detected.blockSignals(True)
        self.cmb_detected.clear()
        self.cmb_detected.addItem("None")
        self.cmb_detected.addItems(keys)

        if current in keys or current == "None":
            self.cmb_detected.setCurrentText(current)
        else:
            self.cmb_detected.setCurrentIndex(0)

        self.cmb_detected.blockSignals(False)

    def _update_selected_drone_table(self, track_key: Optional[str]):
        values = ["", "", ""]
        if track_key and track_key != "None" and track_key in self.remote_tracks:
            track = self.remote_tracks[track_key]
            values = [
                self._f(track.get("drone_lat")),
                self._f(track.get("drone_lon")),
                self._f2(track.get("drone_alt")),
            ]

        for col, text in enumerate(values):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.selected_table.setItem(0, col, item)

    def on_selected_drone_changed(self, track_key: str):
        track_key = track_key.strip()
        if not track_key or track_key == "None":
            self._update_selected_drone_table(None)
            self.web.page().runJavaScript("selectTrack(null);")
            return

        self._update_selected_drone_table(track_key)
        self.web.page().runJavaScript(f"selectTrack({json.dumps(track_key)});")

    def start_reader(self):
        if self._running:
            return

        self.reader = MqttReader()
        self.reader.got_payload.connect(self.on_payload)
        self.reader.got_error.connect(self.on_error)
        self.reader.got_status.connect(self.on_status)
        self.reader.start()

        self._running = True
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.lbl_status.setText("Starting...")

    def stop_reader(self):
        if not self._running or not self.reader:
            return

        self.reader.stop()
        self.reader.wait(1500)
        self.reader = None
        self._running = False
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lbl_status.setText("Stopped")

    def shutdown(self):
        self.stop_reader()

    def clear_table(self):
        self.table.setRowCount(0)
        self.rx_count = 0
        self.remote_tracks.clear()
        self.cmb_detected.blockSignals(True)
        self.cmb_detected.clear()
        self.cmb_detected.addItem("None")
        self.cmb_detected.setCurrentIndex(0)
        self.cmb_detected.blockSignals(False)
        self._update_selected_drone_table(None)
        self.web.setHtml(REMOTEID_HTML)
        self._on_detector_changed()

    def on_error(self, msg: str):
        self.lbl_status.setText("Error")
        QMessageBox.critical(self, "RemoteID Error", msg)

    def on_status(self, msg: str):
        self.lbl_status.setText(msg)

    def on_payload(self, p: Dict[str, Any]):
        if not self._passes_basic_filter(p):
            return

        track_key = self._match_existing_track(p)
        det_lat, det_lon, det_alt = self._detector_location()
        p["track_key"] = track_key
        p["detector_lat"] = det_lat
        p["detector_lon"] = det_lon
        p["detector_alt_m"] = det_alt

        controller_lat, controller_lon = self._filter_point_by_range(
            p.get("operator_lat"), p.get("operator_lon")
        )
        drone_lat, drone_lon = self._filter_point_by_range(
            p.get("drone_lat"), p.get("drone_lon")
        )

        p["operator_lat"] = controller_lat
        p["operator_lon"] = controller_lon
        p["controller_lat"] = controller_lat
        p["controller_lon"] = controller_lon
        p["drone_lat"] = drone_lat
        p["drone_lon"] = drone_lon

        self.remote_tracks[track_key] = {
            "remote_id": p.get("basic_id") or p.get("mac"),
            "sensor_id": p.get("sensor_id"),
            "rssi": p.get("rssi"),
            "channel": p.get("channel"),
            "controller_lat": self._as_float(p.get("operator_lat")),
            "controller_lon": self._as_float(p.get("operator_lon")),
            "drone_lat": self._as_float(p.get("drone_lat")),
            "drone_lon": self._as_float(p.get("drone_lon")),
            "drone_alt": self._as_float(p.get("alt_geo")),
        }

        self._refresh_detected_dropdown()
        selected_key = self.cmb_detected.currentText().strip()
        self._update_selected_drone_table(selected_key if selected_key and selected_key != "None" else None)

        self.lbl_status.setText("Receiving")
        self.lbl_sensor.setText(str(p.get("sensor_id", "-")))
        self.lbl_id.setText(str(p.get("basic_id") or p.get("mac") or "-"))
        self.lbl_ua_type.setText(str(p.get("ua_type", "-")))
        self.lbl_id_type.setText(str(p.get("id_type", "-")))
        self.lbl_time.setText(self._fmt_time_ms(p.get("timestamp_ms")))
        self.lbl_rssi.setText(str(p.get("rssi", "-")))
        self.lbl_channel.setText(str(p.get("channel", "-")))
        self.lbl_controller.setText(f"{self._f(p.get('operator_lat'))}, {self._f(p.get('operator_lon'))}".strip(", "))
        self.lbl_drone.setText(f"{self._f(p.get('drone_lat'))}, {self._f(p.get('drone_lon'))}".strip(", "))
        self.lbl_alt.setText(f"{self._f2(p.get('alt_geo'))}")

        if det_lat is not None and det_lon is not None:
            self.lbl_detector.setText(f"{det_lat:.6f}, {det_lon:.6f}, {det_alt:.1f} m")

        drone_dist, drone_brg = self._distance_and_bearing(
            self._as_float(p.get("drone_lat")), self._as_float(p.get("drone_lon"))
        )
        controller_dist, controller_brg = self._distance_and_bearing(
            self._as_float(p.get("operator_lat")), self._as_float(p.get("operator_lon"))
        )

        self.lbl_drone_vec.setText("-" if drone_dist is None else f"{drone_dist:.1f} m @ {drone_brg:.1f}°T")
        self.lbl_controller_vec.setText("-" if controller_dist is None else f"{controller_dist:.1f} m @ {controller_brg:.1f}°T")

        self.web.page().runJavaScript(f"updatePoints({json.dumps(p)});")

        selected_key = self.cmb_detected.currentText().strip()
        if selected_key and selected_key != "None":
            self.web.page().runJavaScript(f"selectTrack({json.dumps(selected_key)});")
        else:
            self.web.page().runJavaScript("selectTrack(null);")

        self.rx_count += 1
        row = self.table.rowCount()
        self.table.insertRow(row)

        def set_cell(col: int, text: str):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.table.setItem(row, col, item)

        set_cell(0, str(self.rx_count))
        set_cell(1, track_key)
        set_cell(2, str(p.get("basic_id", "")))
        set_cell(3, str(p.get("sensor_id", "")))
        set_cell(4, str(p.get("rssi", "")))
        set_cell(5, str(p.get("channel", "")))
        set_cell(6, self._f(p.get("operator_lat")))
        set_cell(7, self._f(p.get("operator_lon")))
        set_cell(8, self._f(p.get("drone_lat")))
        set_cell(9, self._f(p.get("drone_lon")))

        if self.table.rowCount() > self.max_rows:
            self.table.removeRow(0)

        self.table.scrollToBottom()

        if self.store is not None:
            self.store.update_remoteid(dict(p))