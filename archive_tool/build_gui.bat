@echo off
setlocal
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build PeaceWalkerArchiveTool.spec
endlocal
