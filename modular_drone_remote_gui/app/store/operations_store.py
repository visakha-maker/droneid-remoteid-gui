from typing import Dict, Any, Optional

from PySide6.QtCore import QObject, Signal


class OperationsStore(QObject):
    updated = Signal()

    def __init__(self):
        super().__init__()
        self._items: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _key(source: str, payload: Dict[str, Any]) -> str:
        if source == "droneid":
            return str(
                payload.get("track_key")
                or payload.get("device_type")
                or payload.get("drone_id")
                or payload.get("serial_number")
                or "unknown-droneid"
            )
        return str(
            payload.get("track_key")
            or payload.get("basic_id")
            or payload.get("mac")
            or payload.get("sensor_id")
            or "unknown-remoteid"
        )

    def _ensure_item(self, key: str) -> Dict[str, Any]:
        if key not in self._items:
            self._items[key] = {
                "key": key,
                "source_droneid": False,
                "source_remoteid": False,
                "device_type": None,
                "remote_id": None,
                "sensor_id": None,
                "rssi": None,
                "channel": None,
                "drone_lat": None,
                "drone_lon": None,
                "drone_alt": None,
                "controller_lat": None,
                "controller_lon": None,
                "controller_alt": None,
                "detector_lat": None,
                "detector_lon": None,
                "detector_alt": None,
            }
        return self._items[key]

    @staticmethod
    def _copy_if_present(dst: Dict[str, Any], src: Dict[str, Any], dst_key: str, *src_keys: str):
        for key in src_keys:
            if key in src and src[key] is not None:
                dst[dst_key] = src[key]
                return

    def update_droneid(self, payload: Dict[str, Any]):
        key = self._key("droneid", payload)
        item = self._ensure_item(key)

        item["source_droneid"] = True

        self._copy_if_present(item, payload, "device_type", "device_type")
        self._copy_if_present(item, payload, "drone_lat", "drone_lat")
        self._copy_if_present(item, payload, "drone_lon", "drone_lon")
        self._copy_if_present(item, payload, "drone_alt", "altitude", "drone_alt")

        self._copy_if_present(item, payload, "controller_lat", "app_lat", "controller_lat")
        self._copy_if_present(item, payload, "controller_lon", "app_lon", "controller_lon")
        self._copy_if_present(item, payload, "controller_alt", "app_alt", "controller_alt")

        self._copy_if_present(item, payload, "detector_lat", "detector_lat")
        self._copy_if_present(item, payload, "detector_lon", "detector_lon")
        self._copy_if_present(item, payload, "detector_alt", "detector_alt_m", "detector_alt")

        self.updated.emit()

    def update_remoteid(self, payload: Dict[str, Any]):
        key = self._key("remoteid", payload)
        item = self._ensure_item(key)

        item["source_remoteid"] = True

        self._copy_if_present(item, payload, "remote_id", "basic_id", "mac")
        self._copy_if_present(item, payload, "sensor_id", "sensor_id")
        self._copy_if_present(item, payload, "rssi", "rssi")
        self._copy_if_present(item, payload, "channel", "channel")

        self._copy_if_present(item, payload, "drone_lat", "drone_lat")
        self._copy_if_present(item, payload, "drone_lon", "drone_lon")
        self._copy_if_present(item, payload, "drone_alt", "alt_geo", "drone_alt")

        self._copy_if_present(item, payload, "controller_lat", "operator_lat", "controller_lat")
        self._copy_if_present(item, payload, "controller_lon", "operator_lon", "controller_lon")
        self._copy_if_present(item, payload, "controller_alt", "operator_alt", "controller_alt")

        self._copy_if_present(item, payload, "detector_lat", "detector_lat")
        self._copy_if_present(item, payload, "detector_lon", "detector_lon")
        self._copy_if_present(item, payload, "detector_alt", "detector_alt_m", "detector_alt")

        self.updated.emit()

    def update_detector(self, lat: Optional[float], lon: Optional[float], alt: Optional[float]):
        for item in self._items.values():
            item["detector_lat"] = lat
            item["detector_lon"] = lon
            item["detector_alt"] = alt
        self.updated.emit()

    def items(self):
        return list(self._items.values())

    def clear(self):
        self._items.clear()
        self.updated.emit()