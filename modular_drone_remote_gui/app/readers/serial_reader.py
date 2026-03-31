from __future__ import annotations

from typing import Optional

import serial
from PySide6.QtCore import QThread, Signal

from app.parsers.common import extract_json


class SerialReader(QThread):
    got_payload = Signal(dict)
    got_line = Signal(str)
    got_error = Signal(str)
    got_status = Signal(str)

    def __init__(self, port: str, baud: int = 115200):
        super().__init__()
        self.port = port
        self.baud = baud
        self._stop = False
        self.ser: Optional[serial.Serial] = None

    def stop(self):
        self._stop = True
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass

    def run(self):
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.5)
            self.got_status.emit(f'Connected to {self.port} @ {self.baud}')
        except Exception as e:
            self.got_error.emit(f'Failed to open {self.port} @ {self.baud}: {e}')
            return

        buf = b''
        while not self._stop:
            try:
                chunk = self.ser.read(4096)
                if not chunk:
                    continue
                buf += chunk
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    s = line.decode('utf-8', errors='ignore').rstrip('\r')
                    if not s:
                        continue
                    self.got_line.emit(s)
                    payload = extract_json(s)
                    if payload:
                        self.got_payload.emit(payload)
            except Exception as e:
                if not self._stop:
                    self.got_error.emit(f'Serial read error: {e}')
                break

        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass
