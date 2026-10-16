@echo off
rem Zips dist\LavatiNoter into dist\LavatiNoter-portable.zip (with a portable.txt so settings stay in a data folder next to the
rem program) and writes dist\SHA256SUMS.txt for the installer and the zip. Run build.bat first.
setlocal
cd /d "%~dp0"
if not exist dist\LavatiNoter\LavatiNoter.exe (echo Run build.bat first. & exit /b 1)
if exist dist\portable rmdir /s /q dist\portable
mkdir dist\portable\LavatiNoter
xcopy /e /i /q /y dist\LavatiNoter dist\portable\LavatiNoter >nul
echo This file makes LavatiNoter keep its settings and backups in the "data" folder next to it. > dist\portable\LavatiNoter\portable.txt
if exist dist\LavatiNoter-portable.zip del dist\LavatiNoter-portable.zip
powershell -NoProfile -Command "Compress-Archive -Path 'dist\portable\LavatiNoter' -DestinationPath 'dist\LavatiNoter-portable.zip'" || exit /b 1
rmdir /s /q dist\portable
powershell -NoProfile -Command "Get-FileHash -Algorithm SHA256 dist\LavatiNoter-Setup.exe, dist\LavatiNoter-portable.zip | ForEach-Object { $_.Hash.ToLower() + '  ' + (Split-Path $_.Path -Leaf) } | Set-Content -Encoding ascii dist\SHA256SUMS.txt"
type dist\SHA256SUMS.txt
echo Portable zip: dist\LavatiNoter-portable.zip
