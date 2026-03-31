from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Optional, Union


def extract_json(line: str) -> Optional[Dict[str, Any]]:
    i = line.find('{')
    if i < 0:
        return None
    try:
        return json.loads(line[i:].strip())
    except json.JSONDecodeError:
        return None


def iter_json_objects(payload_str: str) -> Iterable[Union[dict, list]]:
    s = payload_str.strip()
    if not s:
        return
    if s.startswith('['):
        try:
            yield json.loads(s)
            return
        except Exception:
            pass
    try:
        yield json.loads(s)
        return
    except Exception:
        pass
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if len(lines) > 1:
        for ln in lines:
            try:
                yield json.loads(ln)
            except Exception:
                continue
        return
    rest = s
    while rest:
        pos = rest.find('}{')
        if pos == -1:
            chunk = rest
            rest = ''
        else:
            chunk = rest[:pos + 1]
            rest = rest[pos + 1:]
        try:
            yield json.loads(chunk)
        except Exception:
            if pos == -1:
                return
