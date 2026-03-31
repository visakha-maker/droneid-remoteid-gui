import argparse
import serial.tools.list_ports

from app.main import run_app


def list_ports():
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("No COM ports found.")
        return

    for p in ports:
        print(f"{p.device} - {p.description}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="List COM ports and exit.")
    ap.add_argument("--com", default="", help="Default COM port for DroneID tab, e.g. COM5")
    ap.add_argument("--baud", type=int, default=115200, help="Baud rate for DroneID serial feed")
    ns = ap.parse_args()

    if ns.list:
        list_ports()
        return

    run_app(ns.com, ns.baud)


if __name__ == "__main__":
    main()