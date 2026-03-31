from typing import Optional, Tuple
from PySide6.QtCore import QObject, Signal


class DetectorState(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.lat: Optional[float] = None
        self.lon: Optional[float] = None
        self.alt_m: float = 0.0

    def set_location(self, lat: float, lon: float, alt_m: float):
        self.lat = lat
        self.lon = lon
        self.alt_m = alt_m
        self.changed.emit()

    def get_location(self) -> Tuple[Optional[float], Optional[float], float]:
        return self.lat, self.lon, self.alt_m