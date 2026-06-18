@echo off
echo ==========================================
echo   Wallpaper Switcher - Build EXE
echo ==========================================
echo.

:: Check if PyInstaller is installed
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing PyInstaller...
    pip install pyinstaller
)

echo [INFO] Building EXE...
echo.

python -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "WallpaperSwitcher" ^
    --add-data "config.json;." ^
    --noconfirm ^
    --clean ^
    wallpaper_gui.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

echo.
echo [OK] Build successful!
echo.
echo EXE location: dist\WallpaperSwitcher.exe
echo.
echo To distribute, copy dist\WallpaperSwitcher.exe to any folder.
echo Config, cache and downloads will be created next to the exe.
echo.
pause
