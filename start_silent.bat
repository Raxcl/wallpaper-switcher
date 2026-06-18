@echo off
:: 静默启动 GUI 版（不显示控制台窗口）
cd /d "%~dp0"
start "" /min python wallpaper_gui.py
