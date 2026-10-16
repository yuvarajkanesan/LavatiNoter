# Releasing LavatiNoter

1. Bump `VERSION` in `lavatinoter/__init__.py`, add the changes to `CHANGELOG.md`, commit.
2. `build.bat` builds `dist\LavatiNoter\LavatiNoter.exe`, runs the packaged self-test and compiles `dist\LavatiNoter-Setup.exe`
   (needs Inno Setup 6). `make_portable.bat` then makes `dist\LavatiNoter-portable.zip` and `dist\SHA256SUMS.txt`.
3. **Sign** `LavatiNoter.exe` and the installer (OV/EV certificate or Azure Trusted Signing): set `LAVATI_SIGNTOOL` to a command using
   `$f` for the file before running `build.bat`. Unsigned builds show "Unknown publisher" and SmartScreen warns.
4. **Test on clean machines** (Windows 10 and 11, no Python): install, open files, upgrade over the previous version, uninstall with and
   without keeping data, 100 / 150 / 200 % scaling, a user name with non-ASCII characters.
5. Tag `vX.Y.Z` and push: the GitHub workflow (`.github/workflows/ci.yml`) builds and attaches the files to a release. Check its first run.
6. Submit the installer to Microsoft Security Intelligence (antivirus false positives are common for PyInstaller apps).
7. Update checks read `https://api.github.com/repos/yuvarajkanesan/LavatiNoter/releases/latest`, so publishing a release with a `vX.Y.Z` tag is
   what tells users a new version exists.
