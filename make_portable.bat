@echo off
rem Builds the portable edition: ONE file, dist\LavatiNoter-Portable.exe
rem   Copy it anywhere (a USB stick, a shared folder) and run it. No installer, no registry, no admin rights.
rem   It keeps settings, backups of unsaved text and plugins in a "LavatiNoterData" folder next to the exe.
rem   (A one-file exe unpacks itself to a temporary folder at every start, so it opens a little slower than the installed
rem   app; the temporary files are removed when you close it.)
setlocal
cd /d "%~dp0"
python -m pip install --quiet -r requirements-dev.txt || goto :err
python tools\make_assets.py || goto :err
python tools\make_version.py || goto :err
if exist dist\LavatiNoter-Portable.exe del /q dist\LavatiNoter-Portable.exe
python -m PyInstaller --noconfirm --workpath build\portable --distpath dist LavatiNoterPortable.spec || goto :err
if not exist dist\LavatiNoter-Portable.exe goto :err
rem --- verify the real file: packaged self-test, and the data folder must be beside the exe (not in %APPDATA%) ---
dist\LavatiNoter-Portable.exe --selftest || (type "%TEMP%\lavatinoter-selftest.log" & goto :err)
set CHECK=%TEMP%\lavatinoter-portable-check
if exist "%CHECK%" rmdir /s /q "%CHECK%"
mkdir "%CHECK%"
copy /y dist\LavatiNoter-Portable.exe "%CHECK%\LavatiNoter-Portable.exe" >nul
"%CHECK%\LavatiNoter-Portable.exe" --data-dir-to "%CHECK%\where.txt"
set /p DATADIR=<"%CHECK%\where.txt"
if /i not "%DATADIR%"=="%CHECK%\LavatiNoterData" (
  echo Portable check FAILED: data folder is "%DATADIR%" instead of "%CHECK%\LavatiNoterData"
  goto :err
)
ping -n 3 127.0.0.1 >nul
rmdir /s /q "%CHECK%" 2>nul
rem --- checksums for everything in dist that is a release file ---
powershell -NoProfile -Command "Get-ChildItem dist\*.exe | ForEach-Object { (Get-FileHash -Algorithm SHA256 $_.FullName).Hash.ToLower() + '  ' + $_.Name } | Set-Content -Encoding ascii dist\SHA256SUMS.txt"
echo.
for %%F in (dist\LavatiNoter-Portable.exe) do echo Portable build: dist\LavatiNoter-Portable.exe  ^(%%~zF bytes^)
type dist\SHA256SUMS.txt
exit /b 0
:err
echo Portable build failed.
exit /b 1
