Folder layout:
- main.py                launcher
- app/                   split source files
- build_folder.bat       PyInstaller folder build (not onefile)

Install deps on Windows:
  pip install PySide6 PySide6-WebEngine pyserial paho-mqtt pyinstaller

Build into a folder on Windows:
  build_folder.bat

Output:
  dist\DroneID_RemoteID_GUI\

Run from source:
  python main.py --com COM5
  python main.py --list
