from __future__ import annotations

import base64
import lzma
from dataclasses import dataclass
from typing import Any, Dict, Optional

from modules import open_drone_id

from app.utils.geo import valid_lat_lon


class OpenDroneIdValidBlocks:
    BasicID0_valid = 0
    BasicID1_valid = 0
    LocationValid = 0
    SelfIDValid = 0
    SystemValid = 0
    OperatorIDValid = 0
    AuthValid = [0] * 16


@dataclass
class RemoteIdRow:
    key: str
    timestamp_ms: int
    sensor_id: str = ''
    mac: str = ''
    basic_id: str = ''
    id_type: str = ''
    ua_type: str = ''
    rssi: Optional[float] = None
    channel: Optional[int] = None
    drone_lat: Optional[float] = None
    drone_lon: Optional[float] = None
    operator_lat: Optional[float] = None
    operator_lon: Optional[float] = None
    alt_geo: Optional[float] = None
    alt_baro: Optional[float] = None
    speed_h: Optional[float] = None
    speed_v: Optional[float] = None
    direction: Optional[float] = None


def decode_mqtt_payload(msg_payload: bytes) -> str:
    try:
        s = msg_payload.decode()
    except Exception:
        try:
            s = lzma.decompress(msg_payload).decode()
        except Exception:
            return ''
    if len(s) and ord(s[-1:]) in (0, 10):
        s = s[:-1]
    return s


def protocol_is_remoteid(p: Any) -> bool:
    try:
        return float(p) == 1.0
    except Exception:
        return False


def _u32(payload: bytes, off: int) -> int:
    return int.from_bytes(payload[off:off + 4], 'little', signed=False)


def _f32(payload: bytes, off: int) -> float:
    import struct
    return struct.unpack('<f', payload[off:off + 4])[0]


def _f64(payload: bytes, off: int) -> float:
    import struct
    return struct.unpack('<d', payload[off:off + 8])[0]


def _clean_ascii(b: bytes) -> str:
    return b.decode('ascii', errors='ignore').rstrip('\x00').strip()


def parse_remoteid_row_from_b64(uas_b64: str, data_json: Dict[str, Any]) -> RemoteIdRow:
    uas = base64.b64decode(uas_b64)
    vb = OpenDroneIdValidBlocks()
    open_drone_id.decode_valid_blocks(uas, vb)

    ts = int(data_json.get('timestamp', 0))
    mac = str(data_json.get('MAC address') or '')
    sensor_id = str(data_json.get('sensor ID') or '')
    rssi = data_json.get('RSSI')
    try:
        rssi = float(rssi) if rssi is not None else None
    except Exception:
        rssi = None
    channel = data_json.get('channel')
    try:
        channel = int(channel) if channel is not None else None
    except Exception:
        channel = None

    basic_id = ''
    id_type_text = ''
    ua_type_text = ''
    if vb.BasicID0_valid == 1:
        ua_type = _u32(uas, 0)
        id_type = _u32(uas, 4)
        try:
            ua_type_text = open_drone_id.decode_basicID_UA_type(ua_type)
        except Exception:
            ua_type_text = str(ua_type)
        try:
            id_type_text = open_drone_id.decode_basicID_ID_type(id_type)
        except Exception:
            id_type_text = str(id_type)
        if id_type in (1, 2):
            basic_id = _clean_ascii(uas[8:8 + 21])
        else:
            basic_id = uas[8:8 + 21].hex()

    row = RemoteIdRow(
        key=basic_id or mac or f'unknown-{ts}',
        timestamp_ms=ts,
        sensor_id=sensor_id,
        mac=mac,
        basic_id=basic_id,
        id_type=id_type_text,
        ua_type=ua_type_text,
        rssi=rssi,
        channel=channel,
    )

    if vb.LocationValid == 1:
        loc = 64
        row.direction = _f32(uas, loc + 4)
        row.speed_h = _f32(uas, loc + 8)
        row.speed_v = _f32(uas, loc + 12)
        lat = _f64(uas, loc + 16)
        lon = _f64(uas, loc + 24)
        row.alt_baro = _f32(uas, loc + 32)
        row.alt_geo = _f32(uas, loc + 36)
        if valid_lat_lon(lat, lon):
            row.drone_lat = lat
            row.drone_lon = lon

    if vb.SystemValid == 1:
        sys_off = 808
        op_lat = _f64(uas, sys_off + 8)
        op_lon = _f64(uas, sys_off + 16)
        if valid_lat_lon(op_lat, op_lon):
            row.operator_lat = op_lat
            row.operator_lon = op_lon

    return row
