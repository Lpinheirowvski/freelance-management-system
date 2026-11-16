"""Explicit administrative commands. The original CLI remains freelancer_manager.py."""

import argparse
import json
import sqlite3
from fms.db import Database
from fms.demo import create_demo
from fms.migration import migrate
from fms.storage import backup_database, restore_database


def main():
    parser = argparse.ArgumentParser(description="Freelance Management System v2 administration")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "demo", "check"):
        sub = commands.add_parser(name)
        sub.add_argument("--db", required=True)
    sub = commands.add_parser("migrate")
    sub.add_argument("--source", required=True)
    sub.add_argument("--db", required=True, help="New destination; existing files are never overwritten")
    for name in ("backup", "restore"):
        sub = commands.add_parser(name)
        sub.add_argument("--source", required=True)
        sub.add_argument("--destination", required=True)
    args = parser.parse_args()
    try:
        if args.command == "init":
            Database(args.db).initialize()
        elif args.command == "check":
            from fms.storage import validate_backup

            validate_backup(args.db)
        elif args.command == "demo":
            create_demo(args.db)
        elif args.command == "migrate":
            print(json.dumps(migrate(args.source, args.db), indent=2))
        else:
            (backup_database if args.command == "backup" else restore_database)(args.source, args.destination)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print("Completed successfully.")


if __name__ == "__main__":
    main()
