# FactuposBackup

Respaldo automático de SQL Server (GUI + CLI). El `.exe` de Windows se compila
con **GitHub Actions** (runner `windows-latest` + PyInstaller).

- Fuente: `backup_app.py` (GUI navy), `backup_core.py`, `backup_cli.py`
- Build automático en cada push a `main` → artifact `FactuposBackup-exe`
  (`FactuposBackup.exe` + `FactuposBackupCLI.exe`).
- Bumpear `APP_VERSION` en `backup_core.py` + los números en `version_info.txt`.
