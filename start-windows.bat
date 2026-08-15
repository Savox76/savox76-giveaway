@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -e .
)
if not exist "frontend\dist\index.html" (
  where npm >nul 2>nul || (echo Node.js wird einmalig zum Bauen der Oberflaeche benoetigt. & pause & exit /b 1)
  pushd frontend
  call npm install
  call npm run build
  popd
)
.venv\Scripts\python.exe -m savox_giveaway
