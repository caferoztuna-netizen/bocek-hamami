@echo off
chcp 65001 >nul
title Böcek Hamamı - Yayın İstasyonu
cd /d "%~dp0"
python istasyon\istasyon.py
pause
