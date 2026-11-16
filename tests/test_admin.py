import json
import pytest
from fms.__main__ import main
from fms.db import Database
from fms.service import Service


def invoke(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["fms", *map(str, args)])
    main()


def test_admin_init_demo_check_backup_restore(tmp_path, monkeypatch):
    empty = tmp_path / "empty.sqlite3"
    invoke(monkeypatch, "init", "--db", empty)
    assert Database(empty).integrity()
    demo = tmp_path / "demo.sqlite3"
    invoke(monkeypatch, "demo", "--db", demo)
    invoke(monkeypatch, "check", "--db", demo)
    backup = tmp_path / "backup.sqlite3"
    invoke(monkeypatch, "backup", "--source", demo, "--destination", backup)
    restored = tmp_path / "restored.sqlite3"
    invoke(monkeypatch, "restore", "--source", backup, "--destination", restored)
    assert len(Service(Database(restored)).rows("projects")) == 5


def test_admin_migration_and_failure_exit(tmp_path, monkeypatch, capsys):
    source = tmp_path / "legacy.json"
    source.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "nome": "Example",
                    "projeto": "Web",
                    "horas": 1,
                    "valor_hora": 10,
                    "total": 10,
                    "pago": False,
                    "data": "01/11/2026",
                }
            ]
        )
    )
    db = tmp_path / "migrated.sqlite3"
    invoke(monkeypatch, "migrate", "--source", source, "--db", db)
    assert "source_sha256" in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, "migrate", "--source", source, "--db", db)
    assert error.value.code == 1
    assert "already exists" in capsys.readouterr().err
