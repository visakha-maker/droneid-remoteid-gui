from __future__ import annotations

import json
from typing import Any, Dict, Optional, Sequence

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QWidget

from .constants import COLOR_BUFFER, COLOR_HIGH, COLOR_LOW
from .engine import GeofenceEngine
from .models import DroneAlertResult


class CommandOperationGeofenceController:
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
        self._bridge_installing = False
        self._bridge_retry_count = 0
        self._pending_fit = False
        self._previous_global_alert = False

    def ensure_table_columns(self) -> None:
        desired = [
            "Track",
            "DroneID",
            "Remote ID",
            "Drone Lat",
            "Drone Lon",
            "Controller Lat",
            "Controller Lon",
            "Detector Lat/Lon",
            "Breached Zone",
            "Alert State",
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
            self.install_map_bridge(fit_after=False)
            return

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

    def install_map_bridge(self, fit_after: bool = False) -> None:
        self._pending_fit = self._pending_fit or fit_after

        if self._map_js_installed:
            fit = self._pending_fit
            self._pending_fit = False
            QTimer.singleShot(0, lambda: self.render_zones(fit=fit))
            return

        if self._bridge_installing:
            return

        self._bridge_installing = True

        js = r'''
(function() {
  if (window.__cmdopGeoFence || typeof map === 'undefined' || typeof L === 'undefined') return;

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
    if (
      points[0][0] !== points[points.length - 1][0] ||
      points[0][1] !== points[points.length - 1][1]
    ) {
      closed.push(points[0]);
    }

    const xy = closed.map(p => proj.forward(p[0], p[1]));
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

      const ll = proj.inverse(
        curr[0] + bufferMeters * nx / nlen,
        curr[1] + bufferMeters * ny / nlen
      );
      out.push(ll);
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
      if (blinkTimer) {
        clearInterval(blinkTimer);
        blinkTimer = null;
      }
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
      if (blinkTimer) {
        clearInterval(blinkTimer);
        blinkTimer = null;
      }
      el.style.background = 'rgba(220,0,0,0.95)';
    }
  }

  function drawZones(zones, fitView) {
    zoneLayer.clearLayers();
    labelLayer.clearLayers();

    if (!Array.isArray(zones)) return;

    let bounds = null;

    for (const zone of zones) {
      const baseColor = zone.baseColor || 'orange';
      const bufferColor = zone.bufferColor || 'yellow';

      if (zone.type === 'Circular' && zone.center && zone.center.length === 2) {
        let outerLayer = null;

        if (zone.bufferRadius > 0) {
          outerLayer = L.circle(zone.center, {
            radius: zone.radius + zone.bufferRadius,
            color: bufferColor,
            weight: 3,
            fillColor: bufferColor,
            fillOpacity: 0.14
          }).addTo(zoneLayer);
        }

        const innerLayer = L.circle(zone.center, {
          radius: zone.radius,
          color: baseColor,
          weight: 3,
          fillColor: baseColor,
          fillOpacity: 0.24
        }).addTo(zoneLayer);

        const b = (outerLayer || innerLayer).getBounds();
        bounds = bounds ? bounds.extend(b) : b;

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
        let drawPoly = null;

        if (zone.bufferRadius > 0) {
          const bufferPts = bufferedPolygonLatLngs(zone.points, zone.bufferRadius);
          drawPoly = L.polygon(bufferPts, {
            color: bufferColor,
            weight: 3,
            fillColor: bufferColor,
            fillOpacity: 0.14
          }).addTo(zoneLayer);
        }

        const poly = L.polygon(zone.points, {
          color: baseColor,
          weight: 3,
          fillColor: baseColor,
          fillOpacity: 0.24
        }).addTo(zoneLayer);

        const b = (drawPoly || poly).getBounds();
        bounds = bounds ? bounds.extend(b) : b;

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

    if (fitView && bounds && bounds.isValid()) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 17 });
    }
  }

  window.__cmdopGeoFence = {
    drawZones: drawZones,
    setAlertState: setAlertState
  };
})();
'''
        self.webview.page().runJavaScript(js, lambda _=None: self._verify_map_bridge())

    def _verify_map_bridge(self) -> None:
        check_js = "Boolean(window.__cmdopGeoFence && window.__cmdopGeoFence.drawZones && window.__cmdopGeoFence.setAlertState)"
        self.webview.page().runJavaScript(check_js, self._after_verify_map_bridge)

    def _after_verify_map_bridge(self, ok) -> None:
        installed = bool(ok)
        self._map_js_installed = installed
        self._bridge_installing = False

        if installed:
            self._bridge_retry_count = 0
            fit = self._pending_fit
            self._pending_fit = False
            QTimer.singleShot(80, lambda: self.render_zones(fit=fit))
            return

        if self._bridge_retry_count < 5:
            self._bridge_retry_count += 1
            QTimer.singleShot(150, lambda: self.install_map_bridge(fit_after=self._pending_fit))

    def render_zones(self, fit: bool = False) -> None:
        if not self._map_js_installed:
            self.install_map_bridge(fit_after=fit)
            return

        payload = self.engine.map_payload()
        self.webview.page().runJavaScript(
            f"window.__cmdopGeoFence && window.__cmdopGeoFence.drawZones({json.dumps(payload)}, {str(bool(fit)).lower()});"
        )
