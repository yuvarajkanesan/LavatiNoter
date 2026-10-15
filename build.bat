@echo off
rem Builds dist\LavatiNoter\LavatiNoter.exe (and the installer if Inno Setup is installed).
setlocal
cd /d "%~dp0"
python -m pip install --quiet -r requirements-dev.txt || goto :err
python tools\make_assets.py || goto :err
python tools\make_version.py || goto :err
python tools\make_notices.py || goto :err
python -m PyInstaller --noconfirm --clean LavatiNoter.spec || goto :err
rem --- drop Qt components the editor never loads (the self-test below fails the build if something needed was removed) ---
set I=dist\LavatiNoter\_internal
del /q "%I%\PySide6\opengl32sw.dll" "%I%\PySide6\Qt6Quick*.dll" "%I%\PySide6\Qt6Pdf*.dll" "%I%\PySide6\Qt6OpenGL*.dll" "%I%\PySide6\Qt6VirtualKeyboard*.dll" "%I%\PySide6\Qt6Qml*.dll" 2>nul
del /q "%I%\PySide6\plugins\imageformats\qpdf.dll" "%I%\PySide6\plugins\platforminputcontexts\qtvirtualkeyboardplugin.dll" "%I%\PySide6\plugins\generic\qtuiotouchplugin.dll" 2>nul
rmdir /s /q "%I%\PySide6\translations" 2>nul
rmdir /s /q "%I%\PySide6\qml" 2>nul
rmdir /s /q "%I%\PySide6\resources" 2>nul
rmdir /s /q "%I%\PySide6\plugins\qmltooling" 2>nul
rmdir /s /q "%I%\PySide6\plugins\tls" 2>nul
del /q "%I%\PySide6\plugins\imageformats\qicns.dll" "%I%\PySide6\plugins\imageformats\qtga.dll" "%I%\PySide6\plugins\imageformats\qwbmp.dll" 2>nul
del /q "%I%\PySide6\plugins\platforms\qdirect2d.dll" "%I%\PySide6\plugins\platforms\qminimal.dll" 2>nul
del /q "%I%\api-ms-win-*.dll" "%I%\ucrtbase.dll" 2>nul
dist\LavatiNoter\LavatiNoter.exe --selftest || (type "%TEMP%\lavatinoter-selftest.log" & goto :err)
type "%TEMP%\lavatinoter-selftest.log"
echo.
echo Built: dist\LavatiNoter\LavatiNoter.exe

set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
rem Code signing (removes the "Unknown publisher" warning): set LAVATI_SIGNTOOL to a command using $f for the file.
if defined LAVATI_SIGNTOOL call :signapp || goto :err
if not defined ISCC goto :noiscc
if defined LAVATI_SIGNTOOL goto :signedinstaller
"%ISCC%" installer.iss || goto :err
goto :installerdone
:signedinstaller
call set ISIGN=%%LAVATI_SIGNTOOL:"=$q%%
"%ISCC%" /DSign=1 "/Slavatisign=%ISIGN%" installer.iss || goto :err
:installerdone
echo Installer: dist\LavatiNoter-Setup.exe
exit /b 0
:noiscc
echo Inno Setup not found - skipping installer. Install it from https://jrsoftware.org/isdl.php and re-run.
exit /b 0
:err
echo Build failed.
exit /b 1
:signapp
call set SIGNCMD=%%LAVATI_SIGNTOOL:$f=dist\LavatiNoter\LavatiNoter.exe%%
%SIGNCMD%
exit /b %errorlevel%
