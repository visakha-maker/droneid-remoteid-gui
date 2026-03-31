@echo off
setlocal
pyinstaller --noconsole --name DroneID_RemoteID_GUI ^
  --collect-all PySide6 ^
  --collect-all PySide6.QtWebEngineCore ^
  --collect-all PySide6.QtWebEngineWidgets ^
  --add-data "config.py;." ^
  --add-data "modules;modules" ^
  --add-data "app\maps;app\maps" ^
  main.py
endlocal
