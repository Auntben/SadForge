@echo off
echo === SadForge Build ===

echo Installing build dependencies...
pip install pyinstaller pillow

echo Converting icon to .ico...
python -c "from PIL import Image; img = Image.open('sadforge_ico.png').convert('RGBA'); img.save('sadforge_ico.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
if errorlevel 1 (
    echo Icon conversion failed, building without .ico...
    set ICON_FLAG=
) else (
    set ICON_FLAG=--icon=sadforge_ico.ico
)

echo Building SadForge.exe...
pyinstaller --onefile --windowed --name=SadForge %ICON_FLAG% --add-data "sadforge_ico.png;." main.py

echo.
if exist dist\SadForge.exe (
    echo Build successful! Executable is at dist\SadForge.exe
) else (
    echo Build may have failed. Check output above.
)
pause