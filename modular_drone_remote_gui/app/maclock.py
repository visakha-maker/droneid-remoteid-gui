from __future__ import annotations

import subprocess
from typing import Set, Tuple

ALLOWED_MACS = {
    '000100012E22',
    '7E763514CB20',
    '7C763514CB21',
    '7C763514CB20',
    'C09C8C1645C1',
    '8C1645C1A4A8',
    '80FA5B56EA08',
    '902E163307D1',
    '502F9B205522',
    '522F9B205521',
    '502F9B205525',
}


def normalize_mac(value: str) -> str:
    return ''.join(ch for ch in str(value).upper() if ch in '0123456789ABCDEF')


def get_windows_mac_addresses() -> Set[str]:
    macs: Set[str] = set()
    try:
        result = subprocess.run(
            ['getmac', '/fo', 'csv', '/nh'],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip().strip('"') for p in line.split(',')]
            if not parts:
                continue
            mac = normalize_mac(parts[0])
            if len(mac) == 12:
                macs.add(mac)
    except Exception:
        pass
    return macs


def is_authorized_machine() -> Tuple[bool, Set[str]]:
    found = get_windows_mac_addresses()
    return any(mac in ALLOWED_MACS for mac in found), found
