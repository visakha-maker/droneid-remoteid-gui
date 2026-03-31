from pathlib import Path


def _read_map_file(filename: str) -> str:
    base_dir = Path(__file__).resolve().parent
    return (base_dir / filename).read_text(encoding="utf-8")


DRONEID_HTML = _read_map_file("droneid_map.html")
REMOTEID_HTML = _read_map_file("remoteid_map.html")
COMMAND_OPERATION_HTML = _read_map_file("command_operation_map.html")
