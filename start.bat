@echo off
chcp 65001 >nul 2>&1
title 壁纸切换工具

echo ====================================
echo   壁纸切换工具 - GUI 版启动器
echo ====================================
echo.

cd /d "%~dp0"

:: 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

:: 检查依赖是否安装
python -c "import ttkbootstrap" >nul 2>&1
if errorlevel 1 (
    echo [信息] 首次运行，正在安装依赖...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请手动运行: pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo [信息] 依赖安装完成！
    echo.
)

echo [信息] 正在启动壁纸切换工具（GUI 版）...
echo.
python wallpaper_gui.py
