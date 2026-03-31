import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget, QMessageBox

from app.tabs.droneid_tab import DroneIdTab
from app.tabs.remoteid_tab import RemoteIdTab
from app.tabs.command_operation_tab import CommandOperationTab
from app.security.maclock import is_authorized_machine
from app.store import OperationsStore, DetectorState


class MainWindow(QMainWindow):
    def __init__(self, com_port: str = "", baud: int = 115200):
        super().__init__()
        self.setWindowTitle("DroneID + RemoteID GUI")
        self.resize(1550, 930)

        self.store = OperationsStore()
        self.detector_state = DetectorState()

        self.tabs = QTabWidget()

        self.droneid_tab = DroneIdTab(self.detector_state, com_port, baud)
        self.remoteid_tab = RemoteIdTab(self.detector_state)
        self.command_operation_tab = CommandOperationTab(self.store, self.detector_state)

        self.droneid_tab.store = self.store
        self.remoteid_tab.store = self.store
        self.command_operation_tab.attach_sources(self.droneid_tab, self.remoteid_tab)

        self.tabs.addTab(self.command_operation_tab, "Command Operation")
        self.tabs.addTab(self.droneid_tab, "DroneID (USB / ANTSDR)")
        self.tabs.addTab(self.remoteid_tab, "Remote ID (Ethernet / MQTT)")
        self.tabs.setCurrentIndex(0)

        self.setCentralWidget(self.tabs)

    def closeEvent(self, event):
        try:
            self.droneid_tab.shutdown()
        except Exception:
            pass
        try:
            self.remoteid_tab.shutdown()
        except Exception:
            pass
        super().closeEvent(event)


def run_app(com_port: str = "", baud: int = 115200):
    app = QApplication(sys.argv)

    ok, found_macs = is_authorized_machine()
    if not ok:
        found_text = ", ".join(sorted(found_macs)) if found_macs else "No MAC addresses detected"
        QMessageBox.critical(
            None,
            "Unauthorized Machine",
            "This application is locked to approved network adapters.\n\n"
            f"Detected MAC addresses:\n{found_text}",
        )
        sys.exit(1)

    win = MainWindow(com_port, baud)
    win.show()
    sys.exit(app.exec())