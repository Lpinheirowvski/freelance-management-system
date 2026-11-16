"""Publish new SQLite artifacts atomically; never overwrite destination files."""

from contextlib import closing, contextmanager
import os
from pathlib import Path
import sqlite3
import tempfile

from fms.db import Database, SCHEMA, SCHEMA_VERSION


@contextmanager
def new_database(destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Destination already exists. Choose a new filename.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fms-", dir=destination.parent) as folder:
        staged = Path(folder) / "database.sqlite3"
        db = Database(staged)
        yield db
        if not db.integrity():
            raise ValueError("Database failed integrity checks.")
        os.chmod(staged, 0o600)
        # Hard linking is atomic and refuses existing files, including racing writers.
        try:
            os.link(staged, destination)
        except FileExistsError as exc:
            raise ValueError("Destination already exists. Choose a new filename.") from exc


def validate_backup(source):
    path = Path(source).resolve()
    if not path.is_file():
        raise ValueError("Backup file does not exist.")
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
            conn.execute("PRAGMA trusted_schema=OFF")
            if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise ValueError("Only v2 SQLite backups are supported.")
            actual = conn.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            ).fetchall()
            with closing(sqlite3.connect(":memory:")) as reference:
                reference.executescript(SCHEMA)
                expected = reference.execute(
                    "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
                ).fetchall()
            if actual != expected:
                raise ValueError("Backup schema does not match this application version.")
            if (
                conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
                or conn.execute("PRAGMA foreign_key_check").fetchall()
            ):
                raise ValueError("Backup failed integrity checks.")
    except sqlite3.DatabaseError as exc:
        raise ValueError("Invalid SQLite backup.") from exc


def backup_database(source, destination):
    """SQLite online backup API gives a consistent snapshot, also with concurrent readers."""
    validate_backup(source)
    with new_database(destination) as target:
        with closing(sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True)) as original:
            with target.connect() as conn:
                original.backup(conn)
    return Path(destination)


def restore_database(source, destination):
    """Restore to a NEW path. Switching the active database requires an application restart."""
    return backup_database(source, destination)
