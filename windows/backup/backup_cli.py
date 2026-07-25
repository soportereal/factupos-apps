#!/usr/bin/env python3
"""
FactuposBackup — CLI del respaldo SQL Server.

Para la versión gráfica usá backup_app.py / FactuposBackup.exe.

Uso típico:
    python backup_cli.py --setup        # configurar interactivo
    python backup_cli.py --list         # solo listar BDs
    python backup_cli.py                # ejecutar respaldo
    python backup_cli.py --show-config  # ver config actual
"""

import argparse
import getpass
import json
import sys

import backup_core as core


def setup_interactive(cfg):
    print("=== FactuposBackup — Configuración ===")
    print("(ENTER para mantener el valor actual)\n")

    def ask(label, current, secret=False):
        shown = "(vacío)" if not current else (current if not secret else "*" * len(current))
        prompt = f"{label} [{shown}]: "
        val = getpass.getpass(prompt) if secret else input(prompt)
        return val.strip() or current

    cfg["server"] = ask("Servidor SQL (IP\\instancia)", cfg.get("server", ""))
    cfg["user"] = ask("Usuario SQL", cfg.get("user", ""))
    cfg["password"] = ask("Password SQL", cfg.get("password", ""), secret=True)
    cfg["backup_path"] = ask("Ruta de backup", cfg.get("backup_path", ""))
    cfg["schedule_hour"] = ask("Hora diaria (HH:MM)", cfg.get("schedule_hour", "23:00"))

    ret = ask("Días de retención (0=infinito)", str(cfg.get("retention_days", 7)))
    try:
        cfg["retention_days"] = int(ret)
    except ValueError:
        pass

    core.save_config(cfg)
    print(f"\nConfiguración guardada en: {core.config_path()}\n")
    return cfg


def main():
    p = argparse.ArgumentParser(description=f"FactuposBackup CLI v{core.APP_VERSION} — respaldo diario SQL Server.")
    p.add_argument("--version", action="version", version=f"FactuposBackup CLI v{core.APP_VERSION}")
    p.add_argument("--setup", action="store_true", help="Configurar interactivamente y salir")
    p.add_argument("--show-config", action="store_true", help="Mostrar configuración y salir")
    p.add_argument("--list", action="store_true", help="Solo listar BDs")
    p.add_argument("--set-server", help="Guardar servidor y salir")
    p.add_argument("--set-user", help="Guardar usuario y salir")
    p.add_argument("--set-password", help="Guardar password y salir")
    p.add_argument("--set-path", help="Guardar ruta de backup y salir")
    args = p.parse_args()

    cfg = core.load_config()

    changed = False
    if args.set_server:   cfg["server"] = args.set_server; changed = True
    if args.set_user:     cfg["user"] = args.set_user; changed = True
    if args.set_password: cfg["password"] = args.set_password; changed = True
    if args.set_path:     cfg["backup_path"] = args.set_path; changed = True
    if changed:
        core.save_config(cfg)
        print(f"Config actualizada en {core.config_path()}")
        return 0

    if args.setup:
        setup_interactive(cfg)
        return 0

    if args.show_config:
        masked = dict(cfg)
        if masked.get("password"):
            masked["password"] = "*" * len(masked["password"])
        print(json.dumps(masked, indent=2, ensure_ascii=False))
        return 0

    log = core.get_logger()
    if args.list:
        try:
            conn = core.get_connection(cfg)
            for d in core.list_databases(conn, cfg.get("exclude_dbs", []), cfg.get("include_dbs", [])):
                print(d)
            return 0
        except Exception as e:
            log.error(str(e))
            return 1

    result = core.run_backup(cfg, log=log)
    if not result.get("ok"):
        return 1
    return 2 if result.get("fail_dbs") else 0


if __name__ == "__main__":
    sys.exit(main())
